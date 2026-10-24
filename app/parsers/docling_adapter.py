from __future__ import annotations

from importlib.util import find_spec
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from collections import Counter
import math
import os
import re
import unicodedata

from app.parsers.base import ParsedAsset, ParsedDocument
from app.schemas.models import BODY_CONTENT_FIELDS, BoundingBox, Element, ExtractionField, Page

FURNITURE_ZONE_FRACTION = float(os.getenv("PDFLENS_FURNITURE_ZONE_FRACTION", "0.12"))
FURNITURE_REPEAT_FRACTION = float(os.getenv("PDFLENS_FURNITURE_REPEAT_FRACTION", "0.10"))
FOOTNOTE_ZONE_START = float(os.getenv("PDFLENS_FOOTNOTE_ZONE_START", "0.78"))
BODY_COVERAGE_REVIEW_THRESHOLD = float(os.getenv("PDFLENS_BODY_COVERAGE_REVIEW_THRESHOLD", "0.90"))
BODY_COVERAGE_RECOVERY_THRESHOLD = float(os.getenv("PDFLENS_BODY_COVERAGE_RECOVERY_THRESHOLD", "0.75"))
if not 0 < FURNITURE_ZONE_FRACTION < 0.5:
    raise RuntimeError("PDFLENS_FURNITURE_ZONE_FRACTION must be between 0 and 0.5")
if not 0 < FURNITURE_REPEAT_FRACTION <= 1:
    raise RuntimeError("PDFLENS_FURNITURE_REPEAT_FRACTION must be in (0, 1]")
if not 0 < FOOTNOTE_ZONE_START < 1:
    raise RuntimeError("PDFLENS_FOOTNOTE_ZONE_START must be between 0 and 1")
if not 0 <= BODY_COVERAGE_RECOVERY_THRESHOLD < BODY_COVERAGE_REVIEW_THRESHOLD <= 1:
    raise RuntimeError("Body coverage thresholds must satisfy 0 <= recovery < review <= 1")


class ParserUnavailableError(RuntimeError):
    """The configured parser package is not installed or importable."""


class ParserExecutionError(RuntimeError):
    """Parsing failed; diagnostic fields intentionally exclude document content."""

    def __init__(self, stage: str, cause_type: str):
        super().__init__(f"Docling failed during {stage} ({cause_type})")
        self.stage = stage
        self.cause_type = cause_type


class DoclingAdapter:
    """Thin Docling adapter. Native labels are retained for later mapping review."""

    def parse(self, pdf_path: str, requested: set[ExtractionField]) -> ParsedDocument:
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as exc:
            raise ParserUnavailableError("Docling is not installed in the active environment.") from exc

        try:
            options = PdfPipelineOptions()
            if requested.intersection({ExtractionField.IMAGE, ExtractionField.TABLE}):
                options.generate_page_images = True
                options.generate_picture_images = True
            converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
            )
            doc = converter.convert(pdf_path).document
        except Exception as exc:
            raise ParserExecutionError("conversion", type(exc).__name__) from exc
        page_items = getattr(doc, "pages", {})
        page_keys = sorted(page_items, key=self._page_key_sort) if page_items else []
        try:
            from pypdf import PdfReader

            source_pages = PdfReader(pdf_path, strict=False).pages
            source_dimensions = [(float(source_page.mediabox.width),
                                 float(source_page.mediabox.height))
                                for source_page in source_pages]
            source_texts = []
            for source_page in source_pages:
                try:
                    source_texts.append(source_page.extract_text() or "")
                except Exception:
                    source_texts.append("")
        except Exception:
            source_dimensions = []
            source_texts = []
        pages: list[Page] = []
        physical_page_count = max(len(page_keys), len(source_dimensions), len(source_texts))
        for idx in range(1, physical_page_count + 1):
            native_page = page_items[page_keys[idx - 1]] if idx <= len(page_keys) else None
            size = getattr(native_page, "size", None)
            source_size = source_dimensions[idx - 1] if idx <= len(source_dimensions) else (None, None)
            width_value = getattr(size, "width", None) or source_size[0]
            height_value = getattr(size, "height", None) or source_size[1]
            if not width_value or not height_value:
                raise ParserExecutionError("normalization", "PageGeometryUnavailable")
            width = float(width_value)
            height = float(height_value)
            source_text = source_texts[idx - 1] if idx <= len(source_texts) else ""
            pages.append(Page(page_number=idx, physical_page_index=idx,
                              source_text_char_count=len(source_text.strip()),
                              width_pt=width, height_pt=height,
                              rotation_degrees=int(getattr(native_page, "rotation", 0) or 0)))

        elements: list[Element] = []
        assets: list[ParsedAsset] = []
        asset_warnings: list[str] = []
        next_order: dict[int, int] = {}
        try:
            native_items = list(doc.iterate_items())
            furniture_items = self._extract_docling_furniture(doc)
            native_items.extend((item, 0) for item in furniture_items)

            for i, item in enumerate(native_items):
                obj = item[0] if isinstance(item, tuple) else item
                label_raw = str(getattr(getattr(obj, "label", None), "value", getattr(obj, "label", "text"))).lower()
                text = getattr(obj, "text", None)
                prov = getattr(obj, "prov", None) or []
                page_no = int(getattr(prov[0] if prov else None, "page_no", 1) or 1)
                if page_no < 1 or page_no > len(pages):
                    continue
                bbox = None
                if prov:
                    raw = getattr(prov[0], "bbox", None)
                    if raw:
                        bbox = self._normalize_bbox(raw, pages[page_no - 1])
                kind = self._map_label(label_raw, text, bbox)
                if kind not in requested:
                    # Keep the text available to consumers that asked for general body text.
                    if (kind in {ExtractionField.HEADER, ExtractionField.FOOTER,
                                 ExtractionField.FOOTNOTE, ExtractionField.PAGE_NUMBER}
                            and ExtractionField.BODY_TEXT in requested):
                        kind = ExtractionField.BODY_TEXT
                    elif (kind == ExtractionField.BODY_TEXT
                          and requested.intersection({ExtractionField.HEADER, ExtractionField.FOOTER})):
                        pass  # Retain candidates until repeated page-edge classification is complete.
                    else:
                        continue
                order = next_order.get(page_no, 0)
                next_order[page_no] = order + 1
                element_id = f"p{page_no:04d}-e{i+1:04d}"
                element = Element(element_id=element_id, type=kind,
                                        text=str(text) if text is not None else None,
                                        reading_order=order, bbox=bbox,
                                        attributes={"parser_label": label_raw})
                if kind == ExtractionField.FOOTNOTE:
                    element.confidence = 1.0 if "footnote" in label_raw else 0.55
                    element.attributes["classification_reason"] = (
                        "docling_footnote_label" if "footnote" in label_raw
                        else "marker_pattern_in_lower_page_region"
                    )
                    if element.confidence < 0.7:
                        pages[page_no - 1].warnings.append(
                            "FOOTNOTE_CLASSIFICATION_LOW_CONFIDENCE"
                        )
                if kind == ExtractionField.HEADER:
                    element.confidence = 1.0
                    element.attributes["classification_reason"] = "docling_furniture_label"
                elif kind == ExtractionField.FOOTER:
                    element.confidence = 1.0
                    element.attributes["classification_reason"] = "docling_furniture_label"
                if kind == ExtractionField.TABLE:
                    self._attach_table_structure(obj, element, pages[page_no - 1])
                if kind == ExtractionField.HEADING:
                    heading_level = getattr(obj, "level", None)
                    if heading_level is not None:
                        element.attributes["heading_level"] = heading_level
                elements.append(element)
                if (kind == ExtractionField.FOOTNOTE and element.confidence is not None
                        and element.confidence < 0.7
                        and ExtractionField.BODY_TEXT in requested and element.text):
                    elements.append(Element(
                        element_id=f"{element_id}-body-candidate",
                        type=ExtractionField.BODY_TEXT, text=element.text,
                        reading_order=order, bbox=bbox, confidence=element.confidence,
                        attributes={"source": "uncertain_footnote_candidate",
                                    "preserved_in_body_text": True},
                    ))
                if kind in {ExtractionField.IMAGE, ExtractionField.TABLE}:
                    try:
                        image_getter = getattr(obj, "get_image", None)
                        crop = image_getter(doc) if image_getter else None
                        if crop is None:
                            raise ValueError("Parser did not provide an image crop")
                        stream = BytesIO()
                        crop.save(stream, format="PNG")
                        assets.append(ParsedAsset(element_id=element_id, page_number=page_no,
                                                  asset_type=kind, content=stream.getvalue()))
                    except Exception as exc:
                        element.attributes["artifact_warning"] = "Parser did not provide an image crop."
                        pages[page_no - 1].warnings.append(f"{kind.value.upper()}_SNAPSHOT_FAILED")
                        asset_warnings.append(
                            f"Could not create {kind.value} snapshot for {element_id} ({type(exc).__name__})."
                        )
            for element in elements:
                pages[int(element.element_id[1:5]) - 1].elements.append(element)
            if requested.intersection({ExtractionField.HEADER, ExtractionField.FOOTER}):
                self._append_repeated_pdf_edge_furniture(pdf_path, pages)
            if ExtractionField.BODY_TEXT in requested:
                self._apply_empty_page_fallback(pages, source_texts)
        except Exception as exc:
            raise ParserExecutionError("normalization", type(exc).__name__) from exc
        if requested.intersection({ExtractionField.HEADER, ExtractionField.FOOTER}):
            self._classify_repeated_page_edges(pages)
        for page in pages:
            page.elements.sort(key=lambda element: (
                0 if element.type == ExtractionField.HEADER else
                2 if element.type == ExtractionField.FOOTNOTE else
                3 if element.type == ExtractionField.FOOTER else
                4 if element.type == ExtractionField.PAGE_NUMBER else 1,
                element.reading_order,
            ))
            for reading_order, element in enumerate(page.elements):
                element.reading_order = reading_order
        link_warnings: list[str] = []
        page_number_warnings: list[str] = []
        if requested.intersection({ExtractionField.PAGE_NUMBER, ExtractionField.BODY_TEXT}):
            try:
                self._append_pdf_page_numbers(pdf_path, pages, requested)
            except Exception as exc:
                page_number_warnings.append(
                    f"PDF page-number extraction failed ({type(exc).__name__})."
                )
        if ExtractionField.HYPERLINK in requested:
            try:
                self._append_pdf_links(pdf_path, pages, link_warnings)
                self._append_internal_pdf_links(pdf_path, pages, link_warnings)
            except Exception as exc:
                link_warnings.append(f"Hyperlink annotation extraction failed ({type(exc).__name__}).")
        if ExtractionField.FOOTNOTE in requested:
            self._associate_footnote_markers(pages)
        self._order_page_elements(pages)
        try:
            parser_version = version("docling")
        except PackageNotFoundError:
            parser_version = "unknown"
        extracted = {element.type for page in pages for element in page.elements}
        return ParsedDocument(pages, "docling", parser_version,
                              title=getattr(getattr(doc, "name", None), "value", None),
                              warnings=["Parser mapping and coordinate convention require corpus validation.",
                                        "Headers and footers use Docling furniture-tree items and explicit text labels; page numbers are inferred separately.",
                                        *[f"page {page.page_number}: {warning}"
                                          for page in pages for warning in page.warnings],
                                        *asset_warnings, *link_warnings, *page_number_warnings],
                              extracted_fields=extracted, assets=assets)

    @staticmethod
    def _page_key_sort(value: object) -> tuple[int, object]:
        label = str(value)
        try:
            return (0, int(label))
        except ValueError:
            match = re.search(r"\d+", label)
            return (0, int(match.group())) if match else (1, label)

    @staticmethod
    def _normalize_bbox(raw: object, page: Page) -> BoundingBox:
        coords = [float(getattr(raw, attr)) for attr in ("l", "t", "r", "b")]
        origin = getattr(getattr(raw, "coord_origin", "TOPLEFT"), "value",
                         getattr(raw, "coord_origin", "TOPLEFT"))
        if str(origin).upper() == "BOTTOMLEFT":
            top, bottom = page.height_pt - coords[1], page.height_pt - coords[3]
        elif str(origin).upper() == "TOPLEFT":
            top, bottom = coords[1], coords[3]
        else:
            raise ValueError(f"Unsupported Docling coordinate origin: {origin}")
        return BoundingBox(x0=max(0, min(1, coords[0] / page.width_pt)),
                           y0=max(0, min(1, top / page.height_pt)),
                           x1=max(0, min(1, coords[2] / page.width_pt)),
                           y1=max(0, min(1, bottom / page.height_pt)))

    @staticmethod
    def _map_label(label: str, text: object, bbox: BoundingBox | None) -> ExtractionField:
        if "footnote" in label:
            return ExtractionField.FOOTNOTE
        # Docling's section_header label describes headings, not page headers.
        if any(word in label for word in ("title", "section_header", "heading")):
            return ExtractionField.HEADING
        if label in {"header", "page_header", "running_header"}:
            return ExtractionField.HEADER
        if label in {"footer", "page_footer", "running_footer"}:
            return ExtractionField.FOOTER
        if "table" in label:
            return ExtractionField.TABLE
        if any(word in label for word in ("picture", "image", "figure")):
            return ExtractionField.IMAGE
        if "list" in label:
            return ExtractionField.LIST
        if "caption" in label:
            return ExtractionField.CAPTION
        if "code" in label:
            return ExtractionField.CODE
        if isinstance(text, str) and bbox is not None and bbox.y0 >= FOOTNOTE_ZONE_START:
            footnote_marker = re.match(r"^\s*(?:\[\d+\]|\(\d+\)|\d{1,2}[.)]|[*†‡])\s+", text)
            if footnote_marker:
                return ExtractionField.FOOTNOTE
        return ExtractionField.BODY_TEXT if text else ExtractionField.OTHER

    @staticmethod
    def _extract_docling_furniture(document) -> list[object]:
        """Collect explicitly labeled page furniture through the tree and text-item paths."""
        def normalize_label(item: object) -> str:
            label = getattr(item, "label", None)
            if label is None:
                return ""
            return str(getattr(label, "value", label)).lower()

        def resolve_ref(ref: object) -> object | None:
            try:
                return ref.resolve(doc=document)
            except (AttributeError, TypeError, ValueError):
                return None

        found: list[object] = []
        visited: set[str] = set()

        def walk(node: object | None) -> None:
            if node is None:
                return
            item_ref = getattr(node, "self_ref", None)
            if item_ref is not None:
                ref_key = str(item_ref)
                if ref_key in visited:
                    return
                visited.add(ref_key)
            if normalize_label(node) in {"page_header", "page_footer"}:
                found.append(node)
            for child_ref in getattr(node, "children", []) or []:
                walk(resolve_ref(child_ref))

        walk(getattr(document, "furniture", None))
        for item in getattr(document, "texts", []) or []:
            if normalize_label(item) in {"page_header", "page_footer"}:
                found.append(item)

        unique: list[object] = []
        seen: set[tuple[object, ...]] = set()
        for item in found:
            label = normalize_label(item)
            text = getattr(item, "text", None)
            provenance = getattr(item, "prov", []) or []
            locations = tuple(
                (getattr(location, "page_no", None),
                 tuple(getattr(getattr(location, "bbox", None), attr, None)
                       for attr in ("l", "t", "r", "b")))
                for location in provenance
            )
            key = (str(getattr(item, "self_ref", None)), label, text, locations)
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    @classmethod
    def _attach_table_structure(cls, item: object, element: Element, page: Page) -> None:
        table_data = getattr(item, "data", None)
        cells = getattr(table_data, "table_cells", None) or []
        structured_cells: list[dict[str, object]] = []
        for cell in cells:
            cell_data: dict[str, object] = {
                "text": str(getattr(cell, "text", "") or ""),
                "row_index": int(getattr(cell, "start_row_offset_idx", 0) or 0),
                "column_index": int(getattr(cell, "start_col_offset_idx", 0) or 0),
                "row_span": max(1, int(getattr(cell, "row_span", 1) or 1)),
                "column_span": max(1, int(getattr(cell, "col_span", 1) or 1)),
                "is_column_header": bool(getattr(cell, "column_header", False)),
                "is_row_header": bool(getattr(cell, "row_header", False)),
            }
            raw_bbox = getattr(cell, "bbox", None)
            if raw_bbox is not None:
                try:
                    cell_data["bbox"] = cls._normalize_bbox(raw_bbox, page).model_dump()
                except (AttributeError, TypeError, ValueError):
                    cell_data["bbox"] = None
            structured_cells.append(cell_data)
        if structured_cells:
            row_count = max(cell["row_index"] + cell["row_span"]
                            for cell in structured_cells)
            column_count = max(cell["column_index"] + cell["column_span"]
                               for cell in structured_cells)
            element.attributes["table_status"] = "structured"
            element.attributes["table_validation_status"] = "needs_review"
            element.attributes["table_cells"] = structured_cells
            element.attributes["table_metrics"] = {
                "cell_count": len(structured_cells),
                "row_count": row_count,
                "column_count": column_count,
                "empty_cell_count": sum(not cell["text"].strip() for cell in structured_cells),
                "structural_validation": "not_performed",
            }
            page.warnings.append("TABLE_STRUCTURED_NEEDS_REVIEW")
        else:
            element.attributes["table_status"] = "visual_only"
            element.attributes["table_validation_status"] = "needs_review"
            page.warnings.append("TABLE_VISUAL_ONLY")

    @staticmethod
    def _apply_empty_page_fallback(pages: list[Page], source_texts: list[str]) -> None:
        for page in pages:
            source_text = (source_texts[page.page_number - 1]
                           if page.page_number <= len(source_texts) else "")
            has_body_text = any(
                element.type == ExtractionField.BODY_TEXT and element.text
                for element in page.elements
            )
            overlap_chars = 0
            overlap_decisions: list[dict[str, object]] = []
            if source_text.strip():
                # Docling may emit headings, captions, or furniture without any body
                # blocks. Remove those exact spans from the full-page fallback so the
                # same source text is not represented twice in metadata/DOCX.
                fallback_text = source_text
                for element in page.elements:
                    observed_texts = [element.text or ""]
                    observed_texts.extend(
                        str(cell.get("text", ""))
                        for cell in element.attributes.get("table_cells", [])
                        if isinstance(cell, dict)
                    )
                    for observed_text in observed_texts:
                        if len(observed_text.strip()) < 4:
                            continue
                        tokens = observed_text.split()
                        if not tokens:
                            continue
                        pattern = r"\s+".join(re.escape(token) for token in tokens)
                        fallback_text, removed = re.subn(
                            pattern, " ", fallback_text, count=1, flags=re.IGNORECASE
                        )
                        if removed:
                            overlap_chars += len(observed_text)
                            overlap_decisions.append({
                                "element_id": element.element_id,
                                "element_type": element.type.value,
                                "source_char_count": len(observed_text),
                                "decision": "excluded_from_empty_page_fallback",
                            })
                fallback_text = re.sub(r"[ \t]+", " ", fallback_text)
                fallback_text = re.sub(r"\n\s*\n\s*\n+", "\n\n", fallback_text).strip()
            else:
                fallback_text = source_text.strip()
            def element_text(element: Element) -> str:
                table_text = " ".join(
                    str(cell.get("text", ""))
                    for cell in element.attributes.get("table_cells", [])
                    if isinstance(cell, dict)
                )
                return " ".join(value for value in (element.text or "", table_text) if value)

            primary_text = "\n".join(
                element_text(element) for element in page.elements if element.text or
                element.attributes.get("table_cells")
            )
            source_tokens = list(re.finditer(r"\w+", source_text, flags=re.UNICODE))
            primary_tokens = list(re.finditer(r"\w+", primary_text, flags=re.UNICODE))
            def normalize(value: str) -> str:
                return unicodedata.normalize("NFC", value).casefold()

            source_values = [normalize(match.group()) for match in source_tokens]
            primary_values = [normalize(match.group()) for match in primary_tokens]
            available = Counter(primary_values)
            missing_indices: list[int] = []
            for token_index, token in enumerate(source_values):
                if available[token]:
                    available[token] -= 1
                else:
                    missing_indices.append(token_index)
            coverage = ((len(source_tokens) - len(missing_indices)) / len(source_tokens)
                        if source_tokens else None)
            page.source_text_coverage_before_recovery = coverage
            page.unmatched_source_token_count = len(missing_indices)
            missing_runs: list[tuple[int, int]] = []
            for token_index in missing_indices:
                if missing_runs and token_index == missing_runs[-1][1]:
                    missing_runs[-1] = (missing_runs[-1][0], token_index + 1)
                else:
                    missing_runs.append((token_index, token_index + 1))
            page.missing_span_count = len(missing_runs)
            page.unmatched_source_char_count = sum(
                source_tokens[end - 1].end() - source_tokens[start].start()
                for start, end in missing_runs
            )
            if coverage is not None and coverage < BODY_COVERAGE_REVIEW_THRESHOLD:
                page.warnings.append("BODY_TEXT_SOURCE_COVERAGE_LOW")
            recovered = 0
            if fallback_text and source_tokens and has_body_text and (
                coverage is not None and coverage < BODY_COVERAGE_REVIEW_THRESHOLD
            ):
                # Recover source-only runs as separate, provenance-tagged body blocks.
                # Source character offsets allow downstream consumers to audit where
                # the recovered text came from without replacing Docling's structure.
                for index, (source_start, source_end) in enumerate(missing_runs):
                    first = source_tokens[source_start]
                    last = source_tokens[source_end - 1]
                    start, end = first.start(), last.end()
                    snippet = source_text[start:end].strip()
                    if not snippet:
                        continue
                    recovered += len(snippet)
                    page.elements.append(Element(
                        element_id=f"p{page.page_number:04d}-pypdf-recovery-{index + 1:03d}",
                        type=ExtractionField.BODY_TEXT,
                        text=snippet,
                        reading_order=max((element.reading_order for element in page.elements),
                                          default=-1) + 1,
                        attributes={"source": "pypdf_fallback",
                                    "fallback_reason": "unmatched_source_text_span",
                                    "source_char_start": start,
                                    "source_char_end": end,
                                    "source_token_start": source_start,
                                    "source_token_end": source_end,
                                    "parser_label": "pypdf_text"},
                    ))
                if recovered:
                    page.warnings.append("BODY_TEXT_PARTIAL_FALLBACK_USED")
            page.recovered_source_char_count = recovered
            page.fallback_used = bool(recovered or (not has_body_text and fallback_text))
            page.fallback_chars_added = (
                recovered if recovered else len(fallback_text) if not has_body_text else 0
            )
            page.fallback_overlap_chars_removed = overlap_chars if not has_body_text else 0
            page.fallback_overlap_decisions = overlap_decisions if not has_body_text else []
            if not has_body_text and not recovered and fallback_text:
                page.elements.append(Element(
                    element_id=f"p{page.page_number:04d}-pypdf-body",
                    type=ExtractionField.BODY_TEXT, text=fallback_text,
                    reading_order=max((element.reading_order for element in page.elements),
                                      default=-1) + 1,
                    attributes={"source": "pypdf_fallback",
                                "fallback_reason": "docling_body_text_empty",
                                "overlap_removed_char_count": overlap_chars,
                                "parser_label": "pypdf_text"},
                ))
                page.warnings.append("BODY_TEXT_FALLBACK_USED")
            if not has_body_text and overlap_chars:
                page.warnings.append("BODY_TEXT_FALLBACK_OVERLAP_REMOVED")
            if not has_body_text and fallback_text:
                # The optional font decoder warning is relevant to the affected text,
                # not every page that happens to use pypdf as a fallback.
                if "\ufffd" in fallback_text and find_spec("fontTools") is None:
                    page.warnings.append("PYPDF_FONTTOOLS_UNAVAILABLE_WITH_UNICODE_SUSPECT")
            elif not has_body_text and not fallback_text:
                page.warnings.append("BODY_TEXT_SOURCE_LAYER_EMPTY")
            recovered_text = "\n".join(
                element_text(element) for element in page.elements if element.text or
                element.attributes.get("table_cells")
            )
            page.normalized_source_char_count = len(
                re.sub(r"\s+", " ", unicodedata.normalize("NFC", source_text)).strip()
            )
            page.normalized_output_char_count = len(
                re.sub(r"\s+", " ", unicodedata.normalize("NFC", recovered_text)).strip()
            )
            recovered_values = [
                normalize(match.group())
                for match in re.finditer(r"\w+", recovered_text, flags=re.UNICODE)
            ]
            final_available = Counter(recovered_values)
            final_matched = 0
            for token in source_values:
                if final_available[token]:
                    final_available[token] -= 1
                    final_matched += 1
            page.source_text_coverage_ratio = (
                final_matched / len(source_tokens) if source_tokens else None
            )

    @staticmethod
    def _classify_repeated_page_edges(pages: list[Page]) -> None:
        occurrences: dict[tuple[str, str], set[int]] = {}
        for page in pages:
            for element in page.elements:
                if element.type != ExtractionField.BODY_TEXT or not element.text or not element.bbox:
                    continue
                if element.bbox.y1 <= FURNITURE_ZONE_FRACTION:
                    zone = "header"
                    key = re.sub(r"\s+", " ", element.text).strip().casefold()
                elif element.bbox.y0 >= 1 - FURNITURE_ZONE_FRACTION:
                    zone = "footer"
                    key = re.sub(r"\s+", " ", element.text).strip().casefold()
                else:
                    continue
                if key:
                    occurrences.setdefault((zone, key), set()).add(page.page_number)

        repeating = {candidate for candidate, page_numbers in occurrences.items()
                     if len(page_numbers) >= 2}
        if not repeating:
            return
        for page in pages:
            for element in page.elements:
                if element.type != ExtractionField.BODY_TEXT or not element.text or not element.bbox:
                    continue
                key = re.sub(r"\s+", " ", element.text).strip().casefold()
                if element.bbox.y1 <= FURNITURE_ZONE_FRACTION:
                    zone = "header"
                elif element.bbox.y0 >= 1 - FURNITURE_ZONE_FRACTION:
                    zone = "footer"
                else:
                    continue
                if (zone, key) not in repeating:
                    continue
                if zone == "header":
                    element.type = ExtractionField.HEADER
                    element.attributes["classification_reason"] = "repeated_text_at_page_top"
                    element.confidence = 0.8
                else:
                    element.type = ExtractionField.FOOTER
                    element.attributes["classification_reason"] = "repeated_text_at_page_bottom"
                    element.confidence = 0.8

    @staticmethod
    def _append_repeated_pdf_edge_furniture(pdf_path: str, pages: list[Page]) -> None:
        """Use repeated PDF text spans as a second signal alongside Docling furniture."""
        from pypdf import PdfReader, mult

        candidates: list[tuple[int, str, str, BoundingBox, float]] = []
        reader = PdfReader(pdf_path, strict=False)
        for page_index, pdf_page in enumerate(reader.pages[:len(pages)]):
            height = float(pdf_page.mediabox.height)
            width = float(pdf_page.mediabox.width)
            if height <= 0 or width <= 0:
                continue

            def visit(text, cm, tm, _font, font_size):
                value = " ".join(str(text).split()).strip()
                if len(value) < 3:
                    return
                normalized = re.sub(r"\s+", " ", value).casefold()
                if re.fullmatch(r"(?:page\s+)?\d{1,4}(?:\s+of\s+\d{1,4})?|[ivxlcdm]+", normalized):
                    return
                matrix = mult(tm, cm)
                baseline = float(matrix[5])
                size = float(font_size or 0)
                top = max(0, min(1, 1 - (baseline + size) / height))
                bottom = max(0, min(1, 1 - baseline / height))
                if bottom <= FURNITURE_ZONE_FRACTION:
                    zone = "header"
                elif top >= 1 - FURNITURE_ZONE_FRACTION:
                    zone = "footer"
                else:
                    return
                x0 = max(0, min(1, float(matrix[4]) / width))
                x1 = max(x0, min(1, (float(matrix[4]) + max(size, len(value) * size * 0.4)) / width))
                box = BoundingBox(x0=x0, y0=max(0, top), x1=x1, y1=min(1, bottom))
                candidates.append((page_index + 1, zone, value, box, size))

            pdf_page.extract_text(visitor_text=visit)

        counts: dict[tuple[str, str], set[int]] = {}
        for page_no, zone, value, _box, _size in candidates:
            key = re.sub(r"\s+", " ", value).strip().casefold()
            counts.setdefault((zone, key), set()).add(page_no)
        minimum_pages = max(2, math.ceil(len(pages) * FURNITURE_REPEAT_FRACTION))
        repeating = {key: page_numbers for key, page_numbers in counts.items()
                     if len(page_numbers) >= minimum_pages}
        for page_no, zone, value, box, size in candidates:
            key = (zone, re.sub(r"\s+", " ", value).strip().casefold())
            page_numbers = repeating.get(key)
            if page_numbers is None:
                continue
            page = pages[page_no - 1]
            kind = ExtractionField.HEADER if zone == "header" else ExtractionField.FOOTER
            existing = next((element for element in page.elements
                             if element.text and " ".join(element.text.split()).casefold() == key[1]
                             and element.type in {ExtractionField.BODY_TEXT,
                                                  ExtractionField.HEADER,
                                                  ExtractionField.FOOTER}), None)
            if existing is not None:
                existing.type = kind
                existing.bbox = existing.bbox or box
                existing.confidence = max(existing.confidence or 0, 0.75)
                existing.attributes["classification_reason"] = "repeated_pdf_edge_text"
                existing.attributes["repeat_page_count"] = len(page_numbers)
                existing.attributes["font_size_pt"] = round(size, 2)
                continue
            if any(element.type == kind and element.text
                   and " ".join(element.text.split()).casefold() == key[1]
                   for element in page.elements):
                continue
            page.elements.append(Element(
                element_id=f"p{page_no:04d}-pdf-{zone}-{len(page.elements)+1:04d}",
                type=kind, text=value,
                reading_order=max((element.reading_order for element in page.elements),
                                  default=-1) + 1,
                bbox=box, confidence=0.75,
                attributes={"source": "pdf_repeated_edge_text",
                            "classification_reason": "repeated_pdf_edge_text",
                            "repeat_page_count": len(page_numbers),
                            "font_size_pt": round(size, 2)},
            ))
    @staticmethod
    def _append_pdf_page_numbers(pdf_path: str, pages: list[Page],
                                 requested: set[ExtractionField]) -> None:
        from pypdf import PdfReader, mult

        reader = PdfReader(pdf_path, strict=False)
        for page_index, pdf_page in enumerate(reader.pages):
            if page_index >= len(pages):
                break
            height = float(pdf_page.mediabox.height)
            page = pages[page_index]

            def visit(text, cm, tm, _font, font_size):
                line = " ".join(str(text).split())
                if not line or height <= 0:
                    return
                matrix = mult(tm, cm)
                baseline = float(matrix[5])
                normalized = re.sub(r"\s+", " ", text).strip().casefold()
                if not re.fullmatch(
                    r"page\s+\d+(?:\s+of\s+\d+)?|\d{1,4}|[ivxlcdm]+|[a-z]-\d+",
                    normalized,
                ):
                    return
                vertical_position = baseline / height
                if vertical_position < 0 or vertical_position > 1:
                    return
                if (FURNITURE_ZONE_FRACTION < vertical_position
                        < 1 - FURNITURE_ZONE_FRACTION):
                    return
                if page.printed_page_label is None:
                    page.printed_page_label = line
                if ExtractionField.PAGE_NUMBER not in requested:
                    if ExtractionField.BODY_TEXT in requested:
                        kind = ExtractionField.BODY_TEXT
                    else:
                        return
                else:
                    kind = ExtractionField.PAGE_NUMBER
                if kind == ExtractionField.PAGE_NUMBER and any(
                    element.type == ExtractionField.PAGE_NUMBER for element in page.elements
                ):
                    return
                matching_elements = [
                    element for element in page.elements
                    if element.text
                    and re.sub(r"\s+", " ", element.text).strip().casefold() == normalized
                ]
                if any(element.type == kind for element in matching_elements):
                    return
                page.elements.append(Element(
                    element_id=f"p{page.page_number:04d}-pdf-{kind.value}-{len(page.elements)+1:04d}",
                    type=kind,
                    text=text,
                    reading_order=max((element.reading_order for element in page.elements), default=-1) + 1,
                    attributes={"source": "pypdf_page_number", "baseline_y_pt": round(baseline, 2),
                                "font_size_pt": round(float(font_size or 0), 2)},
                ))

            pdf_page.extract_text(visitor_text=visit)

    @staticmethod
    def _order_page_elements(pages: list[Page]) -> None:
        priority = {
            ExtractionField.HEADER: 0,
            ExtractionField.FOOTNOTE: 2,
            ExtractionField.FOOTER: 3,
            ExtractionField.PAGE_NUMBER: 4,
        }
        for page in pages:
            page.elements.sort(key=lambda element: (
                priority.get(element.type, 1), element.reading_order,
            ))
            for reading_order, element in enumerate(page.elements):
                element.reading_order = reading_order

    @staticmethod
    def _append_pdf_links(pdf_path: str, pages: list[Page], warnings: list[str]) -> None:
        import pdfplumber
        from urllib.parse import urlsplit

        with pdfplumber.open(pdf_path) as pdf:
            for page_index, source_page in enumerate(pdf.pages):
                if page_index >= len(pages):
                    break
                page = pages[page_index]
                width = float(source_page.width)
                height = float(source_page.height)
                link_index = 0
                annotation_count = len(source_page.hyperlinks)
                for link in source_page.hyperlinks:
                    uri = link.get("uri")
                    if not uri:
                        page.hyperlink_unresolved_target_count += 1
                        warnings.append(f"page {page.page_number}: PDF link annotation has no URI target.")
                        continue
                    bbox = None
                    link_text = None
                    if width > 0 and height > 0:
                        x0, y0, x1, y1 = (float(link[key]) for key in ("x0", "top", "x1", "bottom"))
                        bbox = BoundingBox(
                            x0=max(0, min(1, x0 / width)), y0=max(0, min(1, y0 / height)),
                            x1=max(0, min(1, x1 / width)), y1=max(0, min(1, y1 / height)),
                        )
                        matching_chars = []
                        for char in source_page.chars:
                            cx = (float(char["x0"]) + float(char["x1"])) / 2 / width
                            cy = (float(char["top"]) + float(char["bottom"])) / 2 / height
                            if bbox.x0 <= cx <= bbox.x1 and bbox.y0 <= cy <= bbox.y1:
                                matching_chars.append(char)
                        if matching_chars:
                            matching_chars.sort(key=lambda char: (round(float(char["top"]), 1),
                                                                 float(char["x0"])))
                            pieces: list[str] = []
                            previous = None
                            for char in matching_chars:
                                if previous is not None:
                                    current_size = float(char.get("size", 0) or 0)
                                    same_line = abs(float(char["top"]) - float(previous["top"])) <= max(
                                        2.0, current_size * 0.5
                                    )
                                    gap = float(char["x0"]) - float(previous["x1"])
                                    if not same_line:
                                        pieces.append("\n")
                                    elif gap > max(1.0, current_size * 0.2):
                                        pieces.append(" ")
                                pieces.append(str(char["text"]))
                                previous = char
                            link_text = "".join(pieces).strip()
                        if not link_text:
                            matching_text = []
                            for element in page.elements:
                                if not element.text or element.bbox is None:
                                    continue
                                intersects = (element.bbox.x0 <= bbox.x1 and element.bbox.x1 >= bbox.x0
                                              and element.bbox.y0 <= bbox.y1 and element.bbox.y1 >= bbox.y0)
                                if intersects:
                                    matching_text.append(element.text)
                            if matching_text:
                                link_text = " ".join(matching_text)
                    link_index += 1
                    try:
                        parsed_uri = urlsplit(str(uri))
                        target_status = "valid_scheme" if parsed_uri.scheme else "missing_scheme"
                    except ValueError:
                        parsed_uri = None
                        target_status = "malformed_uri"
                    if not parsed_uri or not parsed_uri.scheme:
                        page.hyperlink_malformed_uri_count += 1
                        warnings.append(
                            f"page {page.page_number}: hyperlink target validation={target_status} "
                            "(preserved as-is)."
                        )
                    if not link_text:
                        warnings.append(
                            f"page {page.page_number}: HYPERLINK_TEXT_MISSING for annotation {link_index}."
                        )
                    page.elements.append(Element(
                        element_id=f"p{page.page_number:04d}-link-{link_index:04d}",
                        type=ExtractionField.HYPERLINK,
                        text=link_text,
                        reading_order=max((element.reading_order for element in page.elements), default=-1) + 1,
                        bbox=bbox,
                        target_uri=str(uri),
                        attributes={"source": "pdf_link_annotation",
                                    "visible_text_status": "matched" if link_text else "missing",
                                    "target_validation": target_status},
                    ))
                    page.hyperlink_count += 1
                if link_index < annotation_count:
                    warnings.append(
                        f"page {page.page_number}: accounted for {link_index} of "
                        f"{annotation_count} PDF link annotations with URI targets."
                    )

    @staticmethod
    def _append_internal_pdf_links(pdf_path: str, pages: list[Page],
                                   warnings: list[str]) -> None:
        from pypdf import PdfReader

        reader = PdfReader(pdf_path, strict=False)
        for page_index, pdf_page in enumerate(reader.pages):
            if page_index >= len(pages):
                break
            page = pages[page_index]
            width = float(pdf_page.mediabox.width)
            height = float(pdf_page.mediabox.height)
            for annotation_index, annotation_ref in enumerate(pdf_page.get("/Annots", []) or [], 1):
                annotation = annotation_ref.get_object()
                action = annotation.get("/A")
                if action is None or str(action.get("/S")) != "/GoTo":
                    continue
                page.hyperlink_count += 1
                destination = action.get("/D")
                target_uri = None
                try:
                    if isinstance(destination, str):
                        destination = reader.named_destinations.get(destination)
                    destination_page = getattr(destination, "page", None)
                    if destination_page is None:
                        destination_page = destination[0]
                    target_page = reader.get_page_number(destination_page) + 1
                    target_uri = f"#page={target_page}"
                except Exception:
                    page.hyperlink_unresolved_target_count += 1
                    warnings.append(
                        f"page {page.page_number}: internal hyperlink destination could not be resolved."
                    )

                bbox = None
                rect = annotation.get("/Rect")
                if rect is not None and width > 0 and height > 0:
                    x0, y0, x1, y1 = (float(value) for value in rect)
                    bbox = BoundingBox(
                        x0=max(0, min(1, x0 / width)),
                        y0=max(0, min(1, (height - y1) / height)),
                        x1=max(0, min(1, x1 / width)),
                        y1=max(0, min(1, (height - y0) / height)),
                    )
                visible_text = ""
                if bbox is not None:
                    visible_text = " ".join(
                        element.text or "" for element in page.elements
                        if element.type != ExtractionField.HYPERLINK and element.text
                        and element.bbox is not None
                        and element.bbox.x0 <= bbox.x1 and element.bbox.x1 >= bbox.x0
                        and element.bbox.y0 <= bbox.y1 and element.bbox.y1 >= bbox.y0
                    ).strip()
                page.elements.append(Element(
                    element_id=f"p{page.page_number:04d}-internal-link-{annotation_index:04d}",
                    type=ExtractionField.HYPERLINK,
                    text=visible_text or None,
                    reading_order=max((element.reading_order for element in page.elements),
                                      default=-1) + 1,
                    bbox=bbox,
                    target_uri=target_uri,
                    attributes={"source": "pdf_goto_annotation",
                                "target_type": "internal_page",
                                "visible_text_status": "matched" if visible_text else "missing",
                                "target_validation": "valid" if target_uri else "unresolved"},
                ))
                if not visible_text:
                    warnings.append(
                        f"page {page.page_number}: HYPERLINK_TEXT_MISSING for internal annotation {annotation_index}."
                    )

    @staticmethod
    def _associate_footnote_markers(pages: list[Page]) -> None:
        marker_pattern = re.compile(r"^\s*(?:\[(\d+)\]|\((\d+)\)|(\d{1,2})[.)])\s*")
        reference_pattern = re.compile(r"(?<!\d)(\d{1,2})(?=\s*[.,])")
        for page in pages:
            footnotes: dict[str, Element] = {}
            for element in page.elements:
                if element.type != ExtractionField.FOOTNOTE or not element.text:
                    continue
                match = marker_pattern.match(element.text)
                if match:
                    marker = next(value for value in match.groups() if value)
                    element.attributes["marker"] = marker
                    footnotes[marker] = element
            for element in page.elements:
                if element.type != ExtractionField.BODY_TEXT or not element.text:
                    continue
                markers = sorted(set(reference_pattern.findall(element.text)) & set(footnotes), key=int)
                if markers:
                    element.attributes["footnote_markers"] = markers
