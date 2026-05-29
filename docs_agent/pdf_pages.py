from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz
from tqdm import tqdm


@dataclass(frozen=True)
class RenderedPage:
    page_number: int
    image_path: Path


def render_pdf_pages(
    pdf_path: str | Path,
    pages_dir: str | Path,
    dpi: int,
    image_format: str = "png",
    page_range: tuple[int, int | None] | None = None,
) -> tuple[list[RenderedPage], int]:
    source_pdf = Path(pdf_path).expanduser().resolve()
    output_dir = Path(pages_dir).expanduser().resolve()

    if not source_pdf.exists():
        raise FileNotFoundError(f"PDF not found: {source_pdf}")
    if image_format.lower() != "png":
        raise ValueError("Only PNG rendering is currently supported by this lightweight agent.")

    output_dir.mkdir(parents=True, exist_ok=True)
    rendered_pages: list[RenderedPage] = []

    with fitz.open(source_pdf) as document:
        total_pages = len(document)
        start_index, end_index = _page_indexes(total_pages, page_range)
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        page_indexes = range(start_index, end_index)
        for page_index in tqdm(page_indexes, desc="Rendering PDF pages", unit="page"):
            page_number = page_index + 1
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image_path = output_dir / f"page_{page_number:04d}.png"
            pixmap.save(image_path)
            rendered_pages.append(RenderedPage(page_number=page_number, image_path=image_path))

    return rendered_pages, total_pages


def _page_indexes(
    total_pages: int,
    page_range: tuple[int, int | None] | None,
) -> tuple[int, int]:
    if page_range is None:
        return 0, total_pages

    start_page, end_page = page_range
    if start_page < 1:
        raise ValueError("Page ranges are 1-indexed; the start page must be at least 1.")

    resolved_end_page = total_pages if end_page is None else end_page
    if resolved_end_page < start_page:
        raise ValueError("Page range end must be greater than or equal to the start page.")

    start_index = min(start_page - 1, total_pages)
    end_index = min(resolved_end_page, total_pages)
    return start_index, end_index
