# Operations runbook (initial)

## Start locally

Install dependencies with `uv sync --extra dev` and run `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`. `/healthz` reports process liveness. `/readyz` verifies that Docling is importable, but does not download or warm model weights. The first extraction can therefore take longer than subsequent warm requests.

Each process reuses Docling converters by extraction configuration and serializes inference. `PDFLENS_MAX_CONCURRENT_EXTRACTIONS` defaults to `1`; requests above capacity get HTTP 503 `CAPACITY_EXCEEDED` and `Retry-After: 5`. Keep this at one for memory-constrained machines. Raising it does not parallelize Docling inference within a process.

Generate a fresh source inventory before running a corpus evaluation with `uv run python scripts/inventory_pdf_corpus.py rbi_docs --output /tmp/pdflens-corpus-inventory.json`. It records hashes, page counts, per-page text-layer availability, and extraction errors; it does not assert semantic correctness.

## Common failures

- `INVALID_PDF`: upload is empty or lacks `%PDF-` near its start; verify the source file.
- `FILE_TOO_LARGE` / `PAGE_LIMIT_EXCEEDED`: adjust the accepted input envelope only through service-owner approval.
- `PARSER_UNAVAILABLE`: Docling is missing or parsing failed. Check worker logs by `request_id`, model availability, package pin and temporary disk.
- HTTP 500 during packaging: inspect storage/disk availability and package generation logs; no document content should be added to logs.

## Extraction quality signals

`metadata.json` records a one-based `physical_page_index`, the literal `printed_page_label` when detected, source and normalized body-text character counts, their ratio, per-field status, and page warnings. `BODY_TEXT_FALLBACK_USED` means Docling emitted no body text and pypdf supplied extractable page text; it does not prove semantic completeness. `PYPDF_FONTTOOLS_UNAVAILABLE` means some embedded CFF Type1 fonts may not decode fully in the fallback. `BODY_TEXT_SOURCE_LAYER_EMPTY` means the PDF text layer is empty and no body text was emitted; inspect the rendered page and OCR result. `TABLE_VISUAL_ONLY` means a table region was detected but Docling did not expose structured cells; `TABLE_STRUCTURED_NEEDS_REVIEW` means structured cells still need source verification. `FOOTNOTE_CLASSIFICATION_LOW_CONFIDENCE` means the marker/position heuristic needs review. `PAGE_LABEL_NOT_DETECTED` leaves the printed label null rather than guessing. `UNICODE_SUSPECT` flags replacement, mojibake markers, or unexpected control characters without rewriting text. These warnings cause `partial_success` for review.

## Production readiness work still required

Before production, add authentication and authorization, OS/container-enforced CPU, memory, and wall-clock limits, durable job state/retry policy, external storage, temporary-file cleanup monitoring, metrics/alerts, retention/deletion procedures, model warm-up and health policy, dependency/SBOM and license review, and rollback instructions for the selected platform. The in-process capacity gate is not a substitute for worker isolation or a hard execution timeout. This prototype must not be used as an internet-facing service.
