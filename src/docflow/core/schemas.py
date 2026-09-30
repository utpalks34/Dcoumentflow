"""Pydantic schemas for extraction output (FR-EXT-03, TR-DAT-02, TR-EVAL-01/02).

`ModelOutput` holds raw, unvalidated strings exactly as the extraction model
returned them. `CanonicalInvoice` holds normalized, typed values produced by
`docflow.core.normalize`. Money is always `Decimal`, never `float`
(TR-DAT-02): `Money` rejects a Python `float` at validation time so a caller
cannot smuggle a lossy value in.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

MAX_STR_LEN = 500
MAX_LINE_ITEMS = 200
MAX_AMBIGUITIES = 10


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("money fields must not be float; use Decimal or str (TR-DAT-02)")
    return value


Money = Annotated[Decimal, BeforeValidator(_reject_float)]

RawStr = Annotated[str, Field(max_length=MAX_STR_LEN)]


class ModelLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: RawStr | None = None
    qty: RawStr | None = None
    unit_price: RawStr | None = None
    amount: RawStr | None = None


class Ambiguity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: RawStr
    reason: RawStr


class ModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor_name: RawStr | None = None
    invoice_number: RawStr | None = None
    invoice_date: RawStr | None = None
    currency: RawStr | None = None
    subtotal: RawStr | None = None
    tax_total: RawStr | None = None
    total: RawStr | None = None
    line_items: list[ModelLineItem] = Field(default_factory=list, max_length=MAX_LINE_ITEMS)
    ambiguities: list[Ambiguity] = Field(default_factory=list, max_length=MAX_AMBIGUITIES)


class CanonicalLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    qty: Money | None = None
    unit_price: Money | None = None
    amount: Money | None = None


class CanonicalInvoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor_name: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    currency: str | None = None
    subtotal: Money | None = None
    tax_total: Money | None = None
    total: Money | None = None
    line_items: list[CanonicalLineItem] = Field(default_factory=list, max_length=MAX_LINE_ITEMS)
    ambiguities: list[Ambiguity] = Field(default_factory=list, max_length=MAX_AMBIGUITIES)
    flags: list[str] = Field(default_factory=list)


class LabelRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    label_source: Literal["hand", "model_assisted", "generator", "dataset"]
    labeled_fields: list[str]
    values: CanonicalInvoice
