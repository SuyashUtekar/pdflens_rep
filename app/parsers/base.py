from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.schemas.models import ExtractionField, Page


@dataclass
class ParsedDocument:
    pages: list[Page]
    parser_name: str
    parser_version: str
    title: str | None = None
    warnings: list[str] = field(default_factory=list)
    extracted_fields: set[ExtractionField] = field(default_factory=set)
    assets: list["ParsedAsset"] = field(default_factory=list)


@dataclass
class ParsedAsset:
    element_id: str
    page_number: int
    asset_type: ExtractionField
    content: bytes
    media_type: str = "image/png"


class ParserAdapter(Protocol):
    def parse(self, pdf_path: str, requested: set[ExtractionField]) -> ParsedDocument: ...
