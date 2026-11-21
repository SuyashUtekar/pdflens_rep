# PDFLens Finalized UI — Complete Implementation Plan

## 1. Objective and product scope

Build an executive-friendly application for submitting PDFs to PDFLens, tracking requests using confirmed service signals, retrieving processed ZIP packages, comparing outputs with the source PDF, and reporting validation findings.

The experience should use simple business language. Technical details may be available in supporting panels, but users should not need AI or development knowledge to understand the workflow.

Separate three capabilities:
1. **PDF processing** — performed by PDFLens.
2. **Result retrieval** — retrieving the ZIP using the PDFLens request ID.
3. **Validation and comparison** — performed by the application, not by any of the three PDFLens APIs.

## 2. Confirmed PDFLens API contract

PDFLens exposes three APIs in this integration: submit a PDF, retrieve its ZIP result, and check service health. The endpoint URLs and authentication come from the deployment environment. The result method is configurable because it must match the hosted API contract. Do not add other PDFLens calls.

### 2.1 Submit PDF for processing

Request body:

```json
{
  "file_path": "string",
  "config_id": "string",
  "callback_url": "string",
  "extract_tables": true,
  "extract_images": true,
  "extract_header": true,
  "extract_footer": true,
  "extract_hyperlinks": true,
  "extract_footnotes": false
}
```

Response contains `request_id` and `status`.

Implementation constraints:
- The API expects a server-side `file_path`. A browser `File` object or local device path is not a substitute.
- The application backend must stage the PDF in storage accessible to PDFLens and pass the resulting server-side path.
- `config_id` must be a valid configured identifier. Show a friendly configuration label in the UI, but submit the actual ID.
- `callback_url` is optional; include it in the submit request only when configured.
- Do not add undocumented request or response fields.

### 2.2 Retrieve processed result

Input body: `{"request_id": "..."}`. The method and URL come from the hosted API configuration.  
Response: ZIP file.

The application must validate the response as a ZIP archive before exposing it to the user.

Expected artifact types previously described:
- DOCX representation of the source PDF.
- Page-wise metadata JSON.
- Image screenshots/assets folder.
- Table snapshots folder.

Treat these as expected types, not a guaranteed archive layout. Build the UI inventory from the files actually present in each ZIP.

### 2.3 Check service health

Call the configured health-check URL and method for the hosted PDFLens service. The deployment contract determines the exact path and response body. Do not use the UI application's own liveness endpoint as a substitute for the hosted PDFLens health check.

### 2.4 Contract discovery checklist

Confirm before integration:
- Submit/result endpoint paths and HTTP methods.
- Authentication and network access requirements.
- Complete status vocabulary and terminal states.
- Callback support, payload schema, authentication, retry behavior.
- How `file_path` must be staged and made accessible.
- Valid configuration IDs and their source of truth.
- File size limits, timeouts, and error response schema.
- Result availability and retention period.
- Actual ZIP structure and metadata JSON schema.

**Do not invent a separate status polling endpoint or callback receiver.** In the deployed service, the get-result API itself returns queued/processing until it can return the ZIP. After the user starts retrieval with the request ID, repeat that get-result call at a configurable interval and maximum wait. Display the actual returned state, attempt number, and elapsed time; do not fabricate progress percentages or internal processing stages.

## 3. Information architecture

Primary navigation:
1. Dashboard
2. Upload & Process
3. Processing History
4. Comparison & Validation
5. Processed Documents
6. Reports

Global layout:
- Persistent left navigation on desktop; responsive navigation on smaller screens.
- Consistent page titles, concise descriptions, spacing, typography, and status labels.
- Request IDs should be copyable but visually secondary to document names.
- Provide consistent loading, empty, success, warning, and error states.
- Use accessible contrast; never rely on color alone to communicate status.
- Avoid unexplained AI scores, percentages, and technical acronyms.

## 4. Screen specifications

### 4.1 Dashboard

**Purpose:** Give executives a quick view of document activity and recent outcomes.

Summary cards:
- Total submitted.
- Completed.
- Processing.
- Failed.

Only show validation metrics after the application has run validation and has defined denominators.

Recent activity table:
| Column | Meaning |
|---|---|
| Document | Original filename |
| Request ID | PDFLens request identifier |
| Submitted | Submission date/time |
| Status | Actual normalized status |
| Actions | Open details, retrieve result, review validation |

Primary actions: **Upload PDF**, **View History**, and **Review Validation** where a validation result exists.

Dashboard figures must be calculated from application-side persisted job records. Do not imply PDFLens provides dashboard aggregates unless another API is confirmed.

### 4.2 Upload & Process

**File selection**
- Drag-and-drop and browse/select.
- Show filename and file size.
- Allow remove/replace.
- Validate extension, MIME type where available, file signature, and size. Backend validation is authoritative.

**Extraction options**

| UI label | API field | Default |
|---|---|---:|
| Extract tables | `extract_tables` | On |
| Extract images | `extract_images` | On |
| Extract headers | `extract_header` | On |
| Extract footers | `extract_footer` | On |
| Extract hyperlinks | `extract_hyperlinks` | On |
| Extract footnotes | `extract_footnotes` | Off |

Send the exact boolean values. Do not silently change defaults.

**Configuration**
- Provide a configuration selector with a friendly name and optional description.
- Submit the actual `config_id`.
- If no configuration-list API exists, use an approved application configuration source or administrator-managed list. Do not invent IDs.

**Advanced Settings**
- Collapsed by default.
- Include **Callback URL (optional)**.
- Validate URL syntax and permitted schemes.
- A syntactically valid URL is not proof that callback traffic is trustworthy; callback authentication is a backend responsibility.

**Submission summary**
Show filename, selected configuration, extraction options, and whether a callback URL is configured. Primary action: **Submit for Processing**.

**Submission sequence**
1. User selects a PDF and options.
2. Frontend sends the file to the application backend.
3. Backend validates and stages it in storage accessible to PDFLens.
4. Backend obtains the server-side `file_path`.
5. Backend calls the confirmed submit API with `file_path`, `config_id`, optional callback URL, and extraction flags.
6. Backend validates the response.
7. Backend persists the PDFLens `request_id`, returned `status`, and job metadata.
8. Frontend displays confirmation and request ID.
9. User can open the request detail page.

The frontend should normally call the application backend, not PDFLens directly. Keep credentials and internal storage paths out of the browser.

**Error cases**
- No file selected; unsupported file; oversized file; corrupt PDF.
- Invalid configuration or callback URL.
- Upload/staging failure.
- PDFLens timeout or rejection.
- Malformed/incomplete response.
- Duplicate submission attempt.
- Network interruption.

Show concise explanations and safe next actions. Never expose stack traces, credentials, internal hostnames, storage paths, or sensitive upstream payloads.

### 4.3 Processing History

History table:
- Document name.
- Request ID.
- Submitted date/time.
- Configuration.
- Status.
- Result availability.
- Actions.

Filters: status, date range, filename, request ID. Add pagination or incremental loading for large histories.

Request detail page:
- Original filename and PDFLens request ID.
- Submission timestamp.
- Returned and normalized status.
- Configuration and extraction options.
- Callback configured: Yes/No.
- Result availability.
- Safe error summary, if applicable.
- Available actions.

**Processing footprint**
Show only events supported by actual application records or confirmed service signals:
1. PDF submitted — after successful submit response.
2. Queued/processing — only with the actual status returned by the get-result API during bounded polling.
3. Result available — only when confirmed by the supported integration mechanism.
4. Results retrieved — after successful retrieval and ZIP validation.

If a stage is not observable, use neutral wording such as **Waiting for result availability**. Never show invented percentages or claim visibility into undocumented internal stages.

**Callback receiver — conditional**
Implement callbacks only after their contract is confirmed. The current alternative is bounded polling of the confirmed get-result API after the user initiates retrieval; do not add a separate status endpoint.

### 4.4 Processed Documents

Retrieval sequence:
1. User opens a request whose result is available.
2. Backend calls the result API using the stored `request_id`.
3. Backend validates the response and ZIP structure.
4. Backend stores or safely streams the package.
5. Application inspects actual archive contents and builds an artifact inventory.
6. UI displays available artifacts and download actions.

Recognize expected types such as DOCX, metadata JSON, image assets/screenshots, and table snapshots. Show only files actually present. If an expected artifact is missing, say **Not available in this result**.

**ZIP safety**
- Reject malformed ZIPs.
- Prevent ZIP Slip/path traversal.
- Limit file count, total uncompressed size, and compression ratio.
- Avoid blindly extracting executable or unsafe content.
- Generate safe download filenames.
- Enforce authorization.
- Do not expose internal storage paths.
- Apply retention/deletion policy.

Offer complete ZIP download and, where implemented by the application, individual artifact download and preview. Do not imply PDFLens has individual-artifact endpoints; the application can serve files after safe ZIP inspection.

### 4.5 Comparison & Validation

Validation is an application-side capability, not one of the three PDFLens APIs.

Overview should show:
- Pages evaluated / total pages.
- Passed checks.
- Needs-review checks.
- Failed checks.
- Artifact availability.
- Major findings.
- Individual comparison modules.

Do not use one unqualified “accuracy score” that mixes unrelated dimensions. Each metric needs a documented definition, numerator, denominator, normalization method, and source.

#### Module A — PDF vs DOCX

UI: source PDF preview beside DOCX preview/rendering, with a findings panel.

Checks:
- Text coverage.
- Reading order.
- Heading and section hierarchy.
- Paragraph and list preservation.
- Table preservation.
- Image presence and placement.
- Page/section associations.
- Visual similarity where reliable rendering comparison exists.

DOCX is reflowable; page count may differ from the PDF. Equal page counts are not a universal success criterion. Report content/structure preservation separately from visual similarity.

#### Module B — PDF vs Images

UI: source page preview, extracted image gallery, image details panel.

Checks:
- Image count.
- Page association.
- Bounding box, if available.
- Dimensions and aspect ratio.
- Duplicate and missing images.
- Visual similarity where applicable.

Distinguish full-page screenshots from embedded image assets.

#### Module C — PDF vs Tables

UI: source table region, extracted table grid, table snapshot if present, findings panel.

Checks:
- Table count.
- Row and column counts.
- Cell content.
- Missing/extra rows and columns.
- Header recognition.
- Merged-cell handling.
- Reading order.
- Page association.

Normalize harmless whitespace only where appropriate. Preserve numeric, date, sign, and unit semantics.

#### Module D — PDF vs Metadata JSON

UI: PDF page viewer, expandable JSON tree, field-level comparison.

Checks:
- Page count and numbering.
- Body text coverage.
- Headers and footers.
- Heading/section information.
- Footnotes and references.
- Hyperlink text and destinations.
- Image/table metadata and referenced paths.
- JSON schema validity.

Use the actual PDFLens schema. Do not invent fields or assume optional fields occur on every page.

#### Module E — PDF vs Headers and Footers

Checks:
- Text match.
- Correct page association.
- Repeated header/footer consistency.
- Page-number extraction.
- Missing values.
- False positives where body text is classified as a header/footer.

#### Module F — PDF vs Hyperlinks

Checks:
- Link/annotation count.
- Visible text.
- URI or internal destination.
- Page association.
- Missing destinations and duplicates.

Do not treat valid internal page navigation as a broken external URL.

#### Module G — PDF vs Footnotes

Checks:
- Footnote text and marker.
- Page association.
- Reference-to-footnote mapping.
- Missing or duplicate footnotes.

**Comparison states**

| State | Meaning |
|---|---|
| Passed | Defined check met its acceptance rule |
| Needs review | Ambiguous result or review threshold not met |
| Failed | Defined check did not meet its acceptance rule |
| Not requested | Corresponding extraction option was disabled |
| Not available | Expected artifact/data was absent |
| Not evaluated | Validation has not run that check |

Do not count Not requested or Not evaluated as failures. Do not mark Passed merely because a file exists.

**Finding detail** should include, where available: source PDF page and bounding box; output filename/page/record/table; expected and actual values; difference category; severity; validator/rule version; and evidence preview.

**Validation engine components**
1. ZIP Inspector — safe archive inspection and artifact inventory.
2. Artifact Parser — DOCX, JSON, image, and table parsing.
3. Source PDF Analyzer — page rendering and comparable source information.
4. Comparison Engine — text, table, image, metadata, hyperlink, header/footer, and footnote checks.
5. Validation Result Store — run summaries, metrics, and findings.
6. Comparison API — serves results to the frontend.

Version the validation engine and rules so results are reproducible.

### 4.6 Reports

Report contents:
- Document name and request ID.
- Submission/retrieval timestamps.
- Configuration and extraction options.
- Artifact inventory.
- Pages evaluated / total pages.
- Passed / needs review / failed counts.
- Metric definitions and values.
- Major findings with page references.
- Validation method and version.
- Known limitations and items not evaluated.

The application may implement PDF, CSV, and JSON exports. These are application features, not additional confirmed PDFLens APIs.

## 5. Proposed technical architecture

### 5.1 End-to-end flow

```text
Browser UI
   |
   v
Application Backend
   |------------------------|
   v                        v
File Staging             Job Metadata Store
   |
   v
PDFLens Submit API
   |
   v
PDFLens Processing
   |
   | callback, if confirmed and supported
   v
Application Callback Receiver
   |
   v
Application Backend
   |
   v
PDFLens Result API (request_id)
   |
   v
ZIP Validation and Storage
   |
   v
Artifact Inspector and Parser
   |
   v
Source PDF Analyzer + Comparison Engine
   |
   v
Validation Result Store
   |
   v
Dashboard / History / Comparison / Reports
```

The callback branch is conditional. Do not imply callback support before verification.

### 5.2 Frontend folder structure

```text
src/
  app/
    routes/
    layouts/
    providers/
  components/
    navigation/
    status/
    upload/
    extraction-options/
    timeline/
    file-preview/
    comparison/
    validation/
    reports/
    common/
  features/
    dashboard/
    upload-process/
    processing-history/
    processed-documents/
    comparison-validation/
    reports/
  services/
    api-client/
    pdflens/
    jobs/
    results/
    comparisons/
    reports/
  hooks/
  types/
  utils/
  constants/
  tests/
```

Keep page-specific logic in feature modules and shared presentation elements in `components`.

### 5.3 Proposed application backend routes

These are proposed **application routes**, not confirmed PDFLens endpoints:

| Route | Purpose |
|---|---|
| `POST /api/jobs` | Accept upload, stage file, submit to PDFLens |
| `GET /api/jobs` | List persisted jobs |
| `GET /api/jobs/{job_id}` | Retrieve job details |
| `GET /api/jobs/{job_id}/download` | Retrieve/download validated ZIP |
| `POST /api/callbacks/pdflens` | Receive callbacks, only if supported |
| `POST /api/jobs/{job_id}/validations` | Start application-side validation |
| `GET /api/jobs/{job_id}/validations` | List validation runs |
| `GET /api/validations/{validation_id}` | Retrieve validation details |
| `GET /api/validations/{validation_id}/export` | Export validation report |

### 5.4 Job data to persist

- Internal application job ID.
- PDFLens request ID.
- Original filename.
- Server-side file reference.
- File size and content hash.
- Configuration ID.
- Extraction option values.
- Callback configured flag.
- Submission timestamp.
- Raw upstream status where safe.
- Normalized application status.
- Result availability.
- ZIP storage reference.
- Error category and safe error message.
- Created/updated timestamps.

### 5.5 Event history

Record job creation, file staging, submit request, acceptance/rejection, callback receipt if applicable, status changes, result retrieval, ZIP validation, artifact inventory, validation start/completion, report export, and downloads.

Use application job ID, PDFLens request ID, and correlation ID to connect events and logs.

## 6. Security, privacy, and operations

**File handling**
- Validate file type and signature.
- Enforce size limits.
- Use private storage and least-privilege access.
- Generate safe filenames/object keys.
- Protect against ZIP Slip and decompression bombs.
- Apply retention and deletion rules.

**API security**
- Keep PDFLens credentials on the backend.
- Do not expose internal API URLs or server file paths to the browser.
- Authenticate application endpoints and authorize every job/artifact access.
- Apply rate and request-size limits.
- Use timeouts and controlled retries.
- Do not blindly retry a submission when the upstream outcome is unknown; use documented idempotency support if available.

**Callback security, if supported**
- Authenticate sender.
- Validate payload schema and request ID.
- Reject invalid status transitions.
- Make processing idempotent.
- Record receipt and validation outcomes.
- Do not trust arbitrary callback payload content.

**Observability**
Capture application job ID, PDFLens request ID, correlation ID, API operation/outcome, latency, callback outcomes, ZIP size and inventory, validation run/version/findings, and download events. Never log credentials or unnecessarily expose document content.

## 7. Implementation phases and milestones

### Phase 0 — API and artifact discovery
- Obtain API specification and confirm paths, methods, auth, statuses, errors.
- Confirm callback support and contract.
- Confirm `file_path` staging requirements.
- Confirm configuration source.
- Obtain representative PDFs and ZIPs.
- Inspect archive layout and JSON schema.
- Confirm limits, retention, and timeout expectations.

**Exit:** Contract documented, samples available, owners assigned to open questions, no unverified behavior assumed.

### Phase 1 — UX and design system
- Finalize navigation and layouts.
- Define typography, spacing, colors, tables, status labels, and empty states.
- Prototype upload, history, detail, comparison, and reports.
- Review with stakeholders.
- Check responsive and accessibility requirements.

**Exit:** Approved designs, status vocabulary, metric definitions, and executive-friendly copy.

### Phase 2 — Application shell and dashboard
- Implement layout/navigation and shared components.
- Build dashboard cards and recent activity.
- Connect to persisted job records.

**Exit:** Navigation works; dashboard handles loading/empty/error states and uses real records.

### Phase 3 — Upload and submission
- Implement file selection and validation.
- Implement extraction options and defaults.
- Add configuration selector and optional callback field.
- Implement backend staging and submit API integration.
- Persist request ID/status and show confirmation.

**Exit:** Valid PDF submits end-to-end with correct `file_path` and flags; failures are handled.

### Phase 4 — History and lifecycle
- Build history, filters, pagination, and detail view.
- Normalize status using confirmed contract.
- Add event history.
- Implement authenticated callback receiver only if supported.
- Define truthful result-availability behavior.

**Exit:** Users can reopen requests; no fabricated status; callback handling is safe if present.

### Phase 5 — Result retrieval
- Integrate result API using request ID.
- Validate ZIP, store/stream safely, inspect contents.
- Build artifact inventory, ZIP download, and supported previews.

**Exit:** Valid ZIP retrieves safely; unsafe archives are rejected; inventory matches actual contents.

### Phase 6 — Validation engine
- Implement ZIP Inspector, parsers, source PDF analysis, and comparison rules.
- Define thresholds and metric formulas.
- Persist versioned validation runs and findings.

**Exit:** Results reproducible; metrics defined; unrequested/unavailable items classified correctly.

### Phase 7 — Comparison UI and reports
- Build overview and all seven comparison modules.
- Add finding filters/evidence panels.
- Build report view and exports.

**Exit:** Users can inspect available outputs and understand metrics, findings, and limitations.

### Phase 8 — QA, security, release
- End-to-end, browser, responsive, accessibility, security, performance, and recovery testing.
- Configure production monitoring and handover.

**Exit:** Critical/high defects resolved; QA/security sign-off; monitoring and support documented.

## 8. Testing strategy

### Upload/submission
- Valid PDF.
- Non-PDF renamed with `.pdf`.
- Corrupt and empty PDF.
- Oversized file.
- Extraction flag combinations and defaults.
- Footnotes default off.
- Valid/invalid configuration.
- Callback omitted/valid/invalid.
- Staging failure, upstream timeout/rejection.
- Malformed submit response.

### Lifecycle
- Request ID persistence.
- Unknown status.
- Duplicate, invalid, delayed, or out-of-order callback if applicable.
- Callback for unknown request.
- No callback/delayed result.
- Page refresh and revisit.

### Result retrieval
- Valid/invalid ZIP.
- Missing expected artifact and additional files.
- Path traversal entry.
- Excessive decompressed size.
- Timeout and result-not-ready.
- Unauthorized download.

### Validation
- Exact/missing/reordered text.
- Table row/column/cell mismatch.
- Numeric/date mismatch.
- Missing/duplicate image.
- Wrong page association.
- Missing metadata.
- Header/footer false positive.
- Broken external link and valid internal link.
- Missing footnote marker.
- Disabled extraction option.
- Artifact unavailable and validation not run.

### UI/accessibility
- Desktop, tablet, and mobile.
- Keyboard and screen-reader navigation.
- Color contrast.
- Long filenames/request IDs.
- Large history datasets.
- Empty/loading/success/warning/error states.

## 9. Demo and production behavior

**Demo mode**
- Label all sample data as **Sample Data** or **Demo Mode**.
- Label simulated events as simulated.
- Never present sample validation scores as actual PDFLens results.
- Keep demo and production records separate.

**Production mode**
- Use actual API responses and persisted request IDs/statuses.
- Use actual callback events only if supported.
- Retrieve actual ZIPs and inspect actual contents.
- Display actual application-generated validation results.

## 10. Delivery priorities

### First working release
1. Application shell/navigation.
2. Upload PDF.
3. Extraction options/defaults.
4. Configuration selector.
5. Optional callback URL.
6. Backend staging and submit integration.
7. Request ID/status.
8. Processing history/detail.
9. Result API integration.
10. Safe ZIP download.

### Full finalized UI
1. Artifact inventory.
2. DOCX comparison.
3. Image comparison.
4. Table comparison.
5. Metadata JSON comparison.
6. Header/footer comparison.
7. Hyperlink comparison.
8. Footnote comparison.
9. Executive validation summary.
10. Evidence-backed findings and reports.

### Later enhancements
- Historical quality trends.
- Notifications/report scheduling.
- Synchronized PDF/output zoom and pan.
- Reviewer annotations.
- Configurable validation rules.
- Validation run comparisons.
- Reviewer workflow/approval.
- Bulk submission if required.

## 11. Definition of done

- A user can submit a valid PDF.
- Backend stages the file and sends the correct server-side `file_path`.
- Extraction flags map correctly to API fields and defaults.
- Callback URL is optional.
- Returned request ID/status are persisted and displayed.
- Users can view history and request details.
- Results are retrieved using request ID.
- ZIPs are validated and handled safely.
- Artifact inventory reflects actual ZIP contents.
- Comparisons are application-generated and traceable to source evidence.
- Unrequested, unavailable, and unevaluated items are not counted as failures.
- Metrics have documented definitions and denominators.
- Reports include methodology and limitations.
- Production never displays fake progress or unsupported API behavior.
- Authorization, file security, logging, accessibility, QA, and operational sign-off are complete.

## 12. Decisions required before estimation

1. Exact PDFLens endpoint paths, methods, and authentication?
2. Full set of submit status values?
3. Callback support and exact payload/authentication contract?
4. Required staging mechanism for `file_path`?
5. Source of valid `config_id` values?
6. Exact ZIP layout and metadata JSON schema?
7. File-size limits, retention period, and timeout expectations?
8. First-release validation checks and acceptance thresholds?
9. Roles allowed to submit, retrieve, compare, and export?
10. Retention/deletion rules for original PDFs and result ZIPs?

## 13. Recommendation

Deliver the product in two layers:

- **PDF processing experience:** Upload, configure, submit, track using confirmed signals, retrieve, and inspect the output package.
- **Quality and validation experience:** Compare the original PDF with outputs, explain differences with evidence, and produce executive-friendly reports.

This separation keeps the integration faithful to the three PDFLens APIs while allowing the application to provide richer comparison and validation without implying those capabilities are native PDFLens endpoints.
