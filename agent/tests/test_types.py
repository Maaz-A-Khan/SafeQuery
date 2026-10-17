"""The shared types behave as the other modules expect."""

from agent.types import (
    Attempt, Column, Dialect, ForeignKey, Outcome, Result, RuleHit, Schema, StoppedBy,
    Table, Target, Verdict,
)

SCHEMA = Schema(
    Dialect.POSTGRESQL,
    {
        "artist": Table("artist", (Column("artist_id", "INTEGER", False, True), Column("name", "VARCHAR(120)"))),
        "album": Table(
            "album",
            (Column("album_id", "INTEGER", False, True), Column("artist_id", "INTEGER", False)),
            (ForeignKey(("artist_id",), "artist", ("artist_id",)),),
        ),
    },
    restricted={"user_credentials"},
)


def test_schema_json_round_trip():
    again = Schema.from_json(SCHEMA.to_json(), restricted=["user_credentials"])
    assert again == SCHEMA
    assert again.schema_hash() == SCHEMA.schema_hash()


def test_schema_hash_ignores_restricted_list_but_not_structure():
    same = Schema.from_json(SCHEMA.to_json(), restricted=[])
    assert same.schema_hash() == SCHEMA.schema_hash()
    data = SCHEMA.to_json()
    data["tables"][0]["columns"].append({"name": "extra", "type": "TEXT"})
    assert Schema.from_json(data).schema_hash() != SCHEMA.schema_hash()


def test_result_summaries():
    block = Verdict(False, "DELETE FROM album", (
        RuleHit("R3", "Read-only statement", "block", "This system can only read data, not change it."),
        RuleHit("R4", "No write nodes", "block", "The query contains an operation that would modify the database."),
    ))
    result = Result(
        question="delete all albums",
        outcome=Outcome.BLOCKED,
        stopped_by=StoppedBy.VALIDATOR,
        attempts=[Attempt(1, "DELETE FROM album", verdict=block)],
    )
    assert result.attempt_count == 1
    assert result.rules_fired == ["R3", "R4"]
    assert [h.rule_id for h in result.block_hits] == ["R3", "R4"]
    assert result.rows_returned is None


def test_target_repr_hides_url():
    target = Target(1, Dialect.POSTGRESQL, SCHEMA, url="postgresql://agent_ro:secret@localhost/chinook")
    assert "secret" not in repr(target)
