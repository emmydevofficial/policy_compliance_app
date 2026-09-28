# Deployment notes

Written for whoever installs and runs Obligation Desk on a Linux server.

## Layout

```
/srv/obligation-desk/app            the code, a virtualenv in .venv, the .env file
/srv/obligation-desk/data           db.sqlite3 (DATABASE_URL=sqlite:////srv/obligation-desk/data/db.sqlite3)
/srv/obligation-desk/private_media  evidence files (PRIVATE_MEDIA_ROOT); nginx serves it only as internal
/srv/obligation-desk/cache          rate-limit cache (CACHE_DIR)
```

All owned by the `obligationdesk` user, mode 0750. Nothing under `private_media` is ever
served by a public nginx location.

## Install

```
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env    # fill in every value; see below
DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py collectstatic --noinput
DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py check --deploy
```

WeasyPrint needs Pango: `apt install libpango-1.0-0 libpangoft2-1.0-0`.

Required in `.env` for production: `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`,
`DATABASE_URL`, `EMAIL_HOST` (and user, password, port, TLS), `DEFAULT_FROM_EMAIL`,
`SITE_URL`, `PRIVATE_MEDIA_ROOT`, `CACHE_DIR`, `USE_X_ACCEL_REDIRECT=True`.

Copy the unit files in this folder to `/etc/systemd/system/`, the nginx file to
`/etc/nginx/sites-available/`, then:

```
systemctl enable --now obligation-desk obligation-desk-notices.timer
```

Before trusting the reminder schedule, run
`manage.py run_daily_notices --dry-run --as-of YYYY-MM-DD` for a few dates. It writes and
sends nothing.

## Migrations

Migrations are a deliberate deployment step:

1. Read the new migration files in the release. Look for `RemoveField`, `DeleteModel`,
   `AlterField` that narrows a type, and any `RunSQL`.
2. Back up the database and the files (below).
3. `manage.py migrate`, run by a person, on the server.

Never run migrations against the production database from a development machine, and never
edit a migration that has been applied anywhere; add a new one.

## Backups

The database and the evidence files are backed up together, on the same schedule. A
database restored without its files is useless in an audit, because every attachment row
records a SHA-256 hash that the file must still match.

SQLite (current configuration), daily:

```
sqlite3 /srv/obligation-desk/data/db.sqlite3 ".backup '/backup/od-$(date +%F).sqlite3'"
tar -C /srv/obligation-desk -czf /backup/od-files-$(date +%F).tgz private_media
```

Use `.backup` (or `VACUUM INTO`), never a plain `cp` of a live database in WAL mode. Ship
both files off the application server.

## The audit log is insert-only

In code, `AuditEvent.save()` refuses updates, `delete()` refuses deletes on the instance and
the queryset, and the Django admin grants no change or delete permission.

SQLite has no users or grants, so there is no database-level enforcement with the current
configuration. Anyone with shell access to the server can edit the file; protect it with
file permissions and the backups above.

If the database moves to PostgreSQL (set `DATABASE_URL=postgres://...` and
`pip install psycopg[binary]`; no code changes), make the application role insert-only on
this table:

```sql
REVOKE ALL ON audit_event FROM obligation_desk_app;
GRANT SELECT, INSERT ON audit_event TO obligation_desk_app;
GRANT USAGE, SELECT ON SEQUENCE audit_event_id_seq TO obligation_desk_app;
```

Migrations that touch `audit_event` must then be run by a separate owner role. Back up
PostgreSQL daily with `pg_dump`, retained off the application server, alongside the files.

## Email

Development always uses the console backend (`config/settings/dev.py` sets
`ALLOW_REAL_EMAIL=False`, and the sender refuses SMTP when that flag is off). Production
uses SMTP from the environment.
