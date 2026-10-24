# PDF layout metadata fixture

This directory contains the synthetic PDF, the user's quick-reference analysis, and metadata captured before the adapter fixes. The captured metadata is deliberately named `observed-before-fixes.json`: it misclassifies section headings as `header` and omits running furniture/page numbers, so it is a regression reference rather than a golden output. The parser must derive its output from each uploaded PDF; these documents are reference inputs, not application configuration.

The PDF is also kept at `docs/PDF_Layout_Metadata_Test_Fixture.pdf` for convenient manual uploads. Compare a generated result with the source report when exercising the fixture. It is not an automated test.
