"""Tests for src/docflow/evals/manifest.py (TR-EVAL-01).

Pilot-scoped subset of the TR-EVAL-01 manifest schema: with only ~36 real
documents and no dev/test split yet, everything goes into split="pilot"
(docs/05_Phase_Plan.md P1-T3 note; confirmed with the user 2026-09-30).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from docflow.evals.manifest import build_manifest
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
