# QA and security verification

**Date:** 2026-10-29  
**Version:** 0.1.0  
**Verdict:** Accepted with documented limitations. No known blocking or high-severity
defect remains in the verified scope.

## Environment

| Item | Value |
| --- | --- |
| OS | Windows 11 (10.0.26300) |
| Backend | Python 3.14.4, FastAPI 0.111.0, Pydantic 2.13.4, SQLAlchemy 2.0.49 |
| Frontend | Node.js 24.14.1, npm 11.11.0, React 19, Vite 6 |
| Browser automation | Playwright Core 1.64.1, Chromium headless |
| Database | SQLite, Alembic revision `08549d51f874` |
| Docker CLI | 29.8.2; daemon unavailable during verification |

The backend suite was also run in a newly created isolated virtual environment to rule
out interference from globally installed Python packages.

## Test results

| Check | Result |
| --- | --- |
| Backend pytest | **62 passed, 0 failed** |
| Backend clean-environment install + pytest | **62 passed, 0 failed** |
| Backend `pip check` in clean environment | No broken requirements |
| SDK pytest | **8 passed, 0 failed** |
| Frontend Vitest | **8 passed, 0 failed** |
| Frontend production build | **Passed** (644 modules) |
| Clean-database Alembic upgrade | **Passed**, 11 tables, revision `08549d51f874` |
| Live API acceptance | **32/32 checks passed** |
| Live SDK acceptance | **17/17 checks passed** |
| Browser E2E (desktop + mobile) | **Passed**, 15 screenshots, 0 page errors, 0 unexpected console errors |
| Production dependency audit | **0 known npm vulnerabilities** in production dependencies |
| Docker Compose config validation | **Passed** |
| Docker image build/run | **Not executed** — Docker daemon unavailable |

Backend suite breakdown: 7 acceptance, 7 AI, 20 API/security, 19 detection,
8 intervention, 1 migration.

Production build output:

```text
dist/index.html                 0.70 kB │ gzip:   0.41 kB
dist/assets/index-*.css        58.89 kB │ gzip:  11.21 kB
dist/assets/index-*.js        736.56 kB │ gzip: 220.77 kB
```

The JS chunk triggers Vite's 500 kB size warning. It remains below the gzip budget and
does not block the build; lazy-loading Recharts is the obvious future optimization.

## Live acceptance results

Browser E2E was a real Chromium session against the built SPA and live backend at
`http://127.0.0.1:8000`:

- invalid admin token rejected in the UI; valid token signed in;
- desktop 1440×1000 and mobile 390×844 layouts checked;
- no horizontal page overflow at mobile width; drawer navigation opened;
- all six simulator scenarios ran through the real ingestion/detection path:

| Scenario | Result |
| --- | --- |
| Healthy run | 9 events, 0 findings, 0 incidents |
| Exact repetition | 4 events, 2 findings, 2 incidents |
| Oscillation | 8 events, 7 findings, 7 incidents |
| Repeated failure | 7 events, 3 findings, 3 incidents |
| Ambiguous activity | 5 events, 0 findings, 0 incidents |
| Recovery | 4 events, 2 findings, 2 incidents |

- created an ingestion key, captured the one-time value, verified the list view and
  revoked it;
- opened an incident, generated an explanation with AI disabled, and verified the
  deterministic fallback rendered and was persisted;
- acknowledged the incident, requested a pause, approved it, and verified the simulator
  acknowledged the pause with `simulated: true`;
- resolved the incident and verified `RESOLVED` persisted after a full page reload;
- opened the linked session, filtered to failures, and expanded event evidence;
- navigated agent detail, detection rules, and settings without runtime errors;
- dismissed a separate open incident and verified persistence after reload;
- captured populated overview metrics and evidence screenshots in
  `docs/screenshots/`.

The live API script additionally verified:

- public health status and absence of the admin token in health output;
- missing and invalid admin credentials rejected;
- ingestion-key/dashboard separation of privilege;
- missing fields, unknown fields, invalid statuses, duplicate IDs within a batch,
  and oversized bodies rejected with `422`/`413`;
- valid batch ingestion and duplicate-batch idempotency;
- exact-repetition and repeated-failure incidents generated live;
- redaction of API-key fields, metadata tokens, and raw secret values in stored traces;
- `observe` policy returning `409` for a pause request and restoration of
  `approval_required`;
- approval through a non-simulator runtime producing `UNSUPPORTED`, not a false pause;
- operator rejection producing `REJECTED` / `NOT_EXECUTED`;
- revoked keys rejected for ingestion.

The live SDK script verified batching, threshold flush, empty flush, session context
switching and restoration, server-side persistence, redaction, key-usage tracking, and
write-only key behavior.

## Security findings and fixes

No exploitable authentication, authorization, injection, or secret-exposure defect was
found in the verified scope. The following defects were found and corrected during QA:

| Defect | Impact | Fix |
| --- | --- | --- |
| Deterministic explanation was returned by the API but not persisted | The UI displayed no explanation after a successful `200`, despite the operator request; fallback looked broken | Persist every AI outcome, including fallback/error, and render it after reload; added regression assertions |
| Sign-in placeholder advertised a `dl_admin_…` value | Confused the administrator token with a write-only ingestion key | Replaced with neutral administrator-token copy |
| Sign-in hint said the token was “exchanged for this session only” | Inaccurate: the token is stored in `localStorage` | Corrected copy to describe browser storage accurately |
| Production default-token guard had no direct test | Security control could regress silently | Added a test that rejects `dev-admin-token` in production and accepts a strong token |
| SDK package metadata declared MIT while the project had no license | Packaging claimed redistribution terms the repository did not grant | Removed the license metadata; add a project-wide license before distribution |

Existing controls confirmed by tests and live checks: constant-time admin comparison,
hashed write-only ingestion keys, production default-token rejection, strict payload
validation, request and batch limits, recursive redaction, security headers, CORS
allowlist, path-traversal-safe SPA serving, and honest `UNSUPPORTED` intervention
reporting.

## Limitations and remaining issues

1. **Live AI provider not exercised.** No external credential or local model server was
   available. Provider success, failure, retry, malformed output, and prompt-injection
   handling are covered by mocked tests; the real deterministic fallback was exercised
   in Chromium. AI remains optional and is not in the detection path.
2. **Docker image not built or run.** The Docker CLI is installed, but the daemon was
   unavailable. `docker compose config` validated the Compose definition. The Dockerfile
   and Compose runtime path should be smoke-tested on a host with a running daemon
   before publication.
3. **Large frontend chunk.** Recharts pushes the main JS bundle to 736.56 kB
   (220.77 kB gzip), producing a Vite warning.
4. **Single-node scope.** SQLite, one administrator role, no built-in TLS, no rate
   limiting, and no multi-tenant RBAC. Use a trusted network or an authenticating TLS
   proxy for anything beyond local use.
5. **Runtime control is intentionally limited.** Only the demo simulator can acknowledge
   a pause. Real agents without an adapter are recorded as `UNSUPPORTED`; that is a
   safety property, not a hidden failure.
6. **No license selected.** Add a license before distributing the repository.
7. **Global Python environment.** `pip check` in the machine-wide environment reported
   unrelated conflicts from global packages (`mcp`, `streamlit`, `moviepy`). The clean
   project virtual environment had no broken requirements.

## Launch commands

Backend:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m alembic -c alembic.ini upgrade head
$env:DEADLOOP_ADMIN_TOKEN = "choose-a-long-random-token"
$env:DEADLOOP_AUTO_CREATE = "0"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend production assets:

```powershell
cd frontend
npm ci
npm run build
```

Open `http://127.0.0.1:8000` and sign in with the configured admin token.

Docker (after starting a Docker daemon):

```powershell
Copy-Item .env.example .env
# replace DEADLOOP_ADMIN_TOKEN in .env
docker compose up --build
```

Verification commands:

```powershell
cd backend; python -m pytest -q
cd ..\sdk; python -m pytest -q
cd ..\frontend; npm run test; npm run build
```

## Acceptance decision

The implementation satisfies the specified product behavior in the tested scope:
deterministic detection without AI dependence, evidence-backed incidents, safe
approval-gated interventions, honest unsupported-runtime handling, secret redaction,
strict authentication and validation, a usable desktop/mobile dashboard, a clean
production build, and a clean-database migration path. Acceptance is granted with the
limitations above; the unbuilt Docker image and unexercised live AI provider are the two
external-environment gaps to close before a public production launch.
