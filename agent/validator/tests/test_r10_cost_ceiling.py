"""R10 Cost ceiling. Owner: Afraz.

`explain` is faked, so these tests need no database. R10 must EXPLAIN the SQL
after R11 has added its LIMIT.
"""

import pytest


def fake_explain(total_cost):
    seen = []

    def explain(sql):
        seen.append(sql)
        return {"Plan": {"Total Cost": total_cost}}   # shape of PostgreSQL EXPLAIN (FORMAT JSON)[0]

    explain.seen = seen
    return explain


@pytest.mark.parametrize("cost", [100_001, 5_000_000])
def test_blocks_expensive(check, cost):
    verdict = check("SELECT o.id FROM orders o CROSS JOIN products p", explain=fake_explain(cost))
    assert not verdict.allowed
    assert "R10" in verdict.rule_ids


@pytest.mark.parametrize("cost", [10, 99_999])
def test_allows_cheap(check, cost):
    assert "R10" not in check("SELECT * FROM orders WHERE id = 1", explain=fake_explain(cost)).rule_ids


def test_skipped_without_explain(check):
    assert "R10" not in check("SELECT o.id FROM orders o CROSS JOIN products p").rule_ids


def test_explains_the_rewritten_sql(check):
    explain = fake_explain(10)
    check("SELECT * FROM orders", explain=explain)
    assert "LIMIT 1000" in explain.seen[-1].upper()
