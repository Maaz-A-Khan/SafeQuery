# SafeQuery

Ask questions about your own database in plain English. Gemini proposes SQL; a
rule-based validator decides whether it may run; it runs through a read-only account.

AI and Expert Systems, NED University. Team: Maaz (lead), Afraz, Sunil, Fouzan.
The design notes (requirements, rule base, phases) are the source of truth; this
README only covers setup and where to work.

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
python eval/run.py correctness           # 30 Chinook questions -> eval/results/correctness.csv
python eval/run.py security --run 1      # 15 attacks, everything on (run 2: validator off)
```

pytest creates its own test database, so the `safequery` role has `CREATEDB`.

## Who works where

Work only inside your own folders, on your own branch. Changes reach `main` only
through a pull request that Maaz reviews. A branch is done when its tests pass.

| Member | Folders | What is there |
| :--- | :--- | :--- |
| Afraz | `agent/validator/`, `eval/attacks.yaml` | Rules R1 to R11 in `rules.py`, the staged engine in `engine.py`, a test file per rule plus `test_engine.py` and the attack corpus (`attack_corpus.py`, 1,883 attacks, 87 benign queries) |
| Sunil | `core/audit/` | `QueryLog` and `QueryCache`, `log_request`, the cache, anomaly flags, the superuser-only Log pages |
| Fouzan | `core/templates/`, `core/static/` | Every page in the Clearance design; each page's context is documented in `core/sample_context.py` |
| Maaz | `agent/` (except `validator/`), `core/` (rest), `eval/` questions, `db_setup/` | Connection and schema (`connection.py`, `schema.py`), the Gemini client, executor and pipeline (`generator.py`, `executor.py`, `pipeline.py`), the Ask page and CSV download |

Phases 1 to 6 are built; Phase 7 (integration and evaluation) is in progress. Progress and
every decision are in the design notes' Status and Change Log and Decision Log.

### Fixed interfaces

Agreed in Phase 1. Change them only after the whole team agrees.

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
  in `safequery/settings.py` as `SAFEQUERY`. The switches are off only in the ablation run.

`agent/` never imports Django, so it can be tested on its own.

## Layout

```
manage.py, requirements.txt, .env.example, pytest.ini
safequery/      settings, urls
core/           models (DatabaseConnection, SchemaSnapshot), views, forms, services, sample_context
  audit/        QueryLog, QueryCache, log_request, cache, Log views        (Sunil)
  templates/    all pages                                                (Fouzan)
  static/
agent/          types, config, connection, schema, generator, executor, pipeline
  validator/    base, rules (R1 to R11), engine, tests                   (Afraz)
eval/           chinook_questions.yaml, attacks.yaml, run.py (benchmarks), test_benchmark.py
db_setup/       setup_databases.py, sql/ (app DB, read-only user, sensitive seed table)
```
