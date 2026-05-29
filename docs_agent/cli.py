from __future__ import annotations

import argparse
from pathlib import Path

from .agent import PdfExtractionAgent
from .config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a PDF into page images and extract one JSON file per page with Azure OpenAI vision."
    )
    parser.add_argument("--pdf", required=True, help="Path to the PDF document to process.")
    parser.add_argument("--config", default="config.yaml", help="Path to the YAML config file.")
    parser.add_argument("--pages", help="Optional 1-indexed page range, for example 1-5, 3, or 10-.")
    parser.add_argument("--run-id", help="Optional run id used in the per-document output directory name.")
    parser.add_argument("--dry-run", action="store_true", help="Render pages and write a manifest without calling Azure OpenAI.")

    args = parser.parse_args()
    config = load_config(Path(args.config))
    agent = PdfExtractionAgent(config)
    result = agent.process(
        pdf_path=args.pdf,
        page_range=parse_page_range(args.pages),
        run_id=args.run_id,
        dry_run=args.dry_run,
    )

    print(f"Output directory: {result.output_dir}")
    print(f"Rendered pages: {result.rendered_pages}")
    print(f"Extracted JSON pages: {result.extracted_pages}")
    print(f"Failed pages: {result.failed_pages}")
    return 0


def parse_page_range(value: str | None) -> tuple[int, int | None] | None:
    if not value:
        return None

    cleaned_value = value.strip()
    if not cleaned_value:
        return None

    if "-" not in cleaned_value:
        page_number = int(cleaned_value)
        return page_number, page_number

    start_text, end_text = cleaned_value.split("-", 1)
    start_page = int(start_text.strip()) if start_text.strip() else 1
    end_page = int(end_text.strip()) if end_text.strip() else None
    return start_page, end_page


if __name__ == "__main__":
    raise SystemExit(main())
