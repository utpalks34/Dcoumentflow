"""Tests for src/docflow/evals/split.py (TR-EVAL-01, ADR-009)."""

from __future__ import annotations

from docflow.evals.split import DEFAULT_DEV_RATIO, assign_split


class TestAssignSplit:
    def test_deterministic_for_same_doc_id_and_seed(self) -> None:
        assert assign_split("sroie_X001", seed=42) == assign_split("sroie_X001", seed=42)

    def test_returns_a_valid_split_name(self) -> None:
        for i in range(50):
            assert assign_split(f"sroie_{i}", seed=42) in ("dev_hard", "test_hard")

    def test_not_every_doc_id_lands_in_the_same_split(self) -> None:
        results = {assign_split(f"sroie_{i}", seed=42) for i in range(50)}
        assert results == {"dev_hard", "test_hard"}

    def test_ratio_is_approximately_dev_ratio_over_many_ids(self) -> None:
        n = 2000
        dev_count = sum(1 for i in range(n) if assign_split(f"doc_{i}", seed=7) == "dev_hard")
        assert abs(dev_count / n - DEFAULT_DEV_RATIO) < 0.05

    def test_different_seed_changes_assignment_for_at_least_one_doc(self) -> None:
        a = [assign_split(f"doc_{i}", seed=1) for i in range(100)]
        b = [assign_split(f"doc_{i}", seed=2) for i in range(100)]
        assert a != b

    def test_sroie_train_test_folder_has_no_bearing_on_split(self) -> None:
        # Same basename, as if seen identically regardless of which SROIE
        # folder it came from -- assign_split only ever sees the doc_id.
        assert assign_split("sroie_X00016469612", seed=42) == assign_split(
            "sroie_X00016469612", seed=42
        )
