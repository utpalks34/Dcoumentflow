"""Tests for src/docflow/evals/manifest.py (TR-EVAL-01).

Pilot-scoped subset of the TR-EVAL-01 manifest schema: with only ~36 real
documents and no dev/test split yet, everything goes into split="pilot"
(docs/05_Phase_Plan.md P1-T3 note; confirmed with the user 2026-09-30).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from docflow.evals.manifest import (
    build_manifest,
    build_manifest_with_split,
    label_path_for,
    load_manifest,
    merge_manifests,
)
from tests.helpers.pdf_fixtures import pdf_with_text


def _write(path: Path, data: bytes) -> None:
    path.write_bytes(data)


class TestBuildManifest:
    def test_one_row_per_distinct_pdf(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.pdf", pdf_with_text("Invoice A"))
        _write(tmp_path / "b.pdf", pdf_with_text("Invoice B"))
        out_path = tmp_path / "out" / "pilot.jsonl"

        rows = build_manifest(tmp_path, out_path)

        assert len(rows) == 2

    def test_doc_id_and_sha256_match_file_content(self, tmp_path: Path) -> None:
        data = pdf_with_text("Invoice A")
        _write(tmp_path / "a.pdf", data)
        out_path = tmp_path / "out" / "pilot.jsonl"

        rows = build_manifest(tmp_path, out_path)

        expected_hash = hashlib.sha256(data).hexdigest()
        assert rows[0].sha256 == expected_hash
        assert rows[0].doc_id == f"d_{expected_hash[:12]}"

    def test_source_and_split_are_set(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.pdf", pdf_with_text("Invoice A"))
        out_path = tmp_path / "out" / "pilot.jsonl"

        rows = build_manifest(tmp_path, out_path)

        assert rows[0].source == "synthetic"
        assert rows[0].split == "pilot"

    def test_pages_counted_when_readable(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.pdf", pdf_with_text("Invoice A", n_pages=3))
        out_path = tmp_path / "out" / "pilot.jsonl"

        rows = build_manifest(tmp_path, out_path)

        assert rows[0].pages == 3

    def test_pages_none_when_unreadable(self, tmp_path: Path) -> None:
        _write(tmp_path / "corrupt.pdf", b"not a real pdf")
        out_path = tmp_path / "out" / "pilot.jsonl"

        rows = build_manifest(tmp_path, out_path)

        assert len(rows) == 1
        assert rows[0].pages is None
        assert rows[0].sha256 == hashlib.sha256(b"not a real pdf").hexdigest()

    def test_duplicate_content_is_deduped(self, tmp_path: Path) -> None:
        data = pdf_with_text("Same content")
        _write(tmp_path / "a.pdf", data)
        _write(tmp_path / "b_copy.pdf", data)
        out_path = tmp_path / "out" / "pilot.jsonl"

        rows = build_manifest(tmp_path, out_path)

        assert len(rows) == 1

    def test_writes_valid_jsonl(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.pdf", pdf_with_text("Invoice A"))
        _write(tmp_path / "b.pdf", pdf_with_text("Invoice B"))
        out_path = tmp_path / "out" / "pilot.jsonl"

        build_manifest(tmp_path, out_path)

        lines = out_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        for line in lines:
            row = json.loads(line)
            assert set(row.keys()) == {"doc_id", "path", "sha256", "pages", "source", "split"}

    def test_manifest_never_contains_extracted_text(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.pdf", pdf_with_text("TOP SECRET INVOICE CONTENT"))
        out_path = tmp_path / "out" / "pilot.jsonl"

        build_manifest(tmp_path, out_path)

        raw = out_path.read_text(encoding="utf-8")
        assert "TOP SECRET" not in raw

    def test_empty_folder_writes_empty_manifest(self, tmp_path: Path) -> None:
        out_path = tmp_path / "out" / "pilot.jsonl"

        rows = build_manifest(tmp_path, out_path)

        assert rows == []
        assert out_path.read_text(encoding="utf-8") == ""


class TestLoadManifest:
    def test_round_trips_through_build_manifest(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.pdf", pdf_with_text("Invoice A"))
        _write(tmp_path / "b.pdf", pdf_with_text("Invoice B"))
        out_path = tmp_path / "out" / "pilot.jsonl"

        built_rows = build_manifest(tmp_path, out_path)
        loaded_rows = load_manifest(out_path)

        assert loaded_rows == built_rows

    def test_empty_manifest_file_loads_empty_list(self, tmp_path: Path) -> None:
        out_path = tmp_path / "out" / "pilot.jsonl"
        out_path.parent.mkdir(parents=True)
        out_path.write_text("", encoding="utf-8")

        assert load_manifest(out_path) == []


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
