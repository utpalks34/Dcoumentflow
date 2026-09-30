"""Pure normalization functions: amounts, dates, currency, text (FR-EXT-03, TR-PIPE-07).

No I/O. Every function returns the normalized value plus a tuple of flags
describing anything that could not be normalized deterministically (a
genuinely ambiguous input is resolved with a documented default AND
flagged — never guessed silently). A value that cannot be normalized at all
becomes `None` with flag `NORMALIZATION_FAILED`, per TR-PIPE-07.

Money is Decimal end to end; this module never produces or accepts a float
for an amount (TR-DAT-02).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

_AMOUNT_RE = re.compile(r"\(?\s*-?\s*[0-9][0-9.,\s ]*\)?")

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DAY_MONTHNAME_YEAR_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{4})$")
_MONTHNAME_DAY_YEAR_RE = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})$")
_NUMERIC_DATE_RE = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$")

_CURRENCY_SYMBOLS = {
    "€": "EUR",  # €
    "£": "GBP",  # £
    "₹": "INR",  # ₹
    "¥": "JPY",  # ¥
}
_AMBIGUOUS_CURRENCY_SYMBOLS = {
    "$": "USD",
}
_ISO_CODE_RE = re.compile(r"^[A-Z]{3}$")


class AmountResult(NamedTuple):
    value: Decimal | None
    flags: tuple[str, ...]


class DateResult(NamedTuple):
    value: date | None
    flags: tuple[str, ...]


class CurrencyResult(NamedTuple):
    value: str | None
    flags: tuple[str, ...]


def _resolve_single_separator(core: str, sep: str) -> tuple[str | None, str | None, list[str]]:
    """A lone separator character: decide whether it's the decimal point.

    Multiple occurrences can only be thousands grouping. A single
    occurrence followed by exactly 3 digits is genuinely ambiguous between
    thousands grouping (e.g. "1,234" == 1234) and a 3-decimal amount
    (== 1.234); default to grouping and flag it. 1-2 trailing digits can
    only be a fraction, since grouping always chunks by 3.
    """
    if core.count(sep) > 1:
        return None, sep, []
    trailing = core.rsplit(sep, 1)[1]
    if len(trailing) == 3:
        return None, sep, ["AMOUNT_AMBIGUOUS_SEPARATOR"]
    return sep, None, []


def _build_decimal(core: str, decimal_sep: str | None, thousands_sep: str | None) -> Decimal:
    text = core
    if thousands_sep is not None:
        text = text.replace(thousands_sep, "")
    if decimal_sep is not None and decimal_sep != ".":
        text = text.replace(decimal_sep, ".")
    text = text.replace(" ", "").replace(" ", "")
    return Decimal(text)


def parse_amount(raw: str | None) -> AmountResult:
    if raw is None:
        return AmountResult(None, ())
    text = raw.strip()
    if not text:
        return AmountResult(None, ())

    match = _AMOUNT_RE.search(text)
    if match is None:
        return AmountResult(None, ("NORMALIZATION_FAILED",))

    token = match.group().strip()
    negative = False
    if token.startswith("(") and token.endswith(")"):
        negative = True
        token = token[1:-1].strip()
    elif token.startswith("-"):
        negative = True
        token = token[1:].strip()

    core = token.replace(" ", " ").strip()
    if not core or not any(ch.isdigit() for ch in core):
        return AmountResult(None, ("NORMALIZATION_FAILED",))

    has_comma = "," in core
    has_dot = "." in core
    has_space = " " in core

    flags: list[str] = []
    decimal_sep: str | None
    thousands_sep: str | None

    if has_comma and has_dot:
        if core.rfind(",") > core.rfind("."):
            decimal_sep, thousands_sep = ",", "."
        else:
            decimal_sep, thousands_sep = ".", ","
    elif has_space and (has_comma or has_dot):
        thousands_sep = " "
        decimal_sep = "," if has_comma else "."
    elif has_comma:
        decimal_sep, thousands_sep, sep_flags = _resolve_single_separator(core, ",")
        flags.extend(sep_flags)
    elif has_dot:
        decimal_sep, thousands_sep, sep_flags = _resolve_single_separator(core, ".")
        flags.extend(sep_flags)
    elif has_space:
        decimal_sep, thousands_sep = None, " "
    else:
        decimal_sep, thousands_sep = None, None

    try:
        value = _build_decimal(core, decimal_sep, thousands_sep)
    except InvalidOperation:
        return AmountResult(None, ("NORMALIZATION_FAILED",))

    if negative:
        value = -value

    return AmountResult(value, tuple(flags))


def parse_date(raw: str | None, dayfirst: bool | None = None) -> DateResult:
    if raw is None:
        return DateResult(None, ())
    text = raw.strip()
    if not text:
        return DateResult(None, ())

    iso_match = _ISO_DATE_RE.match(text)
    if iso_match:
        iso_year, iso_month, iso_day = (int(g) for g in iso_match.groups())
        try:
            return DateResult(date(iso_year, iso_month, iso_day), ())
        except ValueError:
            return DateResult(None, ("NORMALIZATION_FAILED",))

    dmy_match = _DAY_MONTHNAME_YEAR_RE.match(text)
    if dmy_match:
        day_s, month_name, year_s = dmy_match.groups()
        month = _MONTHS.get(month_name.lower())
        if month is None:
            return DateResult(None, ("NORMALIZATION_FAILED",))
        try:
            return DateResult(date(int(year_s), month, int(day_s)), ())
        except ValueError:
            return DateResult(None, ("NORMALIZATION_FAILED",))

    mdy_match = _MONTHNAME_DAY_YEAR_RE.match(text)
    if mdy_match:
        month_name, day_s, year_s = mdy_match.groups()
        month = _MONTHS.get(month_name.lower())
        if month is None:
            return DateResult(None, ("NORMALIZATION_FAILED",))
        try:
            return DateResult(date(int(year_s), month, int(day_s)), ())
        except ValueError:
            return DateResult(None, ("NORMALIZATION_FAILED",))

    numeric_match = _NUMERIC_DATE_RE.match(text)
    if numeric_match:
        a_s, b_s, year_s = numeric_match.groups()
        a, b, year = int(a_s), int(b_s), int(year_s)
        flags: list[str] = []
        if a > 12 and b <= 12:
            day, month = a, b
        elif b > 12 and a <= 12:
            day, month = b, a
        else:
            use_dayfirst = dayfirst if dayfirst is not None else True
            day, month = (a, b) if use_dayfirst else (b, a)
            flags.append("DATE_AMBIGUOUS_DAY_MONTH")
        try:
            return DateResult(date(year, month, day), tuple(flags))
        except ValueError:
            return DateResult(None, ("NORMALIZATION_FAILED",))

    return DateResult(None, ("NORMALIZATION_FAILED",))


def normalize_currency(raw: str | None) -> CurrencyResult:
    if raw is None:
        return CurrencyResult(None, ())
    text = raw.strip()
    if not text:
        return CurrencyResult(None, ())

    if text in _AMBIGUOUS_CURRENCY_SYMBOLS:
        return CurrencyResult(
            _AMBIGUOUS_CURRENCY_SYMBOLS[text], ("CURRENCY_AMBIGUOUS_SYMBOL",)
        )
    if text in _CURRENCY_SYMBOLS:
        return CurrencyResult(_CURRENCY_SYMBOLS[text], ())

    upper = text.upper()
    if _ISO_CODE_RE.match(upper):
        return CurrencyResult(upper, ())

    return CurrencyResult(None, ("NORMALIZATION_FAILED",))


def normalize_text(raw: str | None) -> str | None:
    if raw is None:
        return None
    collapsed = re.sub(r"\s+", " ", raw).strip()
    return collapsed or None
