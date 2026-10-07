# Obligation Desk on a VPS: step-by-step setup (demonstration, about 2 days)

For the person setting up the demo on an Ubuntu VPS. Run every command as a user with
`sudo`. Commands are meant to be copied and pasted one block at a time. Anything in
`<ANGLE BRACKETS>` is yours to replace.

What you end up with: the app running under gunicorn behind nginx, SQLite as the database,
the demo data loaded, the daily reminder job scheduled for 07:55 Lagos time, and email
written to the server log instead of being sent.

Time needed: about 30 minutes.

---

## 0. Before you start

You need:

- An Ubuntu **24.04** VPS (22.04 also works, see step 2) with at least 1 GB RAM.
- The server's public IP address, written below as `<SERVER_IP>`.
- **Optional:** a domain or subdomain (for example `od.example.com`) whose DNS A record
  points at `<SERVER_IP>`. With a domain you get HTTPS (step 9A). Without one, the demo runs
  on plain HTTP at `http://<SERVER_IP>` (step 9B).
- The code on GitHub. Run `git push` from your Mac first. The `private/` folder, which holds
  the manual, stays on your Mac.

> **About the demo passwords.** Every demo user gets the password you put in `DEMO_PASSWORD`
> in `.env` (step 6). The repository holds no password. If you use the one published in the
> feature manual, remember it is written there. Anyone who has that password and the link can sign in as the Admin.
> Share the link only with the people testing, and take the server down when the demo ends
> (step 12).

---

## 1. Log in and update the server

```bash
ssh root@<SERVER_IP>          # or your own sudo user
sudo apt update && sudo apt -y upgrade
sudo timedatectl set-timezone Africa/Lagos
```

## 2. Install system packages

```bash
sudo apt -y install python3 python3-venv python3-dev git nginx sqlite3 \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 libffi-dev
python3 --version
```

The version must be **3.12 or newer**. Ubuntu 24.04 has 3.12. On Ubuntu 22.04 (which has
3.10), install 3.12 and use `python3.12` wherever this guide says `python3`:

```bash
sudo apt -y install software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa && sudo apt update
sudo apt -y install python3.12 python3.12-venv python3.12-dev
```

## 3. Create the app user and folders

```bash
sudo adduser --system --group --home /srv/obligation-desk obligationdesk
sudo mkdir -p /srv/obligation-desk/{data,private_media,cache}
sudo chown -R obligationdesk:obligationdesk /srv/obligation-desk
sudo chmod 750 /srv/obligation-desk /srv/obligation-desk/{data,private_media,cache}
# nginx must reach the app socket, the static files and (internally) the evidence files
sudo usermod -aG obligationdesk www-data
```

## 4. Get the code

Public repository:

```bash
sudo -u obligationdesk git clone https://github.com/<YOU>/<REPO>.git /srv/obligation-desk/app
```

Private repository: create a GitHub *fine-grained personal access token* with read-only
access to this one repository, then:

```bash
sudo -u obligationdesk git clone https://<TOKEN>@github.com/<YOU>/<REPO>.git /srv/obligation-desk/app
sudo -u obligationdesk git -C /srv/obligation-desk/app remote set-url origin https://github.com/<YOU>/<REPO>.git
```

The second line removes the token from the saved remote. Delete the token on GitHub after
the demo.

## 5. Install the Python packages

```bash
cd /srv/obligation-desk/app
sudo -u obligationdesk python3 -m venv .venv
sudo -u obligationdesk .venv/bin/pip install --upgrade pip
sudo -u obligationdesk .venv/bin/pip install -r requirements.txt
```

## 6. Create the settings file (.env)

Generate a secret key and copy the output:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(60))"
```

Create the file:

```bash
sudo -u obligationdesk nano /srv/obligation-desk/app/.env
```

Paste **one** of the two blocks below, fill in the brackets, then save (Ctrl+O, Enter,
Ctrl+X).

**Option A, with a domain (HTTPS):**

```ini
SECRET_KEY="<PASTE THE GENERATED KEY>"
ALLOWED_HOSTS="<YOUR.DOMAIN>"
CSRF_TRUSTED_ORIGINS="https://<YOUR.DOMAIN>"
SITE_URL="https://<YOUR.DOMAIN>"
HTTPS_ENABLED="True"
SECURE_HSTS_SECONDS="3600"
DATABASE_URL="sqlite:////srv/obligation-desk/data/db.sqlite3"
PRIVATE_MEDIA_ROOT="/srv/obligation-desk/private_media"
CACHE_DIR="/srv/obligation-desk/cache"
USE_X_ACCEL_REDIRECT="True"
X_ACCEL_PREFIX="/protected/"
EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL="Obligation Desk <no-reply@example.org>"
DEMO_PASSWORD="<PASSWORD FOR ALL DEMO USERS>"
```

**Option B, IP address only (plain HTTP, demo only):**

```ini
SECRET_KEY="<PASTE THE GENERATED KEY>"
ALLOWED_HOSTS="<SERVER_IP>"
CSRF_TRUSTED_ORIGINS="http://<SERVER_IP>"
SITE_URL="http://<SERVER_IP>"
HTTPS_ENABLED="False"
DATABASE_URL="sqlite:////srv/obligation-desk/data/db.sqlite3"
PRIVATE_MEDIA_ROOT="/srv/obligation-desk/private_media"
CACHE_DIR="/srv/obligation-desk/cache"
USE_X_ACCEL_REDIRECT="True"
X_ACCEL_PREFIX="/protected/"
EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL="Obligation Desk <no-reply@example.org>"
DEMO_PASSWORD="<PASSWORD FOR ALL DEMO USERS>"
```

Notes:

- `SQLite` needs four slashes in `DATABASE_URL`: three for the scheme, one for the absolute
  path.
- `SECURE_HSTS_SECONDS="3600"` keeps the "HTTPS only" instruction to browsers short (one
  hour) for a demo. Raise it for real use.
- With the console email backend, every notice the system "sends" appears in the log
  (step 11) instead of an inbox. To send real email, replace that line with your mail
  server's details: `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
  `EMAIL_USE_TLS`.

Lock the file down:

```bash
sudo chmod 600 /srv/obligation-desk/app/.env
```

## 7. A shortcut for management commands

Every command must run as the app user with production settings. This helper does both:

```bash
sudo tee /usr/local/bin/od-manage >/dev/null <<'EOF'
#!/bin/sh
cd /srv/obligation-desk/app && exec sudo -u obligationdesk \
  DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py "$@"
EOF
sudo chmod +x /usr/local/bin/od-manage
```

## 8. Database, static files and demo data

```bash
od-manage migrate
od-manage collectstatic --noinput
od-manage seed_demo --force-in-production
od-manage check --deploy
```

- `seed_demo` should end with "Demo data ready." and print the demo password. If you left
  `DEMO_PASSWORD` empty, it prints a random one: note it down.
- `check --deploy` should print "no issues" for option A. Option B shows four warnings about
  HTTPS. They are expected and are exactly why option B is for demos only.

Make sure nginx can read the static files:

```bash
sudo chmod -R g+rX /srv/obligation-desk/app/staticfiles
sudo chmod g+x /srv/obligation-desk/app
```

## 9. Web server

### Start the app (gunicorn)

```bash
sudo cp /srv/obligation-desk/app/deploy/obligation-desk.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now obligation-desk
sudo systemctl status obligation-desk --no-pager
```

The status should say `active (running)`.

### 9A. nginx with a domain (HTTPS)

```bash
sudo cp /srv/obligation-desk/app/deploy/nginx-http.conf /etc/nginx/sites-available/obligation-desk
sudo sed -i 's/SERVER_NAME_HERE/<YOUR.DOMAIN>/' /etc/nginx/sites-available/obligation-desk
sudo ln -sf /etc/nginx/sites-available/obligation-desk /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

sudo apt -y install certbot python3-certbot-nginx
sudo certbot --nginx -d <YOUR.DOMAIN> --redirect -m <YOUR EMAIL> --agree-tos -n
```

Certbot adds the certificate and the HTTP-to-HTTPS redirect to the nginx file.

### 9B. nginx with the IP address only

```bash
sudo cp /srv/obligation-desk/app/deploy/nginx-http.conf /etc/nginx/sites-available/obligation-desk
sudo sed -i 's/SERVER_NAME_HERE/<SERVER_IP>/' /etc/nginx/sites-available/obligation-desk
sudo ln -sf /etc/nginx/sites-available/obligation-desk /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

### Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
```

## 10. Daily reminder job (07:55 Lagos time)

```bash
sudo cp /srv/obligation-desk/app/deploy/obligation-desk-notices.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now obligation-desk-notices.timer
systemctl list-timers obligation-desk-notices.timer --no-pager
```

To see what tomorrow's run will do, without writing or sending anything:

```bash
od-manage run_daily_notices --dry-run --as-of $(date -d tomorrow +%F)
```

## 11. Check it works

1. Open `https://<YOUR.DOMAIN>` (option A) or `http://<SERVER_IP>` (option B). You should
   see the sign-in page.
2. Sign in as the Admin from the demonstration accounts page of the feature manual.
3. Follow the "suggested demonstration path" in the manual.
4. Confirm evidence files are private. While signed out, open
   `/requests/files/evidence/1/`. You should be sent to the sign-in page, not get a file.

Useful commands:

```bash
sudo journalctl -u obligation-desk -f                 # live app log, including "sent" emails
sudo journalctl -u obligation-desk-notices --no-pager  # output of the daily job
sudo systemctl restart obligation-desk                 # after changing .env
```

If the page shows **502 Bad Gateway**, the app is not running or nginx cannot reach it.
Check `sudo systemctl status obligation-desk` and that step 3's `usermod` ran (then
`sudo systemctl restart nginx`). If sign-in says **CSRF verification failed**, the address
in your browser does not exactly match `CSRF_TRUSTED_ORIGINS` (including `http` or
`https`).

## 12. Updating during the demo

After pushing new code from your Mac:

```bash
cd /srv/obligation-desk/app && sudo -u obligationdesk git pull
sudo -u obligationdesk .venv/bin/pip install -r requirements.txt
od-manage migrate && od-manage collectstatic --noinput
sudo systemctl restart obligation-desk
```

Start the demo data again from scratch (this deletes everything, uploads included):

```bash
od-manage seed_demo --reset --force-in-production
```

## 13. Taking it down after the demo

```bash
sudo systemctl disable --now obligation-desk obligation-desk-notices.timer
sudo rm /etc/nginx/sites-enabled/obligation-desk && sudo systemctl reload nginx
```

To remove everything, data included:

```bash
sudo rm -rf /srv/obligation-desk /usr/local/bin/od-manage \
  /etc/systemd/system/obligation-desk*.{service,timer} /etc/nginx/sites-available/obligation-desk
sudo systemctl daemon-reload
```

## Later: moving to PostgreSQL

No code changes are needed. Install PostgreSQL, create a database and user, add
`psycopg[binary]` to the virtualenv, set
`DATABASE_URL="postgres://<USER>:<PASSWORD>@localhost:5432/<DB>"`, then run
`od-manage migrate`. Demo data can be loaded again with `seed_demo`. Real data would need
copying across, which is a separate step to plan. See `deploy/DEPLOYMENT.md` for backups and
the insert-only grant for the audit table.
