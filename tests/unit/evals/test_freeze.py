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
from docflow.evals.manifest import ManifestRow, load_manifest, write_manifest


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
        write_manifest([_manifest_row("sroie_A", "dev_hard")], manifest_path)

        assert [row for row in load_manifest(manifest_path) if row.split == "test_hard"] == []
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
