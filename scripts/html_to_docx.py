from __future__ import annotations

import argparse
from pathlib import Path

from app.artifacts.package import _html_to_docx


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create an editable DOCX from a PDFLens document.html file."
    )
    parser.add_argument("html", type=Path, help="Generated document.html")
    parser.add_argument("--output", type=Path, help="DOCX output path")
    args = parser.parse_args()

    source = args.html.resolve()
    if not source.is_file():
        parser.error(f"HTML input does not exist: {source}")
    destination = (args.output or source.with_suffix(".docx")).resolve()
    _html_to_docx(source, destination)
    print(destination)


if __name__ == "__main__":
    main()
