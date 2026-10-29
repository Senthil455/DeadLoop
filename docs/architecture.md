# Architecture

## Deployment shape

DEADLOOP is one FastAPI process plus a React SPA.

```text
browser ──X-Admin-Token──▶ FastAPI /api/v1/*
agent   ──X-API-Key──────▶ POST /api/v1/events[/batch]
                              │
                              ▼
                        SQL database
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
          detectors       incidents        audit log
```

In production, FastAPI serves the built frontend from `frontend/dist`. In development,
Vite serves the SPA on port 5173 and proxies `/api` to the backend. The browser uses
relative API paths, so there is no separate API URL to configure.

## Backend modules

| Module | Responsibility |
| --- | --- |
| `app/api/` | HTTP routes, dependency-injected admin and ingestion authentication |
| `app/core/security.py` | Constant-time admin comparison, ingestion-key generation and hashing |
| `app/core/redaction.py` | Recursive credential redaction and Bearer-token scrubbing |
| `app/core/fingerprint.py` | Canonical JSON, normalized input hashes, token similarity |
| `app/services/ingestion.py` | Validation, agent/session upsert, idempotency, detector trigger |
| `app/detection/engine.py` | Six deterministic detectors, evidence and risk scoring |
| `app/services/serializers.py` | Response shaping and audit records |
| `app/interventions/service.py` | Policy enforcement and runtime acknowledgement |
| `app/ai/providers.py` | Optional OpenAI-compatible explanation and deterministic fallback |
| `app/services/demo.py` | Isolated simulator scenarios |
| `app/main.py` | App factory, security headers, CORS, request limits, SPA serving |

## Ingestion path

1. `X-API-Key` or an admin token is required. API keys are SHA-256 hashes in the
   database; the raw key is returned only at creation.
2. A request body larger than `DEADLOOP_MAX_REQUEST_BYTES` is rejected with `413`.
3. Pydantic validates the event. Unknown fields are rejected.
4. Inputs, outputs, metadata, and progress notes are redacted before persistence.
   Canonical input hashes are computed after normalization so volatile fields such as
   request IDs and timestamps do not defeat exact-repetition detection.
5. The agent is created if an authenticated write names a new agent. The session is
   created or checked against the agent; a session cannot be reassigned to another
   agent.
6. Events are inserted through a savepoint. Duplicate event IDs are counted and
   skipped, and later endpoints are protected from a single bad record.
7. Detection runs over the affected sessions. Findings are deduplicated by a stable
   fingerprint and existing incidents are updated in place.
8. The response reports accepted, duplicate, and rejected counts plus session IDs.

A batch is not a transaction for unrelated failures: valid events survive a rejected
event, and the response identifies the rejected index. This is deliberate; one bad
telemetry record must not discard the rest of a trace.

## Data model

| Table | Purpose |
| --- | --- |
| `agents` | Identity, framework, status, last-seen, demo marker |
| `sessions` | Trace grouping, status, timestamps, metadata |
| `events` | Redacted tool-call records, hashes, errors, progress, cost/token data |
| `detections` | Rule output, evidence JSON, risk, confidence, explanation cache |
| `incidents` | Operator-facing lifecycle and evidence references |
| `interventions` | Requested pause, policy, approval, execution result, simulation flag |
| `notes` | Operator investigation notes |
| `audit_log` | Append-only operator and demo actions |
| `settings` | Persisted detection and general policy settings |
| `api_keys` | Hashed write-only ingestion credentials |

## Frontend

React 19 + TypeScript + Vite + React Router. Recharts renders the telemetry volume
chart. The dashboard is intentionally a dense forensic console: evidence and status
remain readable at desktop and mobile widths, and controls use explicit confirmation
dialogs with audit notes.

The admin token lives in `localStorage` under `deadloop.adminToken`. A `401` clears
the token and redirects the operator to the sign-in screen. See the security document
for the trade-offs of this approach.

## Failure boundaries

- AI failure never blocks ingestion, detection, triage, or intervention. The
  deterministic explanation is persisted and displayed.
- A runtime that cannot acknowledge a pause is recorded as `UNSUPPORTED`; no session
  state is changed and no success is fabricated.
- A demo reset only deletes agents marked `is_demo`; it requires an explicit
  confirmation flag.
- A malformed AI response is validated and discarded in favor of deterministic output.
  Referenced event IDs are filtered to the detection's real evidence.
