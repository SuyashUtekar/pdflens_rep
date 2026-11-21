# Architecture and implementation status

## Intended flow

Caller → compatibility API → validated intake → parser adapter → canonical metadata → artifact generation → output validation → ZIP response. Parser output is isolated behind `ParserAdapter`; future storage and job tracking integrations should be added behind their own interfaces when the current platform is discovered.

## Implemented

- Synchronous FastAPI feasibility endpoint.
- PDF magic/signature and byte-size checks, filename normalization, SHA-256 digest.
- Docling adapter boundary, canonical page/element types, Docling furniture labels plus conservative repeated page-edge classification, marked-footnote classification, PDF link-annotation extraction, a direct `python-docx` renderer with page breaks and heading styles, coordinate-based heading repair and selectable-text fallback, image/table tags with separate snapshots, metadata, manifest and original PDF ZIP members.
- Per-page pypdf source-text baseline, body-text character/ratio metrics, explicit field statuses, and a provenance-marked fallback when Docling emits no body text for a page with extractable text.
- Table cell data when Docling exposes it, with an explicit visual-only status otherwise; ZIP checksums and metadata artifact paths are validated before returning the package.

## Deliberately pending discovery

- Exact legacy API, ZIP member names and error envelope.
- Docling versus MinerU benchmark, pinning, model provenance and licensing review.
- Bounding-box validation against rotated and mixed-size pages; current adapter emits a warning and must not be treated as certified geometry.
- Header/footer/footnote classification quality and image/table crop quality need review against the golden corpus. Link coverage beyond explicit PDF annotations, OCR validation, and language support also remain open.
- Authentication/authorization, object storage, durable jobs, retries, retention, telemetry and deployment policy.
- DOCX output mode decision and visual-fidelity threshold.

## Boundaries

Keep canonical metadata independent from parser-native models. Preserve page geometry and parser labels as provenance. Return only safe error messages to callers; correlate internal logs with request ID and avoid document contents. Production workers need enforceable CPU, memory, timeout, disk and page limits, beyond this synchronous prototype's checks.
