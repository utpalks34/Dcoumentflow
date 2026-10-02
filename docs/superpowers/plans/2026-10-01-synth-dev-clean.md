# Synthetic DEV-clean Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 36 ungrounded PDFs in `invoices/` with 40 deterministic, seeded, matched (PDF, label) pairs for the DEV-clean split, where the generator's own values are the ground truth.

**Architecture:** A pure data-generation layer (`generate_invoice`/`generate_dataset`, stdlib `random.Random` seeded per-document) produces frozen dataclasses holding both canonical values (`Decimal`/`date`) and the display strings that will be printed on the PDF. A thin I/O layer (`render_pdf` via reportlab, `write_dataset`) turns those into files. This mirrors the existing `core` (pure) vs `tools` (I/O) split already used by `manifest.py`/`profile.py`, and keeps the determinism test cheap (it never has to parse a PDF back).

**Tech Stack:** Python 3.11, reportlab (new dep, PDF generation), pypdf (already a dep, used only in tests to sanity-check the PDF is readable), existing `docflow.core.normalize` / `docflow.core.schemas` / `docflow.evals.metrics`.

**Spec:** User-supplied task (Part A of a 4-part request, this session, 2026-10-01). Related requirement IDs: FR-EVAL-01, FR-EVAL-02, TR-EVAL-01, TR-EVAL-02 (docs/02_TRD_Technical_Requirements.md).

## Global Constraints

- Money is `Decimal` everywhere, never `float` (TR-DAT-02) — `schemas.Money` already enforces this at validation time.
- No raw per-document invoice text/values printed to logs or test output beyond what pytest needs to show a failure (docs/06 Hard rule 7).
- `labeled_fields` must be exactly `HEADER_FIELDS + ["line_items"]` since the generator knows every field with certainty — no partial labeling for this split.
- Arithmetic must be exact: `qty * unit_price == amount` for every line item, `sum(amounts) == subtotal`, `subtotal + tax_total == total` — all as `Decimal` equality, never approximate.
- `reportlab` is a new dependency: add via `uv add`, pin, and add a one-line comment in `pyproject.toml` explaining why (matches the existing scipy/pypdf comment style) — confirmed with the user 2026-10-01.
- mypy strict is **not** currently enforced on `src/docflow/tools/` (pyproject `[tool.mypy].files` only lists `core` and `evals`) — write typed code anyway, matching project style, but this module won't block `make test` on mypy strict violations outside `core`/`evals`.
- Nothing under `invoices/` or `data/` is committed to git (both are gitignored except `.gitkeep`, confirmed 2026-10-01) — only code is committed.

## Review Focus

- **Decimal rounding on tax:** `subtotal * tax_rate` can produce more than 2 decimal places (e.g. 33.33 * 0.18 = 5.9994) — must `.quantize(Decimal("0.01"), ROUND_HALF_UP)` before using it as `tax_total`, and derive `total` from the *quantized* `tax_total`, not the raw product, or `subtotal + tax_total == total` will fail. Covered in Task 1's arithmetic test.
- **Date format ambiguity:** the numeric slash-style date must always render as DD/MM (never MM/DD) since the task forbids genuine ambiguity in this set; `normalize.parse_date` defaults `dayfirst=True` only when both day and month are `<=12`, so a wrong day/month order here would silently mismatch the stored ground truth. Covered in Task 1 by asserting `parse_date(text).value == canonical_date` for every generated invoice, for all three date styles.
- **Currency round-trip:** using a symbol like `$` triggers `CURRENCY_AMBIGUOUS_SYMBOL` in `normalize.normalize_currency` but must still resolve to the correct canonical code — covered in Task 1.
- **Regeneration determinism:** reportlab embeds a `CreationDate` in PDF metadata derived from wall-clock time by default, so PDF *bytes* are not expected to be byte-identical across runs — only the **labels** are required to be byte-identical (this is what the task's own test asks for). The plan does not try to make PDF bytes deterministic; Task 1's determinism test operates on the written label files only, not the PDFs.
- **Thousands-separator coverage:** the task asks the set to include "a few" `1,234.56` / `1.234,56` style amounts. With `qty` up to 20 and `unit_price` up to 250.00 across 1-5 line items, subtotals exceeding 1000 occur naturally for several (not guaranteed-exact-count) of the 40 docs; Task 1's test asserts this happens for at least one of the 40, not a fixed count, so the test doesn't become flaky if the exact distribution shifts.

---

### Task 1: Pure invoice data generation

**Files:**
- Create: `src/docflow/tools/synth.py` (data classes, generation functions, formatting helpers — no I/O yet)
- Test: `tests/unit/tools/test_synth.py`

**Interfaces:**
- Consumes: `docflow.core.normalize.{parse_amount, parse_date, normalize_currency}`, `docflow.core.schemas.{CanonicalInvoice, CanonicalLineItem, LabelRecord}`, `docflow.evals.metrics.HEADER_FIELDS`
- Produces: `SynthLineItem`, `SynthInvoice` (frozen dataclasses), `generate_invoice(index: int, seed: int = DEFAULT_SEED) -> SynthInvoice`, `generate_dataset(seed: int = DEFAULT_SEED, n: int = DEFAULT_N) -> list[SynthInvoice]`, `to_label_record(inv: SynthInvoice) -> LabelRecord`, constants `DEFAULT_SEED = 20260101`, `DEFAULT_N = 40` — later tasks build on these names exactly.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/tools/test_synth.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/tools/test_synth.py -v`
Expected: FAIL / collection error — `docflow.tools.synth` does not exist yet.

- [ ] **Step 3: Implement `src/docflow/tools/synth.py` (generation only, no I/O yet)**

```python
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

import argparse
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
```

(PDF rendering and file I/O are added in Task 2 — this step only adds the pure generation code above, enough to satisfy Task 1's tests.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/tools/test_synth.py -v`
Expected: PASS (all tests green)

- [ ] **Step 5: Run lint and type checks**

Run: `uv run ruff check . && uv run mypy`
Expected: no new errors (synth.py is not in the mypy `files` list, so only ruff applies here)

- [ ] **Step 6: Commit**

```bash
git add src/docflow/tools/synth.py tests/unit/tools/test_synth.py
git commit -m "Add deterministic synthetic invoice data generator (FR-EVAL-01, TR-EVAL-02)"
```

---

### Task 2: PDF rendering and file I/O

**Files:**
- Modify: `src/docflow/tools/synth.py` (add `render_pdf`, `write_dataset`)
- Modify: `pyproject.toml` (add `reportlab` dependency)
- Test: `tests/unit/tools/test_synth.py` (add `TestRenderPdf`, `TestWriteDataset`)

**Interfaces:**
- Consumes: `SynthInvoice`, `to_label_record` from Task 1; `pypdf.PdfReader` (test-only, already a dep)
- Produces: `render_pdf(inv: SynthInvoice) -> bytes`, `write_dataset(out_dir: Path = DEFAULT_OUT_DIR, labels_dir: Path = DEFAULT_LABELS_DIR, seed: int = DEFAULT_SEED, n: int = DEFAULT_N) -> list[SynthInvoice]` — Task 3's CLI calls `write_dataset` by these exact names.

- [ ] **Step 1: Add the reportlab dependency**

Run: `uv add "reportlab>=4.0,<5"`
Expected: `pyproject.toml` and `uv.lock` updated; `uv run python -c "import reportlab; print(reportlab.Version)"` prints a 4.x version.

Then add a one-line comment above the new dependency entry in `pyproject.toml`, matching the existing style:

```toml
    # Needed for tools/synth.py: generates the DEV-clean synthetic invoice
    # PDFs. BSD-licensed (ReportLab Toolkit, open-source edition).
    "reportlab>=4.0,<5",
```

- [ ] **Step 2: Write the failing tests**

```python
# append to tests/unit/tools/test_synth.py
from pypdf import PdfReader

from docflow.tools.synth import render_pdf, write_dataset


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
```

(`import io` and `from pathlib import Path` are already imported at the top of the test file from Task 1.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/tools/test_synth.py -v`
Expected: FAIL — `render_pdf`/`write_dataset` not defined.

- [ ] **Step 4: Implement `render_pdf` and `write_dataset`**

Append to `src/docflow/tools/synth.py`:

```python
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
```

(`io` is imported once at the top of the module alongside the other stdlib imports rather than inside the function.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/tools/test_synth.py -v`
Expected: PASS

- [ ] **Step 6: Run lint and full test suite**

Run: `uv run ruff check . && uv run pytest`
Expected: no errors; full suite green

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/docflow/tools/synth.py tests/unit/tools/test_synth.py
git commit -m "Add PDF rendering and dataset write to synth.py; pin reportlab (TR-EVAL-02)"
```

---

### Task 3: CLI wiring

**Files:**
- Modify: `src/docflow/tools/synth.py` (add `main(argv)`)
- Modify: `src/docflow/cli.py` (dispatch `docflow synth generate`)
- Test: `tests/unit/test_cli.py` (add `test_synth_generate`)

**Interfaces:**
- Consumes: `write_dataset` from Task 2
- Produces: `docflow.tools.synth.main(argv: list[str] | None = None) -> None`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/unit/test_cli.py, inside TestCliDispatch
    def test_synth_generate(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        out_dir = tmp_path / "invoices"
        labels_dir = tmp_path / "labels"

        main(
            [
                "synth",
                "generate",
                "--out",
                str(out_dir),
                "--labels-out",
                str(labels_dir),
                "--seed",
                "1",
                "--n",
                "3",
            ]
        )

        assert len(list(out_dir.glob("*.pdf"))) == 3
        assert len(list(labels_dir.glob("*.json"))) == 3
        assert "wrote 3 matched pairs" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cli.py::TestCliDispatch::test_synth_generate -v`
Expected: FAIL — `docflow synth` is not a recognized command (usage error, `SystemExit`).

- [ ] **Step 3: Add `main` to synth.py**

Append to `src/docflow/tools/synth.py`:

```python
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="docflow synth generate")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--labels-out", type=Path, default=DEFAULT_LABELS_DIR)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--n", type=int, default=DEFAULT_N)
    args = parser.parse_args(argv)

    invoices = write_dataset(args.out, args.labels_out, seed=args.seed, n=args.n)
    print(f"wrote {len(invoices)} matched pairs to {args.out} and {args.labels_out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Wire into cli.py**

Edit `src/docflow/cli.py`:

```python
from docflow.evals import manifest as manifest_tool
from docflow.evals import runner as eval_runner
from docflow.tools import profile as profile_tool
from docflow.tools import synth as synth_tool

_USAGE = (
    "usage: docflow <manifest build <folder> | profile <folder> | "
    "eval run --system S --manifest M | synth generate [--out DIR] [--labels-out DIR] "
    "[--seed N] [--n N]>"
)
```

and inside `main`, add a branch alongside the existing `elif command == "eval":` block:

```python
    elif command == "synth":
        if not rest or rest[0] != "generate":
            _usage_error()
        synth_tool.main(rest[1:])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: PASS

- [ ] **Step 6: Run full suite, lint, mypy**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: all green

- [ ] **Step 7: Commit**

```bash
git add src/docflow/tools/synth.py src/docflow/cli.py tests/unit/test_cli.py
git commit -m "Wire docflow synth generate into the CLI dispatcher (TR-EVAL-02)"
```

---

### Task 4: Regenerate DEV-clean and remove the old ungrounded PDFs

**Files:**
- Delete (filesystem only, not git-tracked): the 36 existing files under `invoices/*.pdf`
- Create (filesystem only, gitignored, not committed): `invoices/dev_clean/dev_clean_000.pdf` .. `dev_clean_039.pdf`, `data/labels/dev_clean/dev_clean_000.json` .. `dev_clean_039.json`

**Interfaces:**
- Consumes: `docflow synth generate` (Task 3's CLI command)
- Produces: the DEV-clean dataset on disk, ready for Part B's manifest builder to pick up by file stem as `doc_id`

- [ ] **Step 1: Back up the old PDFs to the scratchpad (safety net, not committed anywhere)**

Run: `cp invoices/*.pdf "$CLAUDE_SCRATCHPAD/invoices_backup_pre_synth/"` (create the dir first) — purely a local safety net since these files are untracked by git and about to be deleted on explicit instruction.

- [ ] **Step 2: Delete the old PDFs and generate the new set**

Run:
```bash
rm invoices/*.pdf
uv run docflow synth generate --out invoices/dev_clean --labels-out data/labels/dev_clean
```
Expected: `invoices/*.pdf` (flat, old files) gone; `wrote 40 matched pairs to invoices/dev_clean and data/labels/dev_clean` printed; 40 PDFs and 40 label JSONs on disk.

- [ ] **Step 3: Verify regeneration determinism on the real output (not just the test)**

Run:
```bash
uv run docflow synth generate --out /tmp/verify_pdf --labels-out /tmp/verify_labels
diff -rq data/labels/dev_clean /tmp/verify_labels
```
Expected: `diff` prints nothing (identical directory contents) — confirms the committed generator reproduces the exact same labels a second time, matching the task's acceptance test but against the real 40-doc output, not just the 8-doc test fixture.

- [ ] **Step 4: Run the full test suite, lint, and mypy one more time**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: all green — paste the actual output.

- [ ] **Step 5: Commit**

Nothing under `invoices/` or `data/` is tracked by git (confirmed gitignored, 2026-10-01), so there is nothing new to `git add` here — this step only exists to confirm `git status` is still clean after the regeneration.

Run: `git status`
Expected: clean (or only showing changes already committed in Tasks 1-3).

---

## After this plan

Part A (`docs/05_Phase_Plan.md` P1-T4/T5, the DEV-clean portion) is done. Parts B (SROIE ingest), C (freeze/verify TEST-hard), and D (null-predictor proof run) remain blocked on the user manually downloading `urbikn/sroie-datasetv2` to `data/raw/sroie/` and confirming — do not start them until that happens.
