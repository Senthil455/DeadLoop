# Deployment

## Recommended starting point

The supported initial deployment is a single FastAPI container serving the built SPA,
with a persistent SQLite volume. It is appropriate for local use, a lab, or a
single-node internal deployment behind TLS and a trusted network boundary.

The public demo surface is intentionally small. This release does not ship a
multi-tenant identity provider, a managed Postgres driver, or a horizontal-scaling
configuration.

## Docker Compose

1. Copy the environment template and choose a strong admin token:

   ```bash
   cp .env.example .env
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   Put the generated value in `DEADLOOP_ADMIN_TOKEN`. The token is required by the
   Compose file; there is no fallback.

2. Start the service:

   ```bash
   docker compose up --build -d
   docker compose logs -f deadloop
   ```

3. Open `http://127.0.0.1:8000`.

The container:

- builds the frontend with `npm ci && npm run build`;
- installs backend dependencies;
- runs `python -m alembic -c alembic.ini upgrade head` on every start;
- sets `DEADLOOP_ENV=production` and `DEADLOOP_AUTO_CREATE=0`;
- stores `/app/backend/data` in the `deadloop-data` volume;
- runs as UID 10001, with a read-only root filesystem and all capabilities dropped;
- binds the host port to `127.0.0.1` by default.

Change `DEADLOOP_BIND_ADDRESS` only when a reverse proxy or private network sits in
front of the service.

## Manual production run

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export DEADLOOP_ENV=production
export DEADLOOP_ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export DEADLOOP_DATABASE_URL="sqlite:////var/lib/deadloop/deadloop.db"
export DEADLOOP_AUTO_CREATE=0
export DEADLOOP_FRONTEND_DIST=/srv/deadloop/frontend/dist

python -m alembic -c alembic.ini upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
```

Build the frontend separately:

```bash
cd frontend
npm ci
npm run build
```

Do not use `--reload`, `--host 0.0.0.0`, or `DEADLOOP_AUTO_CREATE=1` in production
unless you have a specific reason and compensating controls.

## Reverse proxy

Terminate TLS at nginx, Caddy, or a cloud load balancer and forward to
`127.0.0.1:8000`. Restrict access with your normal network or SSO layer. Example nginx
shape:

```nginx
server {
    listen 443 ssl;
    server_name deadloop.example.internal;

    client_max_body_size 256k;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Keep `DEADLOOP_CORS_ORIGINS` aligned with the browser origin if you run a separate
frontend. Same-origin serving needs no CORS entry beyond the defaults.

## Persistent data and backups

The SQLite database contains agents, traces, evidence, incident history, settings,
hashed API keys, and audit logs. Back it up as a file while the process is stopped, or
use SQLite's online backup facility. The `backend/data/` directory is ignored by Git.

A named volume is used in Compose. Back it up with your container platform's volume
snapshot tooling.

## Migrations

Alembic is the schema authority:

```bash
cd backend
DEADLOOP_DATABASE_URL="sqlite:///data/deadloop.db" python -m alembic -c alembic.ini upgrade head
```

The initial revision is `08549d51f874`. The QA verification includes a clean-database
upgrade. Do not let the app auto-create schema in production; auto-create is a local
development convenience only.

## Health and operations

- Liveness: `GET /api/v1/health`
- OpenAPI: `GET /docs`
- SPA: `/`
- Logs: stdout/stderr from uvicorn. Secrets are not logged by application code.
- The dashboard shows a collector status based on the public health check and current
  intervention policy.

Pruning is available at `POST /api/v1/maintenance/prune` and respects
`retention_days`. Investigate an incident before resolving or dismissing it; closure
does not delete evidence.

## Environment reference

| Variable | Default | Notes |
| --- | --- | --- |
| `DEADLOOP_ENV` | `development` | Production rejects the default admin token |
| `DEADLOOP_ADMIN_TOKEN` | `dev-admin-token` | Required strong value in production |
| `DEADLOOP_DATABASE_URL` | `sqlite:///backend/data/deadloop.db` | Use an absolute SQLite path in production |
| `DEADLOOP_CORS_ORIGINS` | localhost dev origins | Comma-separated exact origins |
| `DEADLOOP_MAX_REQUEST_BYTES` | `262144` | 256 KiB |
| `DEADLOOP_MAX_BATCH_SIZE` | `100` | Events per batch |
| `DEADLOOP_AUTO_CREATE` | `1` | Set `0` in production |
| `DEADLOOP_FRONTEND_DIST` | `frontend/dist` | SPA build directory |
| `DEADLOOP_AI_ENABLED` | `false` | Optional narrative layer |
| `DEADLOOP_AI_BASE_URL` | empty | OpenAI-compatible endpoint, e.g. `http://127.0.0.1:11434/v1` |
| `DEADLOOP_AI_MODEL` | empty | Model name expected by that endpoint |
| `DEADLOOP_AI_API_KEY` | empty | Environment only; never exposed in settings |
| `DEADLOOP_AI_TIMEOUT_SECONDS` | `12` | Clamped 1–60 |

## Troubleshooting

- **App exits because of the default admin token:** set a real
  `DEADLOOP_ADMIN_TOKEN`; production intentionally refuses the development default.
- **Frontend root returns JSON instead of the SPA:** run `npm run build` or point
  `DEADLOOP_FRONTEND_DIST` at the built `dist` directory.
- **401 after refreshing the dashboard:** the admin token in `localStorage` is stale
  or invalid. Sign in again.
- **Pause approved but no session paused:** the runtime is unsupported. That is the
  expected safe outcome; use a capable adapter before claiming control.
- **AI explanation is deterministic:** AI is disabled, disconnected, or returned
  invalid structured output. Detection and intervention remain fully operational.
