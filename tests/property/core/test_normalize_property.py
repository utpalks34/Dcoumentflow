"""Property tests for src/docflow/core/normalize.py (FR-EXT-03).

These generate random amounts/dates in each locale style and assert they
round-trip exactly through parse_amount / parse_date.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from docflow.core.normalize import parse_amount, parse_date

_MONTH_ABBR = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}

amounts = st.integers(min_value=0, max_value=999_999_999)
fractions = st.integers(min_value=0, max_value=99)
signs = st.booleans()


@given(integer_part=amounts, fractional_part=fractions, negative=signs)
def test_round_trip_us_style(integer_part: int, fractional_part: int, negative: bool) -> None:
    expected = Decimal(integer_part) + Decimal(fractional_part) / 100
    formatted = f"{integer_part:,}.{fractional_part:02d}"
    if negative and integer_part != 0:
        formatted = f"-{formatted}"
        expected = -expected

    value, flags = parse_amount(formatted)

    assert value == expected
    assert "AMOUNT_AMBIGUOUS_SEPARATOR" not in flags


@given(integer_part=amounts, fractional_part=fractions, negative=signs)
def test_round_trip_eu_style(integer_part: int, fractional_part: int, negative: bool) -> None:
    expected = Decimal(integer_part) + Decimal(fractional_part) / 100
    grouped = f"{integer_part:,}".replace(",", ".")
    formatted = f"{grouped},{fractional_part:02d}"
    if negative and integer_part != 0:
        formatted = f"({formatted})"
        expected = -expected

    value, flags = parse_amount(formatted)

    assert value == expected
    assert "AMOUNT_AMBIGUOUS_SEPARATOR" not in flags


@given(integer_part=amounts, fractional_part=fractions)
def test_round_trip_space_thousands_style(integer_part: int, fractional_part: int) -> None:
    expected = Decimal(integer_part) + Decimal(fractional_part) / 100
    grouped = f"{integer_part:,}".replace(",", " ")
    formatted = f"{grouped},{fractional_part:02d}"

    value, flags = parse_amount(formatted)

    assert value == expected
    assert "AMOUNT_AMBIGUOUS_SEPARATOR" not in flags


@given(integer_part=st.integers(min_value=0, max_value=999))
def test_round_trip_plain_integer(integer_part: int) -> None:
    value, flags = parse_amount(str(integer_part))

    assert value == Decimal(integer_part)
    assert flags == ()


@given(days_offset=st.integers(min_value=0, max_value=36_500))
def test_round_trip_iso_date(days_offset: int) -> None:
    d = date(2000, 1, 1) + timedelta(days=days_offset)

    value, flags = parse_date(d.isoformat())

    assert value == d
    assert flags == ()


@given(days_offset=st.integers(min_value=0, max_value=36_500))
def test_round_trip_day_month_name_year(days_offset: int) -> None:
    d = date(2000, 1, 1) + timedelta(days=days_offset)
    formatted = f"{d.day} {_MONTH_ABBR[d.month]} {d.year}"

    value, flags = parse_date(formatted)

    assert value == d
    assert flags == ()


# Two-digit years only round-trip unambiguously within the pivot's own
# range (00-69 -> 2000-2069, 70-99 -> 1970-1999): a year outside
# 1970-2069 would pivot back to the wrong century, so this is the only
# range the property can assert on.
_PIVOT_RANGE_START = date(1970, 1, 1)
_PIVOT_RANGE_END = date(2069, 12, 31)


@given(d=st.dates(min_value=_PIVOT_RANGE_START, max_value=_PIVOT_RANGE_END))
def test_round_trip_two_digit_year_day_first(d: date) -> None:
    formatted = f"{d.day:02d}/{d.month:02d}/{d.year % 100:02d}"

    value, flags = parse_date(formatted)

    assert value is not None
    assert value.year == d.year
    assert "DATE_TWO_DIGIT_YEAR" in flags


@given(d=st.dates(min_value=_PIVOT_RANGE_START, max_value=_PIVOT_RANGE_END))
def test_round_trip_two_digit_year_month_first(d: date) -> None:
    formatted = f"{d.month:02d}/{d.day:02d}/{d.year % 100:02d}"

    value, flags = parse_date(formatted)

    assert value is not None
    assert value.year == d.year
    assert "DATE_TWO_DIGIT_YEAR" in flags
