"""Aggregate-only profiling of a folder of PDFs.

Reports file count, page-count distribution, text-layer vs. scanned split,
file-size stats, and PDF producer/creator metadata counts. Never surfaces
a per-file name or any extracted invoice text (docs/06_LLM_Instructions.md,
Hard rules 7 and 8) -- every field on ProfileReport is an aggregate.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

_TEXT_LAYER_MIN_CHARS = 20


@dataclass
class ProfileReport:
    file_count: int = 0
    page_count_distribution: dict[int, int] = field(default_factory=dict)
    text_layer_count: int = 0
    scanned_count: int = 0
    unreadable_count: int = 0
    file_size_bytes_min: int | None = None
    file_size_bytes_max: int | None = None
    file_size_bytes_mean: float | None = None
    producers: dict[str, int] = field(default_factory=dict)
    creators: dict[str, int] = field(default_factory=dict)


def _has_text_layer(reader: PdfReader) -> bool:
    total_chars = 0
    for page in reader.pages:
        total_chars += len(page.extract_text().strip())
        if total_chars >= _TEXT_LAYER_MIN_CHARS:
            return True
    return False


def profile_folder(folder: Path) -> ProfileReport:
    pdf_paths = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() == ".pdf")

    page_counts: Counter[int] = Counter()
    producers: Counter[str] = Counter()
    creators: Counter[str] = Counter()
    sizes: list[int] = []
    text_layer_count = 0
    scanned_count = 0
    unreadable_count = 0

    for pdf_path in pdf_paths:
        sizes.append(pdf_path.stat().st_size)
        try:
            reader = PdfReader(pdf_path)
            n_pages = len(reader.pages)
            page_counts[n_pages] += 1
            if _has_text_layer(reader):
                text_layer_count += 1
            else:
                scanned_count += 1
            metadata = reader.metadata
            if metadata is not None:
                if metadata.producer:
                    producers[metadata.producer] += 1
                if metadata.creator:
                    creators[metadata.creator] += 1
        except (PdfReadError, ValueError, KeyError):
            unreadable_count += 1

    return ProfileReport(
        file_count=len(pdf_paths),
        page_count_distribution=dict(page_counts),
        text_layer_count=text_layer_count,
        scanned_count=scanned_count,
        unreadable_count=unreadable_count,
        file_size_bytes_min=min(sizes) if sizes else None,
        file_size_bytes_max=max(sizes) if sizes else None,
        file_size_bytes_mean=(sum(sizes) / len(sizes)) if sizes else None,
        producers=dict(producers),
        creators=dict(creators),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="docflow profile")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    report = profile_folder(args.folder)

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(f"file_count: {report.file_count}")
        print(f"page_count_distribution: {report.page_count_distribution}")
        print(f"text_layer_count: {report.text_layer_count}")
        print(f"scanned_count: {report.scanned_count}")
        print(f"unreadable_count: {report.unreadable_count}")
        print(f"file_size_bytes_min: {report.file_size_bytes_min}")
        print(f"file_size_bytes_max: {report.file_size_bytes_max}")
        print(f"file_size_bytes_mean: {report.file_size_bytes_mean}")
        print(f"producers: {report.producers}")
        print(f"creators: {report.creators}")


if __name__ == "__main__":
    main()
