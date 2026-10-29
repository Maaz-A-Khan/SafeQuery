"""Introspection, restricted names, sample values and the prompt DDL (Phase 5)."""

from pathlib import Path

import pytest

from agent.config import AgentConfig, ValidatorConfig
from agent.connection import open_engine
from agent.schema import default_restricted, introspect, name_words, render_ddl
from agent.types import Column, Dialect, ForeignKey, Schema, Table

CONFIG = AgentConfig()
CHINOOK_SQLITE = Path(__file__).resolve().parents[2] / "db_setup" / "data" / "chinook.sqlite"


@pytest.mark.parametrize("name,words", [
    ("auth_user", ["auth", "user"]),
    ("UserCredentials", ["user", "credentials"]),
    ("HTTPToken", ["http", "token"]),
    ("password2", ["password", "2"]),
    ("InvoiceLine", ["invoice", "line"]),
])
def test_name_words(name, words):
    assert name_words(name) == words


def _schema(*tables: tuple[str, list[str]]) -> Schema:
    return Schema(Dialect.POSTGRESQL, {t: Table(t, tuple(Column(c, "TEXT") for c in cols)) for t, cols in tables})


def test_default_restricted_matches_whole_words_singular_or_plural():
    schema = _schema(
        ("auth_user", ["id"]), ("authors", ["id"]), ("UserSessions", ["id"]), ("tokenizer_runs", ["id"]),
        ("customers", ["name", "password_hash", "ssn", "hashtag", "passwords", "secret_question"]),
    )
    tables, columns = default_restricted(schema, ValidatorConfig())
    assert tables == {"auth_user", "UserSessions"}
    assert columns == {"customers.password_hash", "customers.ssn", "customers.passwords",
                       "customers.secret_question"}


def test_introspect_reads_tables_keys_and_restrictions(shop_url):
    schema = introspect(open_engine(shop_url, CONFIG), CONFIG)
    assert schema.dialect == Dialect.SQLITE
    assert set(schema.tables) == {"album", "artist", "authors", "orders", "user_credentials"}  # no view
    album = schema.tables["album"]
    assert [c.name for c in album.columns if c.primary_key] == ["album_id"]
    assert album.foreign_keys == (ForeignKey(("artist_id",), "artist", ("artist_id",)),)
    assert not next(c for c in album.columns if c.name == "title").nullable
    assert schema.restricted_tables == {"user_credentials"}
    assert schema.restricted_columns == {"orders.api_token", "user_credentials.password_hash"}


def test_sample_values_only_for_repeating_unrestricted_text(shop_url):
    schema = introspect(open_engine(shop_url, CONFIG), CONFIG)
    samples = {f"{t.name}.{c.name}": c.sample_values for t in schema.tables.values() for c in t.columns}
    assert samples["orders.status"] == ("cancelled", "pending", "shipped")
    assert samples["orders.note"] == ()                   # every value different: per-row data
    assert samples["artist.name"] == ()
    assert samples["user_credentials.username"] == ()     # restricted table: never queried
    assert samples["orders.api_token"] == ()              # restricted column


def test_too_many_distinct_values_means_no_samples(shop_url):
    config = AgentConfig(sample_values_max_distinct=2)
    schema = introspect(open_engine(shop_url, config), config)
    assert next(c for c in schema.tables["orders"].columns if c.name == "status").sample_values == ()


def test_refresh_keeps_the_users_choices(shop_url):
    engine = open_engine(shop_url, CONFIG)
    previous = introspect(engine, CONFIG)
    previous.restricted_tables = {"authors"}                       # user unticked user_credentials
    previous.restricted_columns = {"orders.status"}                # and api_token, added status
    del previous.tables["artist"]                                  # artist is "new" on refresh
    again = introspect(engine, CONFIG, previous)
    assert again.restricted_tables == {"authors"}
    assert again.restricted_columns == {"orders.status"}
    assert next(c for c in again.tables["orders"].columns if c.name == "status").sample_values == ()


def test_render_ddl_leaves_out_restricted_names(shop_url):
    ddl = render_ddl(introspect(open_engine(shop_url, CONFIG), CONFIG))
    assert "CREATE TABLE album (" in ddl
    assert "artist_id INTEGER NOT NULL REFERENCES artist(artist_id)" in ddl
    assert "status VARCHAR(20) NOT NULL, -- e.g. 'cancelled', 'pending', 'shipped'" in ddl
    assert "user_credentials" not in ddl and "api_token" not in ddl and "password" not in ddl
    assert "album_titles" not in ddl


def test_render_ddl_composite_keys_quoting_and_hidden_references():
    schema = Schema(Dialect.POSTGRESQL, {
        "Order Lines": Table("Order Lines", (
            Column("order_id", "INTEGER", False, True), Column("line_no", "INTEGER", False, True),
            Column("owner_id", "INTEGER"), Column("note", "TEXT", sample_values=("it's",)),
        ), (ForeignKey(("owner_id",), "auth_user", ("id",)),)),
    }, restricted_tables={"auth_user"})
    ddl = render_ddl(schema)
    assert 'CREATE TABLE "Order Lines" (' in ddl
    assert "PRIMARY KEY (order_id, line_no)" in ddl
    assert "-- e.g. 'it''s'" in ddl
    assert "auth_user" not in ddl


@pytest.mark.skipif(not CHINOOK_SQLITE.exists(), reason="run db_setup/setup_databases.py sqlite")
def test_chinook_sqlite():
    schema = introspect(open_engine(f"sqlite:///{CHINOOK_SQLITE.as_posix()}", CONFIG), CONFIG)
    assert len(schema.tables) == 12
    assert schema.restricted_tables == {"user_credentials"}
    title = next(c for c in schema.tables["Employee"].columns if c.name == "Title")
    assert "Sales Support Agent" in title.sample_values
