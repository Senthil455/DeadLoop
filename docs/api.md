# API and authentication

Base path: `/api/v1`. Interactive OpenAPI documentation is available at `/docs` when
the backend is running.

## Authentication

| Credential | Header | Scope |
| --- | --- | --- |
| Admin token | `X-Admin-Token` | Dashboard reads, incident actions, settings, API-key management, demo control |
| Ingestion key | `X-API-Key` | `POST /events` and `POST /events/batch` only |

`GET /health` is public. All other platform endpoints require the admin token, with
ingestion endpoints also accepting a valid API key. API keys begin with `dl_` and are
revoked from the dashboard.

Failed authentication returns `401` with `WWW-Authenticate: Token` for admin endpoints.

## Health

```http
GET /api/v1/health
```

```json
{
  "status": "ok",
  "database": "ok",
  "version": "0.1.0",
  "environment": "production",
  "ai_enabled": false,
  "intervention_mode": "approval_required",
  "demo_mode": false,
  "time": "2026-10-29T15:57:30.675522Z"
}
```

## Event ingestion

```http
POST /api/v1/events
POST /api/v1/events/batch
Authorization: X-API-Key: dl_...
Content-Type: application/json
```

Single event:

```json
{
  "event_id": "optional-stable-id",
  "agent_id": "support-agent",
  "session_id": "ticket-4821",
  "timestamp": "2026-10-29T15:57:30Z",
  "tool_name": "search_web",
  "action": "Find the refund policy",
  "input": { "query": "refund policy" },
  "output": { "results": 0 },
  "status": "failure",
  "error_category": "timeout",
  "duration_ms": 4200,
  "retry_count": 1,
  "progress": { "made_progress": false },
  "metadata": { "region": "eu" },
  "task": "Resolve ticket"
}
```

Batch:

```json
{ "events": [ { "...": "event" } ] }
```

Batch response (`202`):

```json
{
  "accepted": 4,
  "duplicates": 0,
  "rejected": [],
  "detections_created": 2,
  "incidents_created": 2,
  "session_ids": ["ticket-4821"]
}
```

Limits and behavior:

- Maximum 100 events per batch by default.
- Maximum request body 256 KiB by default.
- Unknown fields are rejected with `422`.
- Duplicate event IDs are counted, not reinserted.
- A rejected event does not discard valid events elsewhere in the batch; its index is
  listed in `rejected`.

## Dashboard resources

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/stats/overview` | Metrics, recent incidents, agents, interventions |
| `GET` | `/agents` | Agent fleet |
| `GET` | `/agents/{id}` | Agent detail |
| `PATCH` | `/agents/{id}` | Update name, description, framework, configuration |
| `GET` | `/agents/{id}/events` | Filtered agent events |
| `GET` | `/sessions` | Session list with filters |
| `GET` | `/sessions/{id}` | Session trace and incidents |
| `GET` | `/detections` | Detection records |
| `GET` | `/incidents` | Incident queue with filters |
| `GET` | `/incidents/{id}` | Evidence, notes, interventions, audit |

Common filters include status, severity, agent, session, tool, pagination, and search.
See `/docs` for the generated schema.

## Incident workflow

```http
POST /api/v1/incidents/{id}/status
{ "status": "ACKNOWLEDGED", "note": "Investigating" }
```

Allowed statuses: `OPEN`, `ACKNOWLEDGED`, `RESOLVED`, `DISMISSED`.

```http
POST /api/v1/incidents/{id}/notes
{ "body": "Checked the trace; upstream returned 503." }

POST /api/v1/incidents/{id}/explain
```

`explain` returns and persists either a validated AI explanation or a deterministic
fallback. It never changes the finding.

## Interventions

```http
POST /api/v1/incidents/{id}/interventions
{ "action": "pause" }
```

With `approval_required`, the response has `approval_status=PENDING` and
`execution_status=PENDING_APPROVAL`. With `automatic`, execution is attempted
immediately. `observe` and `notify` return `409`.

```http
POST /api/v1/interventions/{id}/approve
{ "note": "Operator reviewed the evidence" }

POST /api/v1/interventions/{id}/reject
{ "note": "Legitimate retries" }
```

Approval executes through the connected runtime adapter. The demo simulator returns
`execution_status=ACKNOWLEDGED` and `simulated=true`. Any unsupported runtime returns
`execution_status=UNSUPPORTED`, `acknowledged=false`, and leaves the session unchanged.

## Settings and keys

| Method | Path | Purpose |
| --- | --- | --- |
| `GET`/`PUT` | `/settings` | Retention, redaction, intervention mode, AI endpoint |
| `GET`/`PUT` | `/settings/detection` | Detector thresholds |
| `GET` | `/settings/detection/defaults` | Reset values |
| `GET` | `/settings/ai-status` | Configuration state without secrets |
| `GET`/`POST` | `/api-keys` | List/create ingestion keys |
| `DELETE` | `/api-keys/{id}` | Revoke a key immediately |
| `POST` | `/maintenance/prune` | Apply retention pruning |

The AI API key comes from `DEADLOOP_AI_API_KEY`, not from the settings API.

## Demo control

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/demo/scenarios/{scenario}` | Run an isolated demo scenario |
| `POST` | `/demo/reset` | Delete demo agents, sessions, events, and incidents |

Scenarios: `healthy`, `exact_repetition`, `oscillation`, `repeated_failure`,
`ambiguous`, `recovery`. Reset requires `{ "confirm": true }`.
