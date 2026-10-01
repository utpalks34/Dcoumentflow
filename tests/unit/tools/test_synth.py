"""Tests for src/docflow/tools/synth.py (FR-EVAL-01, TR-EVAL-02).

DEV-clean is fully synthetic with generator-known ground truth: every test
here checks that the generator's own arithmetic is internally consistent,
and that its display strings actually parse back to the canonical values via
the existing normalize.py (never a parallel parsing implementation).
"""

from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from docflow.core.normalize import normalize_currency, parse_amount, parse_date
from docflow.evals.metrics import HEADER_FIELDS
from docflow.tools.synth import (
    DEFAULT_N,
    DEFAULT_SEED,
    generate_dataset,
    render_pdf,
    to_label_record,
    write_dataset,
)


class TestGenerateDataset:
    def test_produces_n_invoices(self) -> None:
        invoices = generate_dataset(seed=1, n=10)
        assert len(invoices) == 10

    def test_doc_ids_are_unique_and_ordered(self) -> None:
        invoices = generate_dataset(seed=1, n=10)
        assert [inv.doc_id for inv in invoices] == [f"dev_clean_{i:03d}" for i in range(10)]

    def test_same_seed_same_index_is_deterministic(self) -> None:
        a = generate_dataset(seed=42, n=5)
        b = generate_dataset(seed=42, n=5)
        assert [to_label_record(inv).model_dump_json() for inv in a] == [
            to_label_record(inv).model_dump_json() for inv in b
        ]

    def test_different_seed_changes_output(self) -> None:
        a = generate_dataset(seed=1, n=5)
        b = generate_dataset(seed=2, n=5)
        assert [inv.vendor_name for inv in a] != [inv.vendor_name for inv in b]


class TestArithmeticIsExact:
    def test_line_items_multiply_exactly(self) -> None:
        for inv in generate_dataset(seed=DEFAULT_SEED, n=DEFAULT_N):
            for li in inv.line_items:
                assert li.qty * li.unit_price == li.amount

    def test_line_items_sum_to_subtotal(self) -> None:
        for inv in generate_dataset(seed=DEFAULT_SEED, n=DEFAULT_N):
            assert sum((li.amount for li in inv.line_items), Decimal("0")) == inv.subtotal

    def test_subtotal_plus_tax_equals_total(self) -> None:
        for inv in generate_dataset(seed=DEFAULT_SEED, n=DEFAULT_N):
            assert inv.subtotal + inv.tax_total == inv.total

    def test_zero_tax_rate_occurs_and_total_equals_subtotal(self) -> None:
        invoices = generate_dataset(seed=DEFAULT_SEED, n=DEFAULT_N)
        zero_tax = [inv for inv in invoices if inv.tax_total == Decimal("0.00")]
        assert zero_tax
        for inv in zero_tax:
            assert inv.total == inv.subtotal


class TestDisplayStringsRoundTripThroughNormalize:
    def test_date_text_parses_back_to_canonical_date(self) -> None:
        for inv in generate_dataset(seed=DEFAULT_SEED, n=DEFAULT_N):
            result = parse_date(inv.invoice_date_text)
            assert result.value == inv.invoice_date

    def test_amount_text_parses_back_to_canonical_amount(self) -> None:
        for inv in generate_dataset(seed=DEFAULT_SEED, n=DEFAULT_N):
            assert parse_amount(inv.subtotal_text).value == inv.subtotal
            assert parse_amount(inv.tax_text).value == inv.tax_total
            assert parse_amount(inv.total_text).value == inv.total

    def test_currency_text_parses_back_to_canonical_currency(self) -> None:
        for inv in generate_dataset(seed=DEFAULT_SEED, n=DEFAULT_N):
            assert normalize_currency(inv.currency_text).value == inv.currency

    def test_set_includes_a_thousands_separator_case(self) -> None:
        invoices = generate_dataset(seed=DEFAULT_SEED, n=DEFAULT_N)
        assert any(inv.total >= Decimal("1000") for inv in invoices)

    def test_set_mixes_all_three_date_styles(self) -> None:
        invoices = generate_dataset(seed=DEFAULT_SEED, n=DEFAULT_N)
        texts = [inv.invoice_date_text for inv in invoices]
        assert any("-" in t and len(t) == 10 for t in texts)  # ISO
        assert any(t[0].isdigit() and " " in t and "/" not in t for t in texts)  # "14 Mar 2025"
        assert any("/" in t for t in texts)  # numeric DD/MM/YYYY


class TestToLabelRecord:
    def test_label_source_is_generator(self) -> None:
        inv = generate_dataset(seed=DEFAULT_SEED, n=1)[0]
        assert to_label_record(inv).label_source == "generator"

    def test_labeled_fields_is_every_header_field_plus_line_items(self) -> None:
        inv = generate_dataset(seed=DEFAULT_SEED, n=1)[0]
        record = to_label_record(inv)
        assert set(record.labeled_fields) == set(HEADER_FIELDS) | {"line_items"}

    def test_doc_id_matches(self) -> None:
        inv = generate_dataset(seed=DEFAULT_SEED, n=1)[0]
        assert to_label_record(inv).doc_id == inv.doc_id

    def test_values_match_canonical_fields(self) -> None:
        inv = generate_dataset(seed=DEFAULT_SEED, n=1)[0]
        values = to_label_record(inv).values
        assert values.vendor_name == inv.vendor_name
        assert values.invoice_date == inv.invoice_date
        assert values.total == inv.total
        assert len(values.line_items) == len(inv.line_items)


class TestRenderPdf:
    def test_produces_readable_single_page_pdf(self) -> None:
        inv = generate_dataset(seed=DEFAULT_SEED, n=1)[0]
        pdf_bytes = render_pdf(inv)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        assert len(reader.pages) == 1

    def test_pdf_contains_extractable_text(self) -> None:
        inv = generate_dataset(seed=DEFAULT_SEED, n=1)[0]
        pdf_bytes = render_pdf(inv)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        assert len(reader.pages[0].extract_text().strip()) > 0


class TestWriteDataset:
    def test_writes_matched_pdf_and_label_per_doc(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "invoices"
        labels_dir = tmp_path / "labels"

        invoices = write_dataset(out_dir, labels_dir, seed=1, n=5)

        assert len(invoices) == 5
        for inv in invoices:
            assert (out_dir / f"{inv.doc_id}.pdf").exists()
            assert (labels_dir / f"{inv.doc_id}.json").exists()

    def test_label_files_are_byte_identical_across_regeneration(self, tmp_path: Path) -> None:
        out_a, labels_a = tmp_path / "a_pdf", tmp_path / "a_labels"
        out_b, labels_b = tmp_path / "b_pdf", tmp_path / "b_labels"

        write_dataset(out_a, labels_a, seed=99, n=8)
        write_dataset(out_b, labels_b, seed=99, n=8)

        files_a = sorted(labels_a.iterdir())
        files_b = sorted(labels_b.iterdir())
        assert [p.name for p in files_a] == [p.name for p in files_b]
        for pa, pb in zip(files_a, files_b, strict=True):
            assert pa.read_bytes() == pb.read_bytes()

    def test_label_json_is_loadable_as_label_record(self, tmp_path: Path) -> None:
        from docflow.core.schemas import LabelRecord

        write_dataset(tmp_path / "pdf", tmp_path / "labels", seed=1, n=1)
        label_path = next((tmp_path / "labels").iterdir())

        record = LabelRecord.model_validate_json(label_path.read_text(encoding="utf-8"))
        assert record.doc_id == "dev_clean_000"


class TestRenderedPdfMatchesDisplayStrings:
    """Review finding (Critical): INR's '₹' symbol has no glyph in Helvetica's
    WinAnsi encoding and silently renders as a replacement box, so the PDF no
    longer supports the currency its own label claims. This test renders every
    generated document and checks every display string actually made it onto
    the page -- not just that it exists in memory."""

    def test_all_display_strings_appear_in_rendered_text(self) -> None:
        for inv in generate_dataset(seed=DEFAULT_SEED, n=DEFAULT_N):
            pdf_bytes = render_pdf(inv)
            text = PdfReader(io.BytesIO(pdf_bytes)).pages[0].extract_text()
            assert inv.currency_text in text, f"{inv.doc_id}: currency_text missing from PDF text"
            assert inv.invoice_date_text in text, f"{inv.doc_id}: date text missing from PDF text"
            assert inv.total_text in text, f"{inv.doc_id}: total text missing from PDF text"
            for li in inv.line_items:
                assert li.unit_price_text in text, f"{inv.doc_id}: line item price text missing"
                assert li.amount_text in text, f"{inv.doc_id}: line item amount text missing"


class TestDateHasNoAmbiguity:
    """Review finding (Important): a numeric_dmy date with day <= 12 is
    genuinely ambiguous (could be read as MM/DD), contradicting the plan's
    "no genuine ambiguity" requirement for this set."""

    def test_date_round_trip_has_no_ambiguity_flag(self) -> None:
        for inv in generate_dataset(seed=DEFAULT_SEED, n=DEFAULT_N):
            result = parse_date(inv.invoice_date_text)
            assert result.flags == (), f"{inv.doc_id}: {inv.invoice_date_text!r} is ambiguous"


class TestJpyHasNoFractionalMinorUnit:
    """Review finding (Important): JPY has no minor unit; a fractional yen
    amount (e.g. 8970.01) is not a realistic invoice value."""

    def test_jpy_amounts_are_whole_yen(self) -> None:
        jpy_invoices = [
            inv for inv in generate_dataset(seed=DEFAULT_SEED, n=DEFAULT_N) if inv.currency == "JPY"
        ]
        assert jpy_invoices, "expected at least one JPY invoice in the default dataset"
        for inv in jpy_invoices:
            assert inv.subtotal == inv.subtotal.to_integral_value()
            assert inv.tax_total == inv.tax_total.to_integral_value()
            assert inv.total == inv.total.to_integral_value()
            for li in inv.line_items:
                assert li.unit_price == li.unit_price.to_integral_value()
                assert li.amount == li.amount.to_integral_value()


class TestLineItemTextRoundTrips:
    """Review finding (Important): line items were always formatted plain
    US-style regardless of the document's chosen amount style, and were never
    round-tripped through normalize.py."""

    def test_line_item_text_parses_back_to_canonical_values(self) -> None:
        for inv in generate_dataset(seed=DEFAULT_SEED, n=DEFAULT_N):
            for li in inv.line_items:
                assert parse_amount(li.unit_price_text).value == li.unit_price
                assert parse_amount(li.amount_text).value == li.amount
