## Planning Poker – Container Stack

Production is now driven by Docker Compose so the Django app, Postgres, Redis, and Caddy can be deployed as a single unit.

### Prerequisites
- Docker Engine + Compose Plugin (v2+)
- A domain pointed at the server (Cloudflare can proxy it)
- SSH access to the host so you can copy the `.env` secrets file

### Configure secrets
1. Copy the template: `cp .env.example .env`.
2. Update the placeholders:
   - `DJANGO_SECRET_KEY`: generate a new 50+ char key (`python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"`).
   - `POSTGRES_*` and `DB_*`: use the same values so Django can reach Postgres.
   - `CADDY_DOMAIN`: FQDN you’ll expose (e.g., `poker.abrace.eu`).
   - `CADDY_TLS`: set to `internal` for a self-signed cert (works with Cloudflare “Full” mode) or to an email so Caddy can request a public cert.
   - Leave `GUNICORN_WORKERS` at 4 unless you tune it for CPU cores.

> Keep `.env` out of source control. Only `.env.example` is tracked.

### Boot the stack
```bash
docker compose pull          # fetch base images (first run only)
docker compose up -d         # build images and start services
docker compose logs -f web   # follow Django logs
```

- The `web` container runs `gunicorn`, applies migrations, and collects static files on every start.
- Postgres, Redis, and static/media assets live on named volumes (`postgres_data`, `redis_data`, `static_data`, `media_data`), so `docker compose down` will not delete data unless you add `-v`.
- Caddy terminates TLS on port 443, serves `/static/` + `/media/`, and reverse-proxies app traffic to `web:8000`. When Cloudflare proxies the site, keep `CADDY_TLS=internal` or upload a Cloudflare origin certificate and point `CADDY_TLS` to it.

### Common tasks
- Run Django management commands:
  ```bash
  docker compose exec web python manage.py createsuperuser
  docker compose exec web python manage.py collectstatic --noinput
  ```
- Check database shells: `docker compose exec db psql -U $POSTGRES_USER $POSTGRES_DB`.
- Tail Caddy or Postgres logs: `docker compose logs -f caddy` / `docker compose logs -f db`.
- To rebuild after code changes: `docker compose build web && docker compose up -d web caddy`.

### Deployment workflow
1. Push changes to GitHub (`main` or release branch).
2. On the server, pull new commits and run `docker compose pull && docker compose up -d --build web caddy`.
3. Confirm health via `docker compose ps` and hit `/health` once you add one.

This layout keeps Django stateless, uses Postgres for durable data, Redis for future caching/queues, and Caddy for encrypted ingress so it’s ready to sit behind Cloudflare in production.
