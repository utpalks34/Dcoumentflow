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

from docflow.evals.split import DEFAULT_DEV_RATIO, DEFAULT_SPLIT_SEED, assign_split

DEFAULT_OUT_PATH = Path("data/manifests/pilot.jsonl")
DEFAULT_LABELS_ROOT = Path("data/labels")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")

_DOC_ID_PREFIX_TO_DATASET = {
    "sroie_": "sroie",
    "dev_clean_": "dev_clean",
}


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


def write_manifest(rows: list[ManifestRow], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(row.model_dump_json() + "\n")


def build_manifest(
    folder: Path,
    out_path: Path = DEFAULT_OUT_PATH,
    *,
    source: Literal["public", "real", "synthetic"] = "synthetic",
    split: str = "pilot",
    doc_id_mode: Literal["hash", "stem"] = "hash",
) -> list[ManifestRow]:
    pdf_paths = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() == ".pdf")

    seen_hashes: set[str] = set()
    rows: list[ManifestRow] = []
    for pdf_path in pdf_paths:
        digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        doc_id = pdf_path.stem if doc_id_mode == "stem" else f"d_{digest[:12]}"
        rows.append(
            ManifestRow(
                doc_id=doc_id,
                path=str(pdf_path),
                sha256=digest,
                pages=_try_read_page_count(pdf_path),
                source=source,
                split=split,
            )
        )

    write_manifest(rows, out_path)
    return rows


def build_manifest_with_split(
    folder: Path,
    out_path: Path,
    *,
    source: Literal["public", "real", "synthetic"],
    seed: int = DEFAULT_SPLIT_SEED,
    dev_ratio: float = DEFAULT_DEV_RATIO,
    extensions: tuple[str, ...] = IMAGE_EXTENSIONS,
) -> list[ManifestRow]:
    """Build a manifest whose `split` is assigned per-document by
    `assign_split(doc_id, seed)` -- not a single folder-wide value. Used for
    the SROIE hard set, where DocFlow's own seeded hash, not SROIE's
    train/test folders, decides dev_hard vs test_hard (ADR-009).
    """
    paths = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in extensions)

    seen_hashes: set[str] = set()
    rows: list[ManifestRow] = []
    for path in paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        doc_id = path.stem
        rows.append(
            ManifestRow(
                doc_id=doc_id,
                path=str(path),
                sha256=digest,
                pages=1,  # each source file is a single-page receipt image
                source=source,
                split=assign_split(doc_id, seed=seed, dev_ratio=dev_ratio),
            )
        )

    write_manifest(rows, out_path)
    return rows


def merge_manifests(paths: list[Path], out_path: Path) -> list[ManifestRow]:
    rows: list[ManifestRow] = []
    seen_doc_ids: set[str] = set()
    for path in paths:
        for row in load_manifest(path):
            if row.doc_id in seen_doc_ids:
                raise ValueError(f"duplicate doc_id across manifests: {row.doc_id!r}")
            seen_doc_ids.add(row.doc_id)
            rows.append(row)

    rows.sort(key=lambda r: r.doc_id)
    write_manifest(rows, out_path)
    return rows


def label_path_for(doc_id: str, labels_root: Path = DEFAULT_LABELS_ROOT) -> Path:
    for prefix, dataset in _DOC_ID_PREFIX_TO_DATASET.items():
        if doc_id.startswith(prefix):
            return labels_root / dataset / f"{doc_id}.json"
    raise ValueError(f"no known label directory for doc_id {doc_id!r}")


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
    parser.add_argument("--doc-id-mode", choices=["hash", "stem"], default="hash")
    args = parser.parse_args(argv)

    rows = build_manifest(
        args.folder, args.out, source=args.source, split=args.split, doc_id_mode=args.doc_id_mode
    )
    print(f"wrote {len(rows)} rows to {args.out}")


def build_sroie_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="docflow manifest build-sroie")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SPLIT_SEED)
    args = parser.parse_args(argv)

    rows = build_manifest_with_split(args.folder, args.out, source="public", seed=args.seed)
    dev_count = sum(1 for row in rows if row.split == "dev_hard")
    test_count = len(rows) - dev_count
    print(f"wrote {len(rows)} rows to {args.out} ({dev_count} dev_hard, {test_count} test_hard)")


def merge_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="docflow manifest merge")
    parser.add_argument("manifests", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    rows = merge_manifests(args.manifests, args.out)
    print(f"wrote {len(rows)} merged rows to {args.out}")


if __name__ == "__main__":
    main()
