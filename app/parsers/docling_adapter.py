from __future__ import annotations

from importlib.util import find_spec
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
import re
from threading import Lock

from app.parsers.base import ParsedAsset, ParsedDocument
from app.schemas.models import BoundingBox, Element, ExtractionField, Page


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

    def __init__(self) -> None:
        self._converter_lock = Lock()
        self._inference_lock = Lock()
        self._converters: dict[bool, object] = {}

    @staticmethod
    def check_available() -> bool:
        """Return whether Docling can be imported without loading its ML models."""
        return find_spec("docling") is not None

    def _get_converter(self, generate_assets: bool):
        """Reuse model pipelines across requests; callers serialize model inference."""
        converter = self._converters.get(generate_assets)
        if converter is not None:
            return converter
        with self._converter_lock:
            converter = self._converters.get(generate_assets)
            if converter is not None:
                return converter
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption

            options = PdfPipelineOptions()
            if generate_assets:
                options.generate_page_images = True
                options.generate_picture_images = True
            converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
            )
            self._converters[generate_assets] = converter
            return converter

    def parse(self, pdf_path: str, requested: set[ExtractionField]) -> ParsedDocument:
        try:
            # Import check above gives the public, specific unavailable error.
            if not self.check_available():
                raise ImportError("Docling is not installed")
        except ImportError as exc:
            raise ParserUnavailableError("Docling is not installed in the active environment.") from exc

        try:
            generate_assets = bool(requested.intersection(
                {ExtractionField.IMAGE, ExtractionField.TABLE}
            ))
            converter = self._get_converter(generate_assets)
            with self._inference_lock:
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
            if ExtractionField.BODY_TEXT in requested:
                self._apply_empty_page_fallback(pages, source_texts)
        except Exception as exc:
            raise ParserExecutionError("normalization", type(exc).__name__) from exc
        for element in elements:
            pages[int(element.element_id[1:5]) - 1].elements.append(element)
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
        if isinstance(text, str) and bbox is not None and bbox.y0 >= 0.78:
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
            element.attributes["table_status"] = "structured"
            element.attributes["table_validation_status"] = "needs_review"
            element.attributes["table_cells"] = structured_cells
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
            if not has_body_text and source_text.strip():
                page.elements.append(Element(
                    element_id=f"p{page.page_number:04d}-pypdf-body",
                    type=ExtractionField.BODY_TEXT,
                    text=source_text.strip(),
                    reading_order=max((element.reading_order for element in page.elements),
                                      default=-1) + 1,
                    attributes={"source": "pypdf_fallback",
                                "fallback_reason": "docling_body_text_empty",
                                "parser_label": "pypdf_text"},
                ))
                page.warnings.append("BODY_TEXT_FALLBACK_USED")
                if find_spec("fontTools") is None:
                    page.warnings.append("PYPDF_FONTTOOLS_UNAVAILABLE")
            elif not has_body_text:
                page.warnings.append("BODY_TEXT_SOURCE_LAYER_EMPTY")

    @staticmethod
    def _classify_repeated_page_edges(pages: list[Page]) -> None:
        occurrences: dict[tuple[str, str], set[int]] = {}
        for page in pages:
            for element in page.elements:
                if element.type != ExtractionField.BODY_TEXT or not element.text or not element.bbox:
                    continue
                if element.bbox.y1 <= 0.12:
                    zone = "header"
                    key = re.sub(r"\s+", " ", element.text).strip().casefold()
                elif element.bbox.y0 >= 0.88:
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
                if element.bbox.y1 <= 0.12:
                    zone = "header"
                elif element.bbox.y0 >= 0.88:
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
                if 0.12 < vertical_position < 0.88:
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
                            link_text = "".join(str(char["text"]) for char in matching_chars).strip()
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
                if link_index < annotation_count:
                    warnings.append(
                        f"page {page.page_number}: accounted for {link_index} of "
                        f"{annotation_count} PDF link annotations with URI targets."
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
