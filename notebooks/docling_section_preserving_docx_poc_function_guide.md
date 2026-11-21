# Function guide: Docling section-preserving DOCX POC

This guide describes the current code in `notebooks/docling_section_preserving_docx_poc.ipynb` and the chunking helpers in `chunking_strategy/sectionwise_chunking.py`. The earlier pre-refactor notebook is retained under `notebooks/archive/`. It explains what each function consumes, how it works, and which problem it addresses.

## Processing overview

1. The notebook selects an inclusive page range and writes that range to a temporary/output PDF.
2. Docling converts the selected PDF pages and identifies text, headings, tables, pictures, layout, and page images.
3. `pdfplumber` supplies selectable PDF text lines and their coordinates. The notebook compares these against Docling's detected elements to diagnose merged headings, recover omitted lines, identify page furniture, and avoid duplicating structured content.
4. The notebook creates a Word document with Word heading styles and page breaks. Tables and images are represented by tags; furniture and page numbers are filtered from body content.
5. It writes a section index and a Markdown diagnostic report. The DOCX is then read by the section chunker, which writes JSON and Excel chunk outputs.

## Notebook setup and configuration (not functions)

### Imports and project discovery

The setup cell imports Docling, `pdfplumber`, `pypdf`, `python-docx`, and standard-library helpers. It searches the current directory and its parents for `pyproject.toml` to determine `PROJECT_ROOT`, adds that root to `sys.path`, and imports `chunk_docx` and `save_chunks_xlsx` from the project chunking module.

### Input and output paths

`PDF_PATH`, `START_PAGE`, and `END_PAGE` select the source and page range. Page numbers are 1-based and inclusive; `END_PAGE = None` means the PDF's final page. The notebook validates the range, creates a directory under `outputs/section_docx_poc/`, and derives paths for the trimmed PDF, DOCX, section index JSON, layout Markdown, metadata JSON, `table_screenshots/` and `image_crops/` folders, chunk JSON, and chunk Excel file from the PDF filename and selected range.

The currently configured `PDF_PATH` is an input setting, not a value inferred from the notebook at runtime. Change it to use another PDF. Output names and locations are derived from that setting and the page range.

## Notebook stage functions

These functions wrap the notebook's end-to-end stages. The cells define each function and then call it in order, making the execution flow visible while keeping the underlying operations reusable.

### `prepare_selected_pdf(project_root, pdf_path, start_page, end_page)`

Validates a 1-based inclusive page range, creates a per-PDF/per-range output folder, derives the artifact paths, trims the source PDF with `pypdf`, and returns the effective end page, source page count, and output-path mapping.

### `convert_pdf_with_docling(trimmed_pdf_path, start_page, end_page)`

Configures Docling's PDF pipeline for tables, parsed pages, heading hierarchy, and page/picture images; converts the trimmed PDF and returns the Docling document.

### `preview_detected_headings(document, start_page, limit=80)`

Prints and returns Docling's raw title and section-header items with original source page numbers, levels, and positions. It helps inspect Docling before reconstruction.

### `collect_layout_diagnostics(pdf_path, trimmed_pdf_path, start_page, end_page, markdown_path, document)`

Builds coordinate-based page data, identifies header/footer and page-number candidates, discovers recurring margin annotations, writes the source-text and Docling comparison Markdown, and returns page data plus Markdown content for later appending.

### `reconcile_docling_with_pdf(document, pdf_page_data, start_page)`

Builds page-ordered Docling items, replaces merged headings when the PDF lines support a split, and adds missing selectable PDF lines outside structured regions. Returns the prepared page items and reconstructed-heading diagnostics.

### `create_section_docx(...)`

Applies Word page/style settings, writes prepared content in page order, skips furniture/page numbers, inserts image/table tags, saves the DOCX and section index, and appends the reconstructed heading outline to the Markdown report. Its return values are the section index and block counts.

### `validate_and_chunk_docx(...)`

Checks the generated DOCX and section index, runs the sectionwise chunker, writes the chunk JSON and Excel workbook, and returns the chunk result.

### `build_asset_catalog(items_by_page, pdf_page_data)`

Assigns IDs to table and picture tags in DOCX reading order. The metadata stage retains the pasted implementation’s independent counters and image filenames.

### `generate_page_metadata(...)`

Uses Docling and the trimmed PDF to write per-page metadata, snapshots, footnotes, and URI hyperlinks. PyMuPDF’s existing block-based detector remains in place; Docling `PAGE_HEADER`/`PAGE_FOOTER` labels and their page rectangles supplement the resulting header/footer text and furniture exclusion regions. This prevents labeled furniture from entering metadata body text while preserving the existing metadata fields and other extraction stages.

Supporting helpers retain the supplied roles: `bbox_to_absolute_px()` maps document coordinates to rendered pixels; `render_page_to_pil()` renders page snapshots; `crop_image()` crops them; `classify_image_zone()` assigns header/footer/body zones; `_page_margin_blocks()` and `_page_all_blocks()` read selectable text blocks; `_build_hf_repetition()` identifies repeated furniture; `_page_header_footer()` applies the original header/footer rules; `_median_len()` and `_norm()` support its text checks; `_is_page_number()` detects standalone footer numbers; `_overlaps_hf()` excludes furniture from body extraction; `extract_hyperlinks_from_page()` reads URI links; `_get_prov()` and `_label_str()` normalize Docling provenance and labels.

## Notebook functions

### `label_name(item)`

- **Input:** A Docling document item.
- **Uses:** Reads the item's `label` and normalizes enum-like labels to uppercase text.
- **Solves:** Gives downstream code one consistent way to check labels such as `SECTION_HEADER`, `TABLE`, and `PICTURE` despite differences in enum representation.

### `first_page_number(item)`

- **Input:** A Docling item.
- **Uses:** Reads the first provenance record and returns its local page number, or `None` if provenance is absent.
- **Solves:** Associates extracted elements with the correct page for diagnostics and DOCX placement.

### `normalize(value)`

- **Input:** Text or a value convertible to text.
- **Uses:** Unicode NFKC normalization, case folding, removal of Docling CID markers and leading numeric list markers, and replacement of punctuation with spaces.
- **Solves:** Supports tolerant text comparisons between PDF text-layer lines and Docling text, including comparisons used to avoid duplicate fallback text.
- **Caution:** It intentionally discards punctuation and some leading numbering for comparison; it is not used as the displayed output text.

### `clean_pdf_text(value)`

- **Input:** Text extracted from the PDF text layer.
- **Uses:** Replaces `(cid:...)` glyph placeholders with a bullet and strips outer whitespace.
- **Solves:** Makes fallback and diagnostic text more readable when the PDF exposes missing-glyph placeholders.

### `is_parenthetical_margin_label(line, page_width)`

- **Input:** One `pdfplumber` line (including words and x-coordinates) and page width.
- **Uses:** Checks for a short parenthesized phrase, excludes ordinary single-token list markers (letters, Roman numerals, digits), and checks whether its word bounds reach the right-side margin using page-width-relative positions.
- **Solves:** Finds candidate margin annotations without matching a particular annotation phrase.
- **Caution:** This is a structural heuristic. A legitimate short parenthetical phrase placed at the right edge can resemble a margin annotation.

### `is_recurring_margin_label_item(text, bbox, page_data)`

- **Input:** Docling item text and bounding box, plus the page's PDF-derived line data.
- **Uses:** Requires the normalized text to be among labels repeated across selected pages, then compares the Docling box with a matching PDF line's location using page-size-relative tolerances.
- **Solves:** Removes repeated standalone margin annotations while preserving inline occurrences and one-off parenthetical content.

### `is_page_number_text(value)`

- **Input:** A text string.
- **Uses:** Recognizes standalone numeric labels and common page-number forms, including optional `Page`/`P.` prefixes and `n/N` or `n of N` forms.
- **Solves:** Separates short page-number candidates from ordinary prose before position checking.
- **Caution:** This function alone does not decide that a number is a page number; it must also be at a page edge and match PDF source text at the same location.

### `is_near_page_edge(left, right, top, bottom, page_width, page_height)`

- **Input:** A text box's coordinates and page dimensions.
- **Uses:** Defines edge zones as proportions of the actual page width and height, and checks all four sides.
- **Solves:** Makes edge checks work across different page dimensions and orientations rather than relying on fixed point coordinates.

### `is_page_number_line(line, page_width, page_height)`

- **Input:** A PDF text line and its page dimensions.
- **Uses:** Applies `is_page_number_text` and then checks the line's word bounds with `is_near_page_edge`.
- **Solves:** Collects page-number candidates from the PDF text layer for the page data and diagnostics.

### `is_page_number_item(text, bbox, page_data)`

- **Input:** Docling item text and bounding box, plus source-page geometry and candidate lines.
- **Uses:** Requires a recognized page-number form, an edge location, matching normalized PDF-line text, and a close positional match after converting Docling's bottom-origin coordinates to top-origin coordinates.
- **Solves:** Removes page numbers from DOCX while reducing the risk of deleting numeric values in body text, tables, or an index. A number is not removed solely because it is numeric.

### `heading_marker_depth(text)`

- **Input:** A candidate heading line.
- **Uses:** Parses leading numeric/alphanumeric designators separated by punctuation and counts their components. It only treats a marker as structural if it contains a numeric component or has explicit list punctuation.
- **Solves:** Infers relative heading depth for patterns such as nested decimal numbering without hard-coding particular section titles.
- **Caution:** Numbering conventions differ across documents. Unnumbered headings rely on Docling's level or the repeated-label logic below.

### `labeled_heading_signature(text)`

- **Input:** A candidate heading line.
- **Uses:** Looks for a leading label followed by a punctuated alphabetic or numeric designator, then returns the label tokens, designator kind, and punctuation.
- **Solves:** Detects a repeated label/designator pattern from the observed source lines (for example, multiple lines sharing the same label pattern) without embedding a particular label or section name in the code.

### `split_combined_heading(item, tree_level, page_no, page_data)`

- **Input:** A Docling `SECTION_HEADER` or `TITLE`, its tree level and page number, and the corresponding `pdfplumber` page data.
- **Uses:**
  1. Reads the Docling item text and bounding box.
  2. Finds PDF text lines whose centers lie inside that box and whose normalized text occurs in the Docling text.
  3. Sorts matched lines by their source coordinates.
  4. Starts a new heading when a line has a recognized structural marker or repeats the first line's observed label/designator signature; otherwise appends it as a wrapped continuation of the current heading.
  5. Assigns levels relative to the Docling base level and inferred marker depth, bounded by Word's supported heading levels.
- **Solves:** Repairs cases where Docling combines several visually separate numbered headings into one section-header item, while keeping wrapped lines of one heading together.
- **Fallback:** Returns an empty list if there is not enough coordinate/text evidence or no split can be inferred; the original Docling item is then retained.
- **Caution:** It uses general layout and numbering rules, not a trained semantic heading classifier. Ambiguous source layouts can still need review.

### `pdf_page_lines(page)`

- **Input:** A `pdfplumber` page.
- **Uses:** Extracts words, sorts them by vertical and horizontal position, groups words whose vertical bounding boxes overlap, and joins each group's words in horizontal order.
- **Solves:** Produces coordinate-bearing text lines for header/footer detection, page-number checks, margin-label analysis, heading reconstruction, and source-vs-Docling comparison.
- **Caution:** PDF text order and glyph boxes can be imperfect; this groups by geometry, not visual OCR.

### `record_block(category)`

- **Input:** A block category string.
- **Uses:** Increments the notebook's `Counter` for that category.
- **Solves:** Reports how many headings, text blocks, tags, skipped furniture items, and other categories the DOCX builder handled.

## Notebook processing blocks that are inline, not named functions

### PDF page-range trimming

The setup cell validates the requested range and uses `PdfReader`/`PdfWriter` to copy only those pages into a derived PDF. Docling and `pdfplumber` process that selected PDF. Source page numbers in reports and section indexes are adjusted back to the original PDF numbering.

### Docling conversion

The conversion cell enables table-structure extraction, parsed page generation, heading hierarchy, page images, and picture images. `DocumentConverter` runs the PDF pipeline and exposes the resulting Docling document (`doc`). These options configure Docling; the later PDF text comparison and DOCX generation are notebook logic.

### Header/footer and source-page data assembly

The notebook builds `pdf_page_data` from `pdf_page_lines()`. It identifies candidate header and footer lines in size-relative top/bottom bands, records page-number candidates, and excludes these lines from fallback body text. The final DOCX also skips Docling furniture/footnote labels and checks source furniture text before adding ordinary text.

### Recurring margin-label discovery

The notebook counts candidate parenthetical labels by selected page. Only labels recurring on multiple selected pages are marked recurring, then their Docling items are skipped when their position matches the PDF source line. The repetition requirement is dynamic relative to the selected range; with only one selected page, this recurring-label filter will not identify a repeated label.

### Markdown diagnostic generation

The notebook writes source text lines and their coordinates, inferred page headers/footers, page-number candidates, recurring margin labels, Docling elements and coordinates, and Docling's raw Markdown conversion. After DOCX construction it appends reconstructed heading records. This report helps distinguish text/layout problems in the PDF or Docling output from later DOCX formatting.

### DOCX construction and PDF-text reconciliation

Docling items are grouped by page and sorted by coordinates. Reconstructed headings replace the original combined item when available. For text omitted by Docling, the notebook can add complete selectable PDF lines as fallback text, unless the line is already represented or lies inside a table/picture region. Tables and pictures become `<doc_ai .../>` placeholder paragraphs. Word heading styles are used for recognized/reconstructed headings. A page break is added between selected source pages.

The page size is taken from the converted page. Margins and typography are currently explicit formatting settings in the notebook; they are not inferred from every source element. The DOCX is a structured reading/chunking representation, not a pixel-identical PDF reproduction.

## `chunking_strategy/sectionwise_chunking.py` functions

### `Section` dataclass

- **Fields:** `title`, heading `level`, ancestor `path`, and direct content `blocks`.
- **Solves:** Holds the content associated with one heading before it is split into bounded chunks.

### `_paragraph_has_image(paragraph)`

- **Input:** A `python-docx` paragraph.
- **Uses:** Inspects paragraph XML for Word drawing or picture tags.
- **Solves:** Detects embedded images, including when the paragraph has no ordinary text.

### `_table_to_text(table)`

- **Input:** A Word table.
- **Uses:** Normalizes cell whitespace, joins cells within each row, and joins non-empty rows.
- **Solves:** Converts native DOCX tables into readable text for chunking.

### `_iter_blocks(document)`

- **Input:** A `python-docx` document.
- **Uses:** Iterates paragraphs and tables in document order; identifies Title and Heading styles, ordinary text, embedded image paragraphs, and table text.
- **Solves:** Gives the chunker a consistent ordered stream of title, heading, text, image, and table blocks.
- **Note:** The current PDF notebook replaces detected PDF images/tables with textual tags, so these are normally read as text blocks. This helper can also handle native DOCX image and table content.

### `_split_words(text, max_words, overlap_words)`

- **Input:** Text and word-count chunk/overlap limits.
- **Uses:** Splits oversized text on whitespace and repeats the requested number of words between adjacent parts.
- **Solves:** Bounds chunk length while retaining local context between split parts.

### `chunk_docx(source, max_words=800, overlap_words=80)`

- **Input:** DOCX path and optional chunk/overlap word limits.
- **Uses:** Reads ordered blocks, tracks a heading stack, assigns each block to its current section, builds section paths, splits each section body by word count, and prefixes each chunk with the section path joined by ` | `.
- **Solves:** Produces section-aware chunk objects with stable sequential IDs and metadata such as source DOCX, title, section, level, part, text, and word count.
- **Validation:** Rejects invalid word limits (max must be positive; overlap must be nonnegative and smaller than max).

### `save_chunks_xlsx(chunks, destination)`

- **Input:** Chunk dictionaries and an Excel destination path.
- **Uses:** Creates a workbook with `chunk_id` and `chunk_text` columns, applies readable formatting, wrapping, freeze panes, and filters, and creates the destination folder if needed.
- **Solves:** Exports the chunk content in the requested spreadsheet format.

### `main()`

- **Input:** Command-line arguments: DOCX path, optional JSON output, max words, overlap words, and optional Excel output.
- **Uses:** Validates the DOCX path, calls `chunk_docx()`, writes JSON, and optionally writes Excel (the rest of the CLI implementation follows the same path-derived output convention).
- **Solves:** Makes the section chunker usable independently from the notebook.

## What is dynamic and what remains configured

- Heading reconstruction uses text and coordinates found in the current PDF plus general marker/signature patterns; it does not name the fixture's section titles.
- Page-number identification combines recognized standalone forms with edge location and source-position agreement. It is not a blanket deletion of numeric text.
- Repeated margin-label filtering uses the labels and page positions observed in the selected PDF range.
- Page selection, `PDF_PATH`, output directory convention, Word typography/margins, page-number edge bands, and chunk size defaults are configuration/rule choices. They are not learned from the PDF. Adjust them when the desired run needs different values.
- Docling's element labels and heading levels remain the primary semantic signals. The notebook supplements them with PDF geometry and selectable text; it does not guarantee perfect semantic reconstruction for every PDF.
