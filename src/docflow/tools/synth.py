"""Synthetic invoice generator for DEV-clean (FR-EVAL-01, TR-EVAL-02).

Produces matched (PDF, label) pairs in one deterministic, seeded pass: the
generator is the ground truth, so every header field and every line item is
labeled with label_source="generator". Amount and date *display* strings are
deliberately varied (locale styles, date formats) to exercise
docflow.core.normalize when a future extractor reads these PDFs back, but
the stored labels are always the canonical values the generator chose --
never a re-parse of the rendered text.

Arithmetic is exact by construction: line items sum to subtotal, and
subtotal + tax_total == total, always (no synthetic arithmetic errors --
DEV-clean exists to exercise normalization and scoring, not error recovery).
"""

from __future__ import annotations

import io
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from docflow.core.schemas import CanonicalInvoice, CanonicalLineItem, LabelRecord
from docflow.evals.metrics import HEADER_FIELDS

DEFAULT_SEED = 20260101
DEFAULT_N = 40
DEFAULT_OUT_DIR = Path("invoices/dev_clean")
DEFAULT_LABELS_DIR = Path("data/labels/dev_clean")

_VENDOR_PREFIXES = (
    "Blue", "Summit", "Cedar", "Harbor", "Northgate",
    "Ironwood", "Silverline", "Maple", "Union", "Granite",
)
_VENDOR_SUFFIXES = (
    "Supply Co.", "Logistics LLC", "Industrial Group", "Trading Partners",
    "Manufacturing Inc.", "Distribution Co.", "Services Ltd.", "Wholesale Group",
)
_ITEM_DESCRIPTIONS = (
    "Widget assembly", "Replacement cartridge", "Shipping pallet",
    "Safety gloves (box)", "Steel bracket", "Packing tape roll",
    "LED panel", "Cable harness", "Filter unit", "Gasket set",
    "Control relay", "Hex bolt (100ct)",
)
_CURRENCY_DISPLAY = {
    "USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "JPY": "¥",
}
_TAX_RATES = (
    Decimal("0.00"), Decimal("0.05"), Decimal("0.08"),
    Decimal("0.10"), Decimal("0.18"), Decimal("0.20"),
)
_DATE_STYLES = ("iso", "day_month_name", "numeric_dmy")
_AMOUNT_STYLES = ("plain", "us_thousands", "eu_thousands")
_EPOCH = date(2023, 1, 1)
_DATE_SPAN_DAYS = 1065  # spans roughly 2023-01-01..2025-12-31


@dataclass(frozen=True)
class SynthLineItem:
    description: str
    qty: Decimal
    unit_price: Decimal
    amount: Decimal


@dataclass(frozen=True)
class SynthInvoice:
    doc_id: str
    vendor_name: str
    invoice_number: str
    invoice_date: date
    invoice_date_text: str
    currency: str
    currency_text: str
    line_items: tuple[SynthLineItem, ...]
    subtotal: Decimal
    subtotal_text: str
    tax_total: Decimal
    tax_text: str
    total: Decimal
    total_text: str


def _format_date(d: date, style: str) -> str:
    if style == "iso":
        return d.isoformat()
    if style == "day_month_name":
        return f"{d.day} {d.strftime('%b')} {d.year}"
    if style == "numeric_dmy":
        return f"{d.day:02d}/{d.month:02d}/{d.year}"
    raise ValueError(f"unknown date style: {style!r}")


def _format_amount(value: Decimal, style: str) -> str:
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    us = f"{quantized:,.2f}"
    if style == "plain":
        return us.replace(",", "")
    if style == "us_thousands":
        return us
    if style == "eu_thousands":
        return us.replace(",", "\0").replace(".", ",").replace("\0", ".")
    raise ValueError(f"unknown amount style: {style!r}")


def generate_invoice(index: int, seed: int = DEFAULT_SEED) -> SynthInvoice:
    rng = random.Random(f"{seed}:{index}")
    doc_id = f"dev_clean_{index:03d}"

    vendor_name = f"{rng.choice(_VENDOR_PREFIXES)} {rng.choice(_VENDOR_SUFFIXES)}"
    invoice_number = f"INV-{seed % 10000:04d}-{index:04d}"

    invoice_date = _EPOCH + timedelta(days=rng.randrange(_DATE_SPAN_DAYS))
    date_style = _DATE_STYLES[index % len(_DATE_STYLES)]
    invoice_date_text = _format_date(invoice_date, date_style)

    currency = rng.choice(sorted(_CURRENCY_DISPLAY))
    currency_text = _CURRENCY_DISPLAY[currency]

    n_items = rng.randint(1, 5)
    line_items: list[SynthLineItem] = []
    subtotal = Decimal("0.00")
    for _ in range(n_items):
        description = rng.choice(_ITEM_DESCRIPTIONS)
        qty = Decimal(rng.randint(1, 20))
        unit_price = Decimal(rng.randint(100, 25000)) / Decimal(100)
        amount = qty * unit_price
        line_items.append(SynthLineItem(description, qty, unit_price, amount))
        subtotal += amount

    tax_rate = rng.choice(_TAX_RATES)
    tax_total = (subtotal * tax_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total = subtotal + tax_total

    amount_style = _AMOUNT_STYLES[index % len(_AMOUNT_STYLES)]

    return SynthInvoice(
        doc_id=doc_id,
        vendor_name=vendor_name,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        invoice_date_text=invoice_date_text,
        currency=currency,
        currency_text=currency_text,
        line_items=tuple(line_items),
        subtotal=subtotal,
        subtotal_text=_format_amount(subtotal, amount_style),
        tax_total=tax_total,
        tax_text=_format_amount(tax_total, amount_style),
        total=total,
        total_text=_format_amount(total, amount_style),
    )


def generate_dataset(seed: int = DEFAULT_SEED, n: int = DEFAULT_N) -> list[SynthInvoice]:
    return [generate_invoice(i, seed) for i in range(n)]


def to_label_record(inv: SynthInvoice) -> LabelRecord:
    line_items = [
        CanonicalLineItem(
            description=li.description, qty=li.qty, unit_price=li.unit_price, amount=li.amount
        )
        for li in inv.line_items
    ]
    values = CanonicalInvoice(
        vendor_name=inv.vendor_name,
        invoice_number=inv.invoice_number,
        invoice_date=inv.invoice_date,
        currency=inv.currency,
        subtotal=inv.subtotal,
        tax_total=inv.tax_total,
        total=inv.total,
        line_items=line_items,
    )
    return LabelRecord(
        doc_id=inv.doc_id,
        label_source="generator",
        labeled_fields=[*HEADER_FIELDS, "line_items"],
        values=values,
    )


def render_pdf(inv: SynthInvoice) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    width, height = LETTER
    y = height - 72

    def line(text: str, size: int = 11, dy: int = 16) -> None:
        nonlocal y
        c.setFont("Helvetica", size)
        c.drawString(72, y, text)
        y -= dy

    line(inv.vendor_name, size=14, dy=24)
    line(f"Invoice Number: {inv.invoice_number}")
    line(f"Invoice Date: {inv.invoice_date_text}")
    line(f"Currency: {inv.currency_text}")
    y -= 10
    line("Description            Qty  Unit Price   Amount")
    for li in inv.line_items:
        line(
            f"{li.description:<22} {li.qty!s:>4} "
            f"{inv.currency_text}{li.unit_price:.2f} {inv.currency_text}{li.amount:.2f}"
        )
    y -= 10
    line(f"Subtotal: {inv.currency_text}{inv.subtotal_text}")
    line(f"Tax: {inv.currency_text}{inv.tax_text}")
    line(f"Total: {inv.currency_text}{inv.total_text}", size=13, dy=20)

    c.showPage()
    c.save()
    return buf.getvalue()


def write_dataset(
    out_dir: Path = DEFAULT_OUT_DIR,
    labels_dir: Path = DEFAULT_LABELS_DIR,
    seed: int = DEFAULT_SEED,
    n: int = DEFAULT_N,
) -> list[SynthInvoice]:
    out_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    invoices = generate_dataset(seed=seed, n=n)
    for inv in invoices:
        (out_dir / f"{inv.doc_id}.pdf").write_bytes(render_pdf(inv))
        label = to_label_record(inv)
        (labels_dir / f"{inv.doc_id}.json").write_text(label.model_dump_json(), encoding="utf-8")
    return invoices
