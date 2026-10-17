"""R9 Join limit. Owner: Afraz.

Boundary: exactly 6 joins is allowed. Comma joins count as joins.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Phase 2: R9 not implemented yet")

BLOCKED = [
    'SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id JOIN order_items i ON i.order_id = o.id JOIN products p ON p.id = i.product_id JOIN categories k ON k.id = p.category_id JOIN suppliers s ON s.id = p.supplier_id JOIN regions r ON r.id = s.region_id JOIN warehouses w ON w.region_id = r.id JOIN shipments sh ON sh.warehouse_id = w.id',
    'SELECT * FROM orders, customers, order_items, products, categories, suppliers, regions, warehouses, shipments',
]

ALLOWED = [
    'SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id JOIN order_items i ON i.order_id = o.id JOIN products p ON p.id = i.product_id',
    'SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id JOIN order_items i ON i.order_id = o.id JOIN products p ON p.id = i.product_id JOIN categories k ON k.id = p.category_id JOIN suppliers s ON s.id = p.supplier_id JOIN regions r ON r.id = s.region_id',
]


@pytest.mark.parametrize("sql", BLOCKED)
def test_blocks(check, sql):
    verdict = check(sql)
    assert not verdict.allowed
    assert "R9" in verdict.rule_ids


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows(check, sql):
    assert "R9" not in check(sql).rule_ids
