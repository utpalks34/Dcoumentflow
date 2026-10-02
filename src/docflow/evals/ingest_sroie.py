"""SROIE receipt ingestion into DocFlow's labeled hard set (TR-EVAL-01,
TR-EVAL-02, ADR-009).

Pools all labeled receipts from SROIE2019's train/ and test/ folders into
one set. SROIE's own train/test split is NOT a held-out split -- both
folders ship full ground truth (confirmed by inspection) -- so it must
never be mapped onto DocFlow's own dev_hard/test_hard split. Only
`docflow.evals.split.assign_split`, applied downstream of this module to
the doc_ids it produces, decides that.
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from docflow.core.normalize import normalize_text, parse_amount, parse_date
from docflow.core.schemas import CanonicalInvoice, LabelRecord

LABELED_FIELDS = ("vendor_name", "invoice_date", "total")

DEFAULT_TRAIN_DIR = Path("data/sroie/SROIE2019/train")
DEFAULT_TEST_DIR = Path("data/sroie/SROIE2019/test")
DEFAULT_IMAGES_OUT = Path("invoices/sroie")
DEFAULT_LABELS_OUT = Path("data/labels/sroie")


@dataclass(frozen=True)
class IngestReport:
    doc_ids: tuple[str, ...]
    parse_failures: int

    @property
    def total(self) -> int:
        return len(self.doc_ids)

    @property
    def parse_failure_rate(self) -> float:
        return self.parse_failures / self.total if self.total else 0.0


def _find_pairs(source_dir: Path) -> list[tuple[Path, Path]]:
    img_dir = source_dir / "img"
    entities_dir = source_dir / "entities"
    pairs: list[tuple[Path, Path]] = []
    for img_path in sorted(img_dir.glob("*.jpg")):
        entities_path = entities_dir / f"{img_path.stem}.txt"
        if not entities_path.exists():
            raise FileNotFoundError(f"no entities file for {img_path}")
        pairs.append((img_path, entities_path))
    return pairs


def _map_entity(raw: dict[str, str]) -> tuple[CanonicalInvoice, bool]:
    vendor_name = normalize_text(raw.get("company"))
    date_result = parse_date(raw.get("date"))
    amount_result = parse_amount(raw.get("total"))

    flags = [f"invoice_date:{flag}" for flag in date_result.flags]
    flags += [f"total:{flag}" for flag in amount_result.flags]

    parse_failed = date_result.value is None or amount_result.value is None

    invoice = CanonicalInvoice(
        vendor_name=vendor_name,
        invoice_date=date_result.value,
        total=amount_result.value,
        flags=flags,
    )
    return invoice, parse_failed


def ingest(
    train_dir: Path = DEFAULT_TRAIN_DIR,
    test_dir: Path = DEFAULT_TEST_DIR,
    *,
    images_out: Path = DEFAULT_IMAGES_OUT,
    labels_out: Path = DEFAULT_LABELS_OUT,
) -> IngestReport:
    pairs = _find_pairs(train_dir) + _find_pairs(test_dir)

    seen_basenames: dict[str, Path] = {}
    for img_path, _ in pairs:
        if img_path.stem in seen_basenames:
            raise ValueError(
                f"duplicate SROIE basename {img_path.stem!r} in both "
                f"{seen_basenames[img_path.stem]} and {img_path}"
            )
        seen_basenames[img_path.stem] = img_path

    images_out.mkdir(parents=True, exist_ok=True)
    labels_out.mkdir(parents=True, exist_ok=True)

    doc_ids: list[str] = []
    parse_failures = 0
    for img_path, entities_path in pairs:
        doc_id = f"sroie_{img_path.stem}"
        raw = json.loads(entities_path.read_text(encoding="utf-8"))
        invoice, parse_failed = _map_entity(raw)
        if parse_failed:
            parse_failures += 1

        record = LabelRecord(
            doc_id=doc_id,
            label_source="dataset",
            labeled_fields=list(LABELED_FIELDS),
            values=invoice,
        )
        (labels_out / f"{doc_id}.json").write_text(record.model_dump_json(), encoding="utf-8")
        shutil.copy2(img_path, images_out / f"{doc_id}.jpg")
        doc_ids.append(doc_id)

    return IngestReport(doc_ids=tuple(doc_ids), parse_failures=parse_failures)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="docflow sroie ingest")
    parser.add_argument("--train-dir", type=Path, default=DEFAULT_TRAIN_DIR)
    parser.add_argument("--test-dir", type=Path, default=DEFAULT_TEST_DIR)
    parser.add_argument("--images-out", type=Path, default=DEFAULT_IMAGES_OUT)
    parser.add_argument("--labels-out", type=Path, default=DEFAULT_LABELS_OUT)
    args = parser.parse_args(argv)

    report = ingest(
        args.train_dir, args.test_dir, images_out=args.images_out, labels_out=args.labels_out
    )
    print(f"ingested {report.total} documents")
    print(
        f"parse failures (date or total -> None after normalization): "
        f"{report.parse_failures} ({report.parse_failure_rate:.1%})"
    )


if __name__ == "__main__":
    main()
