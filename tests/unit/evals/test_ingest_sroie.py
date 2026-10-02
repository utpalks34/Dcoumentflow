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
                train_dir,
                test_dir,
                images_out=tmp_path / "out_img",
                labels_out=tmp_path / "out_labels",
            )
