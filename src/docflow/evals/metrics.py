"""Evaluation metrics (TR-EVAL-02, TR-EVAL-05, TR-EVAL-06, TR-EVAL-07).

No I/O. Bootstrap intervals resample *documents*, not individual fields,
because fields within one document are not independent (TR-EVAL-06).
Reports bundle a point estimate with an interval; TR-EVAL-06 says a report
never shows a point estimate alone.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Sequence
from difflib import SequenceMatcher
from typing import NamedTuple

from scipy.optimize import linear_sum_assignment
from scipy.stats import beta, norm

from docflow.core.schemas import CanonicalInvoice, CanonicalLineItem

HEADER_FIELDS: tuple[str, ...] = (
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "currency",
    "subtotal",
    "tax_total",
    "total",
)

_LINE_ITEM_NUMERIC_FIELDS: tuple[str, ...] = ("qty", "unit_price", "amount")


class FieldCounts(NamedTuple):
    tp: int
    fp: int
    fn: int


class PrecisionRecallF1(NamedTuple):
    precision: float
    recall: float
    f1: float


class CalibrationBin(NamedTuple):
    n: int
    mean_confidence: float
    accuracy: float


class ECEResult(NamedTuple):
    ece: float
    bins: tuple[CalibrationBin, ...]


class RiskCoverageResult(NamedTuple):
    coverage: tuple[float, ...]
    risk: tuple[float, ...]
    aurc: float


class EvalSummary(NamedTuple):
    n_documents: int
    header_precision: float
    header_recall: float
    header_f1: float
    header_f1_ci: tuple[float, float]


def header_field_counts(
    gold: CanonicalInvoice, pred: CanonicalInvoice, labeled_fields: Sequence[str]
) -> FieldCounts:
    """Per-document TP/FP/FN over header fields, counting only labeled fields.

    gold=None & pred=None -> not counted. gold=None & pred=value -> FP.
    gold=value & pred=None -> FN. Mismatch -> FP+FN (TR-EVAL-02).
    """
    labeled = set(labeled_fields)
    tp = fp = fn = 0
    for field in HEADER_FIELDS:
        if field not in labeled:
            continue
        gold_value = getattr(gold, field)
        pred_value = getattr(pred, field)
        if gold_value is None and pred_value is None:
            continue
        if gold_value is None:
            fp += 1
        elif pred_value is None:
            fn += 1
        elif gold_value == pred_value:
            tp += 1
        else:
            fp += 1
            fn += 1
    return FieldCounts(tp=tp, fp=fp, fn=fn)


def _description_similarity(a: str | None, b: str | None) -> float:
    if a is None or b is None:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _line_item_exact_match(gold: CanonicalLineItem, pred: CanonicalLineItem) -> bool:
    for field in _LINE_ITEM_NUMERIC_FIELDS:
        gold_value = getattr(gold, field)
        if gold_value is None:
            continue
        if getattr(pred, field) != gold_value:
            return False
    return True


def line_item_counts(
    gold_items: Sequence[CanonicalLineItem], pred_items: Sequence[CanonicalLineItem]
) -> FieldCounts:
    """Match gold to predicted line items via Hungarian assignment on
    description similarity; a match is correct only if every gold-stated
    numeric cell is exactly equal (TR-EVAL-05).
    """
    n_gold = len(gold_items)
    n_pred = len(pred_items)
    if n_gold == 0 and n_pred == 0:
        return FieldCounts(tp=0, fp=0, fn=0)
    if n_gold == 0:
        return FieldCounts(tp=0, fp=n_pred, fn=0)
    if n_pred == 0:
        return FieldCounts(tp=0, fp=0, fn=n_gold)

    cost = [
        [1.0 - _description_similarity(g.description, p.description) for p in pred_items]
        for g in gold_items
    ]
    gold_idx, pred_idx = linear_sum_assignment(cost)

    tp = fp = fn = 0
    for gi, pi in zip(gold_idx, pred_idx, strict=True):
        if _line_item_exact_match(gold_items[gi], pred_items[pi]):
            tp += 1
        else:
            fp += 1
            fn += 1

    fn += n_gold - len(gold_idx)
    fp += n_pred - len(pred_idx)

    return FieldCounts(tp=tp, fp=fp, fn=fn)


def micro_f1(counts: Iterable[FieldCounts]) -> PrecisionRecallF1:
    total_tp = total_fp = total_fn = 0
    for c in counts:
        total_tp += c.tp
        total_fp += c.fp
        total_fn += c.fn
    return PrecisionRecallF1(*_prf_from_sums(total_tp, total_fp, total_fn))


def _prf_from_sums(tp: float, fp: float, fn: float) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def _f1_from_sums(tp: float, fp: float, fn: float) -> float:
    return _prf_from_sums(tp, fp, fn)[2]


def wilson_interval(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    z = float(norm.ppf(1 - (1 - confidence) / 2))
    phat = k / n
    denom = 1 + z**2 / n
    center = phat + z**2 / (2 * n)
    margin = z * ((phat * (1 - phat) / n + z**2 / (4 * n**2)) ** 0.5)
    low = (center - margin) / denom
    high = (center + margin) / denom
    return (max(0.0, low), min(1.0, high))


def clopper_pearson(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    alpha = 1 - confidence
    low = 0.0 if k == 0 else float(beta.ppf(alpha / 2, k, n - k + 1))
    high = 1.0 if k == n else float(beta.ppf(1 - alpha / 2, k + 1, n - k))
    return (low, high)


def error_upper_bound(errors: int, n: int, confidence: float = 0.95) -> float:
    """One-sided upper bound on the true error rate (TR-EVAL-07)."""
    if n <= 0:
        raise ValueError("n must be positive")
    if errors >= n:
        return 1.0
    alpha = 1 - confidence
    return float(beta.ppf(1 - alpha, errors + 1, n - errors))


def n_needed_for_error_bound(target_bound: float, confidence: float = 0.95) -> int:
    """Smallest n such that, with zero observed errors, the one-sided upper
    bound on the true error rate is at most target_bound (TR-EVAL-07)."""
    n = 1
    while error_upper_bound(0, n, confidence) > target_bound:
        n += 1
    return n


def bootstrap_f1(
    per_doc_counts: Sequence[FieldCounts],
    n_resamples: int = 10_000,
    confidence: float = 0.95,
    rng: random.Random | None = None,
) -> tuple[float, float]:
    """95% bootstrap interval for micro-F1, resampling documents (TR-EVAL-06)."""
    if not per_doc_counts:
        raise ValueError("per_doc_counts must be non-empty")
    n = len(per_doc_counts)
    generator = rng if rng is not None else random.Random()
    samples = []
    for _ in range(n_resamples):
        resample = generator.choices(per_doc_counts, k=n)
        tp = sum(c.tp for c in resample)
        fp = sum(c.fp for c in resample)
        fn = sum(c.fn for c in resample)
        samples.append(_f1_from_sums(tp, fp, fn))
    samples.sort()
    alpha = 1 - confidence
    return (_percentile(samples, alpha / 2), _percentile(samples, 1 - alpha / 2))


def paired_bootstrap_f1_diff(
    per_doc_counts_a: Sequence[FieldCounts],
    per_doc_counts_b: Sequence[FieldCounts],
    n_resamples: int = 10_000,
    confidence: float = 0.95,
    rng: random.Random | None = None,
) -> tuple[float, float]:
    """Paired bootstrap interval for F1(A) - F1(B) on the same documents."""
    if len(per_doc_counts_a) != len(per_doc_counts_b):
        raise ValueError("paired bootstrap requires equal-length, aligned per-document counts")
    n = len(per_doc_counts_a)
    if n == 0:
        raise ValueError("per_doc_counts must be non-empty")
    generator = rng if rng is not None else random.Random()
    indices = range(n)
    diffs = []
    for _ in range(n_resamples):
        idx_sample = generator.choices(indices, k=n)
        tp_a = fp_a = fn_a = 0
        tp_b = fp_b = fn_b = 0
        for i in idx_sample:
            ca = per_doc_counts_a[i]
            cb = per_doc_counts_b[i]
            tp_a += ca.tp
            fp_a += ca.fp
            fn_a += ca.fn
            tp_b += cb.tp
            fp_b += cb.fp
            fn_b += cb.fn
        diffs.append(_f1_from_sums(tp_a, fp_a, fn_a) - _f1_from_sums(tp_b, fp_b, fn_b))
    diffs.sort()
    alpha = 1 - confidence
    return (_percentile(diffs, alpha / 2), _percentile(diffs, 1 - alpha / 2))


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile, matching numpy's default method."""
    if not sorted_values:
        raise ValueError("sorted_values must be non-empty")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lower = int(pos)
    upper = min(lower + 1, len(sorted_values) - 1)
    frac = pos - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * frac


def risk_coverage(confidence: Sequence[float], correct: Sequence[bool]) -> RiskCoverageResult:
    """Sort by confidence descending; cumulative error rate at each coverage
    level, plus AURC (area under the risk-coverage curve, TR-EVAL-05)."""
    if len(confidence) != len(correct):
        raise ValueError("confidence and correct must be the same length")
    n = len(confidence)
    if n == 0:
        raise ValueError("confidence must be non-empty")

    order = sorted(range(n), key=lambda i: confidence[i], reverse=True)
    coverage: list[float] = []
    risk: list[float] = []
    cumulative_errors = 0
    for rank, idx in enumerate(order, start=1):
        if not correct[idx]:
            cumulative_errors += 1
        coverage.append(rank / n)
        risk.append(cumulative_errors / rank)

    aurc = sum(risk) / n
    return RiskCoverageResult(coverage=tuple(coverage), risk=tuple(risk), aurc=aurc)


def _equal_mass_bin_boundaries(n: int, n_bins: int) -> list[tuple[int, int]]:
    base = n // n_bins
    remainder = n % n_bins
    boundaries = []
    start = 0
    for i in range(n_bins):
        size = base + (1 if i < remainder else 0)
        end = start + size
        if size > 0:
            boundaries.append((start, end))
        start = end
    return boundaries


def expected_calibration_error(
    prob: Sequence[float], outcome: Sequence[bool], n_bins: int = 15
) -> ECEResult:
    """Equal-mass-binned ECE, reporting per-bin counts (needed to read a
    reliability diagram honestly)."""
    if len(prob) != len(outcome):
        raise ValueError("prob and outcome must be the same length")
    n = len(prob)
    if n == 0:
        raise ValueError("prob must be non-empty")

    order = sorted(range(n), key=lambda i: prob[i])
    bins: list[CalibrationBin] = []
    ece = 0.0
    for start, end in _equal_mass_bin_boundaries(n, n_bins):
        idx_slice = order[start:end]
        bin_n = len(idx_slice)
        mean_conf = sum(prob[i] for i in idx_slice) / bin_n
        accuracy = sum(1 for i in idx_slice if outcome[i]) / bin_n
        bins.append(CalibrationBin(n=bin_n, mean_confidence=mean_conf, accuracy=accuracy))
        ece += (bin_n / n) * abs(accuracy - mean_conf)

    return ECEResult(ece=ece, bins=tuple(bins))


def summarize(
    per_doc_header_counts: Sequence[FieldCounts],
    n_resamples: int = 10_000,
    confidence: float = 0.95,
    rng: random.Random | None = None,
) -> EvalSummary:
    """Bundle the header-field point estimate with its interval; TR-EVAL-06
    says a report never shows a point estimate alone."""
    prf = micro_f1(per_doc_header_counts)
    ci = bootstrap_f1(
        per_doc_header_counts, n_resamples=n_resamples, confidence=confidence, rng=rng
    )
    return EvalSummary(
        n_documents=len(per_doc_header_counts),
        header_precision=prf.precision,
        header_recall=prf.recall,
        header_f1=prf.f1,
        header_f1_ci=ci,
    )
