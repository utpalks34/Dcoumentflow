"""Eval runner (TR-EVAL-01, TR-EVAL-05, TR-EVAL-06).

`run_eval` is the original manifest -> predictor -> metrics smoke test: it
scores against an always-empty gold `CanonicalInvoice()` and exists only to
prove the plumbing works on an unlabeled manifest (e.g. the pilot set).

`run_eval_split` is the real path: it loads a named split from a manifest
(default `data/manifests/all.jsonl`), loads each document's actual label
file via `docflow.evals.manifest.label_path_for`, and scores only the
fields that document's label record says were labeled. Any split whose
name starts with "test" is refused unless `allow_test=True` is passed
explicitly (ADR-009, hard rule: never score TEST without an explicit ask).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from docflow.core.schemas import CanonicalInvoice, LabelRecord
from docflow.evals.manifest import ManifestRow, label_path_for, load_manifest
from docflow.evals.metrics import EvalSummary, FieldCounts, header_field_counts, summarize

Predictor = Callable[[ManifestRow], CanonicalInvoice]

DEFAULT_ALL_MANIFEST = Path("data/manifests/all.jsonl")


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
        gold = CanonicalInvoice()  # unlabeled smoke-test path: stub gold
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


def _load_gold(doc_id: str) -> tuple[CanonicalInvoice, list[str]]:
    label_path = label_path_for(doc_id)
    record = LabelRecord.model_validate_json(label_path.read_text(encoding="utf-8"))
    return record.values, record.labeled_fields


def run_eval_split(
    split: str,
    system: str,
    *,
    manifest_path: Path = DEFAULT_ALL_MANIFEST,
    allow_test: bool = False,
) -> EvalSummary:
    if split.startswith("test") and not allow_test:
        raise PermissionError(
            f"split {split!r} looks like a TEST split; pass allow_test=True "
            f"(CLI: --allow-test) only for an explicitly requested milestone run (ADR-009)"
        )
    if system not in _SYSTEMS:
        raise ValueError(f"unknown system: {system!r} (available: {sorted(_SYSTEMS)})")
    predictor = _SYSTEMS[system]

    rows = [row for row in load_manifest(manifest_path) if row.split == split]
    if not rows:
        raise ValueError(f"no rows with split={split!r} in {manifest_path}")

    per_doc_counts: list[FieldCounts] = []
    for row in rows:
        gold, labeled_fields = _load_gold(row.doc_id)
        pred = predictor(row)
        per_doc_counts.append(header_field_counts(gold, pred, labeled_fields=labeled_fields))

    return summarize(per_doc_counts)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="docflow eval run")
    parser.add_argument("--system", required=True, choices=sorted(_SYSTEMS))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--split")
    parser.add_argument("--allow-test", action="store_true")
    args = parser.parse_args(argv)

    if args.split:
        manifest_path = args.manifest or DEFAULT_ALL_MANIFEST
        summary = run_eval_split(
            args.split, args.system, manifest_path=manifest_path, allow_test=args.allow_test
        )
    else:
        if not args.manifest:
            parser.error("--manifest is required when --split is not given")
        summary = run_eval(args.manifest, args.system)

    print(f"n_documents: {summary.n_documents}")
    print(f"header_precision: {summary.header_precision}")
    print(f"header_recall: {summary.header_recall}")
    print(f"header_f1: {summary.header_f1} (95% CI {summary.header_f1_ci})")


if __name__ == "__main__":
    main()
