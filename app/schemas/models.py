from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExtractionField(StrEnum):
    BODY_TEXT = "body_text"
    HEADING = "heading"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    FOOTNOTE = "footnote"
    HYPERLINK = "hyperlink"
    IMAGE = "image"
    TABLE = "table"
    CAPTION = "caption"
    LIST = "list"
    EQUATION = "equation"
    FORM_FIELD = "form_field"
    CODE = "code"
    OTHER = "other"


BODY_CONTENT_FIELDS = frozenset({
    ExtractionField.BODY_TEXT, ExtractionField.HEADING, ExtractionField.LIST,
    ExtractionField.CAPTION, ExtractionField.EQUATION, ExtractionField.CODE,
    ExtractionField.FORM_FIELD, ExtractionField.OTHER,
})


class FieldExtractionStatus(StrEnum):
    EXTRACTED = "extracted"
    EXTRACTED_UNVALIDATED = "extracted_unvalidated"
    VALIDATED = "validated"
    NEEDS_REVIEW = "needs_review"
    NOT_DETECTED = "not_detected"
    NOT_REQUESTED = "not_requested"
    FAILED = "failed"


class BoundingBox(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ordered(self) -> "BoundingBox":
        if self.x0 > self.x1 or self.y0 > self.y1:
            raise ValueError("bbox coordinates must be ordered top-left to bottom-right")
        return self


class Element(BaseModel):
    model_config = ConfigDict(extra="forbid")
    element_id: str
    type: ExtractionField
    text: str | None = None
    reading_order: int = Field(ge=0)
    bbox: BoundingBox | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    target_uri: str | None = None
    artifact_path: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class Page(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_number: int = Field(ge=1)
    width_pt: float = Field(gt=0)
    height_pt: float = Field(gt=0)
    rotation_degrees: int = 0
    coordinate_system: str = "normalized_top_left_0_1"
    body_text: str = ""
    physical_page_index: int | None = Field(default=None, ge=1)
    printed_page_label: str | None = None
    source_text_char_count: int = Field(default=0, ge=0)
    body_text_char_count: int = Field(default=0, ge=0)
    duplicate_text_char_count: int = Field(default=0, ge=0)
    body_text_to_source_text_ratio: float | None = Field(default=None, ge=0)
    source_text_coverage_before_recovery: float | None = Field(default=None, ge=0, le=1)
    source_text_coverage_ratio: float | None = Field(default=None, ge=0, le=1)
    normalized_source_char_count: int = Field(default=0, ge=0)
    normalized_output_char_count: int = Field(default=0, ge=0)
    missing_span_count: int = Field(default=0, ge=0)
    unmatched_source_char_count: int = Field(default=0, ge=0)
    unmatched_source_token_count: int = Field(default=0, ge=0)
    recovered_source_char_count: int = Field(default=0, ge=0)
    fallback_used: bool = False
    fallback_chars_added: int = Field(default=0, ge=0)
    fallback_overlap_chars_removed: int = Field(default=0, ge=0)
    fallback_overlap_decisions: list[dict[str, Any]] = Field(default_factory=list)
    text_quality_status: str = "unassessed"
    hyperlink_count: int = Field(default=0, ge=0)
    hyperlink_unresolved_target_count: int = Field(default=0, ge=0)
    hyperlink_malformed_uri_count: int = Field(default=0, ge=0)
    field_status: dict[str, FieldExtractionStatus] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    elements: list[Element] = Field(default_factory=list)


class DocumentInfo(BaseModel):
    source_filename: str
    source_sha256: str
    page_count: int = Field(ge=0)
    title: str | None = None
    language: str | None = None


class ProcessingInfo(BaseModel):
    parser_name: str
    parser_version: str
    adapter_version: str = "0.5.0"
    run_id: str | None = None
    processed_at_utc: str | None = None
    build_id: str | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)
    dependency_versions: dict[str, str] = Field(default_factory=dict)
    model_version: str | None = None
    status: str = "success"
    requested_fields: list[ExtractionField]
    extracted_fields: list[ExtractionField]
    missing_fields: list[ExtractionField] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    warning_summary: dict[str, int] = Field(default_factory=dict)
    page_quality_summary: dict[str, int] = Field(default_factory=dict)
    docx_layout_mode: str = "editable_reflowable"
    docx_layout_status: str = "not_generated"
    docx_page_width_pt: float | None = Field(default=None, gt=0)
    docx_page_height_pt: float | None = Field(default=None, gt=0)
    errors: list[str] = Field(default_factory=list)


class ArtifactInfo(BaseModel):
    html_path: str | None = None
    docx_path: str = "document.docx"
    image_paths: list[str] = Field(default_factory=list)
    table_snapshot_paths: list[str] = Field(default_factory=list)
    manifest_path: str = "manifest.json"


class Metadata(BaseModel):
    schema_version: str = "1.4"
    document: DocumentInfo
    processing: ProcessingInfo
    pages: list[Page]
    artifacts: ArtifactInfo = Field(default_factory=ArtifactInfo)


class ExtractionRequest(BaseModel):
    extraction_fields: list[ExtractionField] = Field(
        default_factory=lambda: [ExtractionField.BODY_TEXT, ExtractionField.HEADING,
                                 ExtractionField.HEADER, ExtractionField.FOOTER,
                                 ExtractionField.PAGE_NUMBER, ExtractionField.FOOTNOTE, ExtractionField.HYPERLINK,
                                 ExtractionField.IMAGE, ExtractionField.TABLE]
    )
    output_mode: str = "legacy_compatible"
    ocr_mode: str = "auto"


class ApiError(BaseModel):
    code: str
    message: str
    request_id: str
