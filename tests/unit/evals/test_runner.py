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

from docflow.evals.manifest import build_manifest
from docflow.evals.runner import run_eval
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
