# Deploying AttendPro: attendpro.cloud

AttendPro runs next to another site on the same server, fully separated from it:

| | AttendPro | Kept apart by |
|---|---|---|
| Linux user | `attendpro` | own user; can't read the other site's files |
| Code & files | `/srv/attendpro/` | own folder |
| Database | `db_attendpro`, role `attendpro` | own database and login |
| App server | `attendpro.service`, socket `/run/attendpro/gunicorn.sock` | own process; restarting one never touches the other |
| Nginx | `/etc/nginx/sites-available/attendpro`, answers **only** for `attendpro.cloud` | no `default_server`; zone and upstream names are unique |
| Logs | `journalctl -u attendpro`, `/var/log/nginx/attendpro.*.log` | own log files |

Lines starting with `$` are typed on the server, as `root` unless the step says otherwise.
Nothing here changes the other site. The only shared steps are `nginx -t` and a
reload. `nginx -t` checks every site first, and a reload never drops live connections.

## Layout on the server

```
/srv/attendpro/
├── app/       the code, cloned from GitHub (the .env file lives here)
├── venv/      Python packages
├── media/     uploads: organisation logos, member photos, saved reports
├── static/    CSS/JS (collectstatic)
└── backups/   daily database dumps, weekly media archives
```

---

## 1. Point the domain at the server

In Hostinger (Domains → attendpro.cloud → DNS), set these records, replacing any existing
`@`/`www` A records or CNAMEs:

| Type | Name | Value |
|------|------|-------|
| A | `@` | `72.61.202.82` |
| A | `www` | `72.61.202.82` |

Check from your computer: `getent hosts attendpro.cloud` must show `72.61.202.82`
before step 8 (HTTPS) will work.

## 2. The database

PostgreSQL is already running for the other site; AttendPro gets its own role and database.
The role is named `attendpro` like the Linux user, so backups can connect without a password.

```bash
$ sudo -u postgres psql
postgres=# CREATE ROLE attendpro LOGIN PASSWORD 'THE-DATABASE-PASSWORD';
postgres=# CREATE DATABASE db_attendpro OWNER attendpro ENCODING 'UTF8' TEMPLATE template0;
postgres=# \q
```

If `db_attendpro` already exists, make the role its owner instead:
`ALTER DATABASE db_attendpro OWNER TO attendpro;`

## 3. App user and folders

```bash
$ adduser --system --group --home /srv/attendpro --shell /bin/bash attendpro
$ usermod -aG www-data attendpro
$ mkdir -p /srv/attendpro/{media,static,backups}
$ chown -R attendpro:www-data /srv/attendpro
$ chown attendpro:attendpro /srv/attendpro/backups
$ chmod 755 /srv/attendpro /srv/attendpro/static
$ chmod 2750 /srv/attendpro/media
$ chmod 700 /srv/attendpro/backups
```

Let `attendpro` restart only its own service (used by `deploy/update.sh`):

```bash
$ echo 'attendpro ALL=(root) NOPASSWD: /bin/systemctl restart attendpro' > /etc/sudoers.d/attendpro
$ chmod 440 /etc/sudoers.d/attendpro && visudo -c
```

## 4. Get the code

```bash
$ sudo -iu attendpro
$ git clone https://github.com/Dev-Samuel-Jeremiah/attendpro.git /srv/attendpro/app
$ python3 -m venv /srv/attendpro/venv
$ /srv/attendpro/venv/bin/pip install --upgrade pip
$ /srv/attendpro/venv/bin/pip install -r /srv/attendpro/app/requirements.txt
```

## 5. Settings (.env)

Still as `attendpro`:

```bash
$ cd /srv/attendpro/app
$ cp .env.example .env && chmod 600 .env
$ /srv/attendpro/venv/bin/python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
$ nano .env
```

Fill in:
- `DJANGO_SECRET_KEY`: the value printed above.
- `DB_PASSWORD`: the database password from step 2, without quotes.
- `DJANGO_ADMIN_URL`: a hard-to-guess path, e.g. `platform-x7k2q/`.

Everything else (domain, database name, file locations) is already set for this server.

## 6. Create the tables and check

Still as `attendpro`, in `/srv/attendpro/app`:

```bash
$ /srv/attendpro/venv/bin/python manage.py migrate
$ /srv/attendpro/venv/bin/python manage.py collectstatic --noinput
$ /srv/attendpro/venv/bin/python manage.py createsuperuser     # platform super-admin
$ /srv/attendpro/venv/bin/python manage.py check --deploy
$ exit
```

Don't run `seed_demo` here: it creates accounts with publicly known passwords.

## 7. Start the app

```bash
$ cp /srv/attendpro/app/deploy/attendpro.service /etc/systemd/system/
$ systemctl daemon-reload && systemctl enable --now attendpro
$ systemctl status attendpro            # "active (running)"
```

## 8. Nginx and HTTPS

```bash
$ cp /srv/attendpro/app/deploy/nginx-proxy.conf /etc/nginx/snippets/attendpro-proxy.conf
$ cp /srv/attendpro/app/deploy/nginx.conf /etc/nginx/sites-available/attendpro
$ ln -s /etc/nginx/sites-available/attendpro /etc/nginx/sites-enabled/attendpro
$ nginx -t                               # must say "syntax is ok" / "test is successful"
$ systemctl reload nginx
$ certbot --nginx -d attendpro.cloud -d www.attendpro.cloud --redirect
```

If `nginx -t` fails, **don't reload**. Remove the link
(`rm /etc/nginx/sites-enabled/attendpro`) and the other site keeps running as before.

Open https://attendpro.cloud, register an organisation, and test a scan from a phone.
Certbot renews the certificate automatically.

## 9. Daily backups

```bash
$ cp /srv/attendpro/app/deploy/attendpro-backup.* /etc/systemd/system/
$ systemctl daemon-reload && systemctl enable --now attendpro-backup.timer
$ systemctl start attendpro-backup && ls -l /srv/attendpro/backups    # test it now
```

Database every night at 02:15 (kept 14 days), plus uploaded files on Sundays (kept 8 weeks).
Copy `/srv/attendpro/backups` off the server now and then.

Restore a dump:
```bash
$ systemctl stop attendpro
$ sudo -u attendpro pg_restore --clean --if-exists -d db_attendpro /srv/attendpro/backups/db-YYYY-MM-DD-HHMM.dump
$ systemctl start attendpro
```

---

## Updating after a code change

Push to GitHub from your computer, then on the server:

```bash
$ sudo -iu attendpro /srv/attendpro/app/deploy/update.sh
```

It backs up the database, pulls, installs packages, migrates, collects static files and
restarts AttendPro, and only AttendPro.

## When something goes wrong

| Symptom | Look at |
|---|---|
| 502 Bad Gateway | `journalctl -u attendpro -n 50` (the app isn't running or crashed) |
| "Bad Request (400)" | `DJANGO_ALLOWED_HOSTS` in `.env` |
| CSRF error on forms | `DJANGO_CSRF_TRUSTED_ORIGINS` in `.env` |
| Page loads without styling | rerun `collectstatic`; check `/var/log/nginx/attendpro.error.log` |
| In-page camera scanner won't open | the site must be on `https://` |
