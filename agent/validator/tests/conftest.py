"""Fixtures for validator tests: the small shop schema used in the rule base examples."""

from __future__ import annotations

import pytest

from agent.types import Column, Dialect, ForeignKey, Schema, Table
from agent.validator import validate


def _table(name: str, *columns: str, fks: tuple[ForeignKey, ...] = ()) -> Table:
    cols = tuple(Column(c, "INT" if c == "id" or c.endswith("_id") else "TEXT", primary_key=c == "id")
                 for c in columns)
    return Table(name, cols, fks)


def _fk(column: str, table: str) -> ForeignKey:
    return ForeignKey((column,), table, ("id",))


SHOP = Schema(
    dialect=Dialect.POSTGRESQL,
    tables={t.name: t for t in [
        _table("customers", "id", "name", "email", "password_hash", "region_id",
               fks=(_fk("region_id", "regions"),)),
        _table("orders", "id", "customer_id", "status", "total", "created_at",
               fks=(_fk("customer_id", "customers"),)),
        _table("order_items", "id", "order_id", "product_id", "quantity",
               fks=(_fk("order_id", "orders"), _fk("product_id", "products"))),
        _table("products", "id", "name", "category_id", "supplier_id",
               fks=(_fk("category_id", "categories"), _fk("supplier_id", "suppliers"))),
        _table("categories", "id", "name"),
        _table("suppliers", "id", "name", "region_id"),
        _table("regions", "id", "name"),
        _table("warehouses", "id", "name", "region_id"),
        _table("shipments", "id", "order_id", "warehouse_id", "drop_date"),
        _table("auth_user", "id", "email", "password_hash"),
        _table("authors", "id", "name"),
    ]},
    restricted_tables={"auth_user"},
    restricted_columns={"customers.password_hash", "auth_user.password_hash"},
)


@pytest.fixture
def shop_schema() -> Schema:
    return SHOP


@pytest.fixture
def check(shop_schema):
    """check(sql) -> Verdict, on the shop schema in PostgreSQL."""
    def _check(sql: str, dialect: Dialect = Dialect.POSTGRESQL, **kwargs):
        return validate(sql, shop_schema, dialect, **kwargs)
    return _check
