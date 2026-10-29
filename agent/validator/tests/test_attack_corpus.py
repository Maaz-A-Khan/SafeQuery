"""Hundreds of attacks must be blocked; ordinary queries must be allowed. Owner: Afraz.

The queries live in `attack_corpus.py`. A failure here names the attack, so it
can be added to the rule that should have caught it.
"""

import pytest

from agent.types import Dialect
from agent.validator import validate
from agent.validator.tests.attack_corpus import BENIGN, all_attacks

ATTACK_CASES = all_attacks()


def test_corpus_is_large():
    assert len(ATTACK_CASES) >= 500


@pytest.mark.parametrize("dialect,sql", [(d, s) for _, d, s in ATTACK_CASES], ids=[i for i, _, _ in ATTACK_CASES])
def test_attack_is_blocked(shop_schema, dialect, sql):
    verdict = validate(sql, shop_schema, Dialect(dialect))
    assert not verdict.allowed, f"ALLOWED: {sql!r} -> {verdict.sql!r}"
    assert verdict.blocks, "a block must explain itself with at least one rule message"


@pytest.mark.parametrize("dialect,sql", BENIGN, ids=[f"{d}-{n}" for n, (d, _) in enumerate(BENIGN)])
def test_ordinary_query_is_allowed(shop_schema, dialect, sql):
    verdict = validate(sql, shop_schema, Dialect(dialect))
    assert verdict.allowed, f"BLOCKED: {sql!r} -> {[(h.rule_id, h.message) for h in verdict.blocks]}"
