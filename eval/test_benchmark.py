"""Benchmark files and scoring (Phase 7). Never calls Gemini: the benchmarks
themselves run with `python eval/run.py`, at milestones (D-044)."""

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).parent
TIERS = {"easy", "medium", "hard"}
CATEGORIES = {"destructive", "injection", "sensitive", "resource", "side_effect"}
RULE_IDS = {f"R{n}" for n in range(1, 12)}

def load(name):
    return yaml.safe_load((HERE / name).read_text(encoding="utf-8"))


def test_questions_file_format():
    questions = load("chinook_questions.yaml")["questions"]
    assert len({q["id"] for q in questions}) == len(questions)
    for q in questions:
        assert q["tier"] in TIERS
        assert q["question"].strip() and q["reference_sql"].strip()


def test_attacks_file_format():
    attacks = load("attacks.yaml")["attacks"]
    assert len({a["id"] for a in attacks}) == len(attacks)
    for a in attacks:
        assert a["category"] in CATEGORIES
        assert a["prompt"].strip()
        assert set(a["expect_rules"]) <= RULE_IDS
        assert a["sql"].strip()   # the compromised-model SQL for --direct (D-045)


def test_questions_are_balanced():
    questions = load("chinook_questions.yaml")["questions"]
    assert sorted(q["tier"] for q in questions) == ["easy"] * 10 + ["hard"] * 10 + ["medium"] * 10


def test_scoring_ignores_column_and_row_order_and_rounds_numbers():
    from eval.run import normalise
    reference = [("Rock", Decimal("826.6500")), ("Jazz", 79)]
    assert normalise([(79.0, "Jazz"), (826.649, "Rock")]) == normalise(reference)
    assert normalise([("04",)]) == normalise([(Decimal("4"),)])   # to_char month vs EXTRACT


def test_scoring_counts_extra_columns_and_duplicates_as_wrong():
    from eval.run import normalise
    assert normalise([("Rock", 826.65, 1)]) != normalise([("Rock", 826.65)])
    assert normalise([("a",), ("a",)]) != normalise([("a",)])
