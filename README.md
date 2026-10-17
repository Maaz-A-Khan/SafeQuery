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

copy .env.example .env         # then fill in DJANGO_SECRET_KEY, DATABASE_URL password, FERNET_KEY
python db_setup/setup_databases.py postgres   # app DB + Chinook + read-only user; asks for the postgres password
python db_setup/setup_databases.py sqlite     # Chinook as a SQLite file

python manage.py migrate
python manage.py createsuperuser              # for the Log page
python manage.py runserver 127.0.0.1:8000
```

Open http://127.0.0.1:8000/. Both setup commands print the connection string to
paste on the Connect page. Keep `runserver` on `127.0.0.1`: Connect and Ask need
no login, so `0.0.0.0` would open them to everyone on the network (and
`ALLOWED_HOSTS` refuses other hosts anyway).

Note: Chinook's tables are `snake_case` in PostgreSQL (`invoice_line`) and
`PascalCase` in SQLite (`InvoiceLine`).

## Tests

```powershell
pytest                                   # everything; skipped tests are phases not built yet
pytest agent/validator                   # one area
$env:SAFEQUERY_RUN_BENCHMARK="1"; pytest eval   # benchmarks, calls Gemini: milestones only
```

pytest creates its own test database, so the `safequery` role has `CREATEDB`.

## Who works where

Work only inside your own folders, on your own branch. Changes reach `main` only
through a pull request that Maaz reviews. A branch is done when its tests pass.

| Member | Folders | Start from |
| :--- | :--- | :--- |
| Afraz | `agent/validator/`, `eval/attacks.yaml` | `rules.py` (one class per rule, every `check` is a TODO), `engine.py` (`validate` is a stub that allows everything; its docstring is the contract), tests in `agent/validator/tests/` (remove each file's `skip` as the rule is built) |
| Sunil | `core/audit/` | `service.py` (`log_request`, `cache_lookup`, `cache_save`), `models.py` (`QueryLog`, `QueryCache`), `views.py` (Log page; keep the superuser check), tests in `core/audit/tests/` |
| Fouzan | `core/templates/`, `core/static/` | the placeholder templates; every page's context is documented in `core/sample_context.py` |
| Maaz | `agent/` (except `validator/`), `core/` (rest), `eval/` questions, `db_setup/` | `agent/connection.py`, `agent/schema.py` (Phase 5), then `generator.py`, `executor.py`, `pipeline.py` (Phase 6) |

### Fixed interfaces

Agreed in Phase 1. Change them only after the whole team agrees.

- **Shared types** (`agent/types.py`): `Schema`, `Verdict`, `RuleHit`, `Attempt`,
  `Result`, `Outcome`, `StoppedBy`, `Target`.
- **Validator**: `agent.validator.validate(sql, schema, dialect, *, config, explain) -> Verdict`.
  Rules subclass `agent.validator.base.Rule` and run by `Stage`: PARSE, TREE,
  REWRITE (R11), then COST (R10), so the cost check sees the added `LIMIT`.
- **Audit**: `log_request(connection_id, result)`, `cache_lookup(connection_id, question, schema_hash)`,
  `cache_save(connection_id, question, schema_hash, sql)` in `core/audit/service.py`.
- **Views → agent**: `core.services.answer_question(connection_id, question) -> Result`.
  It calls the Django-free `agent.pipeline.run(target, question, config, cache)`.
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
eval/           chinook_questions.yaml, attacks.yaml, test_benchmark.py
db_setup/       setup_databases.py, sql/ (app DB, read-only user, sensitive seed table)
```
