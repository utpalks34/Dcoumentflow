"""Tests for the top-level `docflow` CLI dispatcher (src/docflow/cli.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from docflow.cli import main
from tests.helpers.pdf_fixtures import pdf_with_text


class TestCliDispatch:
    def test_manifest_build(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (tmp_path / "a.pdf").write_bytes(pdf_with_text("Invoice A"))
        out_path = tmp_path / "out" / "pilot.jsonl"

        main(["manifest", "build", str(tmp_path), "--out", str(out_path)])

        assert out_path.exists()
        assert "wrote 1 rows" in capsys.readouterr().out

    def test_profile(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (tmp_path / "a.pdf").write_bytes(pdf_with_text("Invoice A"))

        main(["profile", str(tmp_path)])

        assert "file_count: 1" in capsys.readouterr().out

    def test_eval_run(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (tmp_path / "a.pdf").write_bytes(pdf_with_text("Invoice A"))
        manifest_path = tmp_path / "pilot.jsonl"
        main(["manifest", "build", str(tmp_path), "--out", str(manifest_path)])
        capsys.readouterr()

        main(["eval", "run", "--system", "null", "--manifest", str(manifest_path)])

        assert "n_documents: 1" in capsys.readouterr().out

    def test_unknown_command_exits_nonzero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["bogus"])
        assert exc_info.value.code != 0

    def test_no_command_exits_nonzero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code != 0
