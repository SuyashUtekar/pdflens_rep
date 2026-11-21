# Canonical data mapping

Canonical schema version `1.2` is an implementation of the proposed structure in the project plan, not a recovered PDFLens schema. Coordinates are modeled as normalized `[0,1]` top-left origin; page dimensions are points and page numbering is one-based. Version 1.2 adds run/build identity, aggregated warning counts, duplicate-text diagnostics, and explicit unvalidated/review field states.

| Canonical field | Source in prototype | Caveat |
|---|---|---|
| `document.source_filename` | Sanitized upload basename | Legacy naming may differ |
| `document.source_sha256` | Uploaded bytes | Hash is included for integrity/deduplication investigation |
| `pages` and geometry | Docling document pages plus pypdf page inventory | Physical index is one-based; verify size units/rotation for pinned version |
| `page.source_text_char_count` | Per-page text from pypdf | Completeness baseline, not semantic ground truth |
| `page.body_text_char_count` and ratio | Normalized body output compared with pypdf baseline | Metrics are emitted without a calibrated pass threshold |
| `page.printed_page_label` | Numeric/page-label spans near page edges | Preserved literally and separate from physical index; heuristic needs corpus validation |
| `page.field_status` | Requested fields compared with page elements | Distinguishes not requested, extracted, and not detected; absence does not prove source absence |
| `page.body_text` | Derived page reading order | Joins body text and image/table tags; detailed elements remain under `page.elements` |
| `element.type` | Native Docling labels, explicit furniture labels, and repeated page-edge text | Text is retained and classification reason/confidence are recorded; validate against reviewed examples |
| `element.bbox` | Docling provenance box | Coordinate conversion is provisional; validate overlays before relying on it |
| `element.attributes.parser_label` | Native parser label | Provenance field, not stable public taxonomy |
| `processing.extracted_fields` | Types emitted by adapter | Empty requested categories are not listed |
| `element.artifact_path` | Generated asset path, linked by element ID | Image and table crops are PNGs when Docling provides a crop; missing crops produce a warning |
| `element.attributes.table_status` | Docling `TableCell` data, when available | `structured` means cells were emitted but still need manual validation; otherwise `visual_only` |
| `element.attributes.asset_sha256` | Exact bytes of each extracted image/table snapshot | Exact repeated snapshots are flagged with `exact_duplicate_of`; every page occurrence remains packaged |
| `element.target_uri` | PDF `/Link` annotation action `/URI` | Internal destinations and links without URI actions are not currently emitted |

Unknown parser labels currently map to `body_text` when text exists and `other` otherwise. That is a temporary mapping policy to be measured and revised against the golden corpus.
