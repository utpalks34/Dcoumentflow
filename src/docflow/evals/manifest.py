"""Dataset manifest builder (TR-EVAL-01).

A pilot-scoped subset of the full TR-EVAL-01 manifest schema: with only a
few dozen documents and no labels yet, every row goes into split="pilot"
rather than a DEV/TEST split (docs/05_Phase_Plan.md P1-T3; confirmed with
the user 2026-09-30). Never copies file content into the manifest or
prints it to the console -- only the hash, path, and page count are
recorded.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pypdf import PdfReader
from pypdf.errors import PdfReadError

DEFAULT_OUT_PATH = Path("data/manifests/pilot.jsonl")


class ManifestRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    path: str
    sha256: str
    pages: int | None
    source: Literal["public", "real", "synthetic"]
    split: str


def _try_read_page_count(pdf_path: Path) -> int | None:
    try:
        return len(PdfReader(pdf_path).pages)
    except (PdfReadError, ValueError, KeyError):
        return None


def build_manifest(
    folder: Path,
    out_path: Path = DEFAULT_OUT_PATH,
    *,
    source: Literal["public", "real", "synthetic"] = "synthetic",
    split: str = "pilot",
) -> list[ManifestRow]:
    pdf_paths = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() == ".pdf")

    seen_hashes: set[str] = set()
    rows: list[ManifestRow] = []
    for pdf_path in pdf_paths:
        digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        rows.append(
            ManifestRow(
                doc_id=f"d_{digest[:12]}",
                path=str(pdf_path),
                sha256=digest,
                pages=_try_read_page_count(pdf_path),
                source=source,
                split=split,
            )
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(row.model_dump_json() + "\n")

    return rows


def load_manifest(path: Path) -> list[ManifestRow]:
    rows: list[ManifestRow] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            rows.append(ManifestRow.model_validate_json(stripped))
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="docflow manifest build")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    parser.add_argument("--source", choices=["public", "real", "synthetic"], default="synthetic")
    parser.add_argument("--split", default="pilot")
    args = parser.parse_args(argv)

    rows = build_manifest(args.folder, args.out, source=args.source, split=args.split)
    print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
