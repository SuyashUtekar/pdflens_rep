from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from app.artifacts.docx import build_preserved_docx
from app.parsers.base import ParsedAsset
from app.schemas.models import Element, ExtractionField, Metadata, Page

try:
    from app.schemas.models import BODY_CONTENT_FIELDS
except ImportError:  # Compatibility with the v1 metadata model.
    BODY_CONTENT_FIELDS = frozenset({
        ExtractionField.BODY_TEXT, ExtractionField.HEADING, ExtractionField.CAPTION,
        ExtractionField.LIST, ExtractionField.EQUATION, ExtractionField.FORM_FIELD,
        ExtractionField.CODE, ExtractionField.OTHER,
    })

DOCX_MARGIN_INCHES = float(os.getenv("PDFLENS_DOCX_MARGIN_INCHES", "0.75"))
if not 0 <= DOCX_MARGIN_INCHES < 2:
    raise RuntimeError("PDFLENS_DOCX_MARGIN_INCHES must be in [0, 2)")


def _safe_member(path: str) -> bool:
    member = PurePosixPath(path)
    return not member.is_absolute() and ".." not in member.parts and "\\" not in path


def _validate_png(path: Path) -> None:
    raw = path.read_bytes()
    if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Invalid PNG artifact: {path.name}")
    if int.from_bytes(raw[16:20], "big") <= 0 or int.from_bytes(raw[20:24], "big") <= 0:
        raise ValueError(f"Invalid PNG dimensions: {path.name}")
    try:
        from PIL import Image
    except ImportError:
        return
    with Image.open(path) as image:
        image.verify()


def _validate_docx(path: Path) -> None:
    with zipfile.ZipFile(path) as document:
        if document.testzip() is not None:
            raise ValueError("Generated DOCX contains a corrupt ZIP member")
        required = {"[Content_Types].xml", "word/document.xml"}
        if not required.issubset(document.namelist()):
            raise ValueError("Generated DOCX is missing required Office document parts")
        if b"<w:body" not in document.read("word/document.xml"):
            raise ValueError("Generated DOCX has no document body")


def _page_body_text(page: Page) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    duplicate_chars = 0
    extracted_body_chars = 0
    for element in sorted(page.elements, key=lambda item: item.reading_order):
        if element.type in BODY_CONTENT_FIELDS and element.text:
            value = element.text
        elif element.type in {ExtractionField.IMAGE, ExtractionField.TABLE}:
            asset_name = element.artifact_path or element.element_id
            tag_type = "IMAGE" if element.type == ExtractionField.IMAGE else "TABLE"
            value = f"[[{tag_type}: {asset_name}]]"
        else:
            continue
        normalized = re.sub(r"\s+", " ", value).strip().casefold()
        if normalized and normalized in seen:
            duplicate_chars += len(value)
            continue
        if normalized:
            seen.add(normalized)
            if element.type in BODY_CONTENT_FIELDS:
                extracted_body_chars += len(value.strip())
        parts.append(value)
    if hasattr(page, "duplicate_text_char_count"):
        page.duplicate_text_char_count = max(page.duplicate_text_char_count, duplicate_chars)
    if hasattr(page, "body_text_char_count"):
        page.body_text_char_count = extracted_body_chars
    if duplicate_chars and "BODY_TEXT_EXACT_DUPLICATE_REMOVED" not in page.warnings:
        page.warnings.append("BODY_TEXT_EXACT_DUPLICATE_REMOVED")
    return "\n".join(parts)


def _validate_package_members(work: Path, members: list[Path], metadata: Metadata) -> None:
    available = {file_path.relative_to(work).as_posix() for file_path in members}
    referenced = [metadata.document.source_filename, metadata.artifacts.docx_path,
                  metadata.artifacts.manifest_path, *metadata.artifacts.image_paths,
                  *metadata.artifacts.table_snapshot_paths]
    for page in metadata.pages:
        referenced.extend(element.artifact_path for element in page.elements
                          if element.artifact_path)
    missing = sorted(set(referenced) - available)
    if missing:
        raise ValueError(f"Metadata references missing package artifacts: {', '.join(missing)}")
    if any(not _safe_member(name) for name in available):
        raise ValueError("Unsafe archive member path")



def build_package(metadata: Metadata, output_path: Path, source_pdf_path: Path,
                  assets: list[ParsedAsset] | None = None) -> None:
    """Package the source PDF, styled DOCX, metadata, assets, and manifest without emitting HTML."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = output_path.parent / f".{output_path.stem}-package"
    work.mkdir(parents=True, exist_ok=True)
    image_counts: dict[tuple[int, str], int] = {}
    exact_assets: dict[str, str] = {}
    packaged_asset_paths: dict[tuple[str, str], str] = {}
    for asset in assets or []:
        group = "images" if asset.asset_type == ExtractionField.IMAGE else "tables"
        counts_key = (asset.page_number, group)
        image_counts[counts_key] = image_counts.get(counts_key, 0) + 1
        category = "image" if group == "images" else "table"
        relative_path = (f"{group}/page-{asset.page_number:04d}-{category}-"
                         f"{image_counts[counts_key]:04d}.png")
        if not _safe_member(relative_path):
            raise ValueError("Unsafe asset path")
        asset_digest = hashlib.sha256(asset.content).hexdigest()
        duplicate_key = (group, asset_digest)
        canonical_path = packaged_asset_paths.get(duplicate_key)
        if canonical_path is None:
            canonical_path = relative_path
            asset_path = work / canonical_path
            asset_path.parent.mkdir(parents=True, exist_ok=True)
            asset_path.write_bytes(asset.content)
            _validate_png(asset_path)
            packaged_asset_paths[duplicate_key] = canonical_path
        for page in metadata.pages:
            for element in page.elements:
                if element.element_id == asset.element_id:
                    element.artifact_path = canonical_path
                    element.attributes["asset_sha256"] = asset_digest
                    canonical_id = exact_assets.get(asset_digest)
                    if canonical_id:
                        element.attributes["exact_duplicate_of"] = canonical_id
                    else:
                        exact_assets[asset_digest] = element.element_id
                    break
        target_paths = (metadata.artifacts.image_paths if group == "images"
                        else metadata.artifacts.table_snapshot_paths)
        if canonical_path not in target_paths:
            target_paths.append(canonical_path)

    for page in metadata.pages:
        page.body_text = _page_body_text(page)
        if hasattr(page, "body_text_char_count") and hasattr(page, "source_text_char_count"):
            page.body_text_to_source_text_ratio = (
                page.body_text_char_count / page.source_text_char_count
                if page.source_text_char_count else None
            )

    docx_path = work / "document.docx"
    configuration = getattr(metadata.processing, "configuration", {})
    margin_inches = float(configuration.get("docx_margin_inches", DOCX_MARGIN_INCHES))
    build_preserved_docx(metadata, source_pdf_path, docx_path, margin_inches)
    page_width_pt = metadata.pages[0].width_pt if metadata.pages else 612.0
    page_height_pt = metadata.pages[0].height_pt if metadata.pages else 792.0
    if hasattr(metadata.processing, "docx_layout_status"):
        metadata.processing.docx_layout_status = "generated_editable_reflowable"
    if hasattr(metadata.processing, "docx_page_width_pt"):
        metadata.processing.docx_page_width_pt = page_width_pt
    if hasattr(metadata.processing, "docx_page_height_pt"):
        metadata.processing.docx_page_height_pt = page_height_pt
    _validate_docx(docx_path)
    source_pdf_name = metadata.document.source_filename
    if not _safe_member(source_pdf_name):
        raise ValueError("Unsafe source PDF filename")
    source_pdf_copy = work / source_pdf_name
    shutil.copyfile(source_pdf_path, source_pdf_copy)

    metadata.artifacts.html_path = None
    metadata.artifacts.docx_path = "document.docx"
    metadata.artifacts.manifest_path = "manifest.json"
    meta_path = work / "metadata.json"
    meta_path.write_text(metadata.model_dump_json(indent=2), encoding="utf-8")
    members = [source_pdf_copy, docx_path, meta_path]
    members.extend(sorted((work / "images").glob("*.png")) if (work / "images").exists() else [])
    members.extend(sorted((work / "tables").glob("*.png")) if (work / "tables").exists() else [])
    manifest_items = []
    for file_path in members:
        name = file_path.relative_to(work).as_posix()
        if not _safe_member(name):
            raise ValueError("Unsafe archive member path")
        raw = file_path.read_bytes()
        manifest_items.append({"path": name, "size_bytes": len(raw),
                               "sha256": hashlib.sha256(raw).hexdigest()})
    manifest = {"schema_version": "1.0", "metadata_schema_version": metadata.schema_version,
                "members": manifest_items}
    manifest_path = work / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    members.append(manifest_path)
    _validate_package_members(work, members, metadata)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in members:
            archive.write(file_path, file_path.relative_to(work).as_posix())
    with zipfile.ZipFile(output_path) as archive:
        corrupt_member = archive.testzip()
        if corrupt_member is not None:
            raise ValueError(f"Generated ZIP member failed integrity check: {corrupt_member}")
        packaged_members = set(archive.namelist())
        missing_members = set(manifest_items_path for manifest_items_path in
                              [item["path"] for item in manifest_items]) - packaged_members
        if missing_members:
            raise ValueError("Manifest references files missing from the generated ZIP")
        for item in manifest_items:
            digest = hashlib.sha256(archive.read(item["path"])).hexdigest()
            if digest != item["sha256"]:
                raise ValueError(f"Manifest checksum mismatch for {item['path']}")
    for child in work.rglob("*"):
        if child.is_file():
            child.unlink()
    for child in sorted(work.rglob("*"), reverse=True):
        if child.is_dir():
            child.rmdir()
    work.rmdir()
