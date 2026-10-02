# SROIE Ingestion, Split Assignment, Freeze/Verify Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pool all 973 labeled SROIE receipts into DocFlow's hard eval set, assign each to `dev_hard`/`test_hard` via a new deterministic seeded-hash split (never SROIE's own train/test folders), and build the freeze/verify tamper-detection machinery needed to protect `test_hard` going forward — then run a `null`-system eval on `dev_hard` only, proving (not just asserting) that `test_hard` is frozen and tamper-evident.

**Architecture:** Three new pure/IO-light modules under `src/docflow/evals/` (`split.py`, extensions to `manifest.py`, `ingest_sroie.py`, `freeze.py`) plus a small extension to the existing `runner.py` to load real labels for a named split instead of the current always-empty stub. All new data (images, labels, manifests, frozen hashes) lives under `data/` and `invoices/`, which are entirely gitignored (`data/*`, `invoices/*` except `.gitkeep`) — only code and tests are committed.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, mypy --strict (covers `src/docflow/evals`), ruff. No new dependencies.

**Spec:** The user's task message (steps 0–5, this session) plus `docs/04_Architecture.md` ADR-009 (frozen, hashed, protected test sets) and `docs/05_Phase_Plan.md` P1-T3/T5/T7.

## Global Constraints

- Money is `Decimal` in code, string in JSON — never `float` (hard rule 3, ADR-008). `CanonicalInvoice.total` already enforces this.
- Never log or print raw field values, OCR text, or file names — only doc_ids, counts, and hashes (hard rule 7). Freeze/verify output must only ever name doc_ids, never label contents.
- Never run a scoring eval against `test_hard` without an explicit ask (hard rule 1, ADR-009). The `--split` eval path must refuse any split name starting with `test` unless `--allow-test` is passed.
- Never commit real documents or bulk data — `data/*` and `invoices/*` are gitignored; only `src/`, `tests/`, and this plan file are committed in this work.
- SROIE's own `train/`/`test/` folders are NOT a held-out split (both ship full ground truth) and must never be treated as or mapped onto `dev_hard`/`test_hard`. Only the new `assign_split(doc_id, seed)` decides that.
- Ignore `data/sroie/SROIE2019/*/box/` entirely — not needed until a later phase.
- Reuse `core/normalize.py`'s `parse_date`/`parse_amount` for all date/amount parsing — do not write new parsing logic (hard rule: keep core pure, single source of truth for normalization).
- `mypy --strict` covers `src/docflow/evals/**` — every new function needs full type hints.
- Cite `TR-EVAL-01/02/03` and `ADR-009` in each commit message.

## Review Focus

- SROIE dates are mixed formats (mostly `DD/MM/YYYY`, some `"15 Sep 2017"` style) — both must normalize correctly, including the genuinely ambiguous numeric case, which `parse_date` resolves day-first and flags (`DATE_AMBIGUOUS_DAY_MONTH`) rather than silently guessing.
- SROIE totals sometimes carry stray currency text (e.g. `"RM9.00"`) — `parse_amount` must still extract the numeric value rather than failing outright.
- SROIE's `train/` and `test/` folders could in principle share a basename (same receipt filed in both) — ingestion must fail loudly on a collision rather than silently letting one copy overwrite the other's image/label under the same `sroie_<id>` doc_id.
- Tamper detection must catch an edit to *either* the label file *or* the manifest row (e.g. someone silently moves a doc from `test_hard` to `dev_hard` by editing `all.jsonl`), not just the label file alone.
- `docflow freeze` must refuse to silently overwrite an already-frozen split — re-freezing `test_hard` after an undetected change would defeat the entire guard — unless `--force` is passed explicitly.

---

## Task 1: Deterministic split assignment (`assign_split`)

**Files:**
- Create: `src/docflow/evals/split.py`
- Test: `tests/unit/evals/test_split.py`

**Interfaces:**
- Produces: `assign_split(doc_id: str, seed: int = DEFAULT_SPLIT_SEED, dev_ratio: float = DEFAULT_DEV_RATIO) -> Literal["dev_hard", "test_hard"]`, `DEFAULT_SPLIT_SEED: int`, `DEFAULT_DEV_RATIO: float` — used by Task 2 (`build_manifest_with_split`) and Task 6 (actual SROIE split run).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for src/docflow/evals/split.py (TR-EVAL-01, ADR-009)."""

from __future__ import annotations

from docflow.evals.split import DEFAULT_DEV_RATIO, assign_split


class TestAssignSplit:
    def test_deterministic_for_same_doc_id_and_seed(self) -> None:
        assert assign_split("sroie_X001", seed=42) == assign_split("sroie_X001", seed=42)

    def test_returns_a_valid_split_name(self) -> None:
        for i in range(50):
            assert assign_split(f"sroie_{i}", seed=42) in ("dev_hard", "test_hard")

    def test_not_every_doc_id_lands_in_the_same_split(self) -> None:
        results = {assign_split(f"sroie_{i}", seed=42) for i in range(50)}
        assert results == {"dev_hard", "test_hard"}

    def test_ratio_is_approximately_dev_ratio_over_many_ids(self) -> None:
        n = 2000
        dev_count = sum(1 for i in range(n) if assign_split(f"doc_{i}", seed=7) == "dev_hard")
        assert abs(dev_count / n - DEFAULT_DEV_RATIO) < 0.05

    def test_different_seed_changes_assignment_for_at_least_one_doc(self) -> None:
        a = [assign_split(f"doc_{i}", seed=1) for i in range(100)]
        b = [assign_split(f"doc_{i}", seed=2) for i in range(100)]
        assert a != b

    def test_sroie_train_test_folder_has_no_bearing_on_split(self) -> None:
        # Same basename, as if seen identically regardless of which SROIE
        # folder it came from -- assign_split only ever sees the doc_id.
        assert assign_split("sroie_X00016469612", seed=42) == assign_split(
            "sroie_X00016469612", seed=42
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/evals/test_split.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docflow.evals.split'`

- [ ] **Step 3: Write the implementation**

```python
"""Deterministic DEV/TEST split assignment (ADR-009, TR-EVAL-01).

A document's split is a pure function of its doc_id and a fixed seed --
never of load order, file system state, or which folder a public dataset
happened to ship it in. This is what makes the assignment reproducible
from the doc_id alone and immune to a dataset's own, unrelated train/test
split (e.g. SROIE's, which is not a held-out split -- both of its folders
ship full ground truth).
"""

from __future__ import annotations

import hashlib
from typing import Literal

Split = Literal["dev_hard", "test_hard"]

DEFAULT_SPLIT_SEED = 20261002
DEFAULT_DEV_RATIO = 0.4


def assign_split(
    doc_id: str,
    seed: int = DEFAULT_SPLIT_SEED,
    dev_ratio: float = DEFAULT_DEV_RATIO,
) -> Split:
    digest = hashlib.sha256(f"{seed}:{doc_id}".encode("utf-8")).hexdigest()
    fraction = int(digest[:8], 16) / 0xFFFFFFFF
    return "dev_hard" if fraction < dev_ratio else "test_hard"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/evals/test_split.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src/docflow/evals/split.py tests/unit/evals/test_split.py && uv run mypy`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/docflow/evals/split.py tests/unit/evals/test_split.py
git commit -m "feat(evals): add deterministic seeded-hash split assignment (TR-EVAL-01, ADR-009)"
```

---

## Task 2: Manifest support for stem-based doc_ids, per-doc split assignment, and merging

**Files:**
- Modify: `src/docflow/evals/manifest.py`
- Test: `tests/unit/evals/test_manifest.py`

**Interfaces:**
- Consumes: `assign_split(doc_id, seed, dev_ratio)`, `DEFAULT_SPLIT_SEED`, `DEFAULT_DEV_RATIO` from `docflow.evals.split` (Task 1).
- Produces: `write_manifest(rows: list[ManifestRow], out_path: Path) -> None`; `build_manifest(..., doc_id_mode: Literal["hash", "stem"] = "hash")` (extended, backward compatible); `build_manifest_with_split(folder, out_path, *, source, seed=DEFAULT_SPLIT_SEED, dev_ratio=DEFAULT_DEV_RATIO, extensions=IMAGE_EXTENSIONS) -> list[ManifestRow]`; `merge_manifests(paths: list[Path], out_path: Path) -> list[ManifestRow]`; `label_path_for(doc_id: str, labels_root: Path = Path("data/labels")) -> Path` — used by Task 3 (ingest), Task 4 (freeze/verify), Task 5 (runner), Task 6/7 (execution).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/evals/test_manifest.py`:

```python
from docflow.evals.manifest import (
    build_manifest_with_split,
    label_path_for,
    merge_manifests,
)


class TestBuildManifestDocIdMode:
    def test_stem_mode_uses_filename_as_doc_id(self, tmp_path: Path) -> None:
        _write(tmp_path / "dev_clean_000.pdf", pdf_with_text("Invoice A"))
        out_path = tmp_path / "out" / "m.jsonl"

        rows = build_manifest(tmp_path, out_path, doc_id_mode="stem")

        assert rows[0].doc_id == "dev_clean_000"

    def test_hash_mode_is_still_the_default(self, tmp_path: Path) -> None:
        data = pdf_with_text("Invoice A")
        _write(tmp_path / "a.pdf", data)
        out_path = tmp_path / "out" / "m.jsonl"

        rows = build_manifest(tmp_path, out_path)

        expected_hash = hashlib.sha256(data).hexdigest()
        assert rows[0].doc_id == f"d_{expected_hash[:12]}"


class TestBuildManifestWithSplit:
    def test_assigns_split_per_doc_from_doc_id(self, tmp_path: Path) -> None:
        for i in range(20):
            _write(tmp_path / f"sroie_{i}.jpg", f"image {i}".encode())
        out_path = tmp_path / "out" / "sroie.jsonl"

        rows = build_manifest_with_split(tmp_path, out_path, source="public", seed=42)

        assert len(rows) == 20
        assert {row.split for row in rows} == {"dev_hard", "test_hard"}
        assert all(row.source == "public" for row in rows)
        assert all(row.pages == 1 for row in rows)

    def test_doc_id_is_file_stem(self, tmp_path: Path) -> None:
        _write(tmp_path / "sroie_X001.jpg", b"image bytes")
        out_path = tmp_path / "out" / "sroie.jsonl"

        rows = build_manifest_with_split(tmp_path, out_path, source="public", seed=42)

        assert rows[0].doc_id == "sroie_X001"

    def test_split_matches_assign_split_directly(self, tmp_path: Path) -> None:
        from docflow.evals.split import assign_split

        _write(tmp_path / "sroie_X001.jpg", b"image bytes")
        out_path = tmp_path / "out" / "sroie.jsonl"

        rows = build_manifest_with_split(tmp_path, out_path, source="public", seed=42)

        assert rows[0].split == assign_split("sroie_X001", seed=42)

    def test_only_matches_requested_extensions(self, tmp_path: Path) -> None:
        _write(tmp_path / "sroie_X001.jpg", b"image bytes")
        _write(tmp_path / "ignore_me.box", b"not an image")
        out_path = tmp_path / "out" / "sroie.jsonl"

        rows = build_manifest_with_split(tmp_path, out_path, source="public", seed=42)

        assert len(rows) == 1


class TestMergeManifests:
    def test_concatenates_and_sorts_by_doc_id(self, tmp_path: Path) -> None:
        a_dir = tmp_path / "a"
        a_dir.mkdir()
        _write(a_dir / "dev_clean_001.pdf", pdf_with_text("A"))
        a_path = tmp_path / "a.jsonl"
        build_manifest(a_dir, a_path, doc_id_mode="stem")

        b_dir = tmp_path / "b"
        b_dir.mkdir()
        _write(b_dir / "sroie_X001.jpg", b"img")
        b_path = tmp_path / "b.jsonl"
        build_manifest_with_split(b_dir, b_path, source="public", seed=42)

        out_path = tmp_path / "all.jsonl"
        merged = merge_manifests([a_path, b_path], out_path)

        assert [row.doc_id for row in merged] == sorted(row.doc_id for row in merged)
        assert len(merged) == 2

    def test_duplicate_doc_id_across_manifests_raises(self, tmp_path: Path) -> None:
        _write(tmp_path / "dev_clean_001.pdf", pdf_with_text("A"))
        a_path = tmp_path / "a.jsonl"
        build_manifest(tmp_path, a_path, doc_id_mode="stem")

        out_path = tmp_path / "all.jsonl"
        with pytest.raises(ValueError):
            merge_manifests([a_path, a_path], out_path)


class TestLabelPathFor:
    def test_sroie_doc_id_maps_to_sroie_labels_dir(self) -> None:
        assert label_path_for("sroie_X00016469612", labels_root=Path("data/labels")) == Path(
            "data/labels/sroie/sroie_X00016469612.json"
        )

    def test_dev_clean_doc_id_maps_to_dev_clean_labels_dir(self) -> None:
        assert label_path_for("dev_clean_000", labels_root=Path("data/labels")) == Path(
            "data/labels/dev_clean/dev_clean_000.json"
        )

    def test_unknown_prefix_raises(self) -> None:
        with pytest.raises(ValueError):
            label_path_for("unknown_123")
```

Add `import pytest` to the top of `tests/unit/evals/test_manifest.py` if not already present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/evals/test_manifest.py -v`
Expected: FAIL with `ImportError` (`build_manifest_with_split`, `merge_manifests`, `label_path_for` don't exist) and `TypeError: build_manifest() got an unexpected keyword argument 'doc_id_mode'`

- [ ] **Step 3: Write the implementation**

Replace the body of `src/docflow/evals/manifest.py` from the imports onward with:

```python
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
    print(f"wrote {len(rows)} rows to {args.out} ({dev_count} dev_hard, {len(rows) - dev_count} test_hard)")


def merge_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="docflow manifest merge")
    parser.add_argument("manifests", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    rows = merge_manifests(args.manifests, args.out)
    print(f"wrote {len(rows)} merged rows to {args.out}")


if __name__ == "__main__":
    main()
```

Note: `write_manifest` is defined before `merge_manifests`/`load_manifest` uses it; `load_manifest` must be defined before `merge_manifests` is called at runtime (Python resolves this fine since both are module-level functions resolved at call time, not definition time) — keep `load_manifest`'s existing position (it can stay where it was, after `build_manifest_with_split`, as shown above).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/evals/test_manifest.py -v`
Expected: PASS, including all pre-existing tests (doc_id hash-mode default unchanged) and the new ones.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src/docflow/evals/manifest.py tests/unit/evals/test_manifest.py && uv run mypy`
Expected: no errors

- [ ] **Step 6: Update the CLI dispatcher**

Edit `src/docflow/cli.py`:

```python
elif command == "manifest":
    if not rest:
        _usage_error()
    subcommand, sub_rest = rest[0], rest[1:]
    if subcommand == "build":
        manifest_tool.main(sub_rest)
    elif subcommand == "build-sroie":
        manifest_tool.build_sroie_main(sub_rest)
    elif subcommand == "merge":
        manifest_tool.merge_main(sub_rest)
    else:
        _usage_error()
```

Update `_USAGE` to mention `manifest build-sroie <folder> --out M [--seed N]` and `manifest merge <m1> <m2>... --out M`.

- [ ] **Step 7: Run the full test suite and commit**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: PASS

```bash
git add src/docflow/evals/manifest.py src/docflow/cli.py tests/unit/evals/test_manifest.py
git commit -m "feat(evals): add stem doc_ids, per-doc split assignment, and manifest merge (TR-EVAL-01, ADR-009)"
```

---

## Task 3: SROIE ingestion (`ingest_sroie.py`)

**Files:**
- Create: `src/docflow/evals/ingest_sroie.py`
- Modify: `src/docflow/cli.py`
- Test: `tests/unit/evals/test_ingest_sroie.py`

**Interfaces:**
- Consumes: `normalize_text`, `parse_date`, `parse_amount` from `docflow.core.normalize`; `CanonicalInvoice`, `LabelRecord` from `docflow.core.schemas`.
- Produces: `IngestReport` (dataclass: `doc_ids: tuple[str, ...]`, `parse_failures: int`, `total` and `parse_failure_rate` properties); `ingest(train_dir, test_dir, *, images_out=DEFAULT_IMAGES_OUT, labels_out=DEFAULT_LABELS_OUT) -> IngestReport` — used by Task 6 (the real 973-doc run) and indirectly by Task 4/5/7/8 which read the label/image files it writes.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for src/docflow/evals/ingest_sroie.py (TR-EVAL-01, TR-EVAL-02, ADR-009).

SROIE's own train/ and test/ folders are NOT a held-out split (both ship
full ground truth) -- this module only pools and normalizes; DocFlow's own
assign_split (Task 1/2) is what decides dev_hard vs test_hard, downstream.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docflow.core.schemas import LabelRecord
from docflow.evals.ingest_sroie import ingest


def _write_receipt(root: Path, basename: str, *, company: str, date: str, total: str) -> None:
    (root / "img").mkdir(parents=True, exist_ok=True)
    (root / "entities").mkdir(parents=True, exist_ok=True)
    (root / "img" / f"{basename}.jpg").write_bytes(f"fake image {basename}".encode())
    entities = {"company": company, "date": date, "address": "123 Fake St", "total": total}
    (root / "entities" / f"{basename}.txt").write_text(json.dumps(entities), encoding="utf-8")


class TestIngest:
    def test_pools_receipts_from_both_train_and_test(self, tmp_path: Path) -> None:
        train_dir, test_dir = tmp_path / "train", tmp_path / "test"
        _write_receipt(train_dir, "T001", company="Acme", date="25/12/2018", total="9.00")
        _write_receipt(test_dir, "X001", company="Beta", date="25/12/2018", total="10.00")

        report = ingest(
            train_dir,
            test_dir,
            images_out=tmp_path / "out_img",
            labels_out=tmp_path / "out_labels",
        )

        assert sorted(report.doc_ids) == ["sroie_T001", "sroie_X001"]
        assert report.total == 2

    def test_copies_image_under_sroie_prefixed_doc_id(self, tmp_path: Path) -> None:
        train_dir, test_dir = tmp_path / "train", tmp_path / "test"
        _write_receipt(train_dir, "T001", company="Acme", date="25/12/2018", total="9.00")
        (test_dir / "img").mkdir(parents=True)
        (test_dir / "entities").mkdir(parents=True)
        images_out = tmp_path / "out_img"

        ingest(train_dir, test_dir, images_out=images_out, labels_out=tmp_path / "out_labels")

        assert (images_out / "sroie_T001.jpg").read_bytes() == b"fake image T001"

    def test_writes_label_record_mapped_through_normalize(self, tmp_path: Path) -> None:
        train_dir, test_dir = tmp_path / "train", tmp_path / "test"
        _write_receipt(
            train_dir, "T001", company="BOOK TA .K (TAMAN DAYA)", date="25/12/2018", total="9.00"
        )
        (test_dir / "img").mkdir(parents=True)
        (test_dir / "entities").mkdir(parents=True)
        labels_out = tmp_path / "out_labels"

        ingest(train_dir, test_dir, images_out=tmp_path / "out_img", labels_out=labels_out)

        record = LabelRecord.model_validate_json(
            (labels_out / "sroie_T001.json").read_text(encoding="utf-8")
        )
        assert record.doc_id == "sroie_T001"
        assert record.label_source == "dataset"
        assert record.labeled_fields == ["vendor_name", "invoice_date", "total"]
        assert record.values.vendor_name == "BOOK TA .K (TAMAN DAYA)"
        assert str(record.values.invoice_date) == "2018-12-25"
        assert record.values.total == pytest.approx(9.00)  # type: ignore[comparison-overlap]

    def test_drops_address_field(self, tmp_path: Path) -> None:
        train_dir, test_dir = tmp_path / "train", tmp_path / "test"
        _write_receipt(train_dir, "T001", company="Acme", date="25/12/2018", total="9.00")
        (test_dir / "img").mkdir(parents=True)
        (test_dir / "entities").mkdir(parents=True)
        labels_out = tmp_path / "out_labels"

        ingest(train_dir, test_dir, images_out=tmp_path / "out_img", labels_out=labels_out)

        raw = json.loads((labels_out / "sroie_T001.json").read_text(encoding="utf-8"))
        assert "address" not in json.dumps(raw)

    def test_day_month_name_date_format_parses(self, tmp_path: Path) -> None:
        train_dir, test_dir = tmp_path / "train", tmp_path / "test"
        _write_receipt(train_dir, "T001", company="Acme", date="15 Sep 2017", total="9.00")
        (test_dir / "img").mkdir(parents=True)
        (test_dir / "entities").mkdir(parents=True)
        labels_out = tmp_path / "out_labels"

        ingest(train_dir, test_dir, images_out=tmp_path / "out_img", labels_out=labels_out)

        record = LabelRecord.model_validate_json(
            (labels_out / "sroie_T001.json").read_text(encoding="utf-8")
        )
        assert str(record.values.invoice_date) == "2017-09-15"

    def test_total_with_stray_currency_text_parses(self, tmp_path: Path) -> None:
        train_dir, test_dir = tmp_path / "train", tmp_path / "test"
        _write_receipt(train_dir, "T001", company="Acme", date="25/12/2018", total="RM9.00")
        (test_dir / "img").mkdir(parents=True)
        (test_dir / "entities").mkdir(parents=True)
        labels_out = tmp_path / "out_labels"

        ingest(train_dir, test_dir, images_out=tmp_path / "out_img", labels_out=labels_out)

        record = LabelRecord.model_validate_json(
            (labels_out / "sroie_T001.json").read_text(encoding="utf-8")
        )
        assert record.values.total == pytest.approx(9.00)  # type: ignore[comparison-overlap]

    def test_unparseable_date_counts_as_parse_failure_but_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        train_dir, test_dir = tmp_path / "train", tmp_path / "test"
        _write_receipt(train_dir, "T001", company="Acme", date="not-a-date", total="9.00")
        (test_dir / "img").mkdir(parents=True)
        (test_dir / "entities").mkdir(parents=True)

        report = ingest(
            train_dir, test_dir, images_out=tmp_path / "out_img", labels_out=tmp_path / "out_labels"
        )

        assert report.parse_failures == 1
        assert report.total == 1

    def test_duplicate_basename_across_train_and_test_raises(self, tmp_path: Path) -> None:
        train_dir, test_dir = tmp_path / "train", tmp_path / "test"
        _write_receipt(train_dir, "X001", company="Acme", date="25/12/2018", total="9.00")
        _write_receipt(test_dir, "X001", company="Other", date="01/01/2019", total="5.00")

        with pytest.raises(ValueError, match="duplicate SROIE basename"):
            ingest(
                train_dir, test_dir, images_out=tmp_path / "out_img", labels_out=tmp_path / "out_labels"
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/evals/test_ingest_sroie.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docflow.evals.ingest_sroie'`

- [ ] **Step 3: Write the implementation**

```python
"""SROIE receipt ingestion into DocFlow's labeled hard set (TR-EVAL-01,
TR-EVAL-02, ADR-009).

Pools all labeled receipts from SROIE2019's train/ and test/ folders into
one set. SROIE's own train/test split is NOT a held-out split -- both
folders ship full ground truth (confirmed by inspection) -- so it must
never be mapped onto DocFlow's own dev_hard/test_hard split. Only
`docflow.evals.split.assign_split`, applied downstream of this module to
the doc_ids it produces, decides that.
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from docflow.core.normalize import normalize_text, parse_amount, parse_date
from docflow.core.schemas import CanonicalInvoice, LabelRecord

LABELED_FIELDS = ("vendor_name", "invoice_date", "total")

DEFAULT_TRAIN_DIR = Path("data/sroie/SROIE2019/train")
DEFAULT_TEST_DIR = Path("data/sroie/SROIE2019/test")
DEFAULT_IMAGES_OUT = Path("invoices/sroie")
DEFAULT_LABELS_OUT = Path("data/labels/sroie")


@dataclass(frozen=True)
class IngestReport:
    doc_ids: tuple[str, ...]
    parse_failures: int

    @property
    def total(self) -> int:
        return len(self.doc_ids)

    @property
    def parse_failure_rate(self) -> float:
        return self.parse_failures / self.total if self.total else 0.0


def _find_pairs(source_dir: Path) -> list[tuple[Path, Path]]:
    img_dir = source_dir / "img"
    entities_dir = source_dir / "entities"
    pairs: list[tuple[Path, Path]] = []
    for img_path in sorted(img_dir.glob("*.jpg")):
        entities_path = entities_dir / f"{img_path.stem}.txt"
        if not entities_path.exists():
            raise FileNotFoundError(f"no entities file for {img_path}")
        pairs.append((img_path, entities_path))
    return pairs


def _map_entity(raw: dict[str, str]) -> tuple[CanonicalInvoice, bool]:
    vendor_name = normalize_text(raw.get("company"))
    date_result = parse_date(raw.get("date"))
    amount_result = parse_amount(raw.get("total"))

    flags = [f"invoice_date:{flag}" for flag in date_result.flags]
    flags += [f"total:{flag}" for flag in amount_result.flags]

    parse_failed = date_result.value is None or amount_result.value is None

    invoice = CanonicalInvoice(
        vendor_name=vendor_name,
        invoice_date=date_result.value,
        total=amount_result.value,
        flags=flags,
    )
    return invoice, parse_failed


def ingest(
    train_dir: Path = DEFAULT_TRAIN_DIR,
    test_dir: Path = DEFAULT_TEST_DIR,
    *,
    images_out: Path = DEFAULT_IMAGES_OUT,
    labels_out: Path = DEFAULT_LABELS_OUT,
) -> IngestReport:
    pairs = _find_pairs(train_dir) + _find_pairs(test_dir)

    seen_basenames: dict[str, Path] = {}
    for img_path, _ in pairs:
        if img_path.stem in seen_basenames:
            raise ValueError(
                f"duplicate SROIE basename {img_path.stem!r} in both "
                f"{seen_basenames[img_path.stem]} and {img_path}"
            )
        seen_basenames[img_path.stem] = img_path

    images_out.mkdir(parents=True, exist_ok=True)
    labels_out.mkdir(parents=True, exist_ok=True)

    doc_ids: list[str] = []
    parse_failures = 0
    for img_path, entities_path in pairs:
        doc_id = f"sroie_{img_path.stem}"
        raw = json.loads(entities_path.read_text(encoding="utf-8"))
        invoice, parse_failed = _map_entity(raw)
        if parse_failed:
            parse_failures += 1

        record = LabelRecord(
            doc_id=doc_id,
            label_source="dataset",
            labeled_fields=list(LABELED_FIELDS),
            values=invoice,
        )
        (labels_out / f"{doc_id}.json").write_text(record.model_dump_json(), encoding="utf-8")
        shutil.copy2(img_path, images_out / f"{doc_id}.jpg")
        doc_ids.append(doc_id)

    return IngestReport(doc_ids=tuple(doc_ids), parse_failures=parse_failures)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="docflow sroie ingest")
    parser.add_argument("--train-dir", type=Path, default=DEFAULT_TRAIN_DIR)
    parser.add_argument("--test-dir", type=Path, default=DEFAULT_TEST_DIR)
    parser.add_argument("--images-out", type=Path, default=DEFAULT_IMAGES_OUT)
    parser.add_argument("--labels-out", type=Path, default=DEFAULT_LABELS_OUT)
    args = parser.parse_args(argv)

    report = ingest(
        args.train_dir, args.test_dir, images_out=args.images_out, labels_out=args.labels_out
    )
    print(f"ingested {report.total} documents")
    print(
        f"parse failures (date or total -> None after normalization): "
        f"{report.parse_failures} ({report.parse_failure_rate:.1%})"
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/evals/test_ingest_sroie.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src/docflow/evals/ingest_sroie.py tests/unit/evals/test_ingest_sroie.py && uv run mypy`
Expected: no errors

- [ ] **Step 6: Wire the CLI dispatcher**

Edit `src/docflow/cli.py` to add:

```python
from docflow.evals import ingest_sroie as ingest_sroie_tool
```

```python
elif command == "sroie":
    if not rest or rest[0] != "ingest":
        _usage_error()
    ingest_sroie_tool.main(rest[1:])
```

Update `_USAGE` to mention `sroie ingest [--train-dir D] [--test-dir D] [--images-out D] [--labels-out D]`.

- [ ] **Step 7: Run the full test suite and commit**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: PASS

```bash
git add src/docflow/evals/ingest_sroie.py src/docflow/cli.py tests/unit/evals/test_ingest_sroie.py
git commit -m "feat(evals): ingest SROIE receipts into the labeled hard set (TR-EVAL-01, TR-EVAL-02, ADR-009)"
```

---

## Task 4: Freeze and verify (`freeze.py`)

**Files:**
- Create: `src/docflow/evals/freeze.py`
- Modify: `src/docflow/cli.py`
- Test: `tests/unit/evals/test_freeze.py`

**Interfaces:**
- Consumes: `ManifestRow`, `load_manifest`, `label_path_for` from `docflow.evals.manifest` (Task 2).
- Produces: `FrozenManifest` (pydantic model: `split`, `frozen_at`, `doc_hashes: dict[str, str]`); `freeze_split(split, *, manifest_path, labels_root, frozen_dir, frozen_at=None, force=False) -> FrozenManifest`; `VerifyResult` (NamedTuple: `split`, `checked`, `mismatched: tuple[str, ...]`, `missing: tuple[str, ...]`, `ok` property); `verify_split(split, *, manifest_path, labels_root, frozen_dir) -> VerifyResult` — used by Task 8 (the real freeze/verify/tamper-detection proof run).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for src/docflow/evals/freeze.py (ADR-009).

Freezing pins a sha256 hash per document covering both its manifest row
and its label file, so an edit to either -- including silently moving a
document between splits by editing the manifest -- is detectable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docflow.evals.freeze import freeze_split, verify_split
from docflow.evals.manifest import ManifestRow, write_manifest


def _write_label(labels_root: Path, dataset: str, doc_id: str, total: str = "9.00") -> None:
    (labels_root / dataset).mkdir(parents=True, exist_ok=True)
    record = {
        "doc_id": doc_id,
        "label_source": "dataset",
        "labeled_fields": ["total"],
        "values": {"total": total},
    }
    (labels_root / dataset / f"{doc_id}.json").write_text(json.dumps(record), encoding="utf-8")


def _manifest_row(doc_id: str, split: str) -> ManifestRow:
    return ManifestRow(
        doc_id=doc_id,
        path=f"invoices/sroie/{doc_id}.jpg",
        sha256="a" * 64,
        pages=1,
        source="public",
        split=split,
    )


class TestFreezeSplit:
    def test_freezes_only_rows_in_the_requested_split(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "all.jsonl"
        write_manifest(
            [_manifest_row("sroie_A", "test_hard"), _manifest_row("sroie_B", "dev_hard")],
            manifest_path,
        )
        labels_root = tmp_path / "labels"
        _write_label(labels_root, "sroie", "sroie_A")
        _write_label(labels_root, "sroie", "sroie_B")
        frozen_dir = tmp_path / "frozen"

        frozen = freeze_split(
            "test_hard", manifest_path=manifest_path, labels_root=labels_root, frozen_dir=frozen_dir
        )

        assert set(frozen.doc_hashes) == {"sroie_A"}

    def test_raises_on_no_matching_rows(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "all.jsonl"
        write_manifest([_manifest_row("sroie_B", "dev_hard")], manifest_path)

        with pytest.raises(ValueError):
            freeze_split(
                "test_hard",
                manifest_path=manifest_path,
                labels_root=tmp_path / "labels",
                frozen_dir=tmp_path / "frozen",
            )

    def test_refuses_to_overwrite_without_force(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "all.jsonl"
        write_manifest([_manifest_row("sroie_A", "test_hard")], manifest_path)
        labels_root = tmp_path / "labels"
        _write_label(labels_root, "sroie", "sroie_A")
        frozen_dir = tmp_path / "frozen"
        freeze_split(
            "test_hard", manifest_path=manifest_path, labels_root=labels_root, frozen_dir=frozen_dir
        )

        with pytest.raises(FileExistsError):
            freeze_split(
                "test_hard",
                manifest_path=manifest_path,
                labels_root=labels_root,
                frozen_dir=frozen_dir,
            )

    def test_force_allows_overwrite(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "all.jsonl"
        write_manifest([_manifest_row("sroie_A", "test_hard")], manifest_path)
        labels_root = tmp_path / "labels"
        _write_label(labels_root, "sroie", "sroie_A")
        frozen_dir = tmp_path / "frozen"
        freeze_split(
            "test_hard", manifest_path=manifest_path, labels_root=labels_root, frozen_dir=frozen_dir
        )

        frozen = freeze_split(
            "test_hard",
            manifest_path=manifest_path,
            labels_root=labels_root,
            frozen_dir=frozen_dir,
            force=True,
        )
        assert set(frozen.doc_hashes) == {"sroie_A"}


class TestVerifySplit:
    def _freeze(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        manifest_path = tmp_path / "all.jsonl"
        write_manifest([_manifest_row("sroie_A", "test_hard")], manifest_path)
        labels_root = tmp_path / "labels"
        _write_label(labels_root, "sroie", "sroie_A")
        frozen_dir = tmp_path / "frozen"
        freeze_split(
            "test_hard", manifest_path=manifest_path, labels_root=labels_root, frozen_dir=frozen_dir
        )
        return manifest_path, labels_root, frozen_dir

    def test_clean_state_verifies_ok(self, tmp_path: Path) -> None:
        manifest_path, labels_root, frozen_dir = self._freeze(tmp_path)

        result = verify_split(
            "test_hard", manifest_path=manifest_path, labels_root=labels_root, frozen_dir=frozen_dir
        )

        assert result.ok
        assert result.checked == 1
        assert result.mismatched == ()
        assert result.missing == ()

    def test_editing_the_label_file_is_detected(self, tmp_path: Path) -> None:
        manifest_path, labels_root, frozen_dir = self._freeze(tmp_path)
        _write_label(labels_root, "sroie", "sroie_A", total="999.00")

        result = verify_split(
            "test_hard", manifest_path=manifest_path, labels_root=labels_root, frozen_dir=frozen_dir
        )

        assert not result.ok
        assert result.mismatched == ("sroie_A",)

    def test_editing_the_manifest_row_is_detected(self, tmp_path: Path) -> None:
        manifest_path, labels_root, frozen_dir = self._freeze(tmp_path)
        # Simulate silently moving the doc to a different split by editing the manifest.
        write_manifest([_manifest_row("sroie_A", "dev_hard")], manifest_path)

        current_rows_in_test_hard = [
            row for row in __import__("docflow.evals.manifest", fromlist=["load_manifest"])
            .load_manifest(manifest_path)
            if row.split == "test_hard"
        ]
        assert current_rows_in_test_hard == []
        result = verify_split(
            "test_hard", manifest_path=manifest_path, labels_root=labels_root, frozen_dir=frozen_dir
        )
        assert not result.ok
        assert result.missing == ("sroie_A",)

    def test_missing_label_file_is_detected(self, tmp_path: Path) -> None:
        manifest_path, labels_root, frozen_dir = self._freeze(tmp_path)
        (labels_root / "sroie" / "sroie_A.json").unlink()

        result = verify_split(
            "test_hard", manifest_path=manifest_path, labels_root=labels_root, frozen_dir=frozen_dir
        )

        assert not result.ok
        assert result.missing == ("sroie_A",)

    def test_raises_if_never_frozen(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "all.jsonl"
        write_manifest([_manifest_row("sroie_A", "test_hard")], manifest_path)

        with pytest.raises(FileNotFoundError):
            verify_split(
                "test_hard",
                manifest_path=manifest_path,
                labels_root=tmp_path / "labels",
                frozen_dir=tmp_path / "frozen",
            )
```

Simplify `test_editing_the_manifest_row_is_detected`'s awkward dynamic import — use a normal import at the top of the file instead:

```python
from docflow.evals.manifest import ManifestRow, load_manifest, write_manifest
```

and replace the body with:

```python
    def test_editing_the_manifest_row_is_detected(self, tmp_path: Path) -> None:
        manifest_path, labels_root, frozen_dir = self._freeze(tmp_path)
        write_manifest([_manifest_row("sroie_A", "dev_hard")], manifest_path)

        assert [row for row in load_manifest(manifest_path) if row.split == "test_hard"] == []
        result = verify_split(
            "test_hard", manifest_path=manifest_path, labels_root=labels_root, frozen_dir=frozen_dir
        )
        assert not result.ok
        assert result.missing == ("sroie_A",)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/evals/test_freeze.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docflow.evals.freeze'`

- [ ] **Step 3: Write the implementation**

```python
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
```

This requires adding `DEFAULT_LABELS_ROOT` to the imports from `docflow.evals.manifest` (already defined there in Task 2).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/evals/test_freeze.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src/docflow/evals/freeze.py tests/unit/evals/test_freeze.py && uv run mypy`
Expected: no errors

- [ ] **Step 6: Wire the CLI dispatcher**

Edit `src/docflow/cli.py`:

```python
from docflow.evals import freeze as freeze_tool
```

```python
elif command == "freeze":
    freeze_tool.freeze_main(rest)
elif command == "verify":
    freeze_tool.verify_main(rest)
```

Update `_USAGE` to mention `freeze --split S [--manifest M] [--force]` and `verify [--split S] [--manifest M]`.

- [ ] **Step 7: Run the full test suite and commit**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: PASS

```bash
git add src/docflow/evals/freeze.py src/docflow/cli.py tests/unit/evals/test_freeze.py
git commit -m "feat(evals): add freeze/verify tamper detection for protected splits (ADR-009)"
```

---

## Task 5: Label-aware, split-based eval runner with a TEST guard

**Files:**
- Modify: `src/docflow/evals/runner.py`
- Test: `tests/unit/evals/test_runner.py`

**Interfaces:**
- Consumes: `label_path_for` from `docflow.evals.manifest` (Task 2); `LabelRecord` from `docflow.core.schemas`.
- Produces: `run_eval_split(split, system, *, manifest_path=DEFAULT_ALL_MANIFEST, allow_test=False) -> EvalSummary` — used by Task 9 (the real `dev_hard` eval run). `run_eval` (existing, unchanged behavior) is kept for the pilot/smoke-test path.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/evals/test_runner.py`:

```python
from docflow.core.schemas import CanonicalInvoice, LabelRecord
from docflow.evals.manifest import ManifestRow, write_manifest
from docflow.evals.runner import run_eval_split


def _write_label(labels_root: Path, dataset: str, doc_id: str, **values: str) -> None:
    (labels_root / dataset).mkdir(parents=True, exist_ok=True)
    record = LabelRecord(
        doc_id=doc_id,
        label_source="dataset",
        labeled_fields=list(values),
        values=CanonicalInvoice(**values),
    )
    (labels_root / dataset / f"{doc_id}.json").write_text(
        record.model_dump_json(), encoding="utf-8"
    )


class TestRunEvalSplit:
    def test_scores_only_rows_in_the_requested_split(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        write_manifest(
            [
                ManifestRow(
                    doc_id="sroie_A",
                    path="x",
                    sha256="a" * 64,
                    pages=1,
                    source="public",
                    split="dev_hard",
                ),
                ManifestRow(
                    doc_id="sroie_B",
                    path="x",
                    sha256="b" * 64,
                    pages=1,
                    source="public",
                    split="test_hard",
                ),
            ],
            Path("data/manifests/all.jsonl"),
        )
        _write_label(Path("data/labels"), "sroie", "sroie_A", vendor_name="Acme")

        summary = run_eval_split("dev_hard", "null", manifest_path=Path("data/manifests/all.jsonl"))

        assert summary.n_documents == 1

    def test_refuses_test_split_without_allow_test(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        write_manifest(
            [
                ManifestRow(
                    doc_id="sroie_B",
                    path="x",
                    sha256="b" * 64,
                    pages=1,
                    source="public",
                    split="test_hard",
                )
            ],
            Path("data/manifests/all.jsonl"),
        )
        _write_label(Path("data/labels"), "sroie", "sroie_B", vendor_name="Acme")

        with pytest.raises(PermissionError):
            run_eval_split("test_hard", "null", manifest_path=Path("data/manifests/all.jsonl"))

    def test_allow_test_permits_test_split(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        write_manifest(
            [
                ManifestRow(
                    doc_id="sroie_B",
                    path="x",
                    sha256="b" * 64,
                    pages=1,
                    source="public",
                    split="test_hard",
                )
            ],
            Path("data/manifests/all.jsonl"),
        )
        _write_label(Path("data/labels"), "sroie", "sroie_B", vendor_name="Acme")

        summary = run_eval_split(
            "test_hard", "null", manifest_path=Path("data/manifests/all.jsonl"), allow_test=True
        )
        assert summary.n_documents == 1

    def test_raises_on_empty_split(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        write_manifest([], Path("data/manifests/all.jsonl"))

        with pytest.raises(ValueError):
            run_eval_split("dev_hard", "null", manifest_path=Path("data/manifests/all.jsonl"))
```

Add `import pytest` at the top of `tests/unit/evals/test_runner.py` if not already present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/evals/test_runner.py -v`
Expected: FAIL with `ImportError: cannot import name 'run_eval_split'`

- [ ] **Step 3: Write the implementation**

Replace `src/docflow/evals/runner.py` with:

```python
"""Eval runner (TR-EVAL-01, TR-EVAL-05, TR-EVAL-06).

`run_eval` is the original manifest -> predictor -> metrics smoke test: it
scores against an always-empty gold `CanonicalInvoice()` and exists only to
prove the plumbing works on an unlabeled manifest (e.g. the pilot set).

`run_eval_split` is the real path: it loads a named split from a manifest
(default `data/manifests/all.jsonl`), loads each document's actual label
file via `docflow.evals.manifest.label_path_for`, and scores only the
fields that document's label record says were labeled. Any split whose
name starts with "test" is refused unless `allow_test=True` is passed
explicitly (ADR-009, hard rule: never score TEST without an explicit ask).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from docflow.core.schemas import CanonicalInvoice, LabelRecord
from docflow.evals.manifest import ManifestRow, label_path_for, load_manifest
from docflow.evals.metrics import EvalSummary, FieldCounts, header_field_counts, summarize

Predictor = Callable[[ManifestRow], CanonicalInvoice]

DEFAULT_ALL_MANIFEST = Path("data/manifests/all.jsonl")


def null_predictor(row: ManifestRow) -> CanonicalInvoice:
    return CanonicalInvoice()


_SYSTEMS: dict[str, Predictor] = {"null": null_predictor}


def run_eval(manifest_path: Path, system: str) -> EvalSummary:
    if system not in _SYSTEMS:
        raise ValueError(f"unknown system: {system!r} (available: {sorted(_SYSTEMS)})")
    predictor = _SYSTEMS[system]
    rows = load_manifest(manifest_path)

    per_doc_counts: list[FieldCounts] = []
    for row in rows:
        gold = CanonicalInvoice()  # unlabeled smoke-test path: stub gold
        pred = predictor(row)
        per_doc_counts.append(header_field_counts(gold, pred, labeled_fields=[]))

    if not per_doc_counts:
        return EvalSummary(
            n_documents=0,
            header_precision=0.0,
            header_recall=0.0,
            header_f1=0.0,
            header_f1_ci=(0.0, 0.0),
        )

    return summarize(per_doc_counts)


def _load_gold(doc_id: str) -> tuple[CanonicalInvoice, list[str]]:
    label_path = label_path_for(doc_id)
    record = LabelRecord.model_validate_json(label_path.read_text(encoding="utf-8"))
    return record.values, record.labeled_fields


def run_eval_split(
    split: str,
    system: str,
    *,
    manifest_path: Path = DEFAULT_ALL_MANIFEST,
    allow_test: bool = False,
) -> EvalSummary:
    if split.startswith("test") and not allow_test:
        raise PermissionError(
            f"split {split!r} looks like a TEST split; pass allow_test=True "
            f"(CLI: --allow-test) only for an explicitly requested milestone run (ADR-009)"
        )
    if system not in _SYSTEMS:
        raise ValueError(f"unknown system: {system!r} (available: {sorted(_SYSTEMS)})")
    predictor = _SYSTEMS[system]

    rows = [row for row in load_manifest(manifest_path) if row.split == split]
    if not rows:
        raise ValueError(f"no rows with split={split!r} in {manifest_path}")

    per_doc_counts: list[FieldCounts] = []
    for row in rows:
        gold, labeled_fields = _load_gold(row.doc_id)
        pred = predictor(row)
        per_doc_counts.append(header_field_counts(gold, pred, labeled_fields=labeled_fields))

    return summarize(per_doc_counts)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="docflow eval run")
    parser.add_argument("--system", required=True, choices=sorted(_SYSTEMS))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--split")
    parser.add_argument("--allow-test", action="store_true")
    args = parser.parse_args(argv)

    if args.split:
        manifest_path = args.manifest or DEFAULT_ALL_MANIFEST
        summary = run_eval_split(
            args.split, args.system, manifest_path=manifest_path, allow_test=args.allow_test
        )
    else:
        if not args.manifest:
            parser.error("--manifest is required when --split is not given")
        summary = run_eval(args.manifest, args.system)

    print(f"n_documents: {summary.n_documents}")
    print(f"header_precision: {summary.header_precision}")
    print(f"header_recall: {summary.header_recall}")
    print(f"header_f1: {summary.header_f1} (95% CI {summary.header_f1_ci})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/evals/test_runner.py -v`
Expected: PASS, including the pre-existing `run_eval` tests (unchanged behavior).

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src/docflow/evals/runner.py tests/unit/evals/test_runner.py && uv run mypy`
Expected: no errors

- [ ] **Step 6: Update `_USAGE` in `src/docflow/cli.py`**

Mention `eval run --system S (--manifest M | --split NAME [--allow-test])`.

- [ ] **Step 7: Run the full test suite and commit**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: PASS

```bash
git add src/docflow/evals/runner.py src/docflow/cli.py tests/unit/evals/test_runner.py
git commit -m "feat(evals): load real labels for a named split with a TEST guard (TR-EVAL-01, TR-EVAL-06, ADR-009)"
```

---

## Task 6: Run SROIE ingestion for real — CHECKPOINT on parse-failure rate

**Files:** none (execution only; produces gitignored data under `invoices/sroie/` and `data/labels/sroie/`).

- [ ] **Step 1: Delete the stray LayoutLM checkpoint if present**

Run: `test -d data/sroie/SROIE2019/layoutlm-base-uncased && rm -rf data/sroie/SROIE2019/layoutlm-base-uncased || echo "not present, nothing to delete"`

Confirmed during planning recon that this directory does not currently exist anywhere in the repo — this step is expected to print "not present, nothing to delete". Also run `grep -rn "layoutlm" --include="*.py" --include="*.md" .` to confirm nothing references it; expect no output.

- [ ] **Step 2: Run the real ingestion**

Run: `uv run docflow sroie ingest`

This reads all 973 receipts from `data/sroie/SROIE2019/train/` and `.../test/`, writes labels to `data/labels/sroie/*.json`, and copies images to `invoices/sroie/*.jpg`. Paste the actual printed output (document count, parse-failure count and percentage).

- [ ] **Step 3: Checkpoint — evaluate the parse-failure rate**

If the printed parse-failure percentage is above ~5–10%, STOP here and report the exact count/percentage to the user before proceeding to Task 7; do not build the split/freeze on top of an unreviewed failure rate. If at or below that range, continue.

- [ ] **Step 4: Sanity-check the output on disk**

Run: `ls data/labels/sroie | wc -l` and `ls invoices/sroie | wc -l` — both expected to print `973`.

No commit: `data/`, `invoices/` are gitignored. Nothing to add.

---

## Task 7: Build per-dataset manifests and merge into `data/manifests/all.jsonl`

**Files:** none (execution only; produces gitignored manifests under `data/manifests/`).

- [ ] **Step 1: Build the dev_clean manifest**

Run: `uv run docflow manifest build invoices/dev_clean --out data/manifests/dev_clean.jsonl --source synthetic --split dev_clean --doc-id-mode stem`

Paste the output (`wrote 40 rows to ...`). Confirm doc_ids match label files: `uv run python -c "from docflow.evals.manifest import load_manifest; from pathlib import Path; rows = load_manifest(Path('data/manifests/dev_clean.jsonl')); missing = [r.doc_id for r in rows if not Path(f'data/labels/dev_clean/{r.doc_id}.json').exists()]; print('missing labels:', missing)"` — expect `missing labels: []`.

- [ ] **Step 2: Build the SROIE manifest with DocFlow's own seeded split**

Run: `uv run docflow manifest build-sroie invoices/sroie --out data/manifests/sroie.jsonl`

Paste the output (`wrote 973 rows to ... (N dev_hard, M test_hard)`), and confirm `N + M == 973` and the ratio is close to the intended ~40/60.

- [ ] **Step 3: Merge into `all.jsonl`**

Run: `uv run docflow manifest merge data/manifests/dev_clean.jsonl data/manifests/sroie.jsonl --out data/manifests/all.jsonl`

Paste the output (`wrote 1013 merged rows to ...`). Confirm the split counts: `uv run python -c "from docflow.evals.manifest import load_manifest; from pathlib import Path; from collections import Counter; rows = load_manifest(Path('data/manifests/all.jsonl')); print(Counter(r.split for r in rows))"` — expect `dev_clean: 40`, `dev_hard: <N>`, `test_hard: <M>`, totaling 1013.

No commit: `data/manifests/` is gitignored. Nothing to add.

---

## Task 8: Freeze `test_hard`, prove `verify` catches tampering, revert

**Files:** none (execution only; produces a gitignored frozen-hash file under `data/manifests/frozen/`).

- [ ] **Step 1: Freeze `test_hard`**

Run: `uv run docflow freeze --split test_hard`

Paste the output (`froze split='test_hard': M documents`).

- [ ] **Step 2: Verify immediately — expect a clean pass**

Run: `uv run docflow verify --split test_hard`

Paste the exact output. Expected: `test_hard: OK (M documents checked)` and exit code 0.

- [ ] **Step 3: Make one throwaway edit to a `test_hard` label file**

Pick one doc_id that `data/manifests/sroie.jsonl` assigned to `test_hard` (e.g. by grepping `test_hard` in that file). Back up its label file content first, then edit one field (e.g. change the `total` string value) in `data/labels/sroie/<doc_id>.json`.

- [ ] **Step 4: Verify again — expect it to catch the tamper**

Run: `uv run docflow verify --split test_hard`

Paste the exact output. Expected: `test_hard: TAMPERED (M documents checked)`, `mismatched doc_ids: <that one doc_id>`, and a non-zero exit code (confirm with `echo $?` on the following line, expected `1`). This is the proof the guard actually works, not just that it exists.

- [ ] **Step 5: Revert the throwaway edit**

Restore the label file to its original content (from the backup made in Step 3). Re-run `uv run docflow verify --split test_hard` once more and paste the output — expected back to `OK`.

No commit: `data/manifests/frozen/` and `data/labels/` are gitignored. Nothing to add.

---

## Task 9: Run the `null` system on `dev_hard` only

**Files:** none (execution only).

- [ ] **Step 1: Run the eval**

Run: `uv run docflow eval run --system null --split dev_hard`

Paste the exact output (`n_documents`, `header_precision`, `header_recall`, `header_f1` with its 95% CI). Per TR-EVAL-07, if `n_documents` is small, state the one-sided error-rate upper bound alongside the point estimate (`error_upper_bound` in `docflow.evals.metrics`, already implemented — call it, e.g., `uv run python -c "from docflow.evals.metrics import error_upper_bound; print(error_upper_bound(errors=0, n=<dev_hard count>))"` if the null system's score is 0 TP as expected, since it predicts nothing).

- [ ] **Step 2: Confirm no `test_hard` scoring run happened**

State explicitly in the summary to the user that no `docflow eval run ... --split test_hard` was executed beyond the freeze/verify tamper-detection proof in Task 8, per the explicit instruction not to score `test_hard` without being asked.

No commit: this step produces no files.

---

## Out of scope for this plan (explicit follow-ups)

- `TEST_RUNS.md` auto-append and a CI check on the frozen manifest hash are part of `docs/05_Phase_Plan.md` P1-T7 and are not built here. The `--allow-test` guard in Task 5 is the minimal safety net for *this* session; the fuller P1-T7 scope (CI gate, run log) is a separate task.
- `make eval-ci` / `make eval-dev` remain unwired stubs (`Makefile`) — out of scope here; the task explicitly calls `docflow eval run` directly.
- No live model calls, no real `tier1`/`tier2` predictor — only the existing `null` stub system is exercised, per the user's explicit step 5.
