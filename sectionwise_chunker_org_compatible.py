"""Section-wise DOCX chunker compatible with the organization's processor.

Preserves the ``BaseChunker.chunk`` interface and returns the existing mapping:
``{generated_id: {"chunk_text": ..., "page_number": [...]}}``.

The chunking unit is a complete section under a Word heading. There are no
maximum-word or overlap settings, so section boundaries remain intact.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any, Iterable
from unicodedata import normalize

from docx import Document
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
from fastapi import UploadFile
from lxml import etree

from src.exception.custom_exceptions import FieldFilterProcessError
from src.services.base import BaseChunker
from src.utils.chunking_utils import generate_unique_id
from src.utils.log_utils import get_app_logger


app_logger = get_app_logger()
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD_NS_TAG = f"{{{WORD_NS}}}"
WORD_NS_MAP = {"w": WORD_NS}


def _norm(text: str) -> str:
    """Normalize text while retaining letters and digits from all languages."""
    text = normalize("NFKC", str(text or "")).casefold()
    return " ".join(
        "".join(char if char.isalnum() else " " for char in text).split()
    )


def _tokens(text: str) -> list[str]:
    normalized = _norm(text)
    return normalized.split() if normalized else []


def _prefix_table(pattern: list[str]) -> list[int]:
    """Build the KMP prefix table used by the page text matcher."""
    table = [0] * len(pattern)
    matched = 0
    for index in range(1, len(pattern)):
        while matched and pattern[index] != pattern[matched]:
            matched = table[matched - 1]
        if pattern[index] == pattern[matched]:
            matched += 1
            table[index] = matched
    return table


def _longest_prefix_occurrence(pattern: list[str], text: list[str]) -> int:
    """Return the longest prefix of ``pattern`` found contiguously in ``text``."""
    if not pattern or not text:
        return 0
    prefix = _prefix_table(pattern)
    matched = 0
    longest = 0
    for token in text:
        while matched and (matched == len(pattern) or token != pattern[matched]):
            matched = prefix[matched - 1]
        if matched < len(pattern) and token == pattern[matched]:
            matched += 1
            longest = max(longest, matched)
        if matched == len(pattern):
            matched = prefix[matched - 1]
    return longest


def _heading_level(paragraph: Paragraph) -> int | None:
    """Detect built-in, inherited, or outline-level Word headings."""
    style = paragraph.style
    visited: set[str] = set()
    while style is not None and style.style_id not in visited:
        visited.add(style.style_id)
        for candidate in (style.style_id or "", style.name or ""):
            match = re.fullmatch(r"heading\s*(\d+)", candidate, flags=re.IGNORECASE)
            if match:
                return int(match.group(1))
        style = style.base_style

    # Word's outlineLvl uses zero-based values; check paragraph then inherited styles.
    paragraph_properties = paragraph._p.pPr
    outline = (
        paragraph_properties.find(f"{WORD_NS_TAG}outlineLvl")
        if paragraph_properties is not None
        else None
    )
    style = paragraph.style
    while outline is None and style is not None:
        style_properties = style.element.pPr
        outline = (
            style_properties.find(f"{WORD_NS_TAG}outlineLvl")
            if style_properties is not None
            else None
        )
        style = style.base_style
    if outline is not None:
        try:
            value = int(outline.get(f"{WORD_NS_TAG}val"))
        except (TypeError, ValueError):
            return None
        return value + 1 if 0 <= value <= 8 else None
    return None


def _is_title(paragraph: Paragraph) -> bool:
    style = paragraph.style
    return bool(
        style
        and (
            (style.name or "").casefold() == "title"
            or (style.style_id or "").casefold() == "title"
        )
    )


def _paragraph_has_image(paragraph: Paragraph) -> bool:
    xml = paragraph._p.xml
    return "<w:drawing" in xml or "<w:pict" in xml


def _read_footnotes(file_stream: io.BytesIO) -> dict[str, str]:
    """Read footnote text from a DOCX package without changing its stream position."""
    file_stream.seek(0)
    try:
        with zipfile.ZipFile(file_stream) as archive:
            if "word/footnotes.xml" not in archive.namelist():
                return {}
            with archive.open("word/footnotes.xml") as footnotes_file:
                root = etree.parse(footnotes_file).getroot()
    except zipfile.BadZipFile as exc:
        raise FieldFilterProcessError(
            "Failed", "The uploaded document is not a valid DOCX ZIP archive."
        ) from exc
    except etree.XMLSyntaxError as exc:
        raise FieldFilterProcessError(
            "Failed", "The DOCX footnotes XML is malformed."
        ) from exc

    footnotes: dict[str, str] = {}
    for footnote in root.findall("w:footnote", WORD_NS_MAP):
        footnote_id = footnote.get(f"{WORD_NS_TAG}id")
        # Separator records are structural, not document footnotes.
        if footnote_id in {"-1", "0"}:
            continue
        text = "".join(node.text or "" for node in footnote.findall(".//w:t", WORD_NS_MAP))
        if footnote_id is not None and text.strip():
            footnotes[footnote_id] = text.strip()
    file_stream.seek(0)
    return footnotes


def _paragraph_text(paragraph: Paragraph, footnotes: dict[str, str]) -> str:
    """Read visible paragraph runs in order and expand any footnote references."""
    parts: list[str] = []
    for element in paragraph._p.iter():
        if element.tag == f"{WORD_NS_TAG}footnoteReference":
            footnote_id = element.get(f"{WORD_NS_TAG}id")
            footnote_text = footnotes.get(footnote_id or "")
            if footnote_text:
                parts.append(f" ({footnote_text})")
        elif element.tag == f"{WORD_NS_TAG}t":
            parts.append(element.text or "")
    return "".join(parts).strip()


def _table_to_text(table: Table, footnotes: dict[str, str]) -> str:
    """Flatten a native Word table into readable row text in document order."""
    rows: list[str] = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            cell_paragraphs = [
                _paragraph_text(paragraph, footnotes)
                for paragraph in cell.paragraphs
            ]
            cell_text = " ".join(text for text in cell_paragraphs if text)
            cell_text = re.sub(r"\s+", " ", cell_text).strip()
            cells.append(cell_text)
        if any(cells):
            rows.append(" ; ".join(cells))
    return "\n".join(rows)


def _iter_document_blocks(
    document: DocxDocument,
    footnotes: dict[str, str],
) -> Iterable[tuple[str, str, int | None]]:
    """Yield paragraphs and tables in their actual Word document order."""
    image_number = 0
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == f"{WORD_NS_TAG}p":
            paragraph = Paragraph(child, document)
            text = _paragraph_text(paragraph, footnotes)
            if _is_title(paragraph):
                if text:
                    yield "title", text, None
                continue
            level = _heading_level(paragraph)
            if level is not None:
                if text:
                    yield "heading", text, level
                continue
            if text:
                yield "text", text, None
            # A DOCX already containing PDFLens image tags should not gain a duplicate.
            if _paragraph_has_image(paragraph) and not re.search(
                r"<doc_ai\s+type\s*=\s*[\"']image[\"']", text, flags=re.IGNORECASE
            ):
                image_number += 1
                yield "image", f"[Embedded image {image_number}]", None
        elif child.tag == f"{WORD_NS_TAG}tbl":
            table = Table(child, document)
            text = _table_to_text(table, footnotes)
            if text:
                yield "table", text, None


def _extract_sections(file: Any) -> list[tuple[list[str], str]]:
    """Parse a supported DOCX input into complete heading-path/body sections."""
    file_stream: io.BytesIO
    if isinstance(file, DocxDocument):
        file_stream = io.BytesIO()
        file.save(file_stream)
        file_stream.seek(0)
    elif isinstance(file, (str, Path)):
        try:
            file_stream = io.BytesIO(Path(file).expanduser().read_bytes())
        except OSError as exc:
            raise FieldFilterProcessError("Failed", f"Could not read DOCX file: {exc}") from exc
    elif isinstance(file, (bytes, bytearray)):
        file_stream = io.BytesIO(bytes(file))
    elif isinstance(file, UploadFile) or hasattr(file, "file"):
        stream = file.file
        old_position = stream.tell() if hasattr(stream, "tell") else 0
        stream.seek(0)
        file_stream = io.BytesIO(stream.read())
        stream.seek(old_position)
    elif hasattr(file, "read"):
        old_position = file.tell() if hasattr(file, "tell") else 0
        file.seek(0)
        file_stream = io.BytesIO(file.read())
        file.seek(old_position)
    else:
        raise FieldFilterProcessError(
            "Failed",
            f"Unsupported file type for section-wise chunking: {type(file).__name__}.",
        )

    footnotes = _read_footnotes(file_stream)
    file_stream.seek(0)
    try:
        document = Document(file_stream)
    except Exception as exc:
        raise FieldFilterProcessError(
            "Failed", "The uploaded file is not a readable DOCX document."
        ) from exc

    sections: list[tuple[list[str], str]] = []
    heading_stack: list[tuple[int, str]] = []
    current_body: list[str] = []
    current_path: list[str] = []
    preamble: list[str] = []
    image_number = 0

    def flush_body() -> None:
        nonlocal current_body
        body_text = "\n\n".join(text.strip() for text in current_body if text.strip()).strip()
        if body_text:
            sections.append((list(current_path), body_text))
        current_body = []

    for kind, text, level in _iter_document_blocks(document, footnotes):
        if kind == "title":
            # The document title is descriptive metadata, not a section heading.
            continue
        if kind == "heading":
            flush_body()
            assert level is not None
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, text))
            current_path = [heading for _, heading in heading_stack]
            continue
        if kind == "image" and text.startswith("[Embedded image "):
            image_number += 1
            text = f"[Embedded image {image_number}]"
        if current_path:
            current_body.append(text)
        else:
            preamble.append(text)

    flush_body()
    if preamble:
        sections.insert(0, ([], "\n\n".join(preamble).strip()))
    return sections


def _page_records(metadata: Any) -> list[dict[str, Any]]:
    """Normalize supported metadata page containers while preserving page order."""
    if isinstance(metadata, dict):
        metadata = metadata.get("pages", [])
    if not isinstance(metadata, list):
        return []
    records: list[dict[str, Any]] = []
    for index, page in enumerate(metadata, start=1):
        if not isinstance(page, dict):
            continue
        page_number = page.get("page_number", page.get("page", index))
        try:
            page_number = int(page_number)
        except (TypeError, ValueError):
            continue
        page_text = page.get("full_text") or page.get("body_text") or page.get("text") or ""
        records.append({"page_number": page_number, "tokens": _tokens(str(page_text))})
    return records


def _best_edge_pages(tokens: list[str], pages: list[dict[str, Any]], from_end: bool) -> list[int]:
    """Find pages matching the longest available leading or trailing token phrase."""
    if not tokens or not pages:
        return []
    pattern = list(reversed(tokens)) if from_end else tokens
    scores = [
        _longest_prefix_occurrence(pattern, list(reversed(page["tokens"])) if from_end else page["tokens"])
        for page in pages
    ]
    best = max(scores, default=0)
    if not best:
        return []
    return [page["page_number"] for page, score in zip(pages, scores) if score == best]


class SectionTextChunker(BaseChunker):
    """Build one complete chunk per DOCX section, preserving the org contract."""

    def __init__(self, _) -> None:
        pass

    def chunk(self, input_data: Any = None, **kwargs: Any) -> dict[str, dict]:
        prefix = kwargs.get("prefix")
        file = input_data if input_data is not None else kwargs.get("file")
        metadata = kwargs.get("metadata", [])
        if file is None:
            raise FieldFilterProcessError(
                "Failed", "Section-wise chunking requires a valid DOCX document payload."
            )

        try:
            sections = _extract_sections(file)
            pages = _page_records(metadata)
            result: dict[str, dict] = {}
            for heading_path, body_text in sections:
                # Keep the requested pipe-delimited heading path and body format.
                chunk_text = " | ".join([*heading_path, body_text]) if heading_path else body_text
                matched_pages = self._match_page_span(body_text, pages)
                matched_pages.extend(self._match_page_set(heading_path, pages))
                page_numbers = sorted(set(matched_pages))
                unique_id = generate_unique_id(prefix=prefix)
                result[unique_id] = {
                    "chunk_text": chunk_text,
                    "page_number": page_numbers,
                }
            if not result:
                app_logger.info("Section-wise chunking found no non-empty section text.")
            return result
        except FieldFilterProcessError:
            raise
        except Exception as exc:
            app_logger.exception("Failed to process and chunk document layers.")
            raise FieldFilterProcessError(
                "Failed", f"Failed to process and chunk document layers: {exc}"
            ) from exc

    def _match_page_span(self, leaf_text: str, norm_pages: list[dict[str, Any]]) -> list[int]:
        """Map a section body to known source pages without inventing page numbers."""
        if not norm_pages:
            return []
        known_pages = [page["page_number"] for page in norm_pages]
        matched_pages: set[int] = set()
        # Body paragraphs provide independent anchors, including when a section
        # continues across pages or the metadata has gaps in its page sequence.
        for paragraph_text in re.split(r"\n\s*\n", leaf_text):
            paragraph_tokens = _tokens(paragraph_text)
            if not paragraph_tokens:
                continue
            first_hits = _best_edge_pages(paragraph_tokens, norm_pages, from_end=False)
            last_hits = _best_edge_pages(paragraph_tokens, norm_pages, from_end=True)
            if not first_hits and not last_hits:
                continue
            start_candidates = first_hits or last_hits
            end_candidates = last_hits or first_hits
            low, high = sorted((min(start_candidates), max(end_candidates)))
            matched_pages.update(number for number in known_pages if low <= number <= high)
        return [number for number in known_pages if number in matched_pages]

    def _match_page_set(self, heading_path: list[str], norm_pages: list[dict[str, Any]]) -> list[int]:
        """Find page references for each heading using the longest exact token match."""
        if not heading_path or not norm_pages:
            return []
        found: set[int] = set()
        for heading in heading_path:
            tokens = _tokens(heading)
            if not tokens:
                continue
            scores = [
                _longest_prefix_occurrence(tokens, page["tokens"])
                for page in norm_pages
            ]
            best = max(scores, default=0)
            if best:
                found.update(
                    page["page_number"]
                    for page, score in zip(norm_pages, scores)
                    if score == best
                )
        return sorted(found)

    def section_chunk(self, file: Any) -> list[str]:
        """Compatibility helper returning pipe-delimited complete sections."""
        return [
            " | ".join([*heading_path, body_text]) if heading_path else body_text
            for heading_path, body_text in _extract_sections(file)
        ]
