# Multi-PDF Validation Report: PDFLens Replacement with Docling

**Document type:** Technical validation and remediation plan\
**Parser under evaluation:** Docling 2.141.0\
**Scope:** Cross-document extraction quality, vulnerabilities,
remediation strategy, improvement roadmap, and production-readiness
criteria\
**Current status:** **Not production-ready; continue controlled testing
and remediation**

## 1. Executive summary

The available evaluations show that Docling can extract useful content
from regulatory PDFs, including body text, headings, footers,
hyperlinks, footnotes, images, and some table regions. However,
extraction quality is inconsistent across documents and fields. The most
consequential observed problem is **missing or sparse body text on some
pages**. Other recurring gaps include inconsistent header/footer
classification, page numbers appearing only as footer text instead of a
dedicated field, incomplete or fragmented hyperlinks, unreliable
footnote classification, and table regions being detected without
verified structured row/cell data.

From the six document evaluations currently available in the
conversation history:

-   **2 documents were rejected for production use** because of
    significant extraction risks, particularly incomplete body text.
-   **4 documents were considered acceptable for continued testing**,
    with minor issues or improvements required.
-   These outcomes do **not** establish full parity with PDFLens, and
    they do not establish the results for the other nine documents in
    the intended 15-document corpus. Those nine evaluations must be
    recovered or run before making a corpus-wide claim.

### Overall recommendation

Treat Docling as a promising parsing component, not as a drop-in
replacement for the full PDFLens contract. Build a validation and
normalization layer around it, add deterministic checks for content
completeness and field coverage, and compare the output with PDFLens on
the same corpus. Do not approve production deployment until critical
content-loss tests and regression thresholds pass.

## 2. Scope and evidence limitations

This report consolidates the six evaluations available in the current
conversation history:

-   `doc30.pdf` --- *Commercial Banks -- Transfer and Distribution of
    Credit Risk Directions, 2025*
-   2018 circular --- *Co-origination of loans by Banks and NBFCs for
    lending to priority sector*
-   `doc28.pdf` --- *Non-Banking Financial Companies -- Microfinance
    Institution Directions, 2025*
-   `doc12.pdf` --- *Authentication Mechanisms for Digital Payment
    Transactions Directions, 2025*
-   `32.pdf` --- *Commercial Banks -- Cybersecurity, Technology: Risk,
    Resilience and Assurance Framework Directions, 2026*
-   `doc11.pdf` --- *Master Direction on Digital Payment Security
    Controls, 2021*

The following distinction is important:

-   **Observed:** explicitly recorded in the available document
    evaluations.
-   **Risk / inference:** a likely engineering risk based on those
    observations; it must be verified with repeatable tests.
-   **Not verified:** an aspect for which the available evaluation did
    not prove correctness, such as whether detected table regions
    contain complete structured cells.

This report does not invent results for the other nine PDFs. It also
does not treat "not detected" as proof that an element does not exist in
the source PDF. Each absence must be checked against the rendered source
page and, where possible, the original PDF text/annotations.

## 3. Cross-document validation findings

  ------------------------------------------------------------------------------
  Validation area   Cross-document      Risk level        Required action
                    finding                               
  ----------------- ------------------- ----------------- ----------------------
  Body text         Some documents have **Critical**      Implement per-page
  completeness      sparse or empty                       completeness checks
                    `body_text` on                        and source-to-output
                    pages where                           regression tests.
                    meaningful source                     
                    content may exist.                    
                    One evaluated PDF                     
                    had empty body text                   
                    on nine pages;                        
                    another had                           
                    significant                           
                    body-text gaps.                       

  Headers           Headers may be      High              Normalize header
                    missing from a                        extraction; validate
                    dedicated field,                      positional and
                    split into multiple                   repeated text patterns
                    elements, or                          against the page.
                    confused with                         
                    headings/annex                        
                    labels.                               

  Footers           Usually captured    Medium--High      Add text-quality
                    reasonably well,                      checks and normalize
                    but footer content                    footer classification
                    can contain garbled                   without discarding
                    Hindi text or                         source text.
                    inconsistent                          
                    classification.                       

  Hyperlinks        Often captured, but High              Validate both visible
                    some visible link                     link text and target
                    text is fragmented;                   URI/annotation
                    one evaluation                        coverage.
                    found only two                        
                    links and suggested                   
                    possible                              
                    incompleteness.                       

  Footnotes         Detection is        High              Use layout, markers,
                    inconsistent;                         position, and
                    numbered clauses                      references in the
                    can be                                body; keep confidence
                    misclassified as                      and provenance.
                    footnotes, and some                   
                    documents report no                   
                    footnotes.                            

  Page numbers      Page labels often   High              Separate physical page
                    appear in footer                      index from printed
                    elements, while a                     page label and
                    dedicated                             validate sequence.
                    `page_number` field                   
                    is missing or                         
                    inconsistent.                         
                    Printed page                          
                    numbering may                         
                    differ from                           
                    physical PDF page                     
                    indices.                              

  Tables            Some table regions  **Critical for    Require cell-level
                    are detected, but   table-heavy       validation, preserve
                    structured          PDFs**            table snapshots, and
                    rows/cells are not                    test merged cells,
                    always confirmed.                     multi-page tables, and
                    In some output, the                   reading order.
                    table field is                        
                    missing or tables                     
                    are represented as                    
                    image artifacts.                      

  Images            RBI logos and other Medium            Deduplicate only when
                    image regions are                     safe; preserve
                    generally detected.                   meaningful
                    Repeated logos may                    stamps/signatures and
                    create duplicate                      track page
                    artifacts;                            coordinates.
                    signatures/stamps                     
                    can also be                           
                    important.                            

  Encoding /        Hindi footer text   High where        Add
  multilingual text was garbled in one  legally           Unicode/text-quality
                    evaluation.         meaningful        validation and compare
                                                          rendered text to
                                                          extraction.

  Output schema /   Field availability  **Critical for    Build a stable adapter
  artifacts         varies across PDFs; integration**     schema and validate
                    some content is                       required
                    available only in                     fields/artifacts for
                    generic elements or                   every page.
                    footer text rather                    
                    than the expected                     
                    dedicated field.                      
  ------------------------------------------------------------------------------

## 4. Main vulnerability points and how to tackle them

Here, "vulnerability" means a reliability or data-integrity weakness in
the extraction pipeline---not necessarily a security exploit.

### 4.1 Critical: incomplete or missing body text

**Evidence from evaluations**

-   `doc30.pdf` had significant body-text gaps across multiple pages.
-   `doc11.pdf` had empty `body_text` on nine pages, including pages 5,
    8--12, 14, 17, and 19. Some of those pages may still have content in
    other element lists, but that does not prove that the expected
    body-text output is complete.
-   Other evaluations also noted sparse `body_text` on some pages even
    when elements were present.

**Why this matters**

Regulatory PDFs can contain operative requirements, exceptions,
definitions, deadlines, and conditions. Missing paragraphs can make
downstream search, summarization, compliance analysis, or retrieval
misleading. This is the highest-priority failure because an apparently
successful parse may still omit material content.

**Remediation**

1.  Measure extracted text length and non-whitespace character count per
    physical page.
2.  Flag pages with empty or unusually short text, especially where the
    rendered page contains substantive text.
3.  Compare Docling output with a baseline text layer extracted from the
    PDF and/or the approved PDFLens output.
4.  Use a fallback extractor such as PyMuPDF for pages that fail
    completeness checks; merge results only with page-level provenance
    and duplicate-control rules.
5.  For scanned or image-only pages, detect low text-layer coverage and
    route to OCR. Keep OCR output marked as OCR-derived.
6.  Preserve both raw parser output and normalized output so that
    content is never silently overwritten.
7.  Add regression fixtures for every known failed page and require
    those fixtures to pass after changes.

**Acceptance checks**

-   No unexplained empty body-text page where the source page contains
    substantive text.
-   No material source paragraph is absent from the normalized result
    without an explicit, documented reason.
-   Every fallback or OCR decision is logged with page index, trigger,
    extractor, and outcome.

### 4.2 High: headers and footers are inconsistently classified

**Evidence from evaluations**

-   Some documents contain header/footer text in generic elements but
    lack the dedicated `header` field.
-   `doc30.pdf` had "Annex III" misclassified as a header while expected
    repeating headers were absent.
-   `32.pdf` captured repeating headers on most content pages, but some
    headers were split.
-   Footer content was generally more successful, although multilingual
    encoding issues were observed.

**Why this matters**

Header/footer classification affects document navigation, repeated-text
suppression, page-level metadata, and clean body-text generation.
Over-aggressive removal can delete genuine legal content;
under-classification can pollute body text.

**Remediation**

1.  Retain raw page elements and their bounding boxes before
    classification.
2.  Use a combined strategy: Docling layout/furniture signals plus
    positional heuristics and repeated-text detection across pages.
3.  Treat repetition as evidence, not as the sole rule. A repeated title
    can be meaningful, and a one-off annex label is not necessarily a
    header.
4.  Use page-relative coordinates and validate coordinate conventions on
    representative PDFs.
5.  Keep a configurable classification confidence score and an
    `unclassified` state instead of forcing every element into a
    category.
6.  Do not delete header/footer text by default; expose classification
    separately so downstream consumers can choose whether to suppress
    it.

**Acceptance checks**

-   Repeating headers and footers are identified consistently across a
    document.
-   Main headings, annex labels, and operative body paragraphs are not
    incorrectly removed as furniture.
-   Classification can be traced to raw text, page number, coordinates,
    and rule/model confidence.

### 4.3 High: page numbers are not normalized into a reliable field

**Evidence from evaluations**

-   Page numbers often appear as footer text but the dedicated
    `page_number` field is absent or inconsistent.
-   In `doc12.pdf`, printed numbering ran from 1 to 7 across eight
    physical PDF pages, with a cover/index page excluded from printed
    numbering.
-   `doc11.pdf` had page numbers as footer elements but no dedicated
    page-number field.

**Why this matters**

Physical PDF page index and printed page label are different concepts.
Conflating them can break citations, search result navigation, and
document references.

**Remediation**

Store separate fields:

-   `physical_page_index`: zero- or one-based index, with convention
    documented.
-   `printed_page_label`: literal label visible on the page, such as
    `Page 3 of 7`, `iii`, or `A-2`.
-   `printed_page_number`: optional parsed numeric value when
    unambiguous.
-   `page_number_source`: parser, footer heuristic, or OCR.
-   `page_number_confidence`: confidence or validation status.

Validate monotonic sequences where applicable, but do not force a
sequence when front matter, annexes, Roman numerals, or omitted cover
numbering explain the difference.

**Acceptance checks**

-   Physical page index exists for every page.
-   Printed labels are preserved literally when detected.
-   Missing or ambiguous printed numbers are explicitly
    null/unknown---not guessed.
-   The output distinguishes physical page count from printed numbering.

### 4.4 High: hyperlink text and targets may be incomplete

**Evidence from evaluations**

-   Several documents captured hyperlinks but had fragmented visible
    text.
-   `doc11.pdf` produced only two hyperlinks, with possible
    under-detection.
-   PDF link annotations and email targets were captured in at least one
    evaluation.

**Why this matters**

A link can have correct target metadata but unusable visible text, or
visible text without a target. Regulatory circulars frequently reference
other directions, web pages, and email addresses.

**Remediation**

1.  Extract both PDF link annotations and visible link text.
2.  Preserve each link as a structured object with page index, bounding
    box, visible text, target URI, link type, and extraction source.
3.  Merge adjacent text fragments only when their geometry and reading
    order support it.
4.  Validate targets for malformed URIs, missing schemes, and obvious
    truncation; do not silently rewrite targets.
5.  Compare annotation counts and positions against the source PDF where
    available.
6.  Distinguish a hyperlink from plain text that merely resembles a URL
    or email address.

**Acceptance checks**

-   Known PDF annotations are accounted for, or the omission is logged.
-   Visible text is readable and in correct reading order.
-   Target URI is preserved exactly unless normalization is explicitly
    documented.

### 4.5 High: footnotes are missed or ordinary clauses are misclassified

**Evidence from evaluations**

-   `doc30.pdf` reported 49 footnotes, many of which appeared to be
    ordinary numbered clauses.
-   The 2018 co-origination circular also had footnote-like clauses
    classified as footnotes.
-   Some PDFs reported no footnotes even though dedicated footnote
    support was expected.

**Why this matters**

Misclassification can distort clause numbering, legal references, and
the relationship between a footnote marker and its explanatory text.

**Remediation**

1.  Detect likely footnote markers in body text and match them to
    candidate notes near the page bottom.
2.  Use font size, vertical position, indentation, marker format, and
    cross-reference evidence together.
3.  Do not classify every numbered paragraph as a footnote.
4.  Preserve raw text and add `classification_confidence` and
    `classification_reason`.
5.  Support footnotes that continue across pages and notes marked with
    symbols, letters, or numerals.
6.  Maintain a distinction between `footnote`, `endnote`,
    `numbered_clause`, and `unknown_note`.

**Acceptance checks**

-   Ordinary numbered legal clauses remain body text unless evidence
    supports footnote classification.
-   Footnote markers and note text can be associated when the source
    supports the relationship.
-   Uncertain cases remain reviewable instead of being silently
    misclassified.

### 4.6 Critical for table-heavy documents: table regions without structured cells

**Evidence from evaluations**

-   Some documents reported table regions but did not demonstrate
    complete structured rows/cells.
-   `doc11.pdf` had three table regions represented as image artifacts.
-   `32.pdf` did not report a table field.
-   A table snapshot is useful for visual reference, but it is not proof
    of machine-readable table extraction.

**Why this matters**

Tables may contain thresholds, applicability conditions, deadlines,
exceptions, and cross-referenced requirements. A screenshot-only result
is insufficient for reliable data querying or downstream analysis.

**Remediation**

1.  Preserve the original table crop/snapshot as a visual artifact.
2.  Also produce structured table data with rows, cells, row/column
    indices, bounding boxes, and header associations.
3.  Validate reading order, merged cells, multi-line cells, nested
    tables, and tables split across pages.
4.  Compare structured output with rendered snapshots and a manually
    checked reference for critical tables.
5.  When confidence is low, label the table `visual_only` or
    `needs_review`; do not imply that structured extraction succeeded.
6.  Preserve table provenance and page references.

**Acceptance checks**

-   Every detected table has a status: `structured`, `visual_only`,
    `failed`, or `not_a_table`.
-   Required cell values are checked against the source for critical
    tables.
-   Table snapshots and structured data refer to the same source region.

### 4.7 Medium--High: image handling, repeated logos, signatures, and stamps

**Evidence from evaluations**

-   RBI logos were detected in multiple documents and often repeated
    across pages.
-   `doc11.pdf` also had a signature/stamp among detected images.
-   A 57-image result in `doc30.pdf` may largely reflect a recurring
    logo.

**Why this matters**

Repeated decorative logos can inflate artifact counts, while signatures,
seals, stamps, and diagrams may be semantically important. Blind
deduplication risks removing meaningful evidence.

**Remediation**

1.  Store image page index, bounding box, dimensions, MIME/type if
    known, and artifact path.
2.  Use perceptual similarity to flag likely repeated assets, but retain
    per-page references.
3.  Never deduplicate solely on filename or a weak similarity signal.
4.  Preserve signatures, stamps, charts, and diagrams even if visually
    similar.
5.  Make artifact naming deterministic and ensure every metadata path
    resolves inside the output package.
6.  Validate that ZIP packaging includes all referenced artifacts.

**Acceptance checks**

-   Every image metadata entry resolves to an existing artifact or has
    an explicit failure status.
-   Repeated assets can be linked to a canonical asset without losing
    page-specific occurrences.
-   Important stamps/signatures are retained.

### 4.8 High: multilingual text and character encoding

**Evidence from evaluations**

Hindi footer text was garbled in one document. English text remained
usable.

**Why this matters**

Encoding defects can corrupt names, legal text, contact information, and
other content. A parser status of `partial_success` does not describe
the semantic severity of a character corruption problem.

**Remediation**

1.  Ensure all output stages use UTF-8 consistently.
2.  Add Unicode sanity checks for replacement characters, control
    characters, suspicious mojibake, and unexpected script changes.
3.  Compare suspect text with the PDF's rendered page; do not
    automatically "repair" it without preserving the raw value.
4.  Keep `raw_text` and, if correction is applied, `normalized_text`
    separate.
5.  Test Hindi and any other languages present in the full corpus using
    dedicated fixtures.

**Acceptance checks**

-   No unexplained encoding corruption in required fields.
-   Raw extracted text is preserved for audit.
-   Any normalization is reproducible and logged.

### 4.9 High: inconsistent output schema and field availability

**Evidence from evaluations**

Across PDFs, the available extraction fields differ. Headers or page
numbers may exist in generic elements but not in their dedicated fields;
tables may be missing from the expected field while image artifacts
exist.

**Why this matters**

The consumer expects a stable contract. A field being absent must not
ambiguously mean "not present in source," "parser did not detect it,"
"mapping failed," or "feature not requested."

**Remediation**

Define a normalized output schema with explicit status fields, for
example:

-   `status`: `success`, `partial_success`, `failed`
-   `requested_fields`: fields requested by the caller
-   `field_status`: `extracted`, `not_detected`, `not_applicable`,
    `failed`, `not_requested`
-   `pages`: one record per physical page
-   `elements`: raw and normalized element records
-   `tables`, `images`, `hyperlinks`, `footnotes`: structured arrays
-   `artifacts`: relative paths and checksums
-   `warnings` and `errors`: machine-readable diagnostics

Never use an empty list or missing key to represent multiple different
states. Document the schema version and keep it stable across parser
upgrades.

**Acceptance checks**

-   Every response conforms to the same schema version.
-   Every requested field has an explicit extraction status.
-   All artifact paths exist and remain within the generated ZIP.
-   Partial success reports exactly which pages/fields are incomplete.

## 5. Recommended processing architecture

Use Docling as the primary parser behind a controlled adapter and
validation layer.

``` text
Input PDF + requested fields
          |
          v
Preflight validation
(file integrity, page count, encryption, text layer, page images)
          |
          v
Docling primary extraction
(raw document, elements, layout, tables, images, links where available)
          |
          v
Normalization adapter
(stable schema, page indices, element types, artifact paths)
          |
          v
Validation and quality gates
(body-text coverage, page numbers, links, tables, encoding, artifacts)
          |
          +-------------------+
          |                   |
          v                   v
Pass / partial result     Fallback route
                          (PyMuPDF text/link checks,
                           OCR for image-only pages,
                           targeted table extraction)
          |                   |
          +---------+---------+
                    v
          Merge with provenance
          (no silent overwrite; deduplicate carefully)
                    |
                    v
          DOCX + JSON + snapshots + ZIP
                    |
                    v
          Regression tests and audit log
```

### Architectural principles

-   Preserve raw parser output before normalization.
-   Keep each page and element traceable to the source PDF.
-   Make fallbacks targeted, not an unconditional second parse of every
    page.
-   Do not allow fallback merging to duplicate paragraphs or reorder
    content silently.
-   Make extraction-field selection explicit and test it.
-   Keep generated DOCX, JSON, table snapshots, and image artifacts
    synchronized.
-   Version the parser, adapter, OCR engine, schema, and extraction
    configuration in metadata.
-   Treat `partial_success` as a measurable quality state, not an
    automatic pass.

## 6. Prioritized improvement roadmap

### P0 --- Blockers before production

1.  **Body-text completeness gate**
    -   Add per-page character counts and source text coverage checks.
    -   Flag empty/suspiciously short pages.
    -   Add targeted fallback extraction and regression tests.
2.  **15-PDF corpus inventory**
    -   Recover or rerun evaluations for all 15 PDFs.
    -   Record source filename, page count, language, scanned/text-based
        status, complexity, and expected fields.
3.  **Stable schema and field status**
    -   Normalize missing/not-detected/not-requested/failed states.
    -   Guarantee a page record for every physical page.
4.  **Artifact integrity**
    -   Verify every JSON path exists in the ZIP.
    -   Verify DOCX, JSON, images, and table snapshots are packaged
        correctly.
5.  **Regression corpus**
    -   Keep representative source PDFs and expected outputs under
        version control or controlled test storage.
    -   Add fixtures for known failures in `doc30.pdf` and `doc11.pdf`.

### P1 --- High-priority quality improvements

1.  Normalize physical page index and printed page label separately.
2.  Improve header/footer classification with position and repetition
    checks.
3.  Validate hyperlink annotations, target URIs, and visible text.
4.  Improve footnote-versus-numbered-clause classification.
5.  Add structured table validation and explicit visual-only status.
6.  Add multilingual/Unicode quality checks.

### P2 --- Reliability and maintainability

1.  Add deterministic artifact naming and checksums.
2.  Add structured warnings and page-level diagnostics.
3.  Add parser/configuration version metadata.
4.  Track runtime, memory, and failure rates by PDF type.
5.  Add review tooling for low-confidence pages, tables, footnotes, and
    furniture classification.
6.  Benchmark Docling against PDFLens and a candidate alternative parser
    such as MinerU on the same fixed corpus before deciding whether a
    fallback or replacement is justified.

## 7. Test plan for the complete 15-PDF corpus

### 7.1 Corpus inventory

For every PDF, record:

-   Stable document ID and filename
-   Physical page count
-   Text-based, scanned, or mixed classification
-   Languages/scripts present
-   Presence of headers, footers, page labels, hyperlinks, footnotes,
    tables, images, stamps/signatures
-   Expected extraction fields
-   PDFLens baseline output location, if available
-   Parser version and configuration

Do not infer expected content solely from Docling output. Establish
expectations from the source PDF and, where available, the trusted
PDFLens output.

### 7.2 Per-page validation

For each physical page, capture:

-   Source page index
-   Extracted body-text character count
-   Number of normalized elements
-   Header/footer candidates
-   Printed page label
-   Hyperlink count
-   Footnote count
-   Table count and structured/visual-only status
-   Image count
-   OCR/fallback use
-   Warnings and validation result

Prioritize manual review of pages flagged by automated checks.

### 7.3 Differential validation

Run the same PDF and requested fields through PDFLens and the
Docling-based replacement. Compare:

-   Text coverage and reading order
-   Field classification
-   Page numbering
-   Link text and targets
-   Footnote content and association
-   Table rows/cells and snapshots
-   Image artifacts
-   DOCX contents
-   JSON schema and artifact paths
-   ZIP contents

Use text normalization only for safe comparisons (for example,
line-ending normalization). Do not normalize away meaningful
punctuation, clause numbers, symbols, or multilingual characters.

### 7.4 Suggested metrics

  ----------------------------------------------------------------------------------
  Metric                  What it measures                   Why it matters
  ----------------------- ---------------------------------- -----------------------
  Page text coverage      Fraction of source text recovered  Finds missing body
                          per page                           content

  Empty-page false        Source pages with content but      Critical content-loss
  negative rate           empty/near-empty extraction        signal

  Element classification  Correct assignment to              Measures taxonomy
  precision/recall        body/header/footer/footnote/etc.   reliability

  Page-label accuracy     Correct literal printed page       Supports navigation and
                          labels                             citations

  Link recall and target  Annotation coverage and correct    Supports reliable
  accuracy                URIs                               references

  Footnote                Correct note detection and         Prevents legal
  precision/recall        classification                     structure errors

  Table cell accuracy     Correct cell text and structure    Measures
                                                             machine-readability

  Artifact integrity rate Referenced artifacts that exist    Validates ZIP contract
                          and open                           

  Schema conformance rate Outputs conforming to the          Prevents integration
                          versioned contract                 failures

  Partial-success rate    Documents/pages with unresolved    Measures operational
                          issues                             reliability
  ----------------------------------------------------------------------------------

Do not set arbitrary thresholds without a baseline. Establish initial
measurements, review the critical use cases, then set acceptance
thresholds. For high-risk content such as operative clauses and table
values, require explicit, manually verified quality gates.

## 8. Production acceptance gates

Production approval should require all of the following:

1.  All 15 PDFs have documented evaluation results; no corpus-wide
    verdict is based on only six.
2.  No unexplained loss of substantive body text on any required page.
3.  Known failure cases from `doc30.pdf` and `doc11.pdf` pass regression
    tests.
4.  Header/footer classification errors do not remove operative text.
5.  Physical page index and printed page label are separate and
    correctly represented.
6.  Required hyperlinks have readable text and correct targets, or
    omissions are documented.
7.  Footnote classification is validated against a reviewed sample,
    including numbered legal clauses.
8.  Required tables have structured cell data validated against the
    source; otherwise the output clearly states `visual_only` or
    `needs_review`.
9.  Every artifact referenced in JSON exists and is included in the ZIP.
10. Multilingual text passes encoding checks.
11. Schema validation and extraction-field selection tests pass.
12. Logs capture parser version, adapter version, fallback/OCR use,
    warnings, and per-page quality metrics.
13. The team has a documented failure policy: return partial output with
    warnings, retry, use fallback, or fail the request---never silently
    claim full success.

## 9. Suggested normalized schema fields

A simplified conceptual example:

``` json
{
  "schema_version": "1.0",
  "document_id": "stable-document-id",
  "source_filename": "input.pdf",
  "parser": {
    "name": "docling",
    "version": "2.141.0"
  },
  "status": "partial_success",
  "requested_fields": [
    "body_text",
    "header",
    "footer",
    "hyperlink",
    "footnote",
    "page_number",
    "table",
    "image"
  ],
  "pages": [
    {
      "physical_page_index": 0,
      "printed_page_label": null,
      "body_text": "...",
      "field_status": {
        "header": "not_detected",
        "footer": "extracted",
        "page_number": "not_detected",
        "table": "not_applicable"
      },
      "warnings": []
    }
  ],
  "artifacts": [],
  "warnings": [],
  "errors": []
}
```

This is an illustrative schema, not a claim that the current
implementation already emits these fields. Extend it with typed element
records, bounding boxes, provenance, table cells, hyperlink targets,
footnote associations, and checksums as required.

## 10. Operational monitoring and error handling

Monitor the following after deployment:

-   Percentage of PDFs returning `success`, `partial_success`, and
    `failed`
-   Number of pages with empty or unusually short body text
-   Fallback and OCR invocation rate
-   Tables detected versus tables successfully structured
-   Missing page-label rate
-   Link annotation coverage
-   Unicode quality warnings
-   Missing artifact paths or corrupt ZIP entries
-   Parser runtime and resource consumption
-   Quality regressions after parser or dependency upgrades

For each partial result, return actionable warnings such as:

-   `BODY_TEXT_SPARSE`: source page may contain text not captured in
    body output.
-   `PAGE_LABEL_NOT_DETECTED`: printed label could not be identified.
-   `TABLE_VISUAL_ONLY`: table crop exists, but structured cells were
    not validated.
-   `HYPERLINK_TEXT_FRAGMENTED`: visible text may need reconstruction.
-   `FOOTNOTE_CLASSIFICATION_LOW_CONFIDENCE`: review required.
-   `UNICODE_SUSPECT`: extracted text may contain encoding corruption.
-   `ARTIFACT_MISSING`: metadata points to a missing file.

These names are recommendations for the replacement's own diagnostic
contract, not existing Docling error codes.

## 11. Final verdict

**Current verdict: NOT PRODUCTION-READY.**

The available evidence supports continued development of Docling as the
primary parsing component, provided a robust adapter, validation layer,
and targeted fallback strategy are added. The most urgent blocker is
body-text completeness, followed by schema consistency and reliable
table/page-number handling. Hyperlinks, footnotes, headers/footers, and
multilingual text also need systematic validation.

The six available evaluations indicate two production rejections and
four documents acceptable for continued testing with improvements. They
do not establish the outcome for the complete 15-PDF corpus. Before
approval, rerun or recover all 15 evaluations, compare the outputs
against PDFLens using the same inputs and requested fields, and pass the
production gates above.

**Decision rule:** Do not equate `partial_success`, successful ZIP
creation, or the presence of snapshots with correct extraction.
Production readiness must be demonstrated through source-grounded
content coverage, field-level correctness, schema conformance, artifact
integrity, and repeatable regression tests.
