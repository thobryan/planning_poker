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
   - `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS`: keep `localhost,127.0.0.1` for dev and append `poker.abrace.eu` (or your domain) for prod.
   - `DJANGO_DEBUG` + `DJANGO_SECURE_COOKIES`: set `DJANGO_DEBUG=True` / `DJANGO_SECURE_COOKIES=False` locally; flip them back for prod.
   - `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY`: Cloudflare Turnstile credentials used on `/auth/login` and `/admin/login`. Leave them blank to disable (not recommended in prod).
   - `ORG_ALLOWED_EMAIL_DOMAIN`: default `welltech.com`. Update if your org uses a different workspace domain.
   - `ORG_ACCESS_TOKEN_TTL_SECONDS`: how long a login token remains valid (defaults to 600 seconds).
   - `ERROR_REPORT_EMAIL`: address that will receive crash emails (defaults to `poker@abrace.eu`).
   - `CADDY_DOMAIN`: use `localhost` for dev; change to `poker.abrace.eu` (or whatever FQDN you pointed at the server) for prod.
   - `CADDY_TLS`: keep `internal` for a self-signed cert locally (works with Cloudflare “Full” mode) or set an ACME email / cert path for public TLS.
   - `CADDY_HTTP_PORT` / `CADDY_HTTPS_PORT`: default to 8080/8443 for localhost dev; change to 80/443 (or your preferred published ports) when deploying behind a public domain.
   - `MAILHOG_SMTP_PORT` / `MAILHOG_UI_PORT`: optional overrides if you want MailHog exposed on different localhost ports (defaults: 1025/8025).
   - Leave `GUNICORN_WORKERS` at 4 unless you tune it for CPU cores.
   - Email settings: set `DEFAULT_FROM_EMAIL` and (optionally) `EMAIL_BACKEND`. For SMTP, configure `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and `EMAIL_USE_TLS`/`EMAIL_USE_SSL`. In development you can stick with the console backend so emails print to the log.

### Local vs production quickstart
- **Local (docker compose or `runserver`)**
  - Copy `.env.example` → `.env`, set `DJANGO_DEBUG=True` and `DJANGO_SECURE_COOKIES=False`.
  - Leave the provided `localhost` entries in `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`.
  - Keep `CADDY_DOMAIN=localhost` (the env file already publishes 8080/8443 so Docker avoids privileged ports) or skip Caddy and run `python manage.py runserver`.
  - `ORG_ALLOWED_EMAIL_DOMAIN` can be blank if you don’t want to enforce @welltech.com locally.
  - MailHog now ships in the compose stack (`mailhog` service). Use the defaults (`EMAIL_HOST=mailhog`, `EMAIL_PORT=1025`) to capture OTP emails locally at http://localhost:8025. Prefer the console backend if you don’t want MailHog running, but if you change `EMAIL_BACKEND` to SMTP without a listener you’ll hit “Connection refused”.
  - The org login and Django admin screens include a Cloudflare Turnstile challenge; the provided keys work locally too. If you remove them from `.env`, Turnstile checks are skipped.
- **Production (`poker.abrace.eu`)**
  - Set `DJANGO_DEBUG=False`, `DJANGO_SECURE_COOKIES=True`, and restrict `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS` to your public host.
  - Point `CADDY_DOMAIN` at `poker.abrace.eu`, change `CADDY_HTTP_PORT`/`CADDY_HTTPS_PORT` back to 80/443 (or your ingress ports), and set `CADDY_TLS` to either an email (for Let’s Encrypt) or a path to a Cloudflare origin cert.
  - Configure `EMAIL_*` variables to point at your SMTP relay (SES SMTP endpoint, Postmark, etc.) so login codes reach teammates.
  - Keep the rest of the stack identical; the Compose file is environment-agnostic once env vars are set.

### Org login & OTP flow
- Users hit `/auth/login`, enter their work email, and receive a 6-digit token via the configured email backend. The token lifetime is controlled by `ORG_ACCESS_TOKEN_TTL_SECONDS`.
- The login form then prompts for the token. A correct token stores `org_email` in the session; the middleware (`poker/middleware.py`) requires this for every view.
- Users can resend the code or switch emails without refreshing manually. Logging out clears both the session and any pending tokens.
- Both `/auth/login` and `/admin/login` are protected by Cloudflare Turnstile—make sure the site & secret keys are valid in production so users can authenticate.

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
2. On the server run `./scripts/reload.sh` (it pulls git, updates images, rebuilds `web`, and restarts the stack). Use `bash scripts/reload.sh` if your shell doesn’t execute it directly.
3. Confirm health via `docker compose ps` and hit `/health` once you add one.

This layout keeps Django stateless, uses Postgres for durable data, Redis for future caching/queues, and Caddy for encrypted ingress so it’s ready to sit behind Cloudflare in production.
