"""The inference engine. Owner: Afraz.

Phase 1 STUB: allows every query unchanged, so the pipeline can be built and
tested before the real rules are merged. Never connect a writable account
while this stub is in place.
"""

from __future__ import annotations

from typing import Callable

from agent.config import ValidatorConfig
from agent.types import Dialect, Schema, Verdict


def validate(
    sql: str,
    schema: Schema,
    dialect: Dialect,
    *,
    config: ValidatorConfig | None = None,
    explain: Callable[[str], dict] | None = None,
) -> Verdict:
    """Decide whether `sql` may run.

    Contract (Phase 2 must keep it):
    - Parse with sqlglot using `dialect`, then run `rules.ALL_RULES` stage by
      stage: PARSE, TREE, REWRITE, COST (see `base.Stage`).
    - A PARSE failure blocks immediately; within TREE every rule runs and every
      violation is collected.
    - COST runs on the SQL produced by REWRITE.
    - Fails closed: any unexpected exception is a BLOCK, never an ALLOW (NFR-S3).
    - Returns `Verdict(allowed, sql, hits)`; `sql` is the rewritten SQL to execute.
    - Pure apart from `explain`: the same input always gives the same verdict.
    """
    # TODO(Afraz): replace this stub with the engine described above.
    return Verdict(allowed=True, sql=sql, hits=())
