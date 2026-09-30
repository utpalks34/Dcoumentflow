"""Tests for src/docflow/tools/profile.py.

Aggregate-only report over a folder of PDFs: file count, page-count
distribution, text-layer vs. scanned, file sizes, producer/creator. Must
never surface per-file names or any extracted invoice text.
"""

from __future__ import annotations

from pathlib import Path

from docflow.tools.profile import profile_folder
from tests.helpers.pdf_fixtures import pdf_scanned_blank, pdf_with_metadata, pdf_with_text


def _write(path: Path, data: bytes) -> None:
    path.write_bytes(data)


class TestProfileFolder:
    def test_empty_folder(self, tmp_path: Path) -> None:
        report = profile_folder(tmp_path)
        assert report.file_count == 0
        assert report.page_count_distribution == {}
        assert report.text_layer_count == 0
        assert report.scanned_count == 0
        assert report.unreadable_count == 0

    def test_counts_pdfs_with_text_layer(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.pdf", pdf_with_text("Invoice A with enough extractable text"))
        _write(tmp_path / "b.pdf", pdf_with_text("Invoice B with enough extractable text"))

        report = profile_folder(tmp_path)

        assert report.file_count == 2
        assert report.text_layer_count == 2
        assert report.scanned_count == 0

    def test_counts_scanned_pdfs(self, tmp_path: Path) -> None:
        _write(tmp_path / "scan1.pdf", pdf_scanned_blank())
        _write(tmp_path / "scan2.pdf", pdf_scanned_blank())

        report = profile_folder(tmp_path)

        assert report.file_count == 2
        assert report.text_layer_count == 0
        assert report.scanned_count == 2

    def test_mixed_text_and_scanned(self, tmp_path: Path) -> None:
        _write(tmp_path / "real.pdf", pdf_with_text("Has plenty of extractable text"))
        _write(tmp_path / "scan.pdf", pdf_scanned_blank())

        report = profile_folder(tmp_path)

        assert report.file_count == 2
        assert report.text_layer_count == 1
        assert report.scanned_count == 1

    def test_page_count_distribution(self, tmp_path: Path) -> None:
        _write(tmp_path / "one.pdf", pdf_with_text("x", n_pages=1))
        _write(tmp_path / "two.pdf", pdf_with_text("y", n_pages=2))
        _write(tmp_path / "two_b.pdf", pdf_with_text("z", n_pages=2))

        report = profile_folder(tmp_path)

        assert report.page_count_distribution == {1: 1, 2: 2}

    def test_unreadable_pdf_is_counted_not_raised(self, tmp_path: Path) -> None:
        _write(tmp_path / "corrupt.pdf", b"not a real pdf")
        _write(tmp_path / "good.pdf", pdf_with_text("This one has plenty of real text"))

        report = profile_folder(tmp_path)

        assert report.file_count == 2
        assert report.unreadable_count == 1
        assert report.text_layer_count == 1

    def test_non_pdf_files_are_ignored(self, tmp_path: Path) -> None:
        _write(tmp_path / "notes.txt", b"not a pdf at all")
        _write(tmp_path / "good.pdf", pdf_with_text("ok"))

        report = profile_folder(tmp_path)

        assert report.file_count == 1

    def test_file_size_stats(self, tmp_path: Path) -> None:
        data = pdf_with_text("ok")
        _write(tmp_path / "good.pdf", data)

        report = profile_folder(tmp_path)

        assert report.file_size_bytes_min == len(data)
        assert report.file_size_bytes_max == len(data)
        assert report.file_size_bytes_mean == len(data)

    def test_producer_and_creator_counts(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "a.pdf",
            pdf_with_metadata(producer="Acrobat", creator="Word"),
        )
        _write(
            tmp_path / "b.pdf",
            pdf_with_metadata(producer="Acrobat", creator="Excel"),
        )

        report = profile_folder(tmp_path)

        assert report.producers == {"Acrobat": 2}
        assert report.creators == {"Word": 1, "Excel": 1}

    def test_missing_metadata_not_counted(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.pdf", pdf_with_text("no metadata"))

        report = profile_folder(tmp_path)

        assert report.producers == {}
        assert report.creators == {}

    def test_report_never_exposes_filenames(self, tmp_path: Path) -> None:
        _write(tmp_path / "secret_vendor_name.pdf", pdf_with_text("ok"))

        report = profile_folder(tmp_path)

        report_repr = repr(report)
        assert "secret_vendor_name" not in report_repr

    def test_report_never_exposes_extracted_text(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.pdf", pdf_with_text("TOP SECRET INVOICE TEXT"))

        report = profile_folder(tmp_path)

        report_repr = repr(report)
        assert "TOP SECRET" not in report_repr
