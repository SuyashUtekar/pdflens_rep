from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
import re

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
        page_keys = sorted(page_items, key=lambda value: str(value)) if page_items else []
        try:
            from pypdf import PdfReader

            source_pages = PdfReader(pdf_path, strict=False).pages
            source_dimensions = [(float(source_page.mediabox.width),
                                 float(source_page.mediabox.height))
                                for source_page in source_pages]
        except Exception:
            source_dimensions = []
        pages: list[Page] = []
        for idx, key in enumerate(page_keys, start=1):
            native_page = page_items[key]
            size = getattr(native_page, "size", None)
            source_size = source_dimensions[idx - 1] if idx <= len(source_dimensions) else (None, None)
            width = float(getattr(size, "width", None) or source_size[0])
            height = float(getattr(size, "height", None) or source_size[1])
            pages.append(Page(page_number=idx, width_pt=width, height_pt=height,
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
                    else:
                        continue
                order = next_order.get(page_no, 0)
                next_order[page_no] = order + 1
                element_id = f"p{page_no:04d}-e{i+1:04d}"
                element = Element(element_id=element_id, type=kind,
                                        text=str(text) if text is not None else None,
                                        reading_order=order, bbox=bbox,
                                        attributes={"parser_label": label_raw})
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
                        asset_warnings.append(
                            f"Could not create {kind.value} snapshot for {element_id} ({type(exc).__name__})."
                        )
        except Exception as exc:
            raise ParserExecutionError("normalization", type(exc).__name__) from exc
        for element in elements:
            pages[int(element.element_id[1:5]) - 1].elements.append(element)
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
                                        *asset_warnings, *link_warnings, *page_number_warnings],
                              extracted_fields=extracted, assets=assets)

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
        if isinstance(text, str) and bbox is not None:
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
                if not re.fullmatch(r"page\s+\d+|\d{1,4}", normalized):
                    return
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

        with pdfplumber.open(pdf_path) as pdf:
            for page_index, source_page in enumerate(pdf.pages):
                if page_index >= len(pages):
                    break
                page = pages[page_index]
                width = float(source_page.width)
                height = float(source_page.height)
                link_index = 0
                for link in source_page.hyperlinks:
                    uri = link.get("uri")
                    if not uri:
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
                    page.elements.append(Element(
                        element_id=f"p{page.page_number:04d}-link-{link_index:04d}",
                        type=ExtractionField.HYPERLINK,
                        text=link_text,
                        reading_order=max((element.reading_order for element in page.elements), default=-1) + 1,
                        bbox=bbox,
                        target_uri=str(uri),
                        attributes={"source": "pdf_link_annotation"},
                    ))

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
