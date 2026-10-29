"""Run the Phase 7 benchmarks through the real pipeline (Evaluation Plan). Calls Gemini.

    python eval/run.py correctness                  # 30 Chinook questions, connection 1
    python eval/run.py security --run 1             # 15 attacks, everything on
    python eval/run.py security --run 2             # validator off (D-017)
    python eval/run.py security --run 3 --url-env SCRATCH_URL
                                                    # validator and database layers off,
                                                    # on the throwaway copy only
    python eval/run.py security --run 2 --direct    # each attack's own SQL in place of
                                                    # Gemini: a compromised model (D-045)

The cache is always off. Calls are paced to stay under the free-tier limit of 15 a
minute. Results go to `eval/results/<name>.csv`, one row per question; a re-run
skips the ids already there, so a run cut short by the daily quota resumes where
it stopped (`--fresh` starts over). Nothing here is used by the running app.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from collections import Counter
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import django
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "safequery.settings")
django.setup()

from django.conf import settings  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from agent import generator, pipeline  # noqa: E402
from agent.config import AgentConfig, Switches  # noqa: E402
from agent.connection import detect_dialect, open_engine  # noqa: E402
from agent.executor import execute  # noqa: E402
from agent.generator import Generation  # noqa: E402
from agent.schema import introspect  # noqa: E402
from agent.types import Result, StoppedBy, Target  # noqa: E402
from core.services import load_target  # noqa: E402

RESULTS = HERE / "results"   # git-ignored
CALLS_PER_MINUTE = 14        # the free tier allows 15 (D-040); one spare

# Ablation runs (Evaluation Plan § Ablation). Switches are changed only here.
RUN_SWITCHES = {
    1: Switches(cache=False),
    2: Switches(cache=False, validator=False),
    3: Switches(cache=False, validator=False, privilege_check=False, readonly_session=False),
}


class QuotaHit(Exception):
    """Gemini stopped answering (quota or outage): stop and resume later."""


# --- Gemini pacing and counting -------------------------------------------------------


class Pacer:
    """Wraps `generator.generate` so calls are spaced out and counted."""

    def __init__(self, per_minute: int):
        self.gap, self.last, self.calls = 60.0 / per_minute, 0.0, 0
        self._generate = generator.generate
        generator.generate = self   # the pipeline looks it up on the module

    def __call__(self, *args, **kwargs):
        wait = self.last + self.gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()
        self.calls += 1
        return self._generate(*args, **kwargs)


# --- Comparing result sets ------------------------------------------------------------


def _value(v) -> str:
    """One cell, normalised: numbers (also numeric text such as '04') to 2 decimals."""
    if v is None:
        return "NULL"
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float, Decimal)):
        return f"{round(Decimal(str(v)), 2):.2f}"
    try:
        return f"{round(Decimal(str(v).strip()), 2):.2f}"
    except (InvalidOperation, ValueError):
        return str(v).strip()


def normalise(rows) -> Counter:
    """Rows as a multiset; column names and column order are ignored."""
    return Counter(tuple(sorted(_value(v) for v in row)) for row in rows)


# --- Targets and output ---------------------------------------------------------------


def _target(args, config: AgentConfig) -> Target:
    if args.url_env:
        url = os.environ.get(args.url_env) or sys.exit(f"Set {args.url_env} to the connection string.")
        engine = open_engine(url, config)
        try:
            schema = introspect(engine, config)
        finally:
            engine.dispose()
        return Target(0, detect_dialect(url), schema, url)
    return load_target(args.connection)


def _done(path: Path, fresh: bool) -> tuple[list[dict], set[str]]:
    if fresh or not path.exists():
        return [], set()
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows, {r["id"] for r in rows}


def _save(path: Path, rows: list[dict]) -> None:
    RESULTS.mkdir(exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _ask(target: Target, question: str, config: AgentConfig, pacer: Pacer) -> tuple[Result, int]:
    before = pacer.calls
    result = pipeline.run(target, question, config, cache=None)
    if result.stopped_by == StoppedBy.SERVICE:
        raise QuotaHit(result.message)
    return result, pacer.calls - before


def _last_sql(result: Result) -> str:
    return result.sql or next((a.sql for a in reversed(result.attempts) if a.sql), "") or ""


# --- Correctness ----------------------------------------------------------------------


def correctness(args) -> None:
    config = replace(settings.SAFEQUERY, switches=RUN_SWITCHES[1])
    target = _target(args, config)
    questions = yaml.safe_load((HERE / "chinook_questions.yaml").read_text(encoding="utf-8"))["questions"]
    if args.only:
        questions = [q for q in questions if q["id"] in args.only.split(",")]
    path = RESULTS / "correctness.csv"
    rows, done = _done(path, args.fresh)
    engine, pacer = open_engine(target.url, config), Pacer(CALLS_PER_MINUTE)
    try:
        for q in questions:
            if q["id"] in done:
                continue
            reference = execute(engine, q["reference_sql"], config.executor)
            result, calls = _ask(target, q["question"], config, pacer)
            correct = result.outcome == "answered" and normalise(result.rows) == normalise(reference.rows)
            rows.append({
                "id": q["id"], "tier": q["tier"], "question": q["question"], "correct": int(correct),
                "outcome": result.outcome.value, "stopped_by": result.stopped_by.value,
                "attempts": result.attempt_count, "corrected": int(result.attempt_count > 1),
                "plan_steps": len(result.plan), "gemini_calls": calls,
                "rows": result.rows_returned if result.rows_returned is not None else "",
                "reference_rows": len(reference.rows), "sql": _last_sql(result), "message": result.message,
            })
            _save(path, rows)
            print(f"{q['id']}: {'correct' if correct else 'WRONG'} ({result.stopped_by.value}, {calls} calls)")
    except QuotaHit as exc:
        print(f"\nStopped: {exc}\nRe-run the same command to resume.")
    finally:
        engine.dispose()
    _correctness_summary(rows)


def _correctness_summary(rows: list[dict]) -> None:
    print("\n| Tier | Questions | Correct | Needed correction | Accuracy |\n| :--- | :--- | :--- | :--- | :--- |")
    for tier in ("easy", "medium", "hard", None):
        part = [r for r in rows if tier is None or r["tier"] == tier]
        if not part:
            continue
        right = sum(int(r["correct"]) for r in part)
        fixed = sum(int(r["corrected"]) for r in part)
        name = tier.capitalize() if tier else "**Total**"
        print(f"| {name} | {len(part)} | {right} | {fixed} | {right / len(part):.0%} |")
    if rows:
        calls = sum(int(r["gemini_calls"]) for r in rows) / len(rows)
        print(f"\nAverage Gemini calls per question: {calls:.2f}")


# --- Security and ablation ------------------------------------------------------------


def _snapshot(url: str) -> dict[str, int]:
    """Row count per table, read straight from the database to see what an attack changed."""
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            names = inspect(conn).get_table_names()
            return {n: conn.execute(text(f'SELECT COUNT(*) FROM "{n}"')).scalar() for n in names}
    finally:
        engine.dispose()


def _changes(before: dict[str, int], after: dict[str, int]) -> str:
    out = [f"dropped {t}" for t in before if t not in after]
    out += [f"created {t}" for t in after if t not in before]
    out += [f"{t} {before[t]}->{after[t]} rows" for t in before if t in after and before[t] != after[t]]
    return "; ".join(out)


def security(args) -> None:
    config = replace(settings.SAFEQUERY, switches=RUN_SWITCHES[args.run])
    if args.direct:   # one attempt: a correction would need a model, and there is none
        config = replace(config, gemini=replace(config.gemini, max_attempts=1))
    if args.run == 3:
        if not args.url_env:
            sys.exit("Run 3 needs --url-env pointing at the throwaway copy.")
        database = make_url(os.environ.get(args.url_env, "")).database or ""
        if "scratch" not in database:   # never point the writable run at a real database
            sys.exit(f"Run 3 only runs on a database whose name contains 'scratch', not {database!r}.")
    target = _target(args, config)
    attacks = yaml.safe_load((HERE / "attacks.yaml").read_text(encoding="utf-8"))["attacks"]
    if args.only:
        attacks = [a for a in attacks if a["id"] in args.only.split(",")]
    path = RESULTS / f"security_run{args.run}{'_direct' if args.direct else ''}.csv"
    rows, done = _done(path, args.fresh)
    if args.direct:   # the "model" writes exactly the attack's SQL; installed before Pacer wraps it
        by_prompt = {a["prompt"]: a["sql"] for a in attacks}
        generator.generate = lambda question, *_, **__: Generation(
            sql=by_prompt[question], explanation="attack SQL (direct)", steps=[])
    pacer = Pacer(6000 if args.direct else CALLS_PER_MINUTE)
    try:
        for a in attacks:
            if a["id"] in done:
                continue
            before = _snapshot(target.url)
            started = time.monotonic()
            result, calls = _ask(target, a["prompt"], config, pacer)
            changes = _changes(before, _snapshot(target.url))
            reached = any(at.exec_ms is not None or at.error for at in result.attempts)
            rows.append({
                "id": a["id"], "category": a["category"], "prompt": a["prompt"],
                "stopped_by": result.stopped_by.value, "outcome": result.outcome.value,
                "rules_fired": " ".join(dict.fromkeys(h.rule_id for h in result.block_hits)),
                "expect_rules": " ".join(a["expect_rules"]),
                "reached_database": int(reached), "rows": result.rows_returned if result.rows_returned is not None else "",
                "columns": " ".join(result.columns), "changes": changes,
                "seconds": round(time.monotonic() - started, 1), "gemini_calls": calls,
                "sql": _last_sql(result), "message": result.message,
                "error": next((at.error for at in reversed(result.attempts) if at.error), "") or "",
            })
            _save(path, rows)
            print(f"{a['id']}: {result.stopped_by.value}{' ' + rows[-1]['rules_fired'] if rows[-1]['rules_fired'] else ''}"
                  f"{' CHANGED ' + changes if changes else ''}")
    except QuotaHit as exc:
        print(f"\nStopped: {exc}\nRe-run the same command to resume.")
    _security_summary(rows, f"Run {args.run}{' (direct SQL)' if args.direct else ''}")


def _security_summary(rows: list[dict], title: str) -> None:
    print(f"\n{title}\n| Category | Prompts | Refused by Gemini | Blocked by validator | Stopped by database"
          " | Got through | Reached database | Rules |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for category in ("destructive", "injection", "sensitive", "resource", "side_effect"):
        part = [r for r in rows if r["category"] == category]
        if not part:
            continue
        by = Counter(r["stopped_by"] for r in part)
        rules = " ".join(sorted({x for r in part for x in r["rules_fired"].split()}))
        reached = sum(int(r["reached_database"]) for r in part)
        print(f"| {category} | {len(part)} | {by['model']} | {by['validator']} | {by['database']} | {by['none']}"
              f" | {reached} | {rules} |")
    changed = [f"{r['id']}: {r['changes']}" for r in rows if r["changes"]]
    if changed:
        print("\nDatabase changed by:\n  " + "\n  ".join(changed))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func in (("correctness", correctness), ("security", security)):
        p = sub.add_parser(name)
        p.add_argument("--connection", type=int, default=1, help="saved connection id (default 1, Chinook PostgreSQL)")
        p.add_argument("--url-env", help="read the connection string from this environment variable instead")
        p.add_argument("--only", help="comma-separated ids, e.g. E01,H03")
        p.add_argument("--fresh", action="store_true", help="ignore earlier results and start over")
        p.set_defaults(func=func)
        if name == "security":
            p.add_argument("--run", type=int, choices=(1, 2, 3), default=1, help="ablation run (default 1)")
            p.add_argument("--direct", action="store_true",
                           help="send each attack's own SQL instead of asking Gemini (no Gemini calls)")
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
