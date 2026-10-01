"""Tests for src/docflow/tools/synth.py (FR-EVAL-01, TR-EVAL-02).

DEV-clean is fully synthetic with generator-known ground truth: every test
here checks that the generator's own arithmetic is internally consistent,
and that its display strings actually parse back to the canonical values via
the existing normalize.py (never a parallel parsing implementation).
"""

from __future__ import annotations

from decimal import Decimal

from docflow.core.normalize import normalize_currency, parse_amount, parse_date
from docflow.evals.metrics import HEADER_FIELDS
from docflow.tools.synth import DEFAULT_N, DEFAULT_SEED, generate_dataset, to_label_record


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
