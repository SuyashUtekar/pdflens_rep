from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from app.schemas.models import Element, ExtractionField, Metadata, Page

_FURNITURE_FIELDS = {
    ExtractionField.HEADER,
    ExtractionField.FOOTER,
    ExtractionField.FOOTNOTE,
    ExtractionField.PAGE_NUMBER,
}
_FURNITURE_LABELS = {"page_header", "header", "running_header", "page_footer",
                     "footer", "running_footer", "footnote", "footnote_reference"}
_BODY_FIELDS = {
    ExtractionField.BODY_TEXT,
    ExtractionField.HEADING,
    ExtractionField.CAPTION,
    ExtractionField.LIST,
    ExtractionField.EQUATION,
    ExtractionField.FORM_FIELD,
    ExtractionField.CODE,
    ExtractionField.OTHER,
}
_PAGE_NUMBER_PATTERN = re.compile(
    r"(?:(?:page|p)\.?\s*)?\d{1,4}(?:\s*(?:/|of)\s*\d{1,4})?",
    re.IGNORECASE,
)


def _xml_safe_text(value: str | None) -> str:
    text = str(value or "")
    return "".join(
        character if (character in "\t\n\r"
                      or "\u0020" <= character <= "\uD7FF"
                      or "\uE000" <= character <= "\uFFFD"
                      or "\U00010000" <= character <= "\U0010FFFF")
        else "\uFFFD"
        for character in text
    )


def _normalize(text: str | None) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    value = re.sub(r"\(?cid:\d+\)?", " ", value)
    value = re.sub(r"^\s*\d+[.)]\s+", " ", value)
    return re.sub(r"[^\w]+", " ", value).strip()


def _is_furniture_element(element: Element) -> bool:
    label = str(element.attributes.get("parser_label", "")).strip().casefold()
    return element.type in _FURNITURE_FIELDS or label in _FURNITURE_LABELS


def _line_bounds(line: dict[str, Any]) -> tuple[float, float, float, float]:
    words = line["words"]
    return (
        min(float(word["x0"]) for word in words),
        min(float(word["top"]) for word in words),
        max(float(word["x1"]) for word in words),
        max(float(word["bottom"]) for word in words),
    )


def _pdf_page_lines(source_pdf_path: Path) -> list[dict[str, Any]]:
    """Read selectable PDF lines and their coordinates for fallback and page-number checks."""
    import pdfplumber

    result: list[dict[str, Any]] = []
    with pdfplumber.open(source_pdf_path) as pdf:
        for page in pdf.pages:
            words = sorted(page.extract_words(), key=lambda item: (item["top"], item["x0"]))
            lines: list[dict[str, Any]] = []
            for word in words:
                match = next((line for line in reversed(lines)
                              if word["top"] < line["bottom"]
                              and word["bottom"] > line["top"]), None)
                if match is None:
                    match = {"top": word["top"], "bottom": word["bottom"], "words": []}
                    lines.append(match)
                else:
                    match["top"] = min(match["top"], word["top"])
                    match["bottom"] = max(match["bottom"], word["bottom"])
                match["words"].append(word)
            for line in lines:
                line["words"].sort(key=lambda item: item["x0"])
                line["text"] = " ".join(str(item["text"]) for item in line["words"])
            result.append({"width": float(page.width), "height": float(page.height),
                           "lines": sorted(lines, key=lambda line: line["top"])})
    return result


def _element_rect(element: Element, width: float, height: float) -> tuple[float, float, float, float] | None:
    if element.bbox is None:
        return None
    return (element.bbox.x0 * width, element.bbox.y0 * height,
            element.bbox.x1 * width, element.bbox.y1 * height)


def _intersection_ratio(first: tuple[float, float, float, float],
                        second: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = first
    rx0, ry0, rx1, ry1 = second
    overlap = max(0.0, min(x1, rx1) - max(x0, rx0)) * max(
        0.0, min(y1, ry1) - max(y0, ry0)
    )
    return overlap / max(1.0, (x1 - x0) * (y1 - y0))


def _is_page_number_line(line: dict[str, Any], width: float, height: float) -> bool:
    text = re.sub(r"\s+", " ", str(line["text"] or "")).strip()
    if not _PAGE_NUMBER_PATTERN.fullmatch(text):
        return False
    x0, y0, x1, y1 = _line_bounds(line)
    return (x0 <= width * 0.08 or x1 >= width * 0.92
            or y0 <= height * 0.08 or y1 >= height * 0.92)


def _is_page_number_element(element: Element, source_page: dict[str, Any]) -> bool:
    if not element.text:
        return False
    text = re.sub(r"\s+", " ", element.text).strip()
    if not _PAGE_NUMBER_PATTERN.fullmatch(text):
        return False
    width, height = source_page["width"], source_page["height"]
    if element.attributes.get("source") == "pypdf_page_number":
        # pypdf supplies a baseline in bottom-origin points but no text box.
        # Require both an edge position and a matching PDF text line there.
        try:
            baseline = float(element.attributes["baseline_y_pt"])
        except (KeyError, TypeError, ValueError):
            return False
        top_origin_y = height - baseline
        if not (top_origin_y <= height * 0.08 or top_origin_y >= height * 0.92):
            return False
        tolerance_y = max(6.0, height * 0.012)
        normalized = _normalize(text)
        return any(
            _is_page_number_line(line, width, height)
            and _normalize(line["text"]) == normalized
            and abs((_line_bounds(line)[1] + _line_bounds(line)[3]) / 2 - top_origin_y)
            <= tolerance_y
            for line in source_page["lines"]
        )
    if element.bbox is None:
        return False
    item_rect = _element_rect(element, width, height)
    if item_rect is None:
        return False
    x0, y0, x1, y1 = item_rect
    if not (x0 <= width * 0.08 or x1 >= width * 0.92
            or y0 <= height * 0.08 or y1 >= height * 0.92):
        return False
    tolerance_x = max(6.0, width * 0.012)
    tolerance_y = max(6.0, height * 0.012)
    normalized = _normalize(text)
    for line in source_page["lines"]:
        if not _is_page_number_line(line, width, height) or _normalize(line["text"]) != normalized:
            continue
        line_rect = _line_bounds(line)
        if all(abs(a - b) <= tol for a, b, tol in zip(
            item_rect, line_rect, (tolerance_x, tolerance_y, tolerance_x, tolerance_y)
        )):
            return True
    return False


def _heading_marker_depth(text: str) -> int | None:
    match = re.match(r"^\s*[\(\[]?([A-Za-z0-9]+(?:[./-][A-Za-z0-9]+)*)[\)\].:]?\s+", text)
    if not match:
        return None
    marker = match.group(1)
    parts = [part for part in re.split(r"[./-]", marker) if part]
    explicit_alpha = bool(re.match(
        r"^[\(\[]?[A-Za-z][A-Za-z0-9]*[\)\].:]\s+", text.lstrip()
    ))
    if not any(part.isdigit() for part in parts) and not explicit_alpha:
        return None
    return len(parts)


def _heading_signature(text: str) -> tuple[tuple[str, ...], str, str] | None:
    tokens = text.strip().split()
    for split_at in range(1, len(tokens)):
        designator = tokens[split_at]
        punctuation = designator[-1:] if designator[-1:] in {":", "."} else ""
        value = designator[:-1] if punctuation else designator
        if punctuation and (value.isalpha() or value.isdigit()):
            label = tuple(token.casefold() for token in tokens[:split_at])
            return label, "numeric" if value.isdigit() else "alphabetic", punctuation
    return None


def _split_combined_heading(element: Element, source_page: dict[str, Any],
                            page: Page) -> list[tuple[float, float, str, int]]:
    """Split one Docling heading only when separate source lines support the split."""
    if element.type != ExtractionField.HEADING or not element.text or element.bbox is None:
        return []
    width, height = source_page["width"], source_page["height"]
    box = _element_rect(element, width, height)
    if box is None:
        return []
    _, box_top, _, box_bottom = box
    combined = _normalize(element.text)
    candidates = []
    for line in source_page["lines"]:
        x0, y0, x1, y1 = _line_bounds(line)
        center_y = (y0 + y1) / 2
        normalized_line = _normalize(line["text"])
        if box_top <= center_y <= box_bottom and normalized_line and normalized_line in combined:
            candidates.append({"top": y0, "left": x0, "text": line["text"]})
    candidates.sort(key=lambda candidate: (candidate["top"], candidate["left"]))
    if len(candidates) < 2:
        return []

    root_signature = _heading_signature(candidates[0]["text"])
    segments: list[dict[str, Any]] = []
    for candidate in candidates:
        marker_depth = _heading_marker_depth(candidate["text"])
        repeated_label = (root_signature is not None
                          and _heading_signature(candidate["text"]) == root_signature)
        if not segments or marker_depth is not None or repeated_label:
            segments.append({**candidate, "marker_depth": marker_depth})
        else:
            segments[-1]["text"] = f"{segments[-1]['text']} {candidate['text']}".strip()
    if len(segments) < 2:
        return []

    try:
        base_level = int(element.attributes.get("heading_level", 1) or 1)
    except (TypeError, ValueError):
        base_level = 1
    base_level = max(1, min(9, base_level))
    first_depth = segments[0]["marker_depth"]
    reconstructed = []
    for index, segment in enumerate(segments):
        if index == 0 or _heading_signature(segment["text"]) == root_signature:
            level = base_level
        elif segment["marker_depth"] is not None:
            offset = first_depth or 0
            level = base_level + max(1 if first_depth is None else 0,
                                     segment["marker_depth"] - offset)
        else:
            level = base_level
        reconstructed.append((segment["top"], segment["left"], segment["text"],
                              max(1, min(9, level))))
    return reconstructed


def _line_inside_structured_region(line: dict[str, Any], elements: list[Element],
                                   source_page: dict[str, Any]) -> bool:
    line_rect = _line_bounds(line)
    width, height = source_page["width"], source_page["height"]
    x_tolerance = max(4.0, width * 0.005)
    y_tolerance = max(8.0, height * 0.02)
    lx0, ly0, lx1, ly1 = line_rect
    for element in elements:
        if element.type not in {ExtractionField.TABLE, ExtractionField.IMAGE}:
            continue
        rect = _element_rect(element, width, height)
        if rect is None:
            continue
        rx0, ry0, rx1, ry1 = rect
        if (lx1 >= rx0 - x_tolerance and lx0 <= rx1 + x_tolerance
                and ly0 >= ry0 - y_tolerance and ly1 <= ry1 + y_tolerance):
            return True
    return False


def _line_is_represented(line: dict[str, Any], recognized_text: str) -> bool:
    line_tokens = _normalize(line["text"]).split()
    recognized_tokens = recognized_text.split()
    if not line_tokens or len(line_tokens) > len(recognized_tokens):
        return False
    size = len(line_tokens)
    return any(recognized_tokens[index:index + size] == line_tokens
               for index in range(len(recognized_tokens) - size + 1))


def _add_bookmark(paragraph: Any, bookmark_id: int, name: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(bookmark_id))
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(bookmark_id))
    paragraph_properties = paragraph._p.pPr
    insert_at = paragraph._p.index(paragraph_properties) + 1 if paragraph_properties is not None else 0
    paragraph._p.insert(insert_at, start)
    paragraph._p.append(end)


def _add_hyperlink(paragraph: Any, element: Element, page_bookmarks: set[int]) -> None:
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    uri = _xml_safe_text(element.target_uri) if element.target_uri else None
    visible_text = _xml_safe_text(element.text or uri or "")
    if not visible_text:
        return
    if uri:
        page_match = re.fullmatch(r"#page=(\d+)", uri)
        if page_match and int(page_match.group(1)) in page_bookmarks:
            hyperlink = OxmlElement("w:hyperlink")
            hyperlink.set(qn("w:anchor"), f"pdflens_page_{int(page_match.group(1))}")
        else:
            relationship = paragraph.part.relate_to(uri, RT.HYPERLINK, is_external=True)
            hyperlink = OxmlElement("w:hyperlink")
            hyperlink.set(qn("r:id"), relationship)
        run = OxmlElement("w:r")
        properties = OxmlElement("w:rPr")
        color = OxmlElement("w:color")
        color.set(qn("w:val"), "0563C1")
        properties.append(color)
        underline = OxmlElement("w:u")
        underline.set(qn("w:val"), "single")
        properties.append(underline)
        run.append(properties)
        text = OxmlElement("w:t")
        if visible_text != visible_text.strip():
            text.set(qn("xml:space"), "preserve")
        text.text = visible_text
        run.append(text)
        hyperlink.append(run)
        paragraph._p.append(hyperlink)
    else:
        paragraph.add_run(visible_text)


def _configure_document(document: Any, metadata: Metadata, margin_inches: float) -> None:
    from docx.shared import Inches, Pt, RGBColor

    document.core_properties.title = _xml_safe_text(
        metadata.document.title or metadata.document.source_filename
    )
    document.core_properties.subject = "PDFLens section-preserving PDF extraction"
    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(9)
    normal.paragraph_format.space_after = Pt(3)
    normal.paragraph_format.line_spacing = 1.0
    for level, size in enumerate((14, 12, 10.5, 9.5, 9, 9, 9, 9, 9), start=1):
        style = document.styles[f"Heading {level}"]
        style.font.name = "Arial"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.paragraph_format.space_before = Pt(5)
        style.paragraph_format.space_after = Pt(2)
        style.paragraph_format.keep_with_next = True
    if metadata.pages:
        first_section = document.sections[0]
        first_section.page_width = Pt(metadata.pages[0].width_pt)
        first_section.page_height = Pt(metadata.pages[0].height_pt)
    for section in document.sections:
        section.top_margin = Inches(margin_inches)
        section.bottom_margin = Inches(margin_inches)
        section.left_margin = Inches(margin_inches)
        section.right_margin = Inches(margin_inches)


def _render_element(document: Any, element: Element, tag_counters: dict[str, int],
                    page_bookmarks: set[int]) -> Any | None:
    text = _xml_safe_text(element.text)
    if element.type in _FURNITURE_FIELDS:
        return None
    if element.type == ExtractionField.IMAGE:
        tag_counters["image"] += 1
        tag_id = f"image_{tag_counters['image']}"
        element.attributes["docx_tag_id"] = tag_id
        return document.add_paragraph(f'<doc_ai type="image" id="{tag_id}"/>')
    if element.type == ExtractionField.TABLE:
        tag_counters["table"] += 1
        tag_id = f"table_{tag_counters['table']}"
        element.attributes["docx_tag_id"] = tag_id
        return document.add_paragraph(f'<doc_ai type="table" id="{tag_id}"/>')
    if element.type == ExtractionField.HEADING:
        raw_level = element.attributes.get("heading_level", 1)
        try:
            level = max(1, min(9, int(raw_level)))
        except (TypeError, ValueError):
            level = 1
        return document.add_paragraph(text, style=f"Heading {level}") if text.strip() else None
    if element.type == ExtractionField.LIST:
        label = str(element.attributes.get("parser_label", "")).casefold()
        style = "List Number" if any(token in label for token in ("ordered", "numbered")) else "List Bullet"
        return document.add_paragraph(text, style=style) if text.strip() else None
    if element.type == ExtractionField.HYPERLINK:
        paragraph = document.add_paragraph()
        _add_hyperlink(paragraph, element, page_bookmarks)
        return paragraph if paragraph.text.strip() or element.target_uri else None
    if element.type == ExtractionField.CAPTION:
        paragraph = document.add_paragraph(text)
        for run in paragraph.runs:
            run.italic = True
        return paragraph if text.strip() else None
    if element.type == ExtractionField.CODE:
        paragraph = document.add_paragraph(text)
        for run in paragraph.runs:
            run.font.name = "Courier New"
        return paragraph if text.strip() else None
    if element.type in _BODY_FIELDS and text.strip():
        return document.add_paragraph(text)
    return None


def build_preserved_docx(metadata: Metadata, source_pdf_path: Path, docx_path: Path,
                         margin_inches: float) -> None:
    """Build an editable, page-ordered DOCX using the notebook's preservation rules."""
    from docx import Document as WordDocument
    from docx.enum.section import WD_SECTION
    from docx.shared import Pt

    source_pages = _pdf_page_lines(source_pdf_path)
    document = WordDocument()
    _configure_document(document, metadata, margin_inches)
    first_paragraph_by_page: dict[int, Any] = {}
    tag_counters = {"image": 0, "table": 0}

    for page_index, page in enumerate(metadata.pages):
        source_page = (source_pages[page.page_number - 1]
                       if page.page_number - 1 < len(source_pages)
                       else {"width": page.width_pt, "height": page.height_pt, "lines": []})
        if page_index:
            section = document.add_section(WD_SECTION.NEW_PAGE)
            section.page_width = Pt(page.width_pt)
            section.page_height = Pt(page.height_pt)
            section.top_margin = Pt(margin_inches * 72)
            section.bottom_margin = Pt(margin_inches * 72)
            section.left_margin = Pt(margin_inches * 72)
            section.right_margin = Pt(margin_inches * 72)

        elements = sorted(page.elements, key=lambda item: item.reading_order)
        recognized = " ".join(
            element.text or "" for element in elements
            if not _is_furniture_element(element)
        )
        recognized_normalized = _normalize(recognized)
        furniture_rects = [
            rect for element in elements if _is_furniture_element(element)
            if (rect := _element_rect(element, source_page["width"], source_page["height"])) is not None
        ]
        positioned: list[tuple[float, float, int, str, Any]] = []
        sequence = 0
        for element in elements:
            if _is_furniture_element(element) or _is_page_number_element(element, source_page):
                continue
            rect = _element_rect(element, source_page["width"], source_page["height"])
            if element.type == ExtractionField.HEADING:
                split = _split_combined_heading(element, source_page, page)
                if split:
                    for top, left, heading_text, level in split:
                        positioned.append((top, left, sequence, "heading", (heading_text, level)))
                        sequence += 1
                    continue
            top, left = (rect[1], rect[0]) if rect is not None else (
                float("inf"), float(element.reading_order)
            )
            positioned.append((top, left, sequence, "element", element))
            sequence += 1

        # Restore selectable PDF lines omitted by Docling, except furniture, page
        # numbers, and lines inside structured image/table regions.
        for line in source_page["lines"]:
            line_text = str(line["text"] or "").strip()
            if not line_text or _is_page_number_line(line, source_page["width"], source_page["height"]):
                continue
            line_rect = _line_bounds(line)
            # Match the notebook's size-relative furniture bands for PDF-only
            # fallback lines; detected Docling body elements remain untouched.
            if (line_rect[1] <= source_page["height"] * 0.055
                    or line_rect[3] >= source_page["height"] * 0.945):
                continue
            if any(_intersection_ratio(line_rect, rect) >= 0.35 for rect in furniture_rects):
                continue
            if _line_is_represented(line, recognized_normalized):
                continue
            if _line_inside_structured_region(line, elements, source_page):
                continue
            positioned.append((line_rect[1], line_rect[0], sequence, "fallback", line_text))
            sequence += 1

        positioned.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
        first_page_paragraph = None
        for _top, _left, _sequence, kind, payload in positioned:
            if kind == "heading":
                text, level = payload
                paragraph = document.add_paragraph(_xml_safe_text(text), style=f"Heading {level}")
            elif kind == "fallback":
                paragraph = document.add_paragraph(_xml_safe_text(payload))
            else:
                paragraph = _render_element(document, payload, tag_counters,
                                            {item.page_number for item in metadata.pages})
            if paragraph is not None and first_page_paragraph is None:
                first_page_paragraph = paragraph
        if first_page_paragraph is None:
            first_page_paragraph = document.add_paragraph()
        first_paragraph_by_page[page.page_number] = first_page_paragraph

    # Add stable in-document targets after content has been written.
    for bookmark_id, (page_number, paragraph) in enumerate(first_paragraph_by_page.items(), start=1):
        _add_bookmark(paragraph, bookmark_id, f"pdflens_page_{page_number}")
    document.save(docx_path)
