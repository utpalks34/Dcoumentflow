"""Hand-written cases for src/docflow/core/normalize.py (FR-EXT-03, TR-PIPE-07)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from docflow.core.normalize import (
    normalize_currency,
    normalize_text,
    parse_amount,
    parse_date,
)


class TestParseAmount:
    def test_none_returns_none(self) -> None:
        value, flags = parse_amount(None)
        assert value is None
        assert flags == ()

    def test_empty_string_returns_none(self) -> None:
        value, flags = parse_amount("   ")
        assert value is None
        assert flags == ()

    def test_us_style_comma_thousands_dot_decimal(self) -> None:
        value, flags = parse_amount("1,234.56")
        assert value == Decimal("1234.56")
        assert flags == ()

    def test_eu_style_dot_thousands_comma_decimal(self) -> None:
        value, flags = parse_amount("1.234,56")
        assert value == Decimal("1234.56")
        assert flags == ()

    def test_space_thousands_comma_decimal(self) -> None:
        value, flags = parse_amount("1 234,56")
        assert value == Decimal("1234.56")
        assert flags == ()

    def test_nbsp_thousands_comma_decimal(self) -> None:
        value, flags = parse_amount("1 234,56")
        assert value == Decimal("1234.56")
        assert flags == ()

    def test_dollar_sign_prefix(self) -> None:
        value, flags = parse_amount("$1,234.56")
        assert value == Decimal("1234.56")
        assert flags == ()

    def test_parens_are_negative(self) -> None:
        value, flags = parse_amount("(1,234.50)")
        assert value == Decimal("-1234.50")
        assert flags == ()

    def test_leading_minus_is_negative(self) -> None:
        value, flags = parse_amount("-1,234.50")
        assert value == Decimal("-1234.50")
        assert flags == ()

    def test_plain_integer(self) -> None:
        value, flags = parse_amount("1234")
        assert value == Decimal("1234")
        assert flags == ()

    def test_multiple_commas_is_unambiguous_grouping(self) -> None:
        value, flags = parse_amount("1,234,567")
        assert value == Decimal("1234567")
        assert flags == ()

    def test_multiple_dots_is_unambiguous_grouping(self) -> None:
        value, flags = parse_amount("1.234.567")
        assert value == Decimal("1234567")
        assert flags == ()

    def test_sole_comma_two_trailing_digits_is_decimal_unambiguous(self) -> None:
        value, flags = parse_amount("12,50")
        assert value == Decimal("12.50")
        assert flags == ()

    def test_sole_dot_two_trailing_digits_is_decimal_unambiguous(self) -> None:
        value, flags = parse_amount("12.50")
        assert value == Decimal("12.50")
        assert flags == ()

    def test_bare_comma_three_trailing_digits_is_ambiguous(self) -> None:
        value, flags = parse_amount("1,234")
        assert value == Decimal("1234")
        assert "AMOUNT_AMBIGUOUS_SEPARATOR" in flags

    def test_bare_dot_three_trailing_digits_is_ambiguous(self) -> None:
        value, flags = parse_amount("1.234")
        assert value == Decimal("1234")
        assert "AMOUNT_AMBIGUOUS_SEPARATOR" in flags

    def test_unparseable_text_is_flagged_not_guessed(self) -> None:
        value, flags = parse_amount("not an amount")
        assert value is None
        assert flags == ("NORMALIZATION_FAILED",)

    def test_indian_rupees_only_marker_stays_positive(self) -> None:
        """Domain trap: trailing "/-" means "rupees only", not a minus sign."""
        value, flags = parse_amount("Rs. 1,180/-")
        assert value == Decimal("1180")
        assert value is not None
        assert value > 0


class TestParseDate:
    def test_none_returns_none(self) -> None:
        value, flags = parse_date(None)
        assert value is None
        assert flags == ()

    def test_iso_format(self) -> None:
        value, flags = parse_date("2025-03-14")
        assert value == date(2025, 3, 14)
        assert flags == ()

    def test_day_month_name_year(self) -> None:
        value, flags = parse_date("14 Mar 2025")
        assert value == date(2025, 3, 14)
        assert flags == ()

    def test_month_name_day_year(self) -> None:
        value, flags = parse_date("March 14, 2025")
        assert value == date(2025, 3, 14)
        assert flags == ()

    def test_numeric_unambiguous_when_first_component_over_12(self) -> None:
        value, flags = parse_date("14/03/2025")
        assert value == date(2025, 3, 14)
        assert flags == ()

    def test_numeric_ambiguous_defaults_to_dayfirst_and_flags(self) -> None:
        value, flags = parse_date("03/04/2025")
        assert value == date(2025, 4, 3)
        assert "DATE_AMBIGUOUS_DAY_MONTH" in flags

    def test_numeric_ambiguous_respects_dayfirst_false(self) -> None:
        value, flags = parse_date("03/04/2025", dayfirst=False)
        assert value == date(2025, 3, 4)
        assert "DATE_AMBIGUOUS_DAY_MONTH" in flags

    def test_invalid_date_is_flagged_not_guessed(self) -> None:
        value, flags = parse_date("not a date")
        assert value is None
        assert flags == ("NORMALIZATION_FAILED",)

    def test_invalid_month_in_numeric_form(self) -> None:
        value, flags = parse_date("13/13/2025")
        assert value is None
        assert flags == ("NORMALIZATION_FAILED",)


class TestNormalizeCurrency:
    def test_none_returns_none(self) -> None:
        value, flags = normalize_currency(None)
        assert value is None
        assert flags == ()

    def test_iso_code_passthrough(self) -> None:
        value, flags = normalize_currency("USD")
        assert value == "USD"
        assert flags == ()

    def test_iso_code_case_insensitive(self) -> None:
        value, flags = normalize_currency("usd")
        assert value == "USD"
        assert flags == ()

    def test_euro_symbol_unambiguous(self) -> None:
        value, flags = normalize_currency("€")
        assert value == "EUR"
        assert flags == ()

    def test_rupee_symbol_unambiguous(self) -> None:
        value, flags = normalize_currency("₹")
        assert value == "INR"
        assert flags == ()

    def test_bare_dollar_sign_is_ambiguous(self) -> None:
        """Domain trap: bare "$" could be USD, AUD, CAD, SGD... default USD, flag it."""
        value, flags = normalize_currency("$")
        assert value == "USD"
        assert "CURRENCY_AMBIGUOUS_SYMBOL" in flags

    def test_unrecognized_text_is_flagged_not_guessed(self) -> None:
        value, flags = normalize_currency("XYZQ")
        assert value is None
        assert flags == ("NORMALIZATION_FAILED",)


class TestNormalizeText:
    def test_none_returns_none(self) -> None:
        assert normalize_text(None) is None

    def test_blank_returns_none(self) -> None:
        assert normalize_text("   ") is None

    def test_collapses_internal_whitespace(self) -> None:
        assert normalize_text("  Acme   Corp \n") == "Acme Corp"

    def test_already_clean_text_unchanged(self) -> None:
        assert normalize_text("Acme Corp") == "Acme Corp"
