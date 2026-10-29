# SafeQuery

Ask questions about your own database in plain English. Gemini proposes SQL; a
rule-based validator decides whether it may run; it runs through a read-only account.


The design notes (requirements, rule base, decisions) are the source of truth; this
README covers setup, tests and the code layout.

## How it works

1. **Generate.** Gemini gets the question and the schema structure: table and column
   names, types and keys. Restricted tables and columns are left out, and **no row
   data is ever sent**: no results, no sample values, no values quoted in errors.
2. **Validate.** An expert system of eleven rules (R1 to R11) parses the SQL with
   sqlglot and blocks writes, hidden statements, restricted data, system catalogs,
   unlisted functions and runaway queries, explaining every block. It adds a
   `LIMIT` if one is missing.
3. **Execute.** Only the validated SQL runs, on an account the privilege check has
   confirmed can only read, inside a read-only transaction, with a 5-second
   timeout and a 1000-row cap. A database error goes back to Gemini for a
   correction, up to 3 attempts; a block is never retried.

Every question is recorded in the audit log (never its results), which the
superuser reviews on the Log page.

## Setup

Needs Python 3.11+, PostgreSQL 15+ and Git. Windows PowerShell shown; on macOS or
Linux use `source .venv/bin/activate` and `cp` instead.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env         # then fill in DJANGO_SECRET_KEY, DATABASE_URL password, FERNET_KEY, GEMINI_API_KEY
python db_setup/setup_databases.py postgres   # app DB + Chinook + read-only user; asks for the postgres password
python db_setup/setup_databases.py sqlite     # Chinook as a SQLite file

python manage.py migrate
python manage.py createsuperuser              # for the Log page
python manage.py runserver 127.0.0.1:8000
```

Open http://127.0.0.1:8000/. Both setup commands print the connection string to
paste on the Connect page. Keep `runserver` on `127.0.0.1`: Connect and Ask need
no login, so the app only serves this computer. `LocalOnlyMiddleware` refuses any
request from another address, even if the server is started on `0.0.0.0`.

Note: Chinook's tables are `snake_case` in PostgreSQL (`invoice_line`) and
`PascalCase` in SQLite (`InvoiceLine`).

**Gemini quota.** The free tier for `gemini-3.5-flash-lite` allows 15 requests a
minute and about 500 a day (the real figure for your key is on
aistudio.google.com/rate-limit). Every question asked on the Ask page uses at
least one; tests never call Gemini.

## Tests

```powershell
pytest                                   # everything; never calls Gemini
pytest agent/validator                   # one area
```

Benchmarks call Gemini, so they are a separate command, run at milestones only
(paced to 14 calls a minute; a run cut short by the quota resumes where it stopped):

```powershell
python eval/run.py correctness              # 30 Chinook questions -> eval/results/correctness.csv
python eval/run.py security --run 1         # 15 attacks, everything on (run 2: validator off)
python eval/run.py security --run 2 --direct   # each attack's own SQL in place of Gemini
python eval/run.py security --run 3 --direct --url-env SCRATCH_URL   # every layer off, throwaway copy only
```

Run 3 needs a throwaway copy of Chinook whose database name contains `scratch`,
with an account that owns the tables; it refuses any other database. Results are
in the design notes' Evaluation Plan.

pytest creates its own test database, so the `safequery` role has `CREATEDB`.

## Interfaces

- **Shared types** (`agent/types.py`): `Schema`, `Verdict`, `RuleHit`, `Attempt`,
  `Result`, `Outcome`, `StoppedBy`, `Target`.
- **Validator**: `agent.validator.validate(sql, schema, dialect, *, config, explain) -> Verdict`.
  Rules subclass `agent.validator.base.Rule` and run by `Stage`: PARSE, TREE,
  REWRITE (R11), then COST (R10), so the cost check sees the added `LIMIT`.
- **Audit**: `log_request(connection_id, result) -> log id`, `cache_lookup(connection_id, question, schema_hash)`,
  `cache_save(connection_id, question, schema_hash, sql)` in `core/audit/service.py`.
- **Views → agent**: `core.services.answer_question(connection_id, question) -> (Result, log id)`.
  It calls the Django-free `agent.pipeline.run(target, question, config, cache)`;
  the log id is for the CSV link.
- **Templates**: the dictionaries in `core/sample_context.py`. Preview any state
  with `?state=`, e.g. `/ask/1/?state=blocked`, `/connect/?state=refused`, `/log/?state=empty`.
- **Settings**: limits, lists and safety switches in `agent/config.py`, built
  in `safequery/settings.py` as `SAFEQUERY`. The switches are changed only by the
  ablation runs in `eval/run.py`.

`agent/` never imports Django, so it can be tested on its own.

## Layout

```
manage.py, requirements.txt, .env.example, pytest.ini
safequery/      settings, urls
core/           models (DatabaseConnection, SchemaSnapshot), views, forms, services, sample_context
  audit/        QueryLog, QueryCache, log_request, cache, Log views
  templates/    all pages
  static/
agent/          types, config, connection, schema, generator, executor, pipeline
  validator/    base, rules (R1 to R11), engine, tests, attack_corpus (1,883 attacks, 87 benign queries)
eval/           chinook_questions.yaml, attacks.yaml, run.py (benchmarks), test_benchmark.py
db_setup/       setup_databases.py, sql/ (app DB, read-only user, sensitive seed table)
```
