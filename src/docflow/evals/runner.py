"""Minimal eval runner (TR-EVAL-01, TR-EVAL-05, TR-EVAL-06).

Proves the manifest -> predictor -> metrics plumbing works end to end. The
"null" system and the empty label set below are placeholders: there are no
labels yet (docs/05_Phase_Plan.md P1-T5 is still pending), so every score
is 0.0 by construction. This exists to prove the plumbing works, not to
produce a real number.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from docflow.core.schemas import CanonicalInvoice
from docflow.evals.manifest import ManifestRow, load_manifest
from docflow.evals.metrics import EvalSummary, FieldCounts, header_field_counts, summarize

Predictor = Callable[[ManifestRow], CanonicalInvoice]


def null_predictor(row: ManifestRow) -> CanonicalInvoice:
    return CanonicalInvoice()


_SYSTEMS: dict[str, Predictor] = {"null": null_predictor}


def run_eval(manifest_path: Path, system: str) -> EvalSummary:
    if system not in _SYSTEMS:
        raise ValueError(f"unknown system: {system!r} (available: {sorted(_SYSTEMS)})")
    predictor = _SYSTEMS[system]
    rows = load_manifest(manifest_path)

    per_doc_counts: list[FieldCounts] = []
    for row in rows:
        gold = CanonicalInvoice()  # no labels yet (P1-T5 pending): stub gold
        pred = predictor(row)
        per_doc_counts.append(header_field_counts(gold, pred, labeled_fields=[]))

    if not per_doc_counts:
        return EvalSummary(
            n_documents=0,
            header_precision=0.0,
            header_recall=0.0,
            header_f1=0.0,
            header_f1_ci=(0.0, 0.0),
        )

    return summarize(per_doc_counts)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="docflow eval run")
    parser.add_argument("--system", required=True, choices=sorted(_SYSTEMS))
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args(argv)

    summary = run_eval(args.manifest, args.system)
    print(f"n_documents: {summary.n_documents}")
    print(f"header_precision: {summary.header_precision}")
    print(f"header_recall: {summary.header_recall}")
    print(f"header_f1: {summary.header_f1} (95% CI {summary.header_f1_ci})")


if __name__ == "__main__":
    main()
