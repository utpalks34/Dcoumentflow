"""Tests for src/docflow/evals/runner.py.

This runner exists to prove the manifest -> predictor -> metrics plumbing
works end to end, not to produce a real accuracy number: there are no
labels yet (docs/05_Phase_Plan.md P1-T5 is still pending), so the "null"
system is scored against an empty label set and every score is 0.0 by
construction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docflow.core.schemas import CanonicalInvoice, LabelRecord
from docflow.evals.manifest import ManifestRow, build_manifest, write_manifest
from docflow.evals.runner import run_eval, run_eval_split
from tests.helpers.pdf_fixtures import pdf_with_text


class TestRunEval:
    def test_null_system_on_small_manifest(self, tmp_path: Path) -> None:
        (tmp_path / "a.pdf").write_bytes(pdf_with_text("Invoice A"))
        (tmp_path / "b.pdf").write_bytes(pdf_with_text("Invoice B"))
        manifest_path = tmp_path / "pilot.jsonl"
        build_manifest(tmp_path, manifest_path)

        summary = run_eval(manifest_path, "null")

        assert summary.n_documents == 2
        assert summary.header_precision == 0.0
        assert summary.header_recall == 0.0
        assert summary.header_f1 == 0.0
        assert summary.header_f1_ci == (0.0, 0.0)

    def test_unknown_system_raises(self, tmp_path: Path) -> None:
        (tmp_path / "a.pdf").write_bytes(pdf_with_text("Invoice A"))
        manifest_path = tmp_path / "pilot.jsonl"
        build_manifest(tmp_path, manifest_path)

        with pytest.raises(ValueError):
            run_eval(manifest_path, "bogus")

    def test_empty_manifest(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "pilot.jsonl"
        build_manifest(tmp_path, manifest_path)

        summary = run_eval(manifest_path, "null")

        assert summary.n_documents == 0


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
