from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
from typing import Any


def inspect_pdf(path: Path) -> dict[str, Any]:
    from pypdf import PdfReader

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)

    try:
        reader = PdfReader(path, strict=False)
        page_metrics = []
        extraction_errors = 0
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
                char_count = len(text.strip())
                extraction_error = False
            except Exception:
                char_count = 0
                extraction_error = True
                extraction_errors += 1
            page_metrics.append({
                "physical_page_index": page_number,
                "source_text_char_count": char_count,
                "text_layer_present": char_count > 0,
                "extraction_error": extraction_error,
            })
        pages_with_text = sum(page["text_layer_present"] for page in page_metrics)
        if not pages_with_text:
            source_type = "scanned_or_text_layer_unavailable"
        elif pages_with_text == len(page_metrics):
            source_type = "text_based"
        else:
            source_type = "mixed"
        return {
            "filename": path.name,
            "relative_path": str(path),
            "sha256": digest.hexdigest(),
            "page_count": len(page_metrics),
            "source_type": source_type,
            "pages_with_text_layer": pages_with_text,
            "pages_without_text_layer": len(page_metrics) - pages_with_text,
            "page_extraction_errors": extraction_errors,
            "pages": page_metrics,
        }
    except Exception as exc:
        return {
            "filename": path.name,
            "relative_path": str(path),
            "sha256": digest.hexdigest(),
            "error_type": type(exc).__name__,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a source-grounded inventory of PDFs and per-page text layers."
    )
    parser.add_argument("directory", nargs="?", type=Path, default=Path("rbi_docs"))
    parser.add_argument("--output", type=Path,
                        help="Write JSON to this path instead of stdout.")
    args = parser.parse_args()
    logging.getLogger("pypdf._cmap").setLevel(logging.ERROR)
    pdf_paths = sorted(args.directory.rglob("*.pdf"), key=lambda path: str(path).casefold())
    report = {
        "root": str(args.directory),
        "pdf_count": len(pdf_paths),
        "text_extraction_notes": (
            [] if importlib.util.find_spec("fontTools") else [
                "fontTools is not installed; pypdf may not fully decode some embedded CFF Type1 fonts."
            ]
        ),
        "documents": [inspect_pdf(path) for path in pdf_paths],
    }
    serialized = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        print(f"Wrote inventory for {len(pdf_paths)} PDFs to {args.output}")
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()
