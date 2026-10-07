# Obligation Desk

A regulatory compliance obligation register with an evidence request, submission and
verification workflow, for a Nigerian electricity transmission licensee. Django 5.2, SQLite,
HTMX and Alpine.js, server-rendered.

## Run it locally

```
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env                    # set SECRET_KEY
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo    # --reset to start again
.venv/bin/python manage.py runserver
```

Sign in at http://localhost:8000. The password is `DEMO_PASSWORD` from your `.env`, or, if
that is not set, the random one `seed_demo` prints at the end.

| Role | Email |
|---|---|
| Admin (GM, Regulation & Compliance) | gm.regcompliance@example.org |
| Department GM | gm.hse@example.org (any `gm.<code>@example.org`) |
| Compliance officer | officer.hse@example.org (any `officer.<code>@example.org`) |
| Executive | exec.md@example.org, exec.ed@example.org |

Department codes: RC, CP, LEGAL, TS, FIN, BD, RISK, ACS, PROC, MCS, HSE, CSS, ICT, SPD, PCM,
ENG, TMS, IR, REGIONS, ME.

Email goes to the console in development; nothing real is ever sent.

## Commands

```
manage.py seed_demo [--reset] [--force-in-production]
manage.py import_obligations <workbook.xlsx> [--dry-run] [--sheet NAME] [--keep-missing]
manage.py run_daily_notices [--dry-run] [--as-of YYYY-MM-DD]
```

## Tests and checks

```
.venv/bin/pytest
.venv/bin/ruff format --check . && .venv/bin/ruff check .
```

The permission matrix is `apps/core/tests/test_permission_matrix.py`. It fails if a URL is
added without being put in the matrix, or if a view lacks a permission decorator.

## Deployment

See `deploy/DEPLOYMENT.md`.

## Out of scope in this build

Single sign-on, SMS delivery (the preference and phone number exist; no gateway), historical
comparison across periods beyond what the data model supports, a contributor role for
supporting departments, and any integration with a regulator's systems.
