# Deploying GRM / eMGP on the VM (Docker)

Production runs as Docker containers on a VM: **Django (gunicorn) + Celery worker + Celery beat + PostgreSQL + Redis + nginx**. HTTPS is handled **before** the VM by the domain provider, which forwards the traffic to nginx on port 80. (Vercel is only used for demos: see `DEPLOY_VERCEL.md`.)

```
Internet ──HTTPS──> domain provider ──HTTP──> VM:80 nginx ──> django-app:9000 (gunicorn)
                                                   ├─ /static/  (collected files)
                                                   └─ /media/   (attachments, photos)
                         celery-worker  celery-beat  ──> redis, db (PostgreSQL)
```

---

## 1. Build and push the image (your machine)

```bash
cd GRM-Web-App-Benin/src
docker build -t cosobenin/grm-app:v2.1.0 .
docker push cosobenin/grm-app:v2.1.0
```

Use a new tag for every release (never overwrite a tag): it makes rollbacks a one-line change.

---

## 2. Prepare the VM (first time)

Requirements: Docker Engine with the `docker compose` plugin, port 80 reachable by the domain provider.

Copy these files from the repository to a folder on the VM, e.g. `/opt/grm/`:

| Repository file | On the VM |
|---|---|
| `docker/app/docker-compose.yaml` | `/opt/grm/docker-compose.yaml` |
| `docker/app/nginx/default.conf` | `/opt/grm/nginx/default.conf` |
| `docker/app/.env.example` | `/opt/grm/.env` (then edit it) |

```bash
scp docker/app/docker-compose.yaml        user@vm:/opt/grm/
scp docker/app/nginx/default.conf         user@vm:/opt/grm/nginx/
scp docker/app/.env.example               user@vm:/opt/grm/.env
```

Edit `/opt/grm/.env` (every variable is commented in the file). At least:

- `GRM_IMAGE` — the tag pushed in step 1;
- `SECRET_KEY` — generate one: `docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(50))"`;
- `POSTGRES_PASSWORD` **and the same password** in `DATABASE_URL` (`postgres://grm:<password>@db:5432/grm`);
- `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` — the public domain (`mgp.coso.gouv.bj`, `https://mgp.coso.gouv.bj`);
- `BEHIND_HTTPS_PROXY=True` (the domain provider does HTTPS);
- email settings if citizen email notifications are wanted. Keep `TWILIO_DEBUG_MODE=True` until an SMS provider is budgeted (SMS are then only written to the logs).

If the domain name is not `mgp.coso.gouv.bj`, change `server_name` in `nginx/default.conf`.

---

## 3. Start

```bash
cd /opt/grm
docker compose pull
docker compose up -d --wait   # returns once everything is started (first start: ~1 min)
docker compose ps             # every service "running", db and django-app "healthy"
```

**Migrations and static files are automatic.** At each start the `django-app` container runs `migrate`, then `collectstatic`, then starts gunicorn (`src/run.sh serve`). Nothing to run by hand, also after an update.

**Start order** (enforced by `depends_on` + health checks in the compose file):

1. `db` (healthy when PostgreSQL accepts connections) and `redis`;
2. `django-app`: migrations + static files, then gunicorn. It is *healthy* once gunicorn listens on port 9000, i.e. after the migrations;
3. `celery-worker`, `celery-beat` and `nginx`, only once `django-app` is healthy (Celery needs the migrated tables, nginx needs gunicorn and the collected static files).

If `django-app` never becomes healthy, read `docker compose logs django-app` (usually a wrong `DATABASE_URL` / password).

### Scheduled jobs: automatic

Nothing to configure, no crontab, nothing to tick in the admin. When `celery-beat` starts it registers the schedules in the database (*Periodic tasks* in the admin) and `celery-worker` runs them:

| Job | Every |
|---|---|
| `check_issues` — internal code, anonymisation, automatic assignment | 5 min |
| `escalate_issues` — escalations to the next committee | 5 min |
| `mark_issues_to_be_escalated` — committee deadlines (working days) | day |
| `reassign_issues_to_appeal` | hour |
| dashboard statistics (region performance, status bottlenecks) | 30 min to daily |

Check that they are registered and running:

```bash
docker compose logs --tail=50 celery-beat      # "beat: Starting..." then, after 5 min, "Sending due task check issues ..."
docker compose logs --tail=50 celery-worker    # "Task grm.tasks.check_issues[...] succeeded"
```

The first jobs run 5 minutes after the start: an issue reported from the app is assigned to its committee within 5 minutes.

(The Vercel cron `_cron/check-issues` is only for the demo deployment: not used here.)

---

## 4. First start of the application

### 4.1 Create the administrator

The setup wizard is only open to a user flagged **GRM owner**; user management needs **GRM manager**; the Django admin and revealing complainant contacts need **superuser**. One command creates this user with the three roles (the password is asked twice):

```bash
docker compose exec django-app ./run.sh django create_grm_owner --email admin@mgp.bj --first-name Admin --last-name MGP
```

Running it again on an existing email upgrades that user (and optionally resets the password).

> Until the wizard is finished, **only this user can log in to the dashboard**; other dashboard pages answer 404. A user without the *GRM owner* flag gets "Login is not allowed until the customization wizard is completed".

### 4.2 Configure the application (setup wizard)

1. Open `https://<domain>/` and log in with the administrator **email** and password: you land on the wizard.
2. Card **"Import from Excel"** → choose `config-coso/import_configuration_coso.xlsx` → *Import*. Every step is filled (levels, 952 regions, committees and deadlines, types and categories, age groups, components).
3. You land on the **Summary**: review it, then **Save and Finish**. The dashboard opens for everybody.

The same import from the command line (copy the file into the container first):

```bash
docker compose cp import_configuration_coso.xlsx django-app:/tmp/
docker compose exec django-app ./run.sh django import_configuration /tmp/import_configuration_coso.xlsx
```

then finish the wizard summary in the browser. File format: `docs/excel-import.md`.

### 4.3 Create the mobile accounts

Dashboard → **User Management → "Import accounts from Excel"** → `config-coso/import_comptes_coso.xlsx`, and type the **initial password** given to every account (at least 8 characters with letters and digits). Or:

```bash
docker compose cp import_comptes_coso.xlsx django-app:/tmp/
docker compose exec django-app ./run.sh django import_accounts /tmp/import_comptes_coso.xlsx   # asks the password
```

Result: 876 committee accounts (CCGP per village, CLGP per commune, national committee) and 110 field staff accounts (FC, SC) with their villages. Login identifier = email (`ccgp.<village>@mgp.bj`, `clgp.<commune>@mgp.bj`, `cnational@mgp.bj`, `fc|sc.<prénom>.<nom>@mgp.bj`).

**Passwords afterwards:** each user can change their password in the app (*Profile → Change password*, needs a connection). When someone forgets it, a GRM manager sets a new one in the dashboard: *User Management → the user → Reset password* (asks the manager's own password). Nobody is forced to change the initial password for now.

### 4.4 Optional checks in the admin (`/admin/`)

Nothing is required. Useful views: *Periodic tasks* (scheduled jobs, all enabled), *Users*, *Government workers* (committee accounts), *Facilitators* (role FC / SC, covered villages).

### 4.5 Mobile application

The APK must point to the production API: set `API_AUTH_BASE_URL=https://<domain>` in `grm-mobile/config.prod/index.js`, then build the APK as described in `grm-mobile/README.md` (*Building the App*) and distribute it.

---

## 5. Updating to a new version

```bash
# on your machine
docker build -t cosobenin/grm-app:v2.2.0 GRM-Web-App-Benin/src && docker push cosobenin/grm-app:v2.2.0
# on the VM
cd /opt/grm
sed -i 's#^GRM_IMAGE=.*#GRM_IMAGE=cosobenin/grm-app:v2.2.0#' .env
docker compose pull && docker compose up -d     # migrations run automatically
```

Rollback: put the previous tag back in `.env` and `docker compose up -d` (only if the new version added no migration that the old one cannot read).

---

## 6. Backups

Two things hold data: the **database** and the **media volume** (attachments, photos).

```bash
cd /opt/grm
# database
docker compose exec -T db pg_dump -U grm grm | gzip > backup-db-$(date +%F).sql.gz
# attachments and photos
docker run --rm -v grm_media:/media -v "$PWD":/backup alpine tar czf /backup/backup-media-$(date +%F).tar.gz -C /media .
```

Restore the database into an empty one: `gunzip -c backup-db-XXXX.sql.gz | docker compose exec -T db psql -U grm grm`.

Schedule these two commands with the VM crontab (e.g. every night) and copy the files off the VM.

---

## 7. Useful commands

```bash
docker compose ps                                   # state of the services
docker compose logs -f django-app                   # application logs (also: celery-worker, celery-beat, nginx)
docker compose exec django-app ./run.sh django shell # Django shell
docker compose exec django-app ./run.sh django <command>
docker compose restart django-app                   # after changing .env: docker compose up -d
docker compose down                                 # stop (volumes / data are kept)
```

**Do not run** `docker compose down -v`: it deletes the database and the attachments.

---

## 8. Things to know

- **HTTPS settings**: `manage.py check --deploy` warns about `SECURE_HSTS_SECONDS` and `SECURE_SSL_REDIRECT`. Both are the job of the domain provider that terminates HTTPS (redirect HTTP → HTTPS and HSTS there). Only if the provider cannot do HSTS, set `SECURE_HSTS_SECONDS=31536000` in `.env`.
- **No CouchDB, no MinIO, no MySQL**: the legacy `docker/database` stack was removed (CouchDB is deprecated, the other two were unused).
- **Attachments** are served by nginx under `/media/` with random file names and no directory listing; they are not protected by a login. Serving them through Django-checked links (X-Accel-Redirect) is listed in the backlog.
- **SMS** stay in simulation (`TWILIO_DEBUG_MODE=True`) until a provider is budgeted: `docs/notifications.md`.
- `set_benin_demo` (demo data) is never run on this deployment.
