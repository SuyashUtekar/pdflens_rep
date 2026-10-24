# PDFLens Replacement Project — Complete Implementation Plan

**Project:** PDFLens replacement for Intelligent Search  
**Document type:** Technical implementation blueprint  
**Status:** Proposed plan — subject to discovery and benchmark results  
**Date:** 22 October 2026  
**Target team:** Two engineers, with platform/security support as needed

---

## 1. Executive summary

The objective is to replace the current PDFLens service without breaking the Intelligent Search system that consumes its output. The replacement must extract PDF content and metadata while retaining the spatial relationships needed to understand where each element appears on each page.

The current PDFLens behavior, as described for this project, is:

1. A caller submits a PDF and selects the extraction fields it needs, such as body text, headers, footers, footnotes, hyperlinks, images, and tables.
2. PDFLens processes the document and returns a ZIP archive.
3. The ZIP contains a DOCX rendition, an image/screenshot folder, a table-snapshot folder, and a metadata JSON file.
4. The metadata is page-wise and contains extracted text and metadata, plus references to image and table artifacts.

The recommended strategy is **not to build a PDF parser from scratch**. Benchmark at least two existing parsing engines—initially Docling and MinerU—against representative production PDFs. Choose the engine based on measured output quality, layout localization, operational fit, dependency/model licenses, and runtime cost. Put a project-owned adapter around the chosen engine so its native schema never becomes the public API contract.

The main architecture should separate five concerns:

- PDF intake, validation, storage, and job lifecycle.
- Parser execution and any supplementary extraction.
- Canonical metadata normalization, including coordinate systems and reading order.
- Artifact generation: images, table snapshots, DOCX, manifest, and ZIP.
- Contract validation, observability, security controls, and regression testing.

### Delivery recommendation

For two full-time engineers, **one week is appropriate for a feasibility prototype, not a credible commitment to production readiness with zero feature degradation**. Use an initial estimate of **4–7 weeks** for a production candidate, refined after the first benchmark. Complex scans, strict PDF-to-DOCX visual similarity, restrictive deployment constraints, or extensive legacy behavior may extend this estimate.

A production release must be based on a measured comparison with current PDFLens—not on the fact that a candidate parser runs successfully.

---

## 2. Goals and non-goals

### 2.1 Goals

1. Preserve the existing consumer-facing PDFLens API and output contract wherever possible.
2. Extract page-level content and metadata while preserving element locations and reading order.
3. Identify, where supported and validated, body text, headings, headers, footers, page numbers, footnotes, hyperlinks, images, tables, captions, lists, equations, and other relevant blocks.
4. Retain page number, dimensions, rotation, bounding boxes, element type, reading order, and artifact references in a canonical schema.
5. Generate the expected DOCX, image assets, table snapshots, metadata JSON, and ZIP archive.
6. Honor the caller's field-selection flags and define behavior for unsupported or failed fields.
7. Integrate with the existing Intelligent Search service and its storage/job-tracking conventions.
8. Provide reproducible testing, metrics, failure handling, security controls, deployment instructions, and rollback.
9. Avoid introducing unnecessary services or duplicate storage if existing infrastructure already supports the same responsibilities.

### 2.2 Non-goals unless explicitly required

- Building a new layout detection/OCR model from scratch.
- Guaranteeing pixel-perfect PDF-to-DOCX reproduction as an implied side effect of metadata extraction.
- Guaranteeing perfect extraction for every PDF, language, handwriting style, or low-resolution scan.
- Altering downstream chunking, embedding, ranking, or search behavior beyond any required compatibility work.
- Replacing the existing document/job tracker or object storage if the current platform already provides them adequately.
- Adding an LLM to every PDF-processing request. Use deterministic parsing first; make any model-based enrichment explicit, measurable, and optional.

### 2.3 Two separate layout requirements

These must be agreed independently:

**A. Layout-aware metadata:** each detected element has a page reference and position (bounding box), plus type and reading order. This is the primary stated requirement.

**B. Visual PDF-to-DOCX fidelity:** the generated DOCX visually resembles the source PDF, including page breaks, columns, spacing, font sizes, images, and table placement. This is harder and is not guaranteed by structured parsing alone.

If visual similarity is required, define a separate benchmark and acceptance threshold. A reflowable, editable DOCX and a visually faithful, page-image-based DOCX are different products with different trade-offs.

---

## 3. Current-state contract discovery

Before implementation, capture the behavior of the current PDFLens service. Do not assume that the proposed schema in this plan is identical to the existing service schema.

### 3.1 Inventory checklist

- [ ] Record the existing endpoint(s), HTTP methods, request format, authentication, and response codes.
- [ ] Save sanitized request examples for each extraction flag combination.
- [ ] Capture representative successful ZIP archives from PDFLens.
- [ ] Record exact ZIP member names, folder names, file naming rules, and relative-path conventions.
- [ ] Collect representative metadata JSON documents and document every required field.
- [ ] Determine the page-number convention (0-based or 1-based) used today.
- [ ] Determine coordinate units, origin, rotation conventions, and whether boxes are absolute, normalized, or pixel-based.
- [ ] Clarify whether hyperlinks include destination URI, link text, rectangle, and page.
- [ ] Clarify whether image/table metadata references the original PDF region, exported crop, embedded object, or all of these.
- [ ] Record DOCX behavior: editable reflowable content, fixed page layout, images of pages, or a mixture.
- [ ] Record error response format and behavior for encrypted, corrupt, empty, scanned, and oversized PDFs.
- [ ] Identify all downstream consumers and which JSON keys / ZIP paths they actually use.
- [ ] Capture performance baselines by document size and page count.
- [ ] Confirm data classification, retention, residency, and permitted processing locations.

### 3.2 Contract artifacts to produce

1. **API contract** — requests, fields, defaults, response types, errors, and compatibility guarantees.
2. **ZIP manifest contract** — mandatory files, relative paths, and naming rules.
3. **JSON mapping document** — existing PDFLens field → canonical field → output field.
4. **Golden corpus** — approved test PDFs and their reviewed expected outputs.
5. **Compatibility test suite** — automated checks that the replacement output is consumable by existing clients.

No production cutover should be approved until these artifacts exist.

---

## 4. Candidate parser strategy

### 4.1 Start with a benchmark, not a premature commitment

Evaluate Docling and MinerU using the same set of PDFs and the same field requirements. The goal is to find the best fit for the actual contract, not to select based on popularity or a generic benchmark score.

- **Docling:** a general-purpose document conversion framework with structured document representation and JSON export. Its codebase is MIT-licensed, but individual model and dependency licenses still require review. Official documentation: <https://docling-project.github.io/docling/usage/supported_formats/> and <https://github.com/docling-project/docling>.
- **MinerU:** a document parsing engine whose documented output includes page-oriented content, element categories, bounding boxes, and link spans in supported output modes. Its current license is a custom MinerU Open Source License based on Apache 2.0 with additional terms, including an attribution obligation for online services; legal review is mandatory before adoption. See <https://github.com/opendatalab/MinerU> and <https://github.com/opendatalab/MinerU/blob/master/docs/en/reference/output_files.md>.
- **PDF utilities:** a small, separately licensed PDF utility may be used to supplement links, page geometry, or embedded object extraction if the selected parser does not meet those requirements. Review the exact library and version before shipping. For example, PyMuPDF has AGPL and commercial licensing routes; do not use it in a proprietary deployment without an approved licensing decision. See <https://pymupdf.io/licensing>.
- **Marker:** retain as an optional comparison candidate only if its source and model license conditions fit the organization. Its repository describes additional commercial restrictions for model weights; review the current official repository/license before adopting it. See <https://github.com/VikParuchuri/marker>.

**Recommendation:** benchmark Docling and MinerU first. Do not run two heavyweight parsers for every production request unless the measured benefit justifies the latency, infrastructure, and failure complexity. Choose one primary parser and keep the adapter design extensible so a second parser can be used later for limited fallback or special cases.

### 4.2 Parser selection scorecard

Score each candidate from 1 (poor) to 5 (strong) using the project corpus. Record both the numeric score and the observed evidence.

| Criterion | Weight (initial suggestion) | What to inspect |
|---|---:|---|
| Page-level bounding boxes and coordinate clarity | 20% | Bounding boxes accurate, documented origin/units, correct rotation handling |
| Text and reading order | 15% | Single-column, two-column, sidebars, lists, tables |
| Headers, footers, footnotes, page numbers | 15% | Detection and classification without losing content needed downstream |
| Tables and table artifacts | 10% | Structure, merged cells, cross-page continuation, snapshot quality |
| Images and figure artifacts | 10% | Extracted asset quality, captions, traceability to page and region |
| Hyperlinks | 10% | Link text, URI, page, bounding rectangle |
| Scanned PDFs / OCR | 5% | Languages, confidence signals, failure modes |
| Throughput, memory, deployment | 5% | Cold start, warm latency, peak memory, CPU/GPU requirement |
| Licensing and model provenance | 5% | Code, model weights, OCR, transitive dependencies, online-service terms |
| Output/API integration effort | 5% | Adapter complexity, reproducibility, output compatibility |

Weights may be changed after requirements discovery. Do not hide critical failures behind an average score: a parser that cannot reliably produce required hyperlinks or page positions fails that gate even if its aggregate score is high.

### 4.3 Day 1–3 benchmark gate

Use 5–10 representative PDFs early to test the riskiest requirements: multi-column reading order, footnotes, hyperlinks, rotated pages, images, complex tables, and scans.

Proceed with a candidate only if it can produce a useful structured representation for the required cases and its missing capabilities can be addressed with a small, acceptable supplementary layer. If neither candidate clears the gate, revisit requirements or evaluate an alternative before writing extensive integration code.

---

## 5. Recommended target architecture

### 5.1 Logical components

```text
Caller / Intelligent Search
          |
          v
PDFLens-Compatible API (FastAPI)
  - authentication / authorization
  - request validation
  - field selection
  - request ID / idempotency
          |
          v
Job Coordinator
  - status and retries
  - limits and timeout policy
  - existing tracker / Oracle integration if applicable
          |
          v
Original PDF + Work Artifacts (existing object storage / MinIO)
          |
          v
Isolated Parser Worker
  - selected primary parser (Docling or MinerU)
  - optional PDF utility adapter
  - per-job temp directory and resource limits
          |
          v
Canonical Metadata Adapter
  - normalize pages / types / coordinates
  - normalize reading order and links
  - preserve parser provenance and warnings
          |
          v
Artifact Generator
  - selected image assets
  - table snapshots
  - DOCX generator
  - metadata.json + manifest.json
          |
          v
Output Validator
  - JSON/schema validation
  - asset path integrity
  - ZIP layout validation
  - field-toggle validation
          |
          v
ZIP Builder -> Output Storage -> Existing API response / download flow
```

### 5.2 Design principles

1. **Contract-first:** consumers depend on the project-owned schema and API, not parser-native formats.
2. **Modular stages:** parsing, normalization, DOCX generation, and ZIP packaging can be tested independently.
3. **Provenance:** retain parser name/version, model version if applicable, extraction configuration, warnings, and timing.
4. **Fail explicitly:** do not claim full success when a requested output is missing or only partially extracted.
5. **Bound resource use:** PDF parsing can be CPU/memory intensive; isolate workers and enforce limits.
6. **Keep source intact:** preserve the original PDF as the source of truth; never overwrite it with a transformed rendition.
7. **Reuse platform services:** integrate with current authentication, object storage, tracker, Kafka, and observability conventions rather than introducing redundant infrastructure.
8. **Deterministic packaging:** artifact paths and ZIP structure must be stable for identical inputs/configuration, aside from explicitly variable metadata such as timestamps or generated IDs.

### 5.3 Synchronous vs. asynchronous processing

First inspect the current PDFLens API semantics.

- If the existing call returns a ZIP synchronously and representative documents finish reliably within the current timeout budget, preserve that behavior for compatibility.
- If large-document processing is already asynchronous or the platform supports a job ID/status flow, use a worker queue and preserve the existing external contract where possible.
- If the current interface is synchronous but large documents cannot reliably finish in time, propose a versioned asynchronous API rather than silently changing semantics.

Kafka may be used if it is already a standard part of the platform. Do not add a broker solely for a small service when a simpler approved job mechanism meets requirements. If Kafka is used, define event schemas, retry policy, dead-letter behavior, idempotency, and job state transitions explicitly.

---

## 6. Suggested implementation stack

Adapt this list to the approved stack and current production environment.

| Concern | Suggested choice | Notes |
|---|---|---|
| API layer | Python + FastAPI | Compatible with a Python parser integration; preserve existing API contract |
| Primary parser | Select Docling or MinerU after benchmark | Pin exact versions; prefetch model artifacts where required |
| PDF supplementation | A reviewed PDF utility only for identified gaps | Confirm license and output coordinate semantics before adding |
| Metadata validation | Pydantic models + JSON Schema checks | Keep canonical contract versioned and testable |
| Artifact creation | Python standard library + approved DOCX library | DOCX output mode must be explicitly defined |
| Image/table output | Parser-native assets or controlled PDF crop rendering | Standardize formats, naming, DPI, and crop coordinates |
| Object storage | Existing MinIO/object-store service | Store originals and ZIP outputs under scoped, opaque identifiers |
| Job tracking | Existing Oracle/job tracker if appropriate | Do not create duplicate job state without a reason |
| Queueing | Existing Kafka or approved job queue, if needed | Async processing, retries, backpressure, dead-letter flow |
| Containerization | Docker or approved container platform | Pinned dependencies, non-root process, resource limits |
| CI | Existing CI system | Unit, schema, compatibility, regression, image build, vulnerability scans |
| Observability | Existing metrics/logging/tracing stack | Request/job ID correlation, no unnecessary document-content logging |

### Dependency and model lock-down

- Pin parser/library versions and the relevant model versions.
- Generate and retain a software bill of materials (SBOM) where the platform supports it.
- Record every model-weight license, OCR dependency, rendering library, and transitive package.
- Avoid loading models from uncontrolled remote sources at runtime; use an approved artifact source and integrity checks.
- Test cold-start behavior and ensure the worker does not download models unexpectedly in production.

---

## 7. End-to-end processing workflow

### Step 1 — Receive and validate request

1. Validate caller authorization and request shape.
2. Validate requested field names against a whitelist.
3. Validate the upload size and filename length; never trust the caller-provided MIME type alone.
4. Verify the file is a PDF using signature/content validation and parser-level checks.
5. Reject or explicitly handle encrypted, corrupt, empty, or unsupported PDFs according to policy.
6. Assign an opaque request/document ID; calculate SHA-256 for integrity and deduplication if approved.
7. Store the original PDF in the designated private object-storage location.

### Step 2 — Resolve configuration

1. Apply defaults for extraction flags, OCR, page limits, artifact formats, and output mode.
2. Record requested fields and the exact parser/config version.
3. Derive an idempotency key from the source hash plus relevant extraction configuration, if deduplication is approved.
4. Create or update the existing job/document tracker.

### Step 3 — Parse in an isolated worker

1. Create a fresh per-job temporary directory with an opaque name.
2. Invoke the parser through a wrapper, preferably without shell interpolation of user input.
3. Apply timeout, CPU, memory, page-count, and temporary-storage limits.
4. Collect structured output, extracted assets, parser warnings, and timing metrics.
5. If the parser fails, retry only when the error is classified as transient and the operation is safe to retry.
6. Store intermediate results only as long as necessary for debugging or recovery under the retention policy.

### Step 4 — Supplement extraction only where needed

Use the initial benchmark to identify gaps. Potential examples include:

- Extracting hyperlink annotations and destination URIs if the parser's normalized output is incomplete.
- Reading page boxes, rotation, and embedded image references from the PDF structure.
- Rendering precise table/image crops from a known bounding box.
- Resolving native coordinate systems into the project's canonical coordinate system.

Keep each supplementary extractor behind an interface and test it against the same golden corpus. Do not add several PDF libraries pre-emptively; every additional dependency increases licensing, compatibility, and debugging cost.

### Step 5 — Normalize metadata

1. Convert each parser output to the canonical page and element model.
2. Normalize page numbering and coordinates.
3. Assign stable element IDs for the duration of a document version.
4. Normalize type names and text payloads.
5. Preserve reading order and nested relationships where the parser provides them.
6. Normalize hyperlink URI and visible link text when available.
7. Map assets to safe relative paths under the output package.
8. Preserve confidence values only when supplied meaningfully by the parser; do not invent confidence scores.
9. Attach warnings for ambiguous ordering, missing coordinates, OCR uncertainty, and unsupported requested fields.

### Step 6 — Honor selected extraction fields

Define one mapping between existing API flags and canonical fields. For each request, record:

- `requested_fields`: what the caller asked for.
- `extracted_fields`: what was successfully generated.
- `skipped_fields`: what was deliberately omitted due to the request.
- `unsupported_fields`: what the chosen pipeline cannot provide.
- `failed_fields`: what was requested but failed.

Do not silently drop a requested field. Field filtering should occur at a clearly defined stage and should not accidentally remove information needed internally to calculate reading order or locate another requested element.

### Step 7 — Generate artifacts

- **Images:** export the chosen embedded image or rendered crop according to the contract. Record source page, bounding box, format, dimensions, and relative path.
- **Table snapshots:** render a crop from the source page based on the normalized table region, or reuse a parser-provided table image if quality is acceptable. Ensure the snapshot aligns with the metadata bounding box.
- **DOCX:** choose and document one supported output mode:
  - editable/reflowable DOCX rebuilt from parsed content, with expected layout differences documented; or
  - visually oriented DOCX with page renders embedded, preserving appearance but with limited editability; or
  - a hybrid if there is a real consumer need and the test plan supports it.
- **metadata.json:** serialize canonical metadata, then apply any contract-specific compatibility mapping.
- **manifest.json:** list package contents, schema version, file sizes, checksums if required, and field-extraction status.

### Step 8 — Validate and package

1. Validate metadata against the schema.
2. Validate page numbers and bounding boxes.
3. Verify every referenced asset exists and is readable.
4. Reject absolute paths, `..` path traversal, and unexpected archive entries.
5. Confirm mandatory ZIP members and file naming match the current contract.
6. Package to a temporary output file, then atomically publish the completed archive.
7. If validation fails, return a structured failure or partial-success status consistent with the existing contract.

### Step 9 — Return output and clean up

1. Persist final status and metrics in the approved tracker.
2. Return the ZIP through the current download/API flow.
3. Apply object-storage retention and temporary-file cleanup policies.
4. Ensure cleanup runs on both success and failure.
5. Keep a safe trace of the request ID, parser version, duration, warnings, and outcome for diagnostics.

---

## 8. Canonical metadata contract

This is a proposed starting point only. Final field names must be mapped to the actual PDFLens schema discovered in Section 3.

### 8.1 Top-level structure

```json
{
  "schema_version": "1.0",
  "document": {
    "source_filename": "source.pdf",
    "source_sha256": "<sha256>",
    "page_count": 2,
    "title": null,
    "language": null
  },
  "processing": {
    "parser_name": "selected-parser",
    "parser_version": "pinned-version",
    "model_version": null,
    "status": "success",
    "requested_fields": ["body_text", "header", "hyperlink", "image", "table"],
    "extracted_fields": ["body_text", "header", "hyperlink", "image", "table"],
    "warnings": [],
    "errors": []
  },
  "pages": [
    {
      "page_number": 1,
      "width_pt": 612.0,
      "height_pt": 792.0,
      "rotation_degrees": 0,
      "coordinate_system": "normalized_top_left_0_1",
      "elements": [
        {
          "element_id": "p0001-e0001",
          "type": "body_text",
          "text": "Example paragraph",
          "reading_order": 0,
          "bbox": {"x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.27},
          "confidence": null,
          "target_uri": null,
          "artifact_path": null,
          "attributes": {}
        }
      ]
    }
  ],
  "artifacts": {
    "docx_path": "document.docx",
    "image_paths": [],
    "table_snapshot_paths": [],
    "manifest_path": "manifest.json"
  }
}
```

### 8.2 Coordinate rules

Choose one canonical coordinate convention and enforce it everywhere:

- Bounding boxes are normalized to the range `[0, 1]` and use a top-left origin.
- `x0` and `y0` are the top-left corner; `x1` and `y1` are the bottom-right corner.
- Page width/height are stored in PDF points; page rotation is explicitly recorded.
- Validate `0 <= x0 <= x1 <= 1` and `0 <= y0 <= y1 <= 1` after normalization.
- Store parser-native boxes in `attributes` only if needed for provenance or debugging; clearly label their original coordinate convention.
- If the current public contract uses a different coordinate system, preserve that externally through an adapter instead of changing the consumers abruptly.

Normalized coordinates support consistent localization across rendering resolutions. They are not enough on their own for every use case, which is why page dimensions and rotation are also retained.

### 8.3 Suggested element types

Use a controlled vocabulary, retaining raw parser labels in `attributes` when helpful:

- `body_text`
- `heading`
- `header`
- `footer`
- `page_number`
- `footnote`
- `hyperlink`
- `image`
- `table`
- `caption`
- `list`
- `equation`
- `form_field`
- `code`
- `other`

Do not assume every parser can reliably distinguish all of these classes. Unsupported classes must be recorded and tested, not falsely inferred.

### 8.4 Element-level field definitions

| Field | Required? | Meaning |
|---|---|---|
| `element_id` | Yes | Stable within the document output version |
| `type` | Yes | Canonical element category |
| `text` | Conditional | Extracted textual content; null for image-only elements when appropriate |
| `reading_order` | Yes | Deterministic reading order on the page |
| `bbox` | Required where locatable | Normalized top-left coordinate box |
| `confidence` | Optional | Parser/OCR confidence only if actually available |
| `target_uri` | Conditional | Hyperlink target URI |
| `artifact_path` | Conditional | Relative path inside ZIP for image/table/rendered artifact |
| `attributes` | Yes, defaults to `{}` | Supplementary values such as table structure, parser-native label, OCR language, style hints, or warnings |

### 8.5 Schema versioning

- Version the canonical schema independently of the parser version.
- Add optional fields without breaking consumers whenever possible.
- For breaking changes, introduce a new schema/API version and migration plan.
- Keep old output mappings until all consumers have migrated.
- Store schema version in both metadata JSON and manifest.

---

## 9. ZIP package contract

Proposed structure—replace names with the exact existing PDFLens names after discovery:

```text
result.zip
├── document.docx
├── metadata.json
├── manifest.json
├── images/
│   ├── page-0001-image-0001.png
│   └── ...
└── tables/
    ├── page-0001-table-0001.png
    └── ...
```

### Package rules

- Asset paths in JSON are relative to the ZIP root.
- Use generated safe file names; do not use raw user-supplied paths as archive paths.
- Record the source page and element ID for each asset.
- Specify image/table snapshot format and DPI (or rendering scale) so output is reproducible.
- Keep the naming scheme stable and human-debuggable.
- No absolute file paths, temporary directory names, credentials, or local environment paths may leak into the archive.
- No archive entry may escape its package directory during extraction.
- A manifest should list each member, size, relative path, and—if required—SHA-256.

---

## 10. API and job lifecycle

### 10.1 Preserve the existing API

Do not design a new endpoint from scratch until the existing endpoint is documented. Keep method, request fields, authentication, status codes, ZIP member paths, and error envelope stable where feasible. If a change is necessary, make it explicit and versioned.

### 10.2 Request model (illustrative)

```json
{
  "extraction_fields": ["body_text", "header", "footer", "footnote", "hyperlink", "image", "table"],
  "output_mode": "legacy_compatible",
  "ocr_mode": "auto"
}
```

This is illustrative, not a required new public schema. Map it to the actual existing request model.

### 10.3 Job states

Use a finite and documented state model, adapting existing tracker values if they already exist:

- `RECEIVED`
- `VALIDATING`
- `QUEUED`
- `PARSING`
- `NORMALIZING`
- `GENERATING_ARTIFACTS`
- `VALIDATING_OUTPUT`
- `SUCCEEDED`
- `PARTIAL_SUCCESS`
- `FAILED`
- `CANCELLED` (if cancellation is supported)

Every transition should include an appropriate timestamp and failure reason. Avoid infinite retries. Retry only transient failures, and use idempotent writes so duplicate job events do not create duplicate output artifacts.

### 10.4 Error policy

Define stable error codes for invalid PDF, unsupported encryption, PDF corruption, page/size limit exceeded, parser timeout, parser failure, requested field unsupported, artifact generation failure, output validation failure, storage failure, and internal error. Avoid returning internal stack traces or sensitive document content to callers.

For partial success, define exactly whether the API returns a ZIP with warnings or fails the whole request. Keep behavior compatible with current consumers.

---

## 11. Data storage and integration

### 11.1 Original PDF and artifacts

- Use existing MinIO/object storage if that is the current platform standard.
- Store source and output artifacts in separate logical prefixes/buckets with least-privilege access.
- Use opaque IDs rather than personally meaningful filenames in object paths.
- Apply retention and deletion rules to temporary files, parser intermediate files, and final ZIPs.
- Persist a checksum and object version/ID as permitted by the platform.

### 11.2 Job and document trackers

If the current platform uses Oracle and a job/document tracker, extend or reuse it rather than introducing another database by default. Minimum state includes job ID, source object ID/hash, state, requested fields, parser/schema version, timestamps, output location, errors/warnings, and key metrics.

Do not store the entire PDF or large page payloads inside relational job rows unless there is an established reason. Keep large artifacts in object storage and track their references.

### 11.3 Kafka / asynchronous processing

If Kafka is already part of the service workflow:

- Define versioned event schemas.
- Use a stable job ID and idempotency key.
- Make consumers safe to run more than once.
- Bound retries and send poison messages to a dead-letter topic or established equivalent.
- Record the processing stage and correlation ID in every event/log.
- Ensure output publication is atomic; a consumer must not see a completed status before the output is fully written and validated.

If Kafka is not needed for the API contract, do not add it merely because the wider platform uses Kafka elsewhere.

---

## 12. Artifact-generation strategy

### 12.1 Images

Decide whether an “image” means the original embedded object, a crop of a PDF page, or both. These are not interchangeable. For every output image, define:

- asset type (`embedded_image`, `page_crop`, `figure_crop`, or equivalent)
- page number and source element ID
- normalized bounding box and page dimensions
- file format, width, height, and rendering DPI where applicable
- relative path in the ZIP

A page crop should be rendered from the original PDF using a documented coordinate transform. Test rotated pages, points-to-pixels conversion, and off-page/clamped bounding boxes.

### 12.2 Tables

The table snapshot is a visual artifact; it does not by itself prove that the table has been structurally extracted correctly. If downstream components need cells and rows, preserve structured table data too. Test merged cells, multi-line cells, tables across pages, low-quality scans, borderless tables, and tables embedded in images.

### 12.3 DOCX mode decision

Document this as an explicit product choice:

**Mode A — Editable reconstruction:** rebuild paragraphs, headings, tables, and images from parsed structure. This is more editable, but line wraps, spacing, page breaks, font substitution, and table placement may differ from the PDF.

**Mode B — Visual pages:** insert rendered source pages as images into a DOCX. This can preserve appearance more closely but is not equivalent to an editable document and can create large files.

**Mode C — Hybrid:** include editable extracted content and additional page renders or references only if a real use case requires it. This is more complex and needs its own tests.

Do not promise “preserves layout” based solely on generating a DOCX. The core layout evidence should be the page-level metadata and coordinates. Treat DOCX visual similarity as a separate gate.

---

## 13. Security and privacy requirements

PDF parsing must treat input files as untrusted. Apply the organization’s security policy and the relevant secure-upload guidance. OWASP recommends validating file types rather than trusting MIME headers, using allowlists, setting size limits, and using safe server-generated file names. See <https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html>.

### 13.1 Intake controls

- Allow only required file types; verify PDF content rather than relying on extension or `Content-Type` alone.
- Enforce maximum upload size, page count, decompressed/rendered output size, and processing time.
- Reject or route encrypted documents according to the approved password-handling policy.
- Use generated file names and opaque IDs.
- Prevent path traversal and archive entry path manipulation.
- Consider malware scanning where required by policy and available in the environment.

### 13.2 Worker isolation

- Run workers as a non-root user.
- Use per-job temporary directories and clean them on success/failure.
- Apply CPU, memory, execution-time, process-count, and disk limits.
- Restrict network egress from parser workers unless a reviewed model service requires it.
- Do not let the parser fetch arbitrary URLs embedded in the document.
- Keep secrets out of command-line arguments, environment dumps, logs, and package files.
- Use patched base images and scan dependencies.

### 13.3 Data access and retention

- Enforce authorization on both source PDFs and output ZIPs.
- Use private buckets and short-lived download URLs, if signed URLs are part of the platform.
- Do not log raw extracted text, financial/personal information, or document payloads unnecessarily.
- Document how long originals, outputs, intermediate parser data, and failed-job artifacts are retained.
- Apply the project's data residency and deletion policies.

### 13.4 Licensing and model governance

- Review the parser code license, model-weight terms, OCR engine, rendering library, and every transitive dependency.
- Track model source, version, checksum, accepted-use terms, and any attribution requirements.
- Conduct a legal/security approval before shipping a candidate parser.
- Treat the online-service attribution clause in the current MinerU license as a deployment consideration, not a footnote.
- Do not assume a parser code license automatically covers all associated models.

---

## 14. Reliability, performance, and scalability

### 14.1 Reliability

- Make each processing stage restartable or safely repeatable where practical.
- Use bounded retry with backoff for transient storage or infrastructure errors.
- Do not retry deterministic parser failures indefinitely.
- Publish the final archive only after full validation.
- Distinguish complete success, partial success, and failure.
- Maintain a known-good parser image/version to support rollback.

### 14.2 Performance testing

Capture metrics by page count, file size, digital vs scanned PDF, complexity, and OCR mode:

- total processing latency and latency per stage
- pages per second
- peak CPU and RSS memory
- temporary and output storage volume
- cold-start and warm-run times
- retry/failure rate
- output size and asset count

If using model-based parsers, test whether model load time dominates the request. Keep long-lived workers warm when appropriate, subject to memory limits and model isolation requirements.

### 14.3 Capacity policy

Before production, define maximum concurrent documents and queue depth. Apply backpressure rather than allowing an arbitrary number of complex PDFs to consume all worker memory. Use page-count buckets or workload classes if small and large documents have materially different profiles.

### 14.4 Deployment readiness

Follow the platform’s standard container/API deployment practices: HTTPS, startup/readiness/liveness checks, graceful termination, worker restarts, replication, memory limits, and safe configuration. FastAPI’s deployment guidance summarizes these operational concerns: <https://fastapi.tiangolo.com/deployment/concepts/>.

---

## 15. Testing strategy

### 15.1 Test corpus

Create and maintain a permissioned, representative corpus. Use anonymized or synthetic examples for shared reports where documents are sensitive.

| ID | PDF type | Main assertions |
|---|---|---|
| C-01 | Digital, single-column PDF | Text, headings, page count, baseline boxes |
| C-02 | Two-column document | Reading order, column separation, headings |
| C-03 | Image-only scan | OCR text, warnings/confidence where available, no crash |
| C-04 | Repeated headers/footers | Correct classification on multiple pages |
| C-05 | Footnotes and page numbers | Identify auxiliary blocks and correct page association |
| C-06 | Hyperlinks | Visible text, target URI, page, and location |
| C-07 | Dense tables / merged cells | Table localization, snapshot, structured extraction if required |
| C-08 | Figures, charts, embedded images | Asset export, caption association, bbox traceability |
| C-09 | Mixed page sizes / rotated pages | Coordinate conversion and page rotation |
| C-10 | Encrypted/corrupt PDF | Safe, documented failure response |
| C-11 | Large PDF / many pages | Timeout, memory, and size-limit behavior |
| C-12 | Forms / checkboxes / fields | Field classification if in scope |
| C-13 | Repeated text in page furniture and body | Avoid over-classifying body content as header/footer |
| C-14 | Borderless or scanned table | Table detection limits and quality measurements |
| C-15 | Mixed layout report with links, images and tables | End-to-end contract and artifact integrity |

### 15.2 Testing layers

1. **Unit tests:** coordinate normalization, page rotation transforms, path creation, field-flag filtering, schema validation, stable IDs, ZIP manifest.
2. **Parser adapter tests:** convert each parser-native output into the canonical schema; cover missing optional fields and unknown element types.
3. **Contract tests:** API request/response, required ZIP members, JSON schema, field names, status/error semantics.
4. **Golden regression tests:** compare outputs to manually reviewed annotations on the approved corpus.
5. **End-to-end tests:** upload → parse → normalize → generate artifacts → validate → ZIP → download and inspect.
6. **Failure tests:** parser timeout, crash, interrupted storage write, corrupt archive, missing asset, invalid URI, encrypted PDF, cancellation if supported.
7. **Security tests:** invalid MIME/signature, large inputs, path traversal strings, malicious archive names, untrusted URLs, resource exhaustion scenarios.
8. **Performance tests:** concurrent requests, large documents, cold/warm worker behavior, memory pressure, queue backpressure.
9. **Compatibility tests:** existing Intelligent Search consumers should be able to process the new ZIP/JSON without code changes, unless a documented migration is approved.

### 15.3 Quantitative acceptance thresholds

Set thresholds after running the baseline against the real PDFLens implementation. Proposed starting targets—not guarantees—are:

| Gate | Initial target for the approved golden set |
|---|---|
| Required ZIP members / JSON parseability | 100% |
| Referenced asset exists and is readable | 100% |
| Valid page references for emitted elements | 100% |
| Bounding boxes valid and in the documented coordinate system | 100% of boxes emitted |
| Required field flags honored | 100% of contract tests |
| Critical API and ZIP contract compatibility | 100% of contract tests |
| Detection quality for each mandatory element class | Target F1 of at least 0.95 where a reliable reference annotation is feasible; calibrate for scans and difficult cases |
| Bounding-box localization | Agree an IoU/tolerance threshold after corpus review; report per-class and per-document results, not just an overall mean |
| Hyperlink extraction | Measure link precision/recall on documents with known links; agree a target based on observed PDFLens baseline and business need |
| Performance | At or better than approved latency/resource SLOs for each document class |
| Security and licensing | No unresolved release-blocking findings |

Do not claim perfect extraction over arbitrary PDFs. A realistic guarantee is scoped to a defined input envelope and tested corpus, with explicit behavior outside that envelope.

### 15.4 Differential comparison with PDFLens

For each corpus document, run both the current service and the candidate using equivalent flags. Compare:

- page count and page dimensions
- element count by category
- text extraction and reading order
- header/footer/footnote classification
- hyperlink target and link text
- bounding box location
- image/table asset count, readability, and relative-path integrity
- DOCX page count and visual difference, if visual fidelity is required
- error behavior, processing time, memory, and output size

Every difference must be classified as one of:

- acceptable/expected difference
- candidate parser limitation
- adapter/mapping defect
- artifact-generation defect
- existing PDFLens defect
- unresolved / release-blocking

### 15.5 Manual review

Automation cannot fully assess layout quality. A reviewer should inspect rendered overlays that draw extracted boxes and types on top of the source page. This makes coordinate shifts and misclassified regions visible and creates evidence for acceptance decisions.

---

## 16. Observability and support

### 16.1 Structured logs

Record request/job ID, opaque document ID, parser and schema version, stage, duration, counts, outcome, warnings, and error code. Do not log document content or sensitive extracted metadata by default.

### 16.2 Metrics

At minimum:

- requests received / succeeded / partially succeeded / failed
- failure rate by error code and parser version
- processing latency by stage and document class
- queue depth and queue wait time, if asynchronous
- pages processed and pages per second
- peak memory or worker OOM events
- parser timeouts and retries
- asset generation/validation failures
- missing metadata fields and empty extraction outcomes
- storage volume and temporary-file cleanup failures
- output size distribution

### 16.3 Alerts

Alert on sustained failure-rate increases, output schema failures, missing artifact references, parser timeouts, queue backlogs, OOMs, unexplained element-count shifts, and retention/cleanup failures.

### 16.4 Runbooks

Create short runbooks for parser unavailable, model missing, worker OOM, corrupted output, storage unavailable, queue backlog, license/version rollback, and suspected sensitive-data leakage.

---

## 17. CI/CD and repository structure

### 17.1 Suggested repository layout

```text
pdflens-replacement/
├── app/
│   ├── api/                    # Public compatibility endpoints
│   ├── schemas/                # Request, canonical metadata, error schemas
│   ├── coordinator/            # Job lifecycle and idempotency
│   ├── parsers/
│   │   ├── base.py             # Parser interface
│   │   ├── docling_adapter.py  # If selected
│   │   └── mineru_adapter.py   # If selected
│   ├── normalization/          # Types, coordinates, reading order
│   ├── artifacts/              # Images, table snapshots, DOCX, manifest, ZIP
│   ├── storage/                # Existing object-store/database integrations
│   ├── security/               # Validation, limits, path safety
│   ├── observability/          # Structured logs and metrics
│   └── main.py
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── regression/
│   ├── security/
│   └── fixtures/               # Only approved/sanitized PDFs
├── schemas/
│   ├── canonical-metadata-v1.schema.json
│   └── manifest-v1.schema.json
├── docs/
│   ├── architecture.md
│   ├── api-contract.md
│   ├── data-mapping.md
│   ├── operations-runbook.md
│   └── license-inventory.md
├── deployment/
│   ├── Dockerfile
│   └── approved deployment manifests
├── pyproject.toml / lock file
└── README.md
```

Adjust the layout to the team's repository conventions. Avoid prematurely splitting this into many deployable services; separate modules first unless scale or platform requirements justify separate processes.

### 17.2 CI stages

1. Formatting, linting, and static type checks.
2. Unit tests and schema validation.
3. Adapter/contract tests.
4. A small quick regression corpus.
5. Dependency, secret, container, and license scans.
6. Container image build with pinned dependencies.
7. Integration tests in a disposable test environment.
8. Full regression run before release candidate approval.

Large models and large PDF corpora should be downloaded only from approved stores and should not bloat the application source repository.

---

## 18. Implementation roadmap for two engineers

The estimate below assumes two full-time engineers, existing platform services, available PDFLens samples, and no major access/environment blockers. Some work can run in parallel. The final schedule should be re-estimated after discovery.

### Phase 0 — Scope and baseline (Days 1–3)

**Both engineers**
- Inventory existing API, ZIP structure, JSON schema, field flags, error behavior, and consumers.
- Collect and classify the golden PDF corpus.
- Capture baseline PDFLens outputs and performance.
- Confirm whether DOCX visual fidelity is in scope.

**Engineer A — parsing/layout**
- Run Docling and MinerU on 5–10 representative PDFs.
- Inspect page coordinates, reading order, headers/footers, footnotes, hyperlinks, images, tables, and OCR.

**Engineer B — contract/integration**
- Document API and artifact contracts.
- Build automated ZIP/JSON inspection scripts.
- Draft canonical schema and field mapping.

**Exit gate:** candidate parser shortlist with evidence; open gaps and license risks documented.

### Phase 1 — Architecture and contract (Days 4–5)

- Decide parser candidate or continue a time-boxed comparison.
- Approve canonical schema and coordinate convention.
- Define API/ZIP compatibility, job states, error codes, and retention policy.
- Confirm parser/model/license approval path.
- Create repository scaffolding, CI checks, and local development setup.

**Exit gate:** architecture decision record (ADR) signed off by the technical owner.

### Phase 2 — Core parser and normalization (Week 2)

**Engineer A**
- Implement the primary parser adapter.
- Normalize page geometry, type labels, and reading order.
- Add supplementary extraction only for demonstrated gaps.

**Engineer B**
- Implement API request validation and job lifecycle.
- Implement canonical Pydantic/JSON Schema validation.
- Integrate object storage and existing job tracker as applicable.

**Exit gate:** PDFs can be parsed to canonical JSON through a repeatable local/API path.

### Phase 3 — Artifact generation and compatibility (Week 3)

**Engineer A**
- Implement image export/crop logic and table snapshots.
- Validate coordinate transforms and asset/page traceability.
- Add extraction-field filtering and warnings.

**Engineer B**
- Implement DOCX mode chosen by stakeholders.
- Implement manifest and ZIP generation.
- Match current ZIP names, paths, response format, and required metadata fields.

**Both**
- Integrate full end-to-end flow and fix contract mismatches.

**Exit gate:** candidate produces a valid ZIP accepted by contract tests on the baseline corpus.

### Phase 4 — Regression and robustness (Week 4)

- Expand golden corpus to cover scans, complex tables, columns, links, rotation, and mixed layouts.
- Implement automatic PDFLens-versus-candidate diffs.
- Add overlay review for bounding boxes.
- Test encrypted/corrupt/oversized inputs, parser crash, timeout, storage failure, partial extraction, and invalid archive paths.
- Profile runtime/memory and tune worker settings.
- Fix critical defects and document remaining limitations.

**Exit gate:** agreed acceptance gates pass, or a clearly documented gap-remediation plan is approved.

### Phase 5 — Production hardening (Week 5)

- Apply container hardening, access controls, temporary-file cleanup, and retention.
- Finish structured logs, metrics, alerts, dashboards, and support runbooks.
- Review dependencies/model licenses/SBOM and security scan results.
- Rehearse rollback and validate deployment/readiness checks.
- Run full regression and performance suite on release-candidate build.

**Exit gate:** release candidate passes functional, contract, security, licensing, and operational review.

### Phase 6 — Shadow/canary and cutover (Weeks 6–7 as required)

- Run shadow processing on approved documents, without changing the user-visible output.
- Compare candidate with PDFLens and investigate material differences.
- Enable a small canary only after shadow results pass.
- Monitor failure rate, latency, asset integrity, and extraction distributions.
- Increase traffic gradually if thresholds remain stable.
- Keep the old implementation deployable and rollback tested until the observation window ends.

**Exit gate:** owner signs off on observed quality, operational stability, unresolved issues, and rollback readiness.

### Realistic minimum plan

A four-week delivery may be feasible if the current contract is simple, a parser fits well, output fidelity expectations are limited to metadata/layout positions, and infrastructure already exists. Plan toward 4–7 weeks when production hardening, full regression, licensing, and safe rollout are required. Do not compress acceptance testing just to meet a calendar date.

---

## 19. Responsibilities and working model

| Workstream | Engineer A | Engineer B | Shared/other support |
|---|---|---|---|
| Parser evaluation | Lead | Review | Domain reviewers supply PDFs and expected results |
| Metadata and coordinate model | Lead | Co-design | Technical owner approves contract |
| API compatibility | Support | Lead | Existing API owner confirms expected behavior |
| Image/table artifacts | Lead | Support | Visual reviewer checks crops |
| DOCX and ZIP | Support | Lead | Stakeholder confirms DOCX mode |
| Test corpus and diffs | Lead parsing checks | Lead harness/contract checks | Reviewers annotate golden set |
| Security and licensing | Provide dependency details | Provide deployment details | Security/legal approval where required |
| Deployment and monitoring | Support | Lead | Platform/SRE assists if available |
| Release/rollback | Both | Both | Service owner approves cutover |

With only two engineers, avoid parallelizing too many feature branches. Keep the critical path focused on proving parser fit, stabilizing the schema, and getting full output-contract tests passing.

---

## 20. Risk register

| Risk | Likelihood / impact | Mitigation | Release-blocking condition |
|---|---|---|---|
| Header/footer or footnote misclassification | Medium / High | Golden corpus, overlays, supplementary heuristics only when measured | Critical required class falls below agreed threshold |
| Reading-order regressions | High on complex PDFs / High | Multi-column and mixed-layout fixtures; retain source boxes and reading order | Downstream text order is materially corrupted |
| Coordinate transforms/rotation wrong | Medium / High | One canonical convention, mathematical unit tests, rotated-page fixtures | Boxes fail page-bound validation or are visibly shifted |
| Hyperlinks missing | Medium / Medium–High | Dedicated annotation extraction if needed; URI fixtures | Mandatory link fields not recovered to target threshold |
| Table snapshots mismatch metadata boxes | Medium / High | Crop-level visual tests and path traceability | Snapshot not traceable or covers wrong region |
| DOCX visual mismatch | High if visual fidelity required / High | Decide output mode early; separate visual regression | Stakeholder visual-fidelity gate fails |
| Parser model/license incompatibility | Medium / High | Pre-implementation legal review and SBOM/model inventory | Unresolved license terms or attribution obligation |
| Model download/startup delays | Medium / Medium | Warm workers, approved model cache, cold-start tests | SLO cannot be met within approved infrastructure |
| Large PDFs exhaust memory | Medium / High | Limits, per-job isolation, backpressure, stress tests | Worker instability under accepted input envelope |
| API/ZIP contract breaks consumers | Medium / Critical | Capture old outputs; automated contract tests | Any critical downstream consumer breaks |
| Sensitive data leaks into logs/artifacts | Low–Medium / Critical | Logging allowlist, private storage, security tests | Any unresolved exposure issue |
| Candidate chosen based on toy samples | Medium / High | Representative corpus and benchmark scorecard | No evidence on critical document classes |
| Two-person capacity insufficient | High / Medium–High | Scope gates, no custom parser, stakeholder help with annotation | Required features cannot be validated within schedule |

---

## 21. Definition of done

The project is not complete just because the endpoint returns a ZIP.

### Functional readiness

- [ ] All required API parameters and field selections are supported.
- [ ] Required ZIP members and output names match the approved contract.
- [ ] Metadata JSON validates against the released schema.
- [ ] Page numbers, dimensions, rotations, coordinates, and element types are defined and consistent.
- [ ] Headers, footers, footnotes, hyperlinks, images, and tables meet agreed thresholds on the corpus.
- [ ] All asset references resolve; no unsafe paths exist.
- [ ] DOCX behavior and visual-fidelity scope are explicitly documented.
- [ ] Partial success and failures are reported correctly.

### Quality readiness

- [ ] Baseline comparison with PDFLens is complete.
- [ ] All critical differences are resolved or formally accepted.
- [ ] Regression suite runs in CI.
- [ ] Bounding-box overlay review is complete for representative documents.
- [ ] Performance meets approved thresholds for the accepted input envelope.

### Operational readiness

- [ ] Resource, upload, and timeout limits are configured.
- [ ] Logs, metrics, alerts, dashboards, and support runbooks are ready.
- [ ] Security and license reviews are approved.
- [ ] Version pinning and model provenance are recorded.
- [ ] Deployment, readiness checks, and rollback are tested.
- [ ] Retention, cleanup, and data-access rules are documented.
- [ ] Service owner and downstream consumers approve the cutover.

---

## 22. Decisions that must be made before production

1. Is the primary requirement bounding-box/layout metadata, or must the generated DOCX visually resemble the source PDF?
2. What exact API/ZIP/JSON contract must be preserved?
3. What document types, languages, page counts, and file sizes are supported?
4. Which encrypted PDFs are supported, and how are passwords handled?
5. Is OCR allowed to run locally only, and which languages are required?
6. Are there restrictions on CPU/GPU use, model downloads, outbound network, or container size?
7. What is the expected throughput and maximum concurrency?
8. What is the retention period for originals, ZIPs, intermediate files, and logs?
9. Which extraction failures may return partial success, and which must fail the request?
10. What are the acceptance thresholds for each element class and layout localization?
11. Are there licensing/attribution requirements for parser code, model weights, OCR, and PDF utilities?
12. Who signs off on quality, security, licensing, deployment, and rollback?

---

## 23. Immediate next steps

### Within the first two days

1. Obtain 5–10 representative PDFs and matching PDFLens ZIP outputs.
2. Capture the exact API request/response and all extraction flag options.
3. Decide whether DOCX visual fidelity is a hard requirement.
4. Run Docling and MinerU on the same PDFs in the approved environment.
5. Compare page-level types, bounding boxes, reading order, links, images, tables, and runtime.
6. Review current licenses for the parser and its model/dependency stack.
7. Choose the candidate only after the evidence is available.

### By the end of the first week

The team should have a working feasibility prototype and an evidence-based decision on the primary parser, not a claim of production readiness. It should include:

- a reproducible parser environment
- a written mapping from native parser output to canonical metadata
- a basic end-to-end ZIP build
- automated schema and artifact-path validation
- first benchmark results against PDFLens
- a list of missing features and production blockers
- an updated schedule based on observed gaps

### Before production cutover

- Complete the Definition of Done checklist.
- Conduct shadow/canary validation as permitted by data policy.
- Keep a known-good rollback path available.
- Record acceptance evidence, known limitations, owner approvals, and incident procedures.

---

## 24. Reference documentation

The following are official or primary project references to re-check before final dependency approval. Links and license terms can change; record the exact revision/tag used in the implementation.

- **Docling supported formats and outputs:** <https://docling-project.github.io/docling/usage/supported_formats/>
- **Docling project and license:** <https://github.com/docling-project/docling>
- **Docling Core schema/model documentation:** <https://github.com/docling-project/docling-core>
- **MinerU repository and current license:** <https://github.com/opendatalab/MinerU>
- **MinerU output files, page content, coordinates, element types, and link spans:** <https://github.com/opendatalab/MinerU/blob/master/docs/en/reference/output_files.md>
- **PyMuPDF licensing (if considered):** <https://pymupdf.io/licensing>
- **Marker repository (optional; review all model/commercial terms):** <https://github.com/VikParuchuri/marker>
- **OWASP File Upload Cheat Sheet:** <https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html>
- **FastAPI deployment concepts:** <https://fastapi.tiangolo.com/deployment/concepts/>

---

## Final recommendation

Proceed with a parser-based replacement behind a stable compatibility layer. Benchmark Docling and MinerU on actual PDFLens outputs before selecting the engine, normalize all results into a project-owned metadata contract, and validate the full output archive—not just extracted text.

For a two-person team, treat week one as feasibility and architecture validation. Plan approximately 4–7 weeks for a production candidate, then adjust based on benchmark results, required DOCX fidelity, corpus complexity, infrastructure constraints, and formal acceptance criteria. **Do not promise zero degradation without a defined corpus, measured thresholds, and successful differential testing.**
