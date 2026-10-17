"""Audit log, cache and anomaly flags. Owner: Sunil (Phase 3)."""

import pytest

from core.audit.service import normalise_question


def test_normalise_question():
    assert normalise_question("  Top 5   Artists\n by Tracks ") == "top 5 artists by tracks"


pending = pytest.mark.skip(reason="Phase 3: not implemented yet")


@pending
def test_log_request_writes_one_row_per_question():
    ...


@pending
def test_log_never_stores_rows_or_connection_strings():
    ...


@pending
def test_failed_log_write_does_not_raise_into_the_pipeline():
    ...


@pending
def test_cache_hit_on_same_question_and_schema():
    ...


@pending
def test_cache_miss_after_schema_change():
    ...


@pending
def test_flag_many_tables():
    ...


@pending
def test_flag_row_spike():
    ...


@pending
def test_flag_third_block_in_ten_minutes():
    ...
