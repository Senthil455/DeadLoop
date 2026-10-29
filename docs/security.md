# Security model

DEADLOOP has two credential types and one privileged operator role. It is designed for
local or trusted-network deployment, not as a multi-tenant authorization service.

## Credentials

### Administrator token

- Sent as `X-Admin-Token` on dashboard reads and operator actions.
- Compared with `secrets.compare_digest` (constant-time comparison).
- Read from the environment only; never stored in the database or returned by the API.
- `DEADLOOP_ENV=production` refuses to start while the token is the development
  default `dev-admin-token`.
- The browser stores it in `localStorage` under `deadloop.adminToken`.

`localStorage` is deliberate for this single-page console but means an XSS defect could
read the token. The app ships a restrictive CSP and React escaping, but any future
third-party script must be reviewed carefully. For hostile environments, put the app
behind an authenticating reverse proxy and consider a server-side session design.

### Ingestion API keys

- Created in **Integrations**; the raw value is shown once.
- Stored as a SHA-256 hash. Lookup hashes the presented value and compares hashes.
- Write-only: a valid key authorizes event ingestion and nothing else.
- The key list exposes only a prefix, timestamps, and revocation state.
- Revocation takes effect immediately. A revoked key is rejected with `401`.
- Keys are never accepted through a URL query parameter.

An admin token may also ingest events for local demos and tests. This does not grant an
API key access to the dashboard.

## Input and transport controls

- Request bodies over `DEADLOOP_MAX_REQUEST_BYTES` (default 256 KiB) are rejected with
  `413` before parsing.
- Batches are capped at `DEADLOOP_MAX_BATCH_SIZE` (default 100).
- Pydantic models reject unknown fields (`extra="forbid"`).
- Event IDs and session/agent identifiers have length limits. URLs in the SPA are
  resolved beneath the frontend directory and cannot traverse outside it.
- CORS is an explicit origin allowlist; credentials are disabled.
- Responses set `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, `Permissions-Policy` restrictions, and a CSP for
  HTML responses.
- SQLAlchemy parameterized queries are used throughout. Demo scenario names are
  checked against a fixed allowlist.

## Data minimization and redaction

The backend recursively redacts fields whose names resemble API keys, access tokens,
passwords, secrets, cookies, credentials, or private keys. Bearer tokens embedded in
strings are also replaced. Sanitized values are what get persisted and returned; raw
inputs are not retained in the event row.

The Python SDK applies the same policy before transport. Backend redaction remains the
authoritative boundary because clients cannot be trusted to redact correctly.

Redaction is defense in depth, not a guarantee that arbitrary free-form text contains
no sensitive data. Avoid putting secrets in plan text, error messages, or unusual field
names that do not match the policy.

## Intervention safety

- The default policy is `approval_required`: a pause request is recorded but does not
  execute until an operator approves it.
- `observe` and `notify` reject pause requests with `409`.
- The runtime adapter acknowledges a pause only for the demo simulator (or an agent
  explicitly marked with the simulator framework).
- Without a capable adapter, execution is `UNSUPPORTED`, the request is retained for
  audit, and the session is not reported as paused.
- AI explanations cannot trigger interventions and do not alter findings.
- Closing an incident blocks new interventions; evidence and audit history are kept.

## Optional AI data flow

AI is off by default. When enabled:

- Only minimized incident/detection evidence is sent to the configured
  OpenAI-compatible endpoint.
- A local model endpoint keeps execution evidence on-network.
- Responses are parsed as structured JSON and validated. Fabricated event IDs are
  filtered against the detection's real evidence.
- Provider errors, timeouts, and invalid output fall back to deterministic output.
  The fallback is persisted and clearly labeled in the UI.
- Detection and interventions never depend on the AI result.

The AI base URL is an administrator-controlled setting. Restrict dashboard access and
choose a trusted endpoint; no generic SSRF allowlist is imposed on local model servers.

## Known deployment limitations

- No built-in TLS. Put the service behind a TLS-terminating reverse proxy when it is
  not strictly local.
- No rate limiting or login lockout. Use a long random admin token and a trusted network.
- No multi-user accounts, per-user audit attribution, or RBAC. The audit actor is
  `admin` or `system`.
- SQLite is single-node and not intended for a highly concurrent multi-replica setup.
- No secrets manager integration; credentials come from environment variables.
- No license has been selected, so redistribution terms are not yet defined.
