from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tqdm import tqdm

from .config import AppConfig
from .openai_extractor import PageExtractor
from .pdf_pages import RenderedPage, render_pdf_pages


@dataclass(frozen=True)
class ProcessResult:
    output_dir: Path
    rendered_pages: int
    extracted_pages: int
    failed_pages: int


class PdfExtractionAgent:
    def __init__(self, config: AppConfig):
        self.config = config

    def process(
        self,
        pdf_path: str | Path,
        page_range: tuple[int, int | None] | None = None,
        run_id: str | None = None,
        dry_run: bool = False,
    ) -> ProcessResult:
        source_pdf = Path(pdf_path).expanduser().resolve()
        output_dir = self._create_output_dir(source_pdf, run_id)
        pages_dir = output_dir / "pages"
        json_dir = output_dir / "json"
        raw_dir = output_dir / "raw_responses"
        errors_dir = output_dir / "errors"

        for directory in (pages_dir, json_dir, raw_dir, errors_dir):
            directory.mkdir(parents=True, exist_ok=True)

        rendered_pages, total_pages = render_pdf_pages(
            source_pdf,
            pages_dir,
            dpi=self.config.pdf.dpi,
            image_format=self.config.pdf.image_format,
            page_range=page_range,
        )

        manifest: dict[str, Any] = {
            "document_name": source_pdf.name,
            "source_pdf": str(source_pdf),
            "output_dir": str(output_dir),
            "total_pdf_pages": total_pages,
            "rendered_pages": len(rendered_pages),
            "dry_run": dry_run,
            "pages": [],
        }
        _write_json(output_dir / "manifest.json", manifest)

        if dry_run:
            return ProcessResult(output_dir=output_dir, rendered_pages=len(rendered_pages), extracted_pages=0, failed_pages=0)

        extractor = PageExtractor(self.config)
        extracted_pages = 0
        failed_pages = 0

        for rendered_page in tqdm(rendered_pages, desc="Extracting page JSON", unit="page"):
            page_record = self._process_page(
                extractor=extractor,
                rendered_page=rendered_page,
                document_name=source_pdf.name,
                total_pages=total_pages,
                json_dir=json_dir,
                raw_dir=raw_dir,
                errors_dir=errors_dir,
            )
            manifest["pages"].append(page_record)
            _write_json(output_dir / "manifest.json", manifest)

            if page_record["status"] == "ok":
                extracted_pages += 1
            else:
                failed_pages += 1
                if not self.config.extraction.continue_on_error:
                    raise RuntimeError(page_record["error"])

            if self.config.extraction.request_delay_seconds > 0:
                time.sleep(self.config.extraction.request_delay_seconds)

        manifest["extracted_pages"] = extracted_pages
        manifest["failed_pages"] = failed_pages
        _write_json(output_dir / "manifest.json", manifest)

        return ProcessResult(
            output_dir=output_dir,
            rendered_pages=len(rendered_pages),
            extracted_pages=extracted_pages,
            failed_pages=failed_pages,
        )

    def _process_page(
        self,
        extractor: PageExtractor,
        rendered_page: RenderedPage,
        document_name: str,
        total_pages: int,
        json_dir: Path,
        raw_dir: Path,
        errors_dir: Path,
    ) -> dict[str, Any]:
        page_number = rendered_page.page_number
        stem = f"page_{page_number:04d}"
        json_path = json_dir / f"{stem}.json"
        raw_path = raw_dir / f"{stem}.response.json"
        error_path = errors_dir / f"{stem}.error.json"

        try:
            result = extractor.extract_page(
                document_name=document_name,
                page_number=page_number,
                total_pages=total_pages,
                image_path=rendered_page.image_path,
            )
            _write_json(json_path, result.json_payload)
            if result.raw_response is not None:
                _write_json(raw_path, result.raw_response)
            return {
                "page_number": page_number,
                "status": "ok",
                "image_path": str(rendered_page.image_path),
                "json_path": str(json_path),
                "raw_response_path": str(raw_path) if result.raw_response is not None else None,
            }
        except Exception as error:
            error_payload = {
                "page_number": page_number,
                "status": "error",
                "image_path": str(rendered_page.image_path),
                "error": str(error),
            }
            _write_json(error_path, error_payload)
            return {**error_payload, "error_path": str(error_path)}

    def _create_output_dir(self, source_pdf: Path, run_id: str | None) -> Path:
        safe_name = _safe_name(source_pdf.stem)
        resolved_run_id = _safe_name(run_id) if run_id else datetime.now().strftime("%Y%m%d_%H%M%S")
        self.config.extraction.output_root.mkdir(parents=True, exist_ok=True)

        output_dir = self.config.extraction.output_root / f"{safe_name}_{resolved_run_id}"
        counter = 2
        while output_dir.exists():
            output_dir = self.config.extraction.output_root / f"{safe_name}_{resolved_run_id}_{counter}"
            counter += 1
        output_dir.mkdir(parents=True)
        return output_dir


def _safe_name(value: str | None) -> str:
    if not value:
        return "document"
    safe_value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return safe_value or "document"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output_file:
        json.dump(payload, output_file, indent=2, ensure_ascii=False, default=str)
        output_file.write("\n")
