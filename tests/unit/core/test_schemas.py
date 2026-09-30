"""Tests for src/docflow/core/schemas.py (FR-EXT-03, TR-DAT-02, TR-EVAL-01/02)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from docflow.core.schemas import (
    Ambiguity,
    CanonicalInvoice,
    CanonicalLineItem,
    LabelRecord,
    ModelLineItem,
    ModelOutput,
)


class TestModelOutput:
    def test_accepts_valid_input(self) -> None:
        out = ModelOutput(
            vendor_name="Acme Corp",
            invoice_number="INV-001",
            invoice_date="2025-03-14",
            currency="USD",
            subtotal="100.00",
            tax_total="10.00",
            total="110.00",
            line_items=[
                ModelLineItem(description="Widget", qty="2", unit_price="50.00", amount="100.00")
            ],
            ambiguities=[Ambiguity(field="currency", reason="symbol only, no code")],
        )
        assert out.vendor_name == "Acme Corp"
        assert out.line_items[0].description == "Widget"

    def test_accepts_all_none(self) -> None:
        out = ModelOutput()
        assert out.vendor_name is None
        assert out.line_items == []
        assert out.ambiguities == []

    def test_rejects_unknown_keys(self) -> None:
        with pytest.raises(ValidationError):
            ModelOutput.model_validate({"vendor_name": "Acme", "bogus_field": "x"})

    def test_rejects_string_over_max_length(self) -> None:
        with pytest.raises(ValidationError):
            ModelOutput(vendor_name="x" * 501)

    def test_accepts_string_at_max_length(self) -> None:
        out = ModelOutput(vendor_name="x" * 500)
        assert out.vendor_name is not None
        assert len(out.vendor_name) == 500

    def test_line_item_field_rejects_string_over_max_length(self) -> None:
        with pytest.raises(ValidationError):
            ModelLineItem(description="x" * 501)

    def test_line_items_cap_enforced(self) -> None:
        item = ModelLineItem(description="Widget")
        with pytest.raises(ValidationError):
            ModelOutput(line_items=[item] * 201)

    def test_line_items_at_cap_accepted(self) -> None:
        item = ModelLineItem(description="Widget")
        out = ModelOutput(line_items=[item] * 200)
        assert len(out.line_items) == 200

    def test_ambiguities_cap_enforced(self) -> None:
        amb = Ambiguity(field="currency", reason="ambiguous")
        with pytest.raises(ValidationError):
            ModelOutput(ambiguities=[amb] * 11)

    def test_ambiguities_at_cap_accepted(self) -> None:
        amb = Ambiguity(field="currency", reason="ambiguous")
        out = ModelOutput(ambiguities=[amb] * 10)
        assert len(out.ambiguities) == 10

    def test_ambiguity_rejects_unknown_keys(self) -> None:
        with pytest.raises(ValidationError):
            Ambiguity.model_validate({"field": "currency", "reason": "x", "extra": "y"})


class TestCanonicalInvoice:
    def test_accepts_valid_input(self) -> None:
        inv = CanonicalInvoice(
            vendor_name="Acme Corp",
            invoice_number="INV-001",
            invoice_date=date(2025, 3, 14),
            currency="USD",
            subtotal=Decimal("100.00"),
            tax_total=Decimal("10.00"),
            total=Decimal("110.00"),
            line_items=[
                CanonicalLineItem(
                    description="Widget",
                    qty=Decimal("2"),
                    unit_price=Decimal("50.00"),
                    amount=Decimal("100.00"),
                )
            ],
            flags=["CURRENCY_DEFAULTED"],
        )
        assert inv.total == Decimal("110.00")
        assert isinstance(inv.total, Decimal)
        assert inv.flags == ["CURRENCY_DEFAULTED"]

    def test_rejects_unknown_keys(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalInvoice.model_validate({"vendor_name": "Acme", "bogus_field": "x"})

    def test_money_field_rejects_float(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalInvoice(total=110.00)  # type: ignore[arg-type]

    def test_money_field_accepts_decimal_string(self) -> None:
        inv = CanonicalInvoice(total="110.00")  # type: ignore[arg-type]
        assert inv.total == Decimal("110.00")
        assert isinstance(inv.total, Decimal)

    def test_line_item_money_rejects_float(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalLineItem(amount=1.5)  # type: ignore[arg-type]

    def test_line_items_cap_enforced(self) -> None:
        item = CanonicalLineItem(description="Widget")
        with pytest.raises(ValidationError):
            CanonicalInvoice(line_items=[item] * 201)


class TestLabelRecord:
    def test_accepts_valid_input(self) -> None:
        rec = LabelRecord(
            doc_id="d_abc123",
            label_source="hand",
            labeled_fields=["vendor_name", "total"],
            values=CanonicalInvoice(vendor_name="Acme", total=Decimal("110.00")),
        )
        assert rec.label_source == "hand"
        assert rec.labeled_fields == ["vendor_name", "total"]

    def test_rejects_invalid_label_source(self) -> None:
        with pytest.raises(ValidationError):
            LabelRecord(
                doc_id="d_abc123",
                label_source="guessed",  # type: ignore[arg-type]
                labeled_fields=[],
                values=CanonicalInvoice(),
            )

    def test_rejects_unknown_keys(self) -> None:
        with pytest.raises(ValidationError):
            LabelRecord.model_validate(
                {
                    "doc_id": "d_abc123",
                    "label_source": "hand",
                    "labeled_fields": [],
                    "values": CanonicalInvoice().model_dump(mode="json"),
                    "bogus_field": "x",
                }
            )
