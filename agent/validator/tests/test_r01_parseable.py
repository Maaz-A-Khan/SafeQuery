"""R1 Parseable. Owner: Afraz.

A parse failure blocks with "The generated query could not be parsed."
"""

import pytest


BLOCKED = [
    'SELEC * FORM orders',
    'SELECT * FROM (orders',
    '',
    ';',
    '   -- only a comment',
]

ALLOWED = [
    'SELECT * FROM orders',
    'SELECT name FROM customers WHERE id = 1',
]


@pytest.mark.parametrize("sql", BLOCKED)
def test_blocks(check, sql):
    verdict = check(sql)
    assert not verdict.allowed
    assert "R1" in verdict.rule_ids


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows(check, sql):
    assert "R1" not in check(sql).rule_ids
