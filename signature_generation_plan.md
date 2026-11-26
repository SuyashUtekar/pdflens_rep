
# Signature Document Dataset Generator

## Complete Implementation Plan, Architecture, Technology Stack & Feasibility Assessment

**Project Type:** Synthetic + real-asset document dataset generation
**Target Dataset:** 10,000 complete document pages, plus derived signature crops
**Annotation Targets:** Bounding boxes + pixel-level segmentation masks
**Signature Sources:** Hybrid — fictional/generated and real signatures with explicit consent or compatible dataset licences
**Languages:** English, Devanagari, and bilingual English–Devanagari
**Primary Objective:** Generate realistic, annotated document images containing signatures that overlap printed labels, names, dates, addresses, form boundaries, tables, stamps, and other document elements.

---

# 1. Executive Summary

The objective is to develop a configurable Python-based pipeline that generates realistic document images containing handwritten signatures and automatically creates ground-truth annotations.

The generator will combine:

1. Document templates — application forms, bank/KYC-style forms, declarations, authorization forms, agreements, and generic business documents.
2. Signature assets — fictional signature-like marks and real signatures collected with consent or from appropriately licensed datasets.
3. Composition rules — controlled placement of signatures over printed labels, names, dates, addresses, table cells, form lines, stamps, and other signatures.
4. Image degradation — scanning effects, photocopy artifacts, compression, blur, skew, perspective, shadows, and noise.
5. Annotation generation — exact signature bounding boxes, instance masks, semantic masks, and overlap masks.
6. Quality control — automated validation, visual review sheets, data statistics, leakage checks, and real-world evaluation.

The core design principle is **annotation by construction**.

Every rendered document element will have its own image layer and annotation mask. Since the generator knows where each signature and printed element is placed, it can produce accurate ground-truth labels without trying to reconstruct them from the final document using OCR or thresholding.

The target is 10,000 unique complete document pages. Signature-region crops will be generated as additional derived samples and linked to their parent documents.

The project is technically feasible using Python and CPU-based image processing. However, the most important challenge is ensuring that synthetic documents represent real-world document complexity.

Therefore, a pilot dataset and a separately annotated real-document evaluation set are mandatory.

---

# 2. Project Requirements

## 2.1 Functional Requirements

| ID    | Requirement                              | Planned Implementation                         |
| ----- | ---------------------------------------- | ---------------------------------------------- |
| FR-01 | Generate 10,000 complete document images | Template-driven page renderer                  |
| FR-02 | Generate signature-region crops          | Crop extraction using signature bounding boxes |
| FR-03 | Support signature detection              | Per-signature bounding boxes                   |
| FR-04 | Support signature segmentation           | Per-signature binary masks                     |
| FR-05 | Preserve printed-text information        | Independent printed-text masks                 |
| FR-06 | Preserve overlapping classes             | Independent masks and overlap calculations     |
| FR-07 | Support English and Devanagari           | Unicode-capable fonts and text rendering       |
| FR-08 | Support real and fictional signatures    | Signature asset registry                       |
| FR-09 | Support complex document layouts         | Tables, lines, labels, stamps, and fields      |
| FR-10 | Apply scan-like degradation              | Configurable augmentation pipeline             |
| FR-11 | Export model-ready annotations           | COCO JSON, PNG masks, optional YOLO            |
| FR-12 | Support reproducibility                  | Random seeds and generation manifests          |
| FR-13 | Validate annotations                     | Geometry, mask, bbox, and dataset validation   |

## 2.2 Non-functional Requirements

- Deterministic generation using a configurable random seed.
- Configurable document dimensions, DPI, scenario probabilities, and overlap ratios.
- Separation of source assets, generated documents, annotations, and crops.
- No dependency on cloud APIs for core generation.
- Resumable batch processing.
- Structured logging and error reporting.
- Versioned configurations and dataset manifests.
- Documented provenance and usage rights for real signatures.
- No use of real signatures to impersonate or imitate named individuals.

## 2.3 Out of Scope for Version 1

The first version will not implement:

- Signature verification.
- Forgery detection.
- Signer identification.
- Handwriting transcription.
- Legal signature validity assessment.
- Complete document OCR.
- Semantic document understanding.
- Signature imitation of specific real individuals.

These can be developed as separate downstream applications.

---

# 3. Annotation Policy

Annotation semantics must be finalized before implementation.

## 3.1 Recommended Annotation Classes

| Class                | Description                                         | Required    |
| -------------------- | --------------------------------------------------- | ----------- |
| `signature`        | Visible pixels belonging to a signature             | Yes         |
| `printed_text`     | Printed labels, names, dates, addresses, paragraphs | Yes         |
| `handwritten_text` | Non-signature handwritten content                   | Recommended |
| `stamp`            | Stamp and seal pixels                               | Yes         |
| `form_line`        | Printed horizontal and vertical lines, borders      | Yes         |
| `other_ink`        | Ticks, crosses, and other handwritten marks         | Optional    |

### Important: Overlapping Annotation Classes

Use independent binary masks rather than forcing each pixel into exactly one class.

For example, consider a signature written over the printed text:

**Applicant Signature**

The same pixel coordinate may belong to both:

- `signature_mask`
- `printed_text_mask`

Do not overwrite the printed-text annotation simply because the signature was drawn over it.

This is essential for training models that need to distinguish handwritten signatures from printed document content.

## 3.2 Derived Overlap Masks

Generate additional masks using logical intersections:

```python
signature_printed_overlap = (
    signature_mask & printed_text_mask
)

signature_line_overlap = (
    signature_mask & form_line_mask
)

signature_stamp_overlap = (
    signature_mask & stamp_mask
)
```

These masks help measure how well the generated dataset covers difficult overlap scenarios.

## 3.3 Bounding Box Annotations

Each signature instance should contain:

- `instance_id`
- `bbox_xywh`
- `area`
- `mask_path`
- `source_type`
- `placement_scenario`
- `overlap_metadata`

Bounding boxes must be calculated from the final transformed signature mask, not from the original asset dimensions.

## 3.4 Segmentation Annotations

Use exact binary PNG masks as the canonical segmentation representation.

For COCO export, convert instance masks into RLE encoding.

Polygon annotations may also be generated for compatible frameworks, but should not be the only representation because polygon simplification can lose thin signature strokes.

---

# 4. Dataset Composition

## 4.1 Dataset Size and Split

Target: 10,000 unique complete document pages.

| Split           |   Complete Pages | Purpose                    |
| --------------- | ---------------: | -------------------------- |
| Train           |            8,000 | Model training             |
| Validation      |            1,000 | Model selection            |
| Test            |            1,000 | Final synthetic evaluation |
| **Total** | **10,000** |                            |

Split the dataset by template family and signature source group rather than randomly splitting individual images.

This avoids leakage caused by repeated signature assets or nearly identical document templates appearing in multiple splits.

All derived crops must inherit the split of their parent page.

A separate real-world evaluation set should be maintained outside the synthetic dataset. It should contain real documents with appropriate permissions and manually reviewed annotations.

## 4.2 Scenario Distribution

| Scenario                             |            Pages | Description                                      |
| ------------------------------------ | ---------------: | ------------------------------------------------ |
| Signature over printed labels        |            2,000 | Applicant Signature, Authorized Signatory        |
| Signature crossing form boundaries   |            1,800 | Horizontal lines, vertical borders, tables       |
| Signature over other printed text    |            1,800 | Names, dates, addresses, reference numbers       |
| Signature with stamps/seals          |            1,400 | Round stamps, rectangular seals, partial overlap |
| Complex/multiple-signature documents |            1,500 | Multiple signers and dense layouts               |
| Natural/low-interference documents   |            1,500 | Ordinary signature fields and clean scans        |
| **Total**                      | **10,000** |                                                  |

These are primary scenario categories. A page may contain multiple scenario attributes.

## 4.3 Language Distribution

Suggested initial distribution:

| Language Style       | Percentage | Pages |
| -------------------- | ---------: | ----: |
| English              |        60% | 6,000 |
| English + Devanagari |        25% | 2,500 |
| Devanagari-oriented  |        15% | 1,500 |

These proportions should be configurable and revised according to the actual target-document distribution.

## 4.4 Signature Source Distribution

Recommended starting mix:

- 50% fictional/generated signature-like assets.
- 50% real signatures from consented contributors or appropriately licensed datasets.

This is an initial experimental ratio, not a fixed requirement.

Real signatures provide natural handwriting characteristics. Fictional signatures help scale the dataset and create controlled variations.

For every real signature asset, maintain:

- Source information.
- Consent or licence status.
- Permitted use.
- Restrictions.
- Source group identifier.
- Mask quality status.

Do not assume that publicly accessible signatures are automatically available for model training or redistribution.

---

# 5. Document Template Strategy

## 5.1 Template Families

Create reusable document template families:

1. Bank/account application forms.
2. Customer/KYC information forms.
3. Loan and credit application forms.
4. Authorization and consent forms.
5. Office/business declarations.
6. Address and identity detail forms.
7. Service request forms.
8. Agreement/declaration documents.
9. Letter-style documents with signature blocks.
10. Generic tables containing signature fields.

Use fictional organizations, fictional addresses, and dummy identifiers.

Avoid confidential documents and real organization branding unless permission has been obtained.

## 5.2 Template Components

The template engine should support:

- Page headers and footers.
- Section titles.
- Paragraphs.
- Labels and value fields.
- Text boxes.
- Underlined fields.
- Horizontal and vertical lines.
- Tables.
- Checkboxes.
- Radio buttons.
- Signature fields.
- Date and place fields.
- Stamp/seal placeholders.
- Multiple signature areas.
- Variable whitespace.

## 5.3 Template Representation

Templates should be stored in YAML or JSON rather than hard-coded drawing functions.

Example:

```yaml
template_id: bank_application_001

page:
  width: 2480
  height: 3508
  dpi: 300

language: en

elements:
  - type: heading
    text: "ACCOUNT APPLICATION"
    x: 180
    y: 150

  - type: label
    text: "Applicant Name"
    x: 180
    y: 800

  - type: line
    x1: 180
    y1: 860
    x2: 2200
    y2: 860

  - type: signature_field
    field_id: applicant_signature
    label: "Applicant Signature"
    x: 1500
    y: 2800
    width: 700
    height: 300
```

## 5.4 Layout Variation

Generate template variations through:

- Different page margins.
- Different font families and sizes.
- Different label wording.
- Different table dimensions.
- Different field widths.
- Different section ordering.
- Different line thicknesses.
- Different whitespace distributions.
- Different page orientations.
- Different page resolutions.

A pilot target of 30–50 meaningfully different templates is reasonable. Additional templates should be added after evaluating layout diversity.

---

# 6. Signature Asset Pipeline

## 6.1 Fictional Signature Generation

Create fictional signature-like marks using:

- Parametric Bézier curves.
- Randomized connected strokes.
- Loops and curves.
- Variable stroke width.
- Variable slant and baseline.
- Pen-lift gaps.
- Underlines.
- Different ink colours.
- Controlled irregularities.

The generator should produce different visual styles rather than repeating a small number of patterns.

Procedural signatures may appear artificial, so they must be visually evaluated and balanced with real consented samples.

These generated marks must be treated as fictional signature-like assets, not genuine human signatures.

## 6.2 Real Signature Asset Preparation

Potential sources:

- Volunteers who explicitly consent to the intended use.
- Public datasets with licences permitting the intended training and redistribution.
- Organization-owned material with documented authority and approval.

Asset preparation steps:

1. Load the source image.
2. Convert to grayscale or preserve the original ink colour.
3. Separate signature ink from the background.
4. Generate a transparent RGBA asset.
5. Generate a binary signature mask.
6. Crop to the ink boundaries.
7. Preserve aspect ratio.
8. Review detached strokes and dots.
9. Save the asset and its metadata.

Do not remove all small connected components because dots and detached strokes may be legitimate signature parts.

## 6.3 Asset Metadata

Example:

```json
{
  "asset_id": "sig_000123",
  "source_type": "consented_real",
  "source_group_id": "contributor_group_012",
  "ink_colour": "blue",
  "licence_status": "approved_internal_training",
  "consent_reference": "consent_record_012",
  "mask_quality": "reviewed",
  "allowed_uses": [
    "internal_training",
    "internal_evaluation"
  ]
}
```

Do not include contributor names or direct personal identifiers in the training manifest.

---

# 7. Composition Engine

The composition engine is the central component of the project.

## 7.1 Rendering Layers

Maintain independent layers for:

1. Background/paper.
2. Printed text.
3. Form lines and tables.
4. Stamps and seals.
5. Individual signature instances.
6. Other handwriting, if included.

Composite these layers to create the final document image, but preserve independent annotation masks regardless of rendering order.

## 7.2 Signature Placement Scenarios

Implement dedicated placement functions:

```python
place_over_label()

place_across_horizontal_line()

place_across_vertical_border()

place_over_table_cell()

place_over_name_field()

place_over_date_field()

place_over_address_field()

place_near_stamp()

place_under_stamp()

place_partially_over_printed_text()

place_multiple_signatures()

place_free_position()
```

Each function should return:

- Transformed signature image.
- Transformed signature mask.
- Final bounding box.
- Overlap measurements.
- Placement metadata.

## 7.3 Transformations

Supported transformations:

- Translation.
- Rotation.
- Uniform scaling.
- Mild non-uniform scaling.
- Shearing.
- Mild perspective transformation.
- Optional controlled warping.

Apply the same geometric transformation parameters to the signature image and its mask.

Use nearest-neighbour interpolation for binary masks and suitable interpolation for RGB/RGBA images.

Recalculate the bounding box from the final transformed mask.

## 7.4 Overlap Control

Random placement alone is insufficient for generating enough difficult examples.

Define target overlap ratios, perform placement, measure the actual overlap, and retry when placement constraints are not satisfied.

Record:

```text
signature_printed_overlap_ratio

signature_form_line_overlap_ratio

signature_stamp_overlap_ratio

crosses_field_boundary

crosses_table_border

overlaps_label

overlaps_name

overlaps_date
```

Calculate overlap ratio as:

```python
overlap_ratio = (
    intersection_area / signature_mask_area
)
```

Store the achieved overlap ratio rather than only the intended value.

---

# 8. Scan and Image Degradation Pipeline

Apply degradation after the clean document and ground-truth masks have been composed.

| Transformation | Description                                 |
| -------------- | ------------------------------------------- |
| Rotation       | Small page skew, approximately -3° to +3° |
| Perspective    | Mild corner displacement                    |
| Blur           | Gaussian or motion blur                     |
| Noise          | Gaussian and salt-and-pepper noise          |
| Brightness     | Faded photocopy effects                     |
| Contrast       | Low/high contrast variations                |
| Shadows        | Uneven illumination and edge shadows        |
| Compression    | JPEG compression                            |
| Resolution     | Varied DPI and resizing                     |
| Paper texture  | Off-white backgrounds and subtle texture    |
| Bleed-through  | Faint reverse-side text                     |
| Photocopy      | Grayscale and toner gaps                    |
| Camera capture | Mild perspective and lighting gradients     |

All geometric transformations must be synchronized across the document image and every annotation mask.

Photometric transformations should generally affect only the document image.

Avoid excessive degradation that destroys signature visibility or creates unrealistic artifacts.

---

# 9. Annotation Generation and Export

## 9.1 Canonical Annotation Structure

Example:

```json
{
  "image_id": "doc_000001",
  "width": 2480,
  "height": 3508,

  "instances": [
    {
      "instance_id": "sig_000001",
      "class": "signature",
      "bbox_xywh": [1420, 2750, 620, 210],
      "mask_path": "masks/signature/doc_000001_sig_000001.png",
      "source_type": "consented_real",
      "scenario": "over_printed_label"
    }
  ],

  "semantic_masks": {
    "signature": "masks/semantic/signature/doc_000001.png",
    "printed_text": "masks/semantic/printed_text/doc_000001.png",
    "stamp": "masks/semantic/stamp/doc_000001.png",
    "form_line": "masks/semantic/form_line/doc_000001.png"
  }
}
```

## 9.2 Export Formats

Primary outputs:

- PNG document images.
- Per-instance PNG signature masks.
- Per-page semantic masks.
- COCO JSON with bounding boxes and RLE segmentation.
- JSON generation manifest.

Optional outputs:

- YOLO detection labels.
- YOLO segmentation labels.
- Visual overlays.
- Contact sheets.
- Signature-region crops.

Do not use YOLO polygons as the only ground truth. Thin signature strokes and overlap regions are better preserved through PNG masks and COCO RLE.

## 9.3 Crop Generation

For each signature instance:

1. Expand its bounding box using configurable padding.
2. Clip the box to page boundaries.
3. Crop the original document image.
4. Crop the signature mask and other semantic masks.
5. Translate the signature bbox to crop-relative coordinates.
6. Save the parent page ID.
7. Save the signature instance ID.
8. Inherit the parent page's dataset split.

Pages with multiple signatures may generate multiple crops.

Report complete-page counts and crop counts separately.

---

# 10. Technology Stack

| Component            | Recommended Technology          | Purpose                               |
| -------------------- | ------------------------------- | ------------------------------------- |
| Programming language | Python 3.11                     | Core implementation                   |
| Image arrays         | NumPy                           | Pixel and mask operations             |
| Image processing     | OpenCV                          | Warping, transformations, compositing |
| Image rendering      | Pillow                          | Text, fonts, RGBA layers              |
| PDF generation       | ReportLab                       | Optional PDF template generation      |
| PDF rasterization    | PyMuPDF                         | Render PDFs to images                 |
| Configuration        | Pydantic + PyYAML               | Typed configuration and validation    |
| Synthetic text       | Faker                           | Dummy names, addresses, dates, IDs    |
| Indic text rendering | Unicode fonts + Pillow          | Devanagari content                    |
| Augmentation         | Albumentations or custom OpenCV | Scan degradation                      |
| COCO export          | pycocotools                     | RLE and COCO annotations              |
| Geometry             | Shapely                         | Optional layout/intersection checks   |
| Statistics           | pandas                          | Dataset reports                       |
| CLI                  | Typer                           | Command-line interface                |
| Logging              | Python logging / structlog      | Structured logs                       |
| Testing              | pytest                          | Unit and integration tests            |
| Code quality         | Ruff + mypy                     | Linting and type checks               |
| Visualization        | Pillow / Matplotlib             | QA contact sheets                     |
| Packaging            | uv or Poetry                    | Dependency management                 |

### Recommended Implementation Approach

Keep the first version local and CPU-compatible.

The core pipeline does not require:

- GPU.
- Cloud APIs.
- Kubernetes.
- Message queues.
- Distributed infrastructure.
- Database servers.

Use local files and manifests initially. Introduce multiprocessing only after benchmarking identifies a performance bottleneck.

Pin dependency versions after the pilot and commit the lock file.

---

# 11. Python Project Architecture

```text
signature-dataset-generator/

├── README.md
├── pyproject.toml
├── uv.lock
├── .env.example

├── configs/
│   ├── base.yaml
│   ├── dataset_10k.yaml
│   ├── scenarios.yaml
│   ├── languages.yaml
│   ├── augmentations.yaml
│   └── templates/
│       ├── bank_application.yaml
│       ├── kyc_form.yaml
│       ├── declaration.yaml
│       └── authorization_form.yaml

├── assets/
│   ├── fonts/
│   ├── stamps/
│   ├── paper_textures/
│   ├── signatures/
│   │   ├── fictional/
│   │   └── consented/
│   └── asset_registry.json

├── src/
│   └── signature_dataset/

│       ├── __init__.py
│       ├── cli.py

│       ├── config/
│       │   ├── loader.py
│       │   └── schemas.py

│       ├── assets/
│       │   ├── registry.py
│       │   ├── signature_loader.py
│       │   ├── signature_normalizer.py
│       │   └── fictional_signature_generator.py

│       ├── templates/
│       │   ├── template_loader.py
│       │   ├── layout_engine.py
│       │   ├── elements.py
│       │   ├── text_renderer.py
│       │   └── form_renderer.py

│       ├── composition/
│       │   ├── compositor.py
│       │   ├── placement_engine.py
│       │   ├── overlap_controller.py
│       │   └── transforms.py

│       ├── augmentation/
│       │   ├── geometric.py
│       │   ├── photometric.py
│       │   ├── scan_effects.py
│       │   └── pipeline.py

│       ├── annotations/
│       │   ├── mask_manager.py
│       │   ├── bbox.py
│       │   ├── overlap.py
│       │   ├── coco_exporter.py
│       │   ├── yolo_exporter.py
│       │   └── crop_exporter.py

│       ├── generation/
│       │   ├── sample_planner.py
│       │   ├── document_generator.py
│       │   ├── batch_runner.py
│       │   └── manifest.py

│       ├── validation/
│       │   ├── annotation_validator.py
│       │   ├── image_validator.py
│       │   ├── diversity_report.py
│       │   └── leakage_check.py

│       └── visualization/
│           ├── overlay.py
│           └── contact_sheet.py

├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/

├── scripts/
│   ├── prepare_signature_assets.py
│   ├── generate_pilot.py
│   ├── generate_dataset.py
│   ├── validate_dataset.py
│   └── build_contact_sheets.py

├── outputs/

└── docs/
    ├── annotation_policy.md
    ├── asset_provenance_policy.md
    └── dataset_card.md
```

## 11.1 Component Responsibilities

| Component             | Responsibility                                         |
| --------------------- | ------------------------------------------------------ |
| Config loader         | Validate probabilities, paths, dimensions, and classes |
| Asset registry        | Track source, licence, consent, and permitted use      |
| Signature normalizer  | Produce transparent signature and binary mask          |
| Fictional generator   | Create fictional signature-like assets                 |
| Template loader       | Load document layout definitions                       |
| Layout engine         | Resolve element positions and dimensions               |
| Text renderer         | Render text and printed-text masks                     |
| Form renderer         | Render tables, rules, boxes, and masks                 |
| Placement engine      | Place signatures in scenario-specific locations        |
| Overlap controller    | Measure intersections and retry placements             |
| Compositor            | Combine visual layers while preserving masks           |
| Augmentation pipeline | Apply synchronized geometry and photometric effects    |
| Mask manager          | Maintain semantic and instance masks                   |
| COCO exporter         | Export bboxes and RLE masks                            |
| YOLO exporter         | Optional detection and segmentation export             |
| Crop exporter         | Generate crops and crop-relative annotations           |
| Validator             | Check dataset and annotation integrity                 |
| Batch runner          | Generate, resume, and log batches                      |

---

# 12. Configuration Design

The generator should be configurable without modifying Python code for each experiment.

Example `dataset_10k.yaml`:

```yaml
dataset:
  name: signature_documents_10k
  target_pages: 10000
  seed: 20261126
  output_format: png

  dpi_choices:
    - 150
    - 200
    - 300

  page_sizes:
    - [2480, 3508]
    - [2550, 3300]

splits:
  train: 0.80
  val: 0.10
  test: 0.10

  split_by:
    - template_family
    - signature_source_group

languages:
  en: 0.60
  en_devanagari: 0.25
  devanagari: 0.15

signature_sources:
  fictional: 0.50
  consented_real: 0.50

scenarios:
  over_printed_label: 0.20
  cross_form_boundary: 0.18
  over_other_text: 0.18
  with_stamp: 0.14
  complex_multiple_signatures: 0.15
  natural_or_low_interference: 0.15

annotations:
  bbox: true
  instance_masks: true
  semantic_masks: true
  overlap_masks: true
  export_coco: true
  export_yolo_detection: true
  export_yolo_segmentation: false

crops:
  enabled: true
  padding_ratio: 0.20
  min_padding_px: 24

generation:
  max_retries_per_page: 10
  save_intermediate_layers: false
  save_debug_overlays: true
```

All scenario and language probabilities must be validated to sum to 1.0 within a configured tolerance.

---

# 13. End-to-End Generation Workflow

## Phase A — Asset Preparation

1. Load asset registry.
2. Exclude assets without approved provenance.
3. Normalize approved real signatures.
4. Generate fictional signature-like assets.
5. Review signature-mask contact sheets.
6. Assign source group IDs for split isolation.

## Phase B — Dataset Planning

1. Read target page count.
2. Read scenario distribution.
3. Assign template families to splits.
4. Assign signature source groups to splits.
5. Allocate language and degradation styles.
6. Create deterministic per-page random seeds.
7. Persist the sample plan before rendering.

## Phase C — Document Rendering

1. Load template.
2. Generate fictional names, addresses, dates, and dummy identifiers.
3. Render printed text and retain a separate mask.
4. Render form lines and tables with separate masks.
5. Render stamps and seals with separate masks.
6. Keep page background separate.

## Phase D — Signature Composition

1. Select an approved signature asset from the correct split.
2. Select placement scenario.
3. Transform signature pixels and mask together.
4. Place signature.
5. Measure overlap with text, lines, and stamps.
6. Retry if the sample does not satisfy scenario constraints.
7. Save signature instance metadata.

## Phase E — Scan Effects

1. Apply geometric transformations to image and all masks.
2. Apply photometric effects to the image only.
3. Recalculate all instance boxes.
4. Verify signature masks remain non-empty.

## Phase F — Export

1. Save complete page.
2. Save signature instance masks.
3. Save semantic masks.
4. Generate overlap masks.
5. Export COCO annotations.
6. Export optional YOLO labels.
7. Generate signature-region crops.
8. Write manifest records.

## Phase G — Quality Assurance

1. Validate image and mask dimensions.
2. Check bbox-mask consistency.
3. Check overlap logic.
4. Check crop coordinate translation.
5. Check split isolation.
6. Generate visual overlays.
7. Generate contact sheets.
8. Generate dataset statistics.

---

# 14. CLI Design

Use Typer to create a command-line interface.

Example commands:

```bash
# Install dependencies
uv sync --all-groups

# Validate configuration
uv run signature-dataset validate-config \
  --config configs/dataset_10k.yaml

# Prepare signature assets
uv run signature-dataset prepare-assets \
  --config configs/base.yaml

# Generate 100-page pilot
uv run signature-dataset generate \
  --config configs/dataset_10k.yaml \
  --count 100 \
  --output outputs/pilot

# Validate pilot
uv run signature-dataset validate \
  --dataset outputs/pilot

# Generate full dataset
uv run signature-dataset generate \
  --config configs/dataset_10k.yaml \
  --output outputs/signature_documents_10k

# Export COCO annotations
uv run signature-dataset export \
  --dataset outputs/signature_documents_10k \
  --format coco

# Generate contact sheets
uv run signature-dataset visualize \
  --dataset outputs/signature_documents_10k
```

The CLI should support:

- `--resume`
- `--seed`
- `--count`
- `--workers`
- `--output`

Exact command names can be finalized during implementation.

---

# 15. Validation and Quality Assurance

## 15.1 Structural Validation

For every page:

- Image exists and can be decoded.
- All masks have the expected dimensions.
- Mask values are valid.
- Every signature instance has a non-empty mask.
- Every bbox encloses its corresponding mask.
- No bbox extends beyond the image.
- Crop labels use crop-relative coordinates.
- COCO IDs are unique.
- RLE masks decode correctly.
- Manifest paths resolve.

## 15.2 Semantic Validation

- Signature pixels are represented in the signature mask.
- Overlap masks equal the logical intersection of source masks.
- Signature-over-line examples intersect form-line masks.
- Signature-over-label examples intersect printed-text masks.
- Stamps are not labelled as signatures.
- Negative pages contain no signature instances or signature pixels.

## 15.3 Visual QA

Generate contact sheets showing:

1. Original document.
2. Signature mask overlay.
3. Printed-text mask overlay.
4. Stamp and form-line masks.
5. Combined overlap view.
6. Bounding boxes and instance IDs.

Review samples across:

- Every placement scenario.
- Every language style.
- Real and fictional signature sources.
- Different template families.
- Different degradation levels.

During the pilot, use higher human review coverage. After the pipeline stabilizes, review at least 2–5% as an initial QA target.

## 15.4 Quality Gates

Do not generate the final 10,000 pages until:

- Automated integrity tests pass.
- Pilot masks show no systematic alignment defects.
- Overlap distributions meet the intended targets.
- Devanagari rendering is visually correct.
- Split leakage checks pass.
- A small baseline model has been evaluated on real documents.

---

# 16. Feasibility Assessment

## 16.1 Technical Feasibility

| Area                                | Feasibility             | Main Risk                           |
| ----------------------------------- | ----------------------- | ----------------------------------- |
| Template-driven document rendering  | High                    | Layout diversity                    |
| Fictional signature-like generation | High                    | Artificial or repetitive appearance |
| Real signature collection           | Medium                  | Consent, licence, privacy           |
| Signature placement and overlap     | High                    | Correct transformations             |
| Bounding-box annotation             | High                    | Recalculation after transforms      |
| Masks for generated layers          | High                    | Transform synchronization           |
| Masks for real signatures           | Medium                  | Background separation quality       |
| English rendering                   | High                    | Font consistency                    |
| Devanagari rendering                | Medium–High            | Font shaping and glyph support      |
| Scan degradation                    | High                    | Unrealistic augmentation            |
| COCO export                         | High                    | RLE and annotation consistency      |
| 10,000-page generation              | High                    | Runtime and storage                 |
| Real-world generalization           | Unknown until evaluated | Synthetic-to-real domain gap        |

## 16.2 Overall Feasibility

The project is technically feasible using a local Python pipeline.

A GPU is not required for basic dataset generation.

The most difficult parts are:

1. Collecting sufficiently diverse, legally usable real signatures.
2. Creating natural-looking fictional signature-like assets.
3. Building sufficiently diverse document templates.
4. Separating real signature ink from its original background.
5. Ensuring the generated documents represent real scanned documents.
6. Demonstrating generalization using a separate real-world test set.

The project should therefore be treated as a synthetic dataset generation and real-world validation initiative.

## 16.3 Risks and Mitigations

| Risk                                  | Impact   | Mitigation                                                |
| ------------------------------------- | -------- | --------------------------------------------------------- |
| Artificial-looking signatures         | High     | Combine diverse real and fictional assets                 |
| Repeated assets cause memorization    | High     | Source-group tracking and reuse limits                    |
| Repetitive document templates         | High     | Multiple template families and diversity metrics          |
| Incorrect masks after transformations | Critical | Apply identical geometric parameters and regression tests |
| Poor real-asset background extraction | High     | Manual review and rejection criteria                      |
| Devanagari font issues                | Medium   | Validate fonts and sample strings                         |
| Unrealistic overlap                   | High     | Scenario controller and measured overlap metrics          |
| Train/test leakage                    | Critical | Split by template family and source group                 |
| Privacy/licensing issues              | Critical | Consent/provenance registry and access controls           |
| Synthetic-to-real performance gap     | High     | Separate real-world evaluation set                        |

---

# 17. Runtime and Storage Planning

The generator is primarily CPU- and disk-I/O-bound.

Benchmark with a 100-page pilot before estimating total runtime.

Planning assumptions:

- 10,000 pages.
- Approximately 1–5 MB average compressed page image, depending on resolution and content.
- Multiple semantic masks per page.
- One or more instance masks per signature.
- Additional signature crops.
- Optional debug overlays and intermediate layers.

A provisional storage allowance is **50–150 GB** if retaining full-resolution images, masks, crops, and debug outputs.

This is a conservative planning estimate, not a measured prediction.

## Storage Optimization

- Use PNG for annotation masks.
- Use JPEG for RGB pages only if lossy compression is acceptable.
- Avoid retaining all intermediate layers in production mode.
- Retain configurations, seeds, manifests, source IDs, and final outputs.
- Keep debug mode separate.
- Consider lossless WebP only after checking downstream compatibility.

## Runtime Estimation

1. Generate 100 pages using target resolution.
2. Measure wall-clock time.
3. Measure peak memory.
4. Measure output storage per page.
5. Estimate total time:

```python
estimated_runtime = (
    pilot_runtime * (target_pages / pilot_pages)
)
```

6. Add a buffer for retries, validation, and export.
7. Benchmark different worker counts.

Do not promise a generation time until the pilot has been benchmarked.

---

# 18. Development Roadmap and Milestones

| Phase | Work                                               | Deliverable                | Indicative Duration |
| ----- | -------------------------------------------------- | -------------------------- | ------------------: |
| 0     | Freeze annotation/source policy and config schema  | Specification              |           2–3 days |
| 1     | Asset registry, normalization, fictional generator | Reviewed signature library |           4–6 days |
| 2     | Layout primitives and templates                    | Initial template library   |           5–7 days |
| 3     | Signature placement and overlap controller         | Composition engine         |           5–7 days |
| 4     | Bboxes, masks, COCO and crop export                | 100-page pilot             |           3–5 days |
| 5     | Scan effects and validation                        | Degraded pilot             |           4–6 days |
| 6     | Pilot review and real-data evaluation              | Pilot report               |           4–6 days |
| 7     | Scale templates/assets and generate 10k            | Full dataset               |           2–4 days |
| 8     | Final QA and documentation                         | Versioned dataset          |           2–3 days |

**Indicative overall duration: approximately 5–7 weeks for one engineer.**

This assumes signature assets and fonts can be sourced in parallel and there are no major licensing or access blockers. It is an engineering estimate, not a delivery guarantee.

---

# 19. Testing Strategy

## Unit Tests

- Configuration probability validation.
- Template coordinate validation.
- English and Devanagari rendering.
- Signature mask normalization.
- Bounding-box calculation from masks.
- Image/mask transformation consistency.
- Overlap calculation.
- Crop coordinate translation.
- COCO RLE encoding and decoding.
- Deterministic generation with fixed seeds.

## Integration Tests

- Render a page from each template family.
- Generate each placement scenario.
- Apply geometric and photometric augmentation.
- Export COCO and PNG masks.
- Reload exports and verify annotation alignment.
- Generate crops and verify parent/child coordinates.

## Regression Tests

Use fixed random seeds and assert:

- Dimensions.
- Mask areas.
- Bounding boxes.
- Overlap ranges.
- Output structure.
- Annotation consistency.

Avoid relying only on exact pixel hashes because rasterization may vary across library versions.

---

# 20. Dataset Card and Reproducibility

Every dataset release should document:

- Dataset version.
- Generation date.
- Number of complete pages.
- Number of derived crops.
- Train/validation/test counts.
- Template families.
- Language distribution.
- Signature source distribution.
- Asset licence and consent policy.
- Class definitions.
- Overlap semantics.
- Rendering methods.
- Augmentation methods.
- Known limitations.
- Real-world evaluation results.
- Intended and prohibited uses.
- Reproduction commands.
- Configuration hash.

Every page manifest should contain:

- Page ID.
- Random seed.
- Template ID and family.
- Signature asset IDs.
- Signature source groups.
- Language style.
- Placement scenario.
- Actual overlap ratios.
- Transformations applied.
- Image and annotation paths.
- Generator version.
- Configuration hash.

This allows any generated sample to be reproduced and investigated.

---

# 21. Recommended Implementation Order

Do not start by generating 10,000 pages.

Implement in the following order:

1. Define and freeze annotation semantics.
2. Create project structure and typed configuration.
3. Implement a single document renderer with independent layer masks.
4. Implement signature asset normalization.
5. Implement one fictional signature generator.
6. Implement signature placement over a printed label.
7. Implement synchronized mask transformations.
8. Implement bbox calculation.
9. Add form-line and table overlaps.
10. Add printed-text and stamp overlaps.
11. Export one complete page to COCO and PNG masks.
12. Implement signature crop generation.
13. Add scan degradation.
14. Add template families and Devanagari support.
15. Generate a 100-page technical pilot.
16. Generate a 500–1,000-page diversity/model pilot.
17. Evaluate against a separate real-document set.
18. Fix synthetic-to-real domain-gap issues.
19. Generate the final 10,000-page dataset.

---

# 22. Final Recommendation

Proceed with the project, but make the pilot a mandatory feasibility gate.

The recommended architecture is:

- Template-driven document rendering.
- Hybrid fictional and consented real signature assets.
- Independent visual layers and annotation masks.
- Explicit scenario-driven signature placement.
- Synchronized geometric transformations.
- COCO RLE and PNG masks as canonical segmentation labels.
- Derived signature-region crops.
- Provenance-aware dataset splits.
- Automated annotation validation.
- Separate real-world evaluation.

The primary success criterion is not merely generating 10,000 images.

**Success means demonstrating that a model trained on the generated dataset can detect and segment signatures on a separately collected, representative set of real scanned documents.**

---

# Appendix A — Acceptance Checklist

- [ ] 10,000 unique complete pages generated.
- [ ] Signature crops exported and linked to parent pages.
- [ ] Every signature has a non-empty instance mask.
- [ ] Every signature has a bbox calculated from its final mask.
- [ ] Printed-text masks are retained independently.
- [ ] Signature/printed-text overlap masks are correctly derived.
- [ ] Form-line and stamp masks are available.
- [ ] English and Devanagari rendering are visually verified.
- [ ] Real assets have approved provenance.
- [ ] Fictional assets are not represented as genuine signatures.
- [ ] No template/source-group leakage across splits.
- [ ] COCO export reloads and validates.
- [ ] Crop annotations use crop-relative coordinates.
- [ ] Scan effects do not desynchronize masks.
- [ ] Contact sheets and dataset statistics are generated.
- [ ] Real-world evaluation set is separate from synthetic data.
- [ ] Dataset card and generation configuration are included.

# Appendix B — Important Implementation Decision

The canonical ground truth should be:

**Independent PNG masks + structured JSON manifest.**

COCO and YOLO should be derived export formats rather than the source of truth.

This preserves exact pixel-level labels, including cases where multiple annotation classes overlap, and keeps the generator independent of any specific model framework.
