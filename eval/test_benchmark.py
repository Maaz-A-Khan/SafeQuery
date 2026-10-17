"""Benchmarks (Phase 7). The format checks always run; the benchmarks themselves
call Gemini, so they run only with SAFEQUERY_RUN_BENCHMARK=1, at milestones."""

import os
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).parent
TIERS = {"easy", "medium", "hard"}
CATEGORIES = {"destructive", "injection", "sensitive", "resource", "side_effect"}
RULE_IDS = {f"R{n}" for n in range(1, 12)}

run_benchmark = pytest.mark.skipif(
    os.environ.get("SAFEQUERY_RUN_BENCHMARK") != "1", reason="set SAFEQUERY_RUN_BENCHMARK=1 to call Gemini"
)


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


@run_benchmark
def test_correctness_benchmark():
    pytest.skip("Phase 7")


@run_benchmark
def test_security_benchmark():
    pytest.skip("Phase 7")
