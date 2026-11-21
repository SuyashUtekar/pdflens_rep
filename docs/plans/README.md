# Project plans

This folder contains planning and validation documents. These files describe intended or proposed work; the implementation and deployed API contract remain the source of truth for what currently runs.

- [Complete PDFLens replacement project plan](PDFLens_Replacement_Complete_Project_Plan.md)
- [Multi-PDF validation and remediation plan](PDFLens_Multi_PDF_Validation_and_Remediation_Plan.md)
- [PDFLens quality judge workflow plan](PDFLens_Quality_Judge_Complete_Workflow_Plan.md)
- [Section-wise chunk quality judge workflow plan](Section_Wise_Chunk_Quality_Judge_Complete_Workflow_Plan.md)
- [Finalized UI implementation plan](PDFLens_Finalized_UI_Complete_Implementation_Plan.md)

The finalized UI plan includes future asynchronous job, callback, and validation capabilities. The current service remains synchronous at `POST /v1/extract`; see [the API contract](../api-contract.md) for the implementation available today.
