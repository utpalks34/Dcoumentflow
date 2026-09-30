"""Tests for src/docflow/evals/metrics.py (TR-EVAL-02, TR-EVAL-05, TR-EVAL-06, TR-EVAL-07).

Header-field and line-item toy examples are hand-computed on paper in the
docstring of each test, then asserted against the code -- not just asserted
against the code's own output.
"""

from __future__ import annotations

import math
import random
from decimal import Decimal

import pytest

from docflow.core.schemas import CanonicalInvoice, CanonicalLineItem
from docflow.evals.metrics import (
    FieldCounts,
    bootstrap_f1,
    clopper_pearson,
    error_upper_bound,
    expected_calibration_error,
    header_field_counts,
    line_item_counts,
    micro_f1,
    n_needed_for_error_bound,
    paired_bootstrap_f1_diff,
    risk_coverage,
    summarize,
    wilson_interval,
)


class TestHeaderFieldMicroF1:
    def test_only_counts_labeled_fields(self) -> None:
        gold = CanonicalInvoice(vendor_name="Acme", total=Decimal("100"))
        pred = CanonicalInvoice(vendor_name="Acme", total=Decimal("999"))
        counts = header_field_counts(gold, pred, labeled_fields=["vendor_name"])
        assert counts == FieldCounts(tp=1, fp=0, fn=0)

    def test_gold_none_pred_none_not_counted(self) -> None:
        gold = CanonicalInvoice()
        pred = CanonicalInvoice()
        counts = header_field_counts(gold, pred, labeled_fields=["vendor_name"])
        assert counts == FieldCounts(tp=0, fp=0, fn=0)

    def test_gold_none_pred_value_is_false_positive(self) -> None:
        gold = CanonicalInvoice()
        pred = CanonicalInvoice(vendor_name="Acme")
        counts = header_field_counts(gold, pred, labeled_fields=["vendor_name"])
        assert counts == FieldCounts(tp=0, fp=1, fn=0)

    def test_gold_value_pred_none_is_false_negative(self) -> None:
        gold = CanonicalInvoice(vendor_name="Acme")
        pred = CanonicalInvoice()
        counts = header_field_counts(gold, pred, labeled_fields=["vendor_name"])
        assert counts == FieldCounts(tp=0, fp=0, fn=1)

    def test_mismatch_is_false_positive_and_false_negative(self) -> None:
        gold = CanonicalInvoice(vendor_name="Acme")
        pred = CanonicalInvoice(vendor_name="Beta")
        counts = header_field_counts(gold, pred, labeled_fields=["vendor_name"])
        assert counts == FieldCounts(tp=0, fp=1, fn=1)

    def test_three_document_toy_example_hand_computed(self) -> None:
        """
        Doc1: gold(vendor=Acme, total=100) pred(vendor=Acme, total=100)
              -> both match: TP=2
        Doc2: gold(vendor=Beta, total=200) pred(vendor=Beta, total=None)
              -> vendor matches TP=1; total gold-has/pred-missing FN=1
        Doc3: gold(vendor=None, total=300) pred(vendor=Gamma, total=350)
              -> vendor gold-None/pred-value FP=1; total mismatch FP=1,FN=1

        Totals: TP=3, FP=2, FN=2
        Precision = 3/5 = 0.6, Recall = 3/5 = 0.6, F1 = 0.6
        """
        labeled_fields = ["vendor_name", "total"]
        doc1 = header_field_counts(
            CanonicalInvoice(vendor_name="Acme", total=Decimal("100")),
            CanonicalInvoice(vendor_name="Acme", total=Decimal("100")),
            labeled_fields,
        )
        doc2 = header_field_counts(
            CanonicalInvoice(vendor_name="Beta", total=Decimal("200")),
            CanonicalInvoice(vendor_name="Beta"),
            labeled_fields,
        )
        doc3 = header_field_counts(
            CanonicalInvoice(total=Decimal("300")),
            CanonicalInvoice(vendor_name="Gamma", total=Decimal("350")),
            labeled_fields,
        )

        result = micro_f1([doc1, doc2, doc3])

        assert result.precision == 0.6
        assert result.recall == 0.6
        assert result.f1 == 0.6


class TestLineItemF1:
    def test_toy_example_hand_computed(self) -> None:
        """
        Gold: [Widget(qty=2,price=50,amount=100), Gadget(qty=1,price=20,amount=20)]
        Pred: [Widget(qty=2,price=50,amount=100), Gadget(qty=1,price=25,amount=25)]

        Description similarity assigns Widget<->Widget and Gadget<->Gadget
        (exact text match, near-zero cost). Widget pair matches on every
        gold-stated cell -> TP. Gadget pair mismatches unit_price/amount
        -> counts as FP+FN (matched but incorrect).

        Totals: TP=1, FP=1, FN=1 -> Precision=0.5, Recall=0.5, F1=0.5
        """
        gold = [
            CanonicalLineItem(
                description="Widget", qty=Decimal("2"), unit_price=Decimal("50"),
                amount=Decimal("100"),
            ),
            CanonicalLineItem(
                description="Gadget", qty=Decimal("1"), unit_price=Decimal("20"),
                amount=Decimal("20"),
            ),
        ]
        pred = [
            CanonicalLineItem(
                description="Widget", qty=Decimal("2"), unit_price=Decimal("50"),
                amount=Decimal("100"),
            ),
            CanonicalLineItem(
                description="Gadget", qty=Decimal("1"), unit_price=Decimal("25"),
                amount=Decimal("25"),
            ),
        ]

        counts = line_item_counts(gold, pred)
        result = micro_f1([counts])

        assert counts == FieldCounts(tp=1, fp=1, fn=1)
        assert result.precision == 0.5
        assert result.recall == 0.5
        assert result.f1 == 0.5

    def test_extra_predicted_item_is_false_positive(self) -> None:
        gold = [CanonicalLineItem(description="Widget", amount=Decimal("100"))]
        pred = [
            CanonicalLineItem(description="Widget", amount=Decimal("100")),
            CanonicalLineItem(description="Extra thing", amount=Decimal("5")),
        ]
        counts = line_item_counts(gold, pred)
        assert counts == FieldCounts(tp=1, fp=1, fn=0)

    def test_missing_gold_item_is_false_negative(self) -> None:
        gold = [
            CanonicalLineItem(description="Widget", amount=Decimal("100")),
            CanonicalLineItem(description="Missed thing", amount=Decimal("5")),
        ]
        pred = [CanonicalLineItem(description="Widget", amount=Decimal("100"))]
        counts = line_item_counts(gold, pred)
        assert counts == FieldCounts(tp=1, fp=0, fn=1)

    def test_both_empty_is_all_zero(self) -> None:
        assert line_item_counts([], []) == FieldCounts(tp=0, fp=0, fn=0)

    def test_gold_stated_none_cells_are_not_required_to_match(self) -> None:
        gold = [CanonicalLineItem(description="Widget", amount=Decimal("100"))]
        pred = [
            CanonicalLineItem(
                description="Widget", qty=Decimal("999"), amount=Decimal("100")
            )
        ]
        counts = line_item_counts(gold, pred)
        assert counts == FieldCounts(tp=1, fp=0, fn=0)


class TestWilsonInterval:
    def test_matches_closed_form_formula(self) -> None:
        """Independent re-derivation of the Wilson score interval (Wikipedia
        form) for k=1, n=4, z=1.9599639845400545 (97.5th pctile, standard normal).
        """
        k, n = 1, 4
        z = 1.9599639845400545
        phat = k / n
        denom = 1 + z**2 / n
        center = phat + z**2 / (2 * n)
        margin = z * math.sqrt(phat * (1 - phat) / n + z**2 / (4 * n**2))
        expected_low = (center - margin) / denom
        expected_high = (center + margin) / denom

        low, high = wilson_interval(k, n)

        assert low == pytest.approx(expected_low)
        assert high == pytest.approx(expected_high)

    def test_interval_brackets_point_estimate(self) -> None:
        low, high = wilson_interval(30, 100)
        assert low <= 0.3 <= high
        assert 0.0 <= low <= high <= 1.0

    def test_zero_n_returns_full_interval(self) -> None:
        assert wilson_interval(0, 0) == (0.0, 1.0)


class TestClopperPearson:
    def test_zero_of_ten_matches_known_textbook_value(self) -> None:
        """0/10 successes -> 95% Clopper-Pearson upper bound is ~0.3085
        (a commonly cited "rule of thumb" value: 1 - (alpha/2)^(1/n))."""
        low, high = clopper_pearson(0, 10)
        assert low == pytest.approx(0.0)
        assert high == pytest.approx(0.3085, abs=1e-3)

    def test_interval_brackets_point_estimate(self) -> None:
        low, high = clopper_pearson(30, 100)
        assert low <= 0.3 <= high


class TestErrorUpperBound:
    def test_zero_errors_of_sixty_is_about_point_zero_four_nine(self) -> None:
        bound = error_upper_bound(0, 60)
        assert bound == pytest.approx(0.0487, abs=2e-3)
        assert bound > 0.03  # nowhere near a naive "0.01" claim

    def test_all_errors_is_one(self) -> None:
        assert error_upper_bound(5, 5) == 1.0


class TestNNeededForErrorBound:
    def test_one_percent_bound_needs_about_299_docs(self) -> None:
        n = n_needed_for_error_bound(0.01)
        assert n == pytest.approx(299, abs=2)

    def test_result_actually_satisfies_the_bound(self) -> None:
        n = n_needed_for_error_bound(0.02)
        assert error_upper_bound(0, n) <= 0.02
        assert error_upper_bound(0, n - 1) > 0.02


class TestBootstrapF1:
    def test_returns_interval_bracketing_point_estimate(self) -> None:
        counts = [FieldCounts(tp=8, fp=1, fn=1) for _ in range(30)]
        point = micro_f1(counts).f1
        low, high = bootstrap_f1(counts, n_resamples=500, rng=random.Random(1))
        assert 0.0 <= low <= point <= high <= 1.0

    def test_uniform_counts_give_a_tight_interval(self) -> None:
        counts = [FieldCounts(tp=8, fp=1, fn=1) for _ in range(50)]
        low, high = bootstrap_f1(counts, n_resamples=500, rng=random.Random(1))
        assert high - low < 0.05


class TestPairedBootstrapF1Diff:
    def test_identical_systems_bracket_zero(self) -> None:
        counts = [FieldCounts(tp=8, fp=1, fn=1) for _ in range(30)]
        low, high = paired_bootstrap_f1_diff(
            counts, counts, n_resamples=500, rng=random.Random(2)
        )
        assert low <= 0.0 <= high

    def test_clearly_better_system_has_positive_interval(self) -> None:
        better = [FieldCounts(tp=10, fp=0, fn=0) for _ in range(30)]
        worse = [FieldCounts(tp=5, fp=5, fn=5) for _ in range(30)]
        low, high = paired_bootstrap_f1_diff(
            better, worse, n_resamples=500, rng=random.Random(3)
        )
        assert low > 0.0

    def test_mismatched_lengths_raise(self) -> None:
        with pytest.raises(ValueError):
            paired_bootstrap_f1_diff([FieldCounts(1, 0, 0)], [], n_resamples=10)


class TestRiskCoverage:
    def test_toy_example_hand_computed(self) -> None:
        """
        confidence = [0.9, 0.8, 0.7, 0.6], correct = [T, T, F, T] (already
        sorted by confidence descending).
        rank1: errors=0 risk=0/1=0.0     coverage=0.25
        rank2: errors=0 risk=0/2=0.0     coverage=0.50
        rank3: errors=1 risk=1/3=0.3333  coverage=0.75
        rank4: errors=1 risk=1/4=0.25    coverage=1.00
        AURC = mean(risk) = (0+0+0.3333+0.25)/4 = 0.145833...
        """
        confidence = [0.9, 0.8, 0.7, 0.6]
        correct = [True, True, False, True]

        result = risk_coverage(confidence, correct)

        assert result.coverage == (0.25, 0.5, 0.75, 1.0)
        assert result.risk[0] == pytest.approx(0.0)
        assert result.risk[1] == pytest.approx(0.0)
        assert result.risk[2] == pytest.approx(1 / 3)
        assert result.risk[3] == pytest.approx(0.25)
        assert result.aurc == pytest.approx(0.145833, abs=1e-5)


class TestExpectedCalibrationError:
    def test_toy_example_hand_computed(self) -> None:
        """
        prob=[0.1,0.4,0.6,0.9], outcome=[F,F,T,T], n_bins=2 (equal mass, size 2 each)
        bin1: conf=(0.1+0.4)/2=0.25, acc=0/2=0.0, weight=2/4=0.5 -> |0-0.25|*0.5=0.125
        bin2: conf=(0.6+0.9)/2=0.75, acc=2/2=1.0, weight=0.5    -> |1-0.75|*0.5=0.125
        ECE = 0.25
        """
        prob = [0.1, 0.4, 0.6, 0.9]
        outcome = [False, False, True, True]

        result = expected_calibration_error(prob, outcome, n_bins=2)

        assert result.ece == pytest.approx(0.25)
        assert [b.n for b in result.bins] == [2, 2]
        assert result.bins[0].mean_confidence == pytest.approx(0.25)
        assert result.bins[0].accuracy == pytest.approx(0.0)
        assert result.bins[1].mean_confidence == pytest.approx(0.75)
        assert result.bins[1].accuracy == pytest.approx(1.0)


class TestSummarize:
    def test_reports_point_estimate_with_interval_never_alone(self) -> None:
        counts = [FieldCounts(tp=8, fp=1, fn=1) for _ in range(30)]
        result = summarize(counts, n_resamples=200, rng=random.Random(4))
        assert result.n_documents == 30
        assert result.header_f1 == micro_f1(counts).f1
        low, high = result.header_f1_ci
        assert 0.0 <= low <= result.header_f1 <= high <= 1.0
