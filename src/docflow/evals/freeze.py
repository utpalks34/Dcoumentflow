"""Freeze and verify protected manifest splits (ADR-009).

A frozen split pins a sha256 hash per document, covering both its
manifest row and its label file, so any later edit to either -- including
silently moving a document to a different split -- is detectable by
`verify_split`. Freezing refuses to overwrite an existing frozen record
without `force=True`: re-freezing a protected split after an undetected
change would defeat the guard entirely.
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import date
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict

from docflow.evals.manifest import DEFAULT_LABELS_ROOT, ManifestRow, label_path_for, load_manifest

DEFAULT_MANIFEST_PATH = Path("data/manifests/all.jsonl")
DEFAULT_FROZEN_DIR = Path("data/manifests/frozen")


class FrozenManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    split: str
    frozen_at: date
    doc_hashes: dict[str, str]


class VerifyResult(NamedTuple):
    split: str
    checked: int
    mismatched: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.mismatched and not self.missing


def _doc_hash(row: ManifestRow, label_path: Path) -> str:
    if not label_path.exists():
        raise FileNotFoundError(f"label file missing for {row.doc_id}: {label_path}")
    hasher = hashlib.sha256()
    hasher.update(row.model_dump_json().encode("utf-8"))
    hasher.update(label_path.read_bytes())
    return hasher.hexdigest()


def _frozen_path(split: str, frozen_dir: Path) -> Path:
    return frozen_dir / f"{split}.json"


def freeze_split(
    split: str,
    *,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    labels_root: Path = DEFAULT_LABELS_ROOT,
    frozen_dir: Path = DEFAULT_FROZEN_DIR,
    frozen_at: date | None = None,
    force: bool = False,
) -> FrozenManifest:
    out_path = _frozen_path(split, frozen_dir)
    if out_path.exists() and not force:
        raise FileExistsError(
            f"{out_path} already exists; re-freezing a protected split can mask "
            f"tampering -- pass force=True only if you mean to replace it"
        )

    rows = [row for row in load_manifest(manifest_path) if row.split == split]
    if not rows:
        raise ValueError(f"no rows with split={split!r} in {manifest_path}")

    doc_hashes = {
        row.doc_id: _doc_hash(row, label_path_for(row.doc_id, labels_root)) for row in rows
    }
    frozen = FrozenManifest(
        split=split, frozen_at=frozen_at or date.today(), doc_hashes=doc_hashes
    )

    frozen_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(frozen.model_dump_json(indent=2), encoding="utf-8")
    return frozen


def verify_split(
    split: str,
    *,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    labels_root: Path = DEFAULT_LABELS_ROOT,
    frozen_dir: Path = DEFAULT_FROZEN_DIR,
) -> VerifyResult:
    frozen_path = _frozen_path(split, frozen_dir)
    if not frozen_path.exists():
        raise FileNotFoundError(
            f"{frozen_path} not found -- run `docflow freeze --split {split}` first"
        )
    frozen = FrozenManifest.model_validate_json(frozen_path.read_text(encoding="utf-8"))

    current_rows = {
        row.doc_id: row for row in load_manifest(manifest_path) if row.split == split
    }

    mismatched: list[str] = []
    missing: list[str] = []
    for doc_id, frozen_hash in frozen.doc_hashes.items():
        row = current_rows.get(doc_id)
        label_path = label_path_for(doc_id, labels_root)
        if row is None or not label_path.exists():
            missing.append(doc_id)
            continue
        if _doc_hash(row, label_path) != frozen_hash:
            mismatched.append(doc_id)

    return VerifyResult(
        split=split,
        checked=len(frozen.doc_hashes),
        mismatched=tuple(sorted(mismatched)),
        missing=tuple(sorted(missing)),
    )


def freeze_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="docflow freeze")
    parser.add_argument("--split", required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    frozen = freeze_split(args.split, manifest_path=args.manifest, force=args.force)
    print(f"froze split={frozen.split!r}: {len(frozen.doc_hashes)} documents")


def verify_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="docflow verify")
    parser.add_argument("--split")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--frozen-dir", type=Path, default=DEFAULT_FROZEN_DIR)
    args = parser.parse_args(argv)

    splits = (
        [args.split] if args.split else sorted(p.stem for p in args.frozen_dir.glob("*.json"))
    )
    if not splits:
        print(f"no frozen splits found in {args.frozen_dir}")
        raise SystemExit(1)

    all_ok = True
    for split in splits:
        result = verify_split(split, manifest_path=args.manifest, frozen_dir=args.frozen_dir)
        status = "OK" if result.ok else "TAMPERED"
        print(f"{split}: {status} ({result.checked} documents checked)")
        if result.mismatched:
            print(f"  mismatched doc_ids: {', '.join(result.mismatched)}")
        if result.missing:
            print(f"  missing doc_ids: {', '.join(result.missing)}")
        all_ok = all_ok and result.ok

    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    verify_main()
