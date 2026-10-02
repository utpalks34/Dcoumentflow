"""Deterministic DEV/TEST split assignment (ADR-009, TR-EVAL-01).

A document's split is a pure function of its doc_id and a fixed seed --
never of load order, file system state, or which folder a public dataset
happened to ship it in. This is what makes the assignment reproducible
from the doc_id alone and immune to a dataset's own, unrelated train/test
split (e.g. SROIE's, which is not a held-out split -- both of its folders
ship full ground truth).
"""

from __future__ import annotations

import hashlib
from typing import Literal

Split = Literal["dev_hard", "test_hard"]

DEFAULT_SPLIT_SEED = 20261002
DEFAULT_DEV_RATIO = 0.4


def assign_split(
    doc_id: str,
    seed: int = DEFAULT_SPLIT_SEED,
    dev_ratio: float = DEFAULT_DEV_RATIO,
) -> Split:
    digest = hashlib.sha256(f"{seed}:{doc_id}".encode()).hexdigest()
    fraction = int(digest[:8], 16) / 0xFFFFFFFF
    return "dev_hard" if fraction < dev_ratio else "test_hard"
