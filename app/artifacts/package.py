from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from app.parsers.base import ParsedAsset
from app.schemas.models import BODY_CONTENT_FIELDS, Element, ExtractionField, Metadata, Page

DOCX_MARGIN_INCHES = float(os.getenv("PDFLENS_DOCX_MARGIN_INCHES", "0.75"))
if not 0 <= DOCX_MARGIN_INCHES < 2:
    raise RuntimeError("PDFLENS_DOCX_MARGIN_INCHES must be in [0, 2)")


def _xml_safe_text(value: str) -> str:
    """Replace characters forbidden by XML 1.0 before embedding text in HTML/DOCX."""
    return "".join(
        character if (character in "\t\n\r"
                      or "\u0020" <= character <= "\uD7FF"
                      or "\uE000" <= character <= "\uFFFD"
                      or "\U00010000" <= character <= "\U0010FFFF")
        else "\uFFFD"
        for character in value
    )


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
    page.duplicate_text_char_count = max(page.duplicate_text_char_count, duplicate_chars)
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



def _text(value: str) -> str:
    return html.escape(_xml_safe_text(value), quote=True)


def _element_html(element: Element) -> str:
    value = element.text or ""
    if element.type == ExtractionField.HEADING:
        raw_level = element.attributes.get("heading_level", element.attributes.get("level", 2))
        try:
            level = min(6, max(1, int(raw_level)))
        except (TypeError, ValueError):
            level = 2
        return f'<h{level} data-element-id="{_text(element.element_id)}">{_text(value)}</h{level}>'
    if element.type == ExtractionField.HYPERLINK:
        if element.target_uri:
            visible_text = value
            if not visible_text and element.target_uri.startswith("#"):
                return ""
            visible_text = visible_text or element.target_uri
            return (f'<p><a href="{_text(element.target_uri)}">'
                    f'{_text(visible_text)}</a></p>')
        return f"<p>{_text(value)}</p>"
    if element.type == ExtractionField.LIST:
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if not lines and value.strip():
            lines = [value.strip()]
        return "<ul>" + "".join(f"<li>{_text(line)}</li>" for line in lines) + "</ul>"
    if element.type == ExtractionField.CODE:
        return f"<pre><code>{_text(value)}</code></pre>"
    if element.type in {ExtractionField.IMAGE, ExtractionField.TABLE}:
        if element.type == ExtractionField.TABLE and element.attributes.get("table_cells"):
            table_html = _table_html(element)
            if table_html:
                return table_html
        if element.artifact_path and _safe_member(element.artifact_path):
            alt = value or element.attributes.get("alt_text") or element.type.value
            return (f'<figure data-element-id="{_text(element.element_id)}" '
                    f'data-element-type="{element.type.value}"><img '
                    f'src="{_text(element.artifact_path)}" alt="{_text(str(alt))}" />'
                    f'{f"<figcaption>{_text(value)}</figcaption>" if value else ""}</figure>')
        return f'<figure data-element-type="{element.type.value}"><p>{_text(value)}</p></figure>'
    if element.type == ExtractionField.FOOTNOTE:
        marker = element.attributes.get("marker")
        marker_html = f'<strong>{_text(str(marker))} </strong>' if marker else ""
        return f'<p role="doc-footnote">{marker_html}{_text(value)}</p>'
    if element.type == ExtractionField.HEADER:
        return f'<p role="doc-pageheader"><strong>{_text(value)}</strong></p>'
    if element.type == ExtractionField.FOOTER:
        return f'<p role="doc-pagefooter"><small>{_text(value)}</small></p>'
    if element.type == ExtractionField.PAGE_NUMBER:
        return f'<p role="doc-page-number"><small>{_text(value)}</small></p>'
    if element.type == ExtractionField.CAPTION:
        return f"<p><em>{_text(value)}</em></p>"
    if element.type == ExtractionField.BODY_TEXT:
        return "".join(f"<p>{_text(line)}</p>" for line in value.splitlines() if line.strip())
    if element.type == ExtractionField.EQUATION:
        return f'<p data-element-type="equation"><code>{_text(value)}</code></p>'
    return f'<p data-element-type="{element.type.value}">{_text(value)}</p>' if value else ""


def _table_html(element: Element) -> str:
    cells = [cell for cell in element.attributes.get("table_cells", [])
             if isinstance(cell, dict)]
    if not cells:
        return ""
    rows = max(int(cell.get("row_index", 0)) + max(1, int(cell.get("row_span", 1)))
               for cell in cells)
    columns = max(int(cell.get("column_index", 0))
                  + max(1, int(cell.get("column_span", 1))) for cell in cells)
    positions = {(int(cell.get("row_index", 0)), int(cell.get("column_index", 0))): cell
                 for cell in cells}
    covered: set[tuple[int, int]] = set()
    table_rows: list[str] = []
    for row_index in range(rows):
        rendered_cells: list[str] = []
        for column_index in range(columns):
            if (row_index, column_index) in covered:
                continue
            cell = positions.get((row_index, column_index))
            if cell is None:
                rendered_cells.append("<td></td>")
                continue
            row_span = max(1, int(cell.get("row_span", 1)))
            column_span = max(1, int(cell.get("column_span", 1)))
            for row in range(row_index, row_index + row_span):
                for column in range(column_index, column_index + column_span):
                    if (row, column) != (row_index, column_index):
                        covered.add((row, column))
            tag = "th" if cell.get("is_column_header") or cell.get("is_row_header") else "td"
            spans = (f' rowspan="{row_span}"' if row_span > 1 else "")
            spans += f' colspan="{column_span}"' if column_span > 1 else ""
            rendered_cells.append(f"<{tag}{spans}>{_text(str(cell.get('text', '')))}</{tag}>")
        table_rows.append("<tr>" + "".join(rendered_cells) + "</tr>")
    return f'<table data-element-id="{_text(element.element_id)}">' + "".join(table_rows) + "</table>"


def _page_html(page: Page) -> str:
    ordered = sorted(page.elements, key=lambda item: item.reading_order)
    parts: list[str] = []
    section_open = False
    for element in ordered:
        if element.type == ExtractionField.HEADING:
            if section_open:
                parts.append("</section>")
            parts.append(f'<section data-section-start="{_text(element.element_id)}">')
            section_open = True
        rendered = _element_html(element)
        if rendered:
            attributes = [f'data-element-id="{_text(element.element_id)}"',
                          f'data-element-type="{element.type.value}"']
            if element.bbox is not None:
                box = element.bbox
                attributes.append(
                    'data-bbox="{:.6f},{:.6f},{:.6f},{:.6f}"'.format(
                        box.x0, box.y0, box.x1, box.y1))
            parts.append(f'<div {" ".join(attributes)}>{rendered}</div>')
    if section_open:
        parts.append("</section>")
    width = max(1, page.width_pt)
    height = max(1, page.height_pt)
    page_anchor = f'<p>[[PDFLENS_PAGE_ANCHOR_{page.page_number}]]</p>'
    return (f'<section class="pdf-page" data-page-number="{page.page_number}" '
            f'data-source-width-pt="{width:g}" data-source-height-pt="{height:g}">'
            f'{page_anchor}{"".join(parts)}</section>')


def _render_html(metadata: Metadata) -> str:
    title = metadata.document.title or metadata.document.source_filename
    body = "".join(_page_html(page) for page in metadata.pages)
    return f'''<!doctype html>
<html lang="{_text(metadata.document.language or "en")}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{_text(title)}</title>
  <style>
    body {{ font-family: Calibri, Arial, sans-serif; color: #202124; line-height: 1.25; }}
    .pdf-page {{ margin: 0; padding: 0; }}
    h1, h2, h3, h4, h5, h6 {{ color: #17365d; break-after: avoid; }}
    p {{ margin: 0 0 0.7em; }}
    figure {{ margin: 1em 0; }}
    img {{ max-width: 100%; height: auto; }}
    table {{ border-collapse: collapse; }}
    a {{ color: #0563c1; }}
    [role="doc-footnote"] {{ font-size: 0.9em; }}
  </style>
</head>
<body>
  {body}
</body>
</html>
'''


def _html_to_docx(html_source: str, docx_path: Path, asset_root: Path,
                  page_width_pt: float, page_height_pt: float,
                  margin_inches: float = DOCX_MARGIN_INCHES) -> None:
    from htmldocx import HtmlToDocx
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt

    class AssetAwareHtmlToDocx(HtmlToDocx):
        def handle_img(self, attributes):
            resolved = dict(attributes)
            source = resolved.get("src", "")
            if source and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", source):
                resolved["src"] = str((asset_root / source).resolve())
            super().handle_img(resolved)

    converter = AssetAwareHtmlToDocx()
    converter.table_style = "Table Grid"
    document = converter.parse_html_string(html_source)
    for section in document.sections:
        section.page_width = Pt(page_width_pt)
        section.page_height = Pt(page_height_pt)
        section.top_margin = Inches(margin_inches)
        section.bottom_margin = Inches(margin_inches)
        section.left_margin = Inches(margin_inches)
        section.right_margin = Inches(margin_inches)

    bookmark_ids: dict[int, int] = {}
    next_bookmark_id = 1
    for paragraph in list(document.paragraphs):
        match = re.fullmatch(r"\[\[PDFLENS_PAGE_ANCHOR_(\d+)\]\]", paragraph.text.strip())
        if not match:
            continue
        page_number = int(match.group(1))
        bookmark_id = next_bookmark_id
        next_bookmark_id += 1
        start = OxmlElement("w:bookmarkStart")
        start.set(qn("w:id"), str(bookmark_id))
        start.set(qn("w:name"), f"pdflens_page_{page_number}")
        end = OxmlElement("w:bookmarkEnd")
        end.set(qn("w:id"), str(bookmark_id))
        paragraph.clear()
        paragraph._p.insert(0, start)
        paragraph._p.append(end)
        bookmark_ids[page_number] = bookmark_id

    for hyperlink in document.part.element.xpath(".//w:hyperlink"):
        relationship_id = hyperlink.get(qn("r:id"))
        if not relationship_id or relationship_id not in document.part.rels:
            continue
        target = document.part.rels[relationship_id].target_ref
        match = re.fullmatch(r"#page=(\d+)", target)
        if not match:
            continue
        page_number = int(match.group(1))
        if page_number not in bookmark_ids:
            continue
        hyperlink.attrib.pop(qn("r:id"), None)
        hyperlink.set(qn("w:anchor"), f"pdflens_page_{page_number}")
        document.part.drop_rel(relationship_id)
    document.save(docx_path)


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
        page.body_text_to_source_text_ratio = (
            page.body_text_char_count / page.source_text_char_count
            if page.source_text_char_count else None
        )

    html_source = _render_html(metadata)
    docx_path = work / "document.docx"
    page_width_pt = metadata.pages[0].width_pt if metadata.pages else 612.0
    page_height_pt = metadata.pages[0].height_pt if metadata.pages else 792.0
    margin_inches = float(metadata.processing.configuration.get(
        "docx_margin_inches", DOCX_MARGIN_INCHES
    ))
    _html_to_docx(html_source, docx_path, work, page_width_pt, page_height_pt, margin_inches)
    metadata.processing.docx_layout_status = "generated_editable_reflowable"
    metadata.processing.docx_page_width_pt = page_width_pt
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
