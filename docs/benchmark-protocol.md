# Parser benchmark protocol

The parser is intentionally an adapter choice. Docling is wired as the initial candidate, but no winner has been selected because no representative source PDFs or PDFLens baselines are in this repository.

## Corpus and controls

Collect 5–10 approved, sanitized PDFs for the first gate, then expand to the accepted input envelope. Include multi-column and mixed layouts, headers/footers/footnotes, hyperlinks, rotated pages, complex tables, images/captions, and scans across required languages. Store corpus and expected results outside the source repository unless data policy explicitly permits fixtures here. Run each parser with the same files, field requirements, hardware limits, and warm/cold-start conditions. Record exact code, model and OCR versions, configuration, hardware, and artifact hashes.

## Per-document record

Record parser and model versions, input hash, page count, parse outcome, cold and warm duration, peak memory, output size, element counts by class, reading-order findings, bounding-box findings, link precision/recall, asset quality, OCR language/results, warnings, and license/model provenance. Compare candidate output with the current PDFLens ZIP and manually reviewed expected annotations. Classify every material difference using the categories in the project plan (parser limitation, mapping defect, artifact defect, current-service defect, acceptable, or unresolved).

## Scorecard

Use the project plan's initial weights: localization 20%, reading order 15%, headers/footers/footnotes 15%, tables 10%, images 10%, hyperlinks 10%, OCR 5%, throughput/deployment 5%, licensing 5%, integration effort 5%. Rate 1–5 with evidence and keep critical requirements as pass/fail gates; an average score cannot waive missing required links, valid coordinates, or contract compatibility. Record results in a reviewed benchmark report before selecting a primary parser.

## Release gate

Do not declare production fit until the candidate has been run differentially against PDFLens, coordinate overlays have been reviewed, field-toggle behavior is checked, open gaps have owners, and license/security approvals are recorded. Keep this document and the benchmark evidence with the architecture decision record.
