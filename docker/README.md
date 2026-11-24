# Docker deployment

Production stack for the VM: `app/docker-compose.yaml` (Django + Celery worker / beat + PostgreSQL +
Redis + nginx), `app/nginx/default.conf` and `app/.env.example`.

Everything to build, copy and run is described in [DEPLOY.md](../DEPLOY.md) at the repository root.
