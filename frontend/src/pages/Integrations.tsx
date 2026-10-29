import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { api, formatDate, timeAgo } from "../api";
import { errorText, useApi, useDocumentTitle } from "../hooks";
import type { ApiKey, ApiKeyCreated, DemoScenarioResult } from "../types";
import {
  Button,
  Card,
  CodeBlock,
  EmptyState,
  ErrorState,
  Field,
  Icon,
  Modal,
  PageHeader,
  SkeletonRows,
} from "../components/ui";

const SCENARIOS = [
  {
    id: "healthy",
    name: "Healthy run",
    code: "BASELINE",
    description: "A productive debugging session with explicit progress signals. Should create zero incidents.",
    tone: "mint",
    resultHint: "0 incidents expected",
  },
  {
    id: "exact_repetition",
    name: "Exact repetition",
    code: "LOOP_DETECT",
    description: "Four identical failing search calls with no progress. Should raise exact repetition and repeated failure findings.",
    tone: "red",
    resultHint: "2 findings expected",
  },
  {
    id: "oscillation",
    name: "Oscillation",
    code: "CYCLE_DETECT",
    description: "The agent alternates between two failing operations without escaping the cycle.",
    tone: "amber",
    resultHint: "oscillation expected",
  },
  {
    id: "repeated_failure",
    name: "Repeated failure",
    code: "FAILURE_DETECT",
    description: "Different tools fail in sequence while the task makes no advancement.",
    tone: "amber",
    resultHint: "repeated failure expected",
  },
  {
    id: "ambiguous",
    name: "Ambiguous activity",
    code: "EVALUATE",
    description: "Some repeated calls, but each one advances the task. The detector should stay quiet.",
    tone: "neutral",
    resultHint: "0 high-severity incidents expected",
  },
  {
    id: "recovery",
    name: "Recovery",
    code: "CONTROL_TEST",
    description: "A failing loop followed by a successful recovery. Use this to exercise pause approval and acknowledgement.",
    tone: "mint",
    resultHint: "intervention test fixture",
  },
];

function CreateKeyModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (created: ApiKeyCreated) => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) {
      setError("Give the key a recognizable name.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const created = await api.createApiKey(name.trim());
      onCreated(created);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      footer={
        <>
          <Button onClick={onClose} variant="ghost">Cancel</Button>
          <Button disabled={busy} onClick={() => void submit({ preventDefault: () => undefined } as FormEvent)} variant="primary">
            {busy ? "Creating…" : "Create key"}
          </Button>
        </>
      }
      onClose={onClose}
      title="Create ingestion key"
    >
      <form className="form-stack" onSubmit={submit}>
        <p className="modal-copy">
          Keys can write events only. They cannot read incidents or execute interventions, and they
          are shown exactly once.
        </p>
        <Field label="Key name">
          <input
            autoFocus
            maxLength={100}
            onChange={(event) => setName(event.target.value)}
            placeholder="production · support-agent"
            value={name}
          />
        </Field>
        {error ? <div className="inline-error"><Icon name="alert" size={16} />{error}</div> : null}
      </form>
    </Modal>
  );
}

export default function IntegrationsPage() {
  const keys = useApi<ApiKey[]>("/api-keys");
  const [createOpen, setCreateOpen] = useState(false);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<ApiKey | null>(null);
  const [revokeBusy, setRevokeBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [running, setRunning] = useState("");
  const [scenarioResults, setScenarioResults] = useState<Record<string, DemoScenarioResult>>({});
  const [scenarioError, setScenarioError] = useState("");
  useDocumentTitle("Integrations");

  const origin = typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1:8000";

  const curlExample = `curl -X POST "${origin}/api/v1/events/batch" \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: dl_your_key" \\
  -d '{
    "events": [{
      "agent_id": "support-agent",
      "session_id": "run-2026-10-31",
      "tool_name": "search_web",
      "action": "Find refund policy",
      "status": "failure",
      "error_category": "timeout",
      "progress": {"made_progress": false},
      "input": {"query": "refund policy"}
    }]
  }'`;

  const sdkExample = `from deadloop import DeadloopClient

with DeadloopClient(
    endpoint="${origin}",
    api_key="dl_your_key",
    agent_id="support-agent",
    session_id="run-2026-10-31",
) as client:
    client.emit(
        "search_web",
        action="Find refund policy",
        input={"query": "refund policy"},
        output={"error": "timeout"},
        status="failure",
        progress=False,
    )`;

  async function runScenario(id: string) {
    setRunning(id);
    setScenarioError("");
    try {
      const result = await api.demo(id);
      setScenarioResults((current) => ({ ...current, [id]: result }));
    } catch (reason) {
      setScenarioError(`${id}: ${errorText(reason)}`);
    } finally {
      setRunning("");
    }
  }

  async function revoke() {
    if (!revokeTarget) return;
    setRevokeBusy(true);
    setScenarioError("");
    try {
      await api.revokeApiKey(revokeTarget.id);
      setNotice(`Key “${revokeTarget.name}” was revoked. New events using it will be rejected.`);
      setRevokeTarget(null);
      keys.reload();
    } catch (reason) {
      setScenarioError(errorText(reason));
    } finally {
      setRevokeBusy(false);
    }
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="Configure / integrations"
        title="Connect & test"
        description="Create write-only ingestion credentials, instrument an agent, and exercise the detection engine with deterministic scenarios."
      />

      {scenarioError ? <div className="inline-error"><Icon name="alert" size={16} />{scenarioError}</div> : null}
      {notice ? <div className="inline-success"><Icon name="check" size={16} />{notice}</div> : null}

      <div className="integration-grid">
        <Card
          actions={<Button icon="spark" onClick={() => setCreateOpen(true)} variant="primary">Create key</Button>}
          eyebrow="Credentials"
          flush
          title="Ingestion API keys"
        >
          <div className="key-note">
            <Icon name="shield" size={15} />
            <span><b>Write-only by design.</b> A leaked ingestion key can submit events but cannot read traces or act on incidents.</span>
          </div>
          {keys.error ? <ErrorState message={keys.error} retry={keys.reload} /> : null}
          {keys.loading && !keys.data ? <SkeletonRows rows={3} /> : null}
          {keys.data && !keys.data.length ? (
            <EmptyState
              action={<Button icon="spark" onClick={() => setCreateOpen(true)} size="sm">Create your first key</Button>}
              description="API keys are required for event ingestion. Dashboard access uses the separate admin token."
              icon="plug"
              title="No ingestion keys"
            />
          ) : null}
          {keys.data?.length ? (
            <div className="key-list">
              {keys.data.map((key) => (
                <div className={`key-row ${key.revoked_at ? "revoked" : ""}`} key={key.id}>
                  <span className="key-icon"><Icon name="plug" size={16} /></span>
                  <div>
                    <strong>{key.name}</strong>
                    <span className="mono">dl_{key.prefix}••••••••</span>
                  </div>
                  <div className="key-usage">
                    <span>{key.revoked_at ? `revoked ${timeAgo(key.revoked_at)}` : `created ${formatDate(key.created_at)}`}</span>
                    <span>{key.last_used_at ? `used ${timeAgo(key.last_used_at)}` : "never used"}</span>
                  </div>
                  {key.revoked_at ? (
                    <span className="chip tone-neutral">REVOKED</span>
                  ) : (
                    <Button icon="x" onClick={() => setRevokeTarget(key)} size="sm" variant="ghost">Revoke</Button>
                  )}
                </div>
              ))}
            </div>
          ) : null}
        </Card>

        <Card eyebrow="Protocol" title="Ingestion contract">
          <dl className="protocol-list">
            <div><dt>POST /api/v1/events</dt><dd>Single validated event</dd></div>
            <div><dt>POST /api/v1/events/batch</dt><dd>Up to 100 events</dd></div>
            <div><dt>Header</dt><dd><code>X-API-Key: dl_…</code></dd></div>
            <div><dt>Duplicate control</dt><dd>Stable <code>event_id</code> is idempotent</dd></div>
            <div><dt>Timestamps</dt><dd>ISO 8601; missing = received now</dd></div>
            <div><dt>Failure handling</dt><dd>Partial batches persist valid events</dd></div>
          </dl>
          <div className="protocol-note">
            <Icon name="activity" size={15} />
            <span>Include <code>progress.made_progress</code> to make the no-progress detector precise. Without it, DEADLOOP stays conservative.</span>
          </div>
        </Card>
      </div>

      <div className="code-grid">
        <Card eyebrow="Quick start" title="cURL">
          <CodeBlock code={curlExample} label="POST /api/v1/events/batch" />
        </Card>
        <Card eyebrow="Instrumentation" title="Python SDK">
          <CodeBlock code={sdkExample} label="python · sdk/deadloop" />
        </Card>
      </div>

      <Card
        actions={<span className="map-caption">Isolated by Agent.is_demo · safe to reset</span>}
        eyebrow="Demo lab"
        title="Simulator scenarios"
      >
        <p className="muted-copy section-lead">
          Scenarios run through the real ingestion and detection pipeline. They never bypass validation,
          deduplication, or risk scoring.
        </p>
        <div className="scenario-grid">
          {SCENARIOS.map((scenario) => {
            const result = scenarioResults[scenario.id];
            return (
              <div className={`scenario-card tone-${scenario.tone}`} key={scenario.id}>
                <div className="scenario-head">
                  <code>{scenario.code}</code>
                  <span>{scenario.resultHint}</span>
                </div>
                <h3>{scenario.name}</h3>
                <p>{scenario.description}</p>
                {result ? (
                  <div className="scenario-result">
                    <span><b>{result.events_created}</b> events</span>
                    <span><b>{result.detections_created}</b> findings</span>
                    <span><b>{result.incident_ids.length}</b> incidents</span>
                    {result.incident_ids.length ? (
                      <Link className="text-link" to={`/incidents/${result.incident_ids[0]}`}>
                        Open incident <Icon name="arrow-right" size={13} />
                      </Link>
                    ) : (
                      <span className="quiet">No incident raised</span>
                    )}
                  </div>
                ) : null}
                <Button
                  disabled={Boolean(running)}
                  icon={running === scenario.id ? "refresh" : "spark"}
                  onClick={() => runScenario(scenario.id)}
                  size="sm"
                >
                  {running === scenario.id ? "Running…" : "Run scenario"}
                </Button>
              </div>
            );
          })}
        </div>
      </Card>

      <div className="footnote">
        <Icon name="shield" size={15} />
        Demo agents are marked in the UI and isolated in storage. Reset removes only demo records.
      </div>

      {createOpen ? (
        <CreateKeyModal
          onClose={() => setCreateOpen(false)}
          onCreated={(value) => {
            setCreateOpen(false);
            setCreated(value);
            keys.reload();
          }}
        />
      ) : null}

      {created ? (
        <Modal
          footer={<Button onClick={() => setCreated(null)} variant="primary">I stored the key</Button>}
          onClose={() => setCreated(null)}
          title="Copy this key now"
          wide
        >
          <div className="secret-warning">
            <Icon name="alert" size={18} />
            <p>This key is displayed once. DEADLOOP stores only a hash and cannot show it again.</p>
          </div>
          <div className="secret-value mono">{created.api_key}</div>
          <div className="button-row">
            <Button
              icon="copy"
              onClick={() => void navigator.clipboard.writeText(created.api_key)}
              variant="secondary"
            >
              Copy key
            </Button>
            <span className="muted-copy">{created.note}</span>
          </div>
        </Modal>
      ) : null}

      {revokeTarget ? (
        <Modal
          footer={
            <>
              <Button onClick={() => setRevokeTarget(null)} variant="ghost">Cancel</Button>
              <Button disabled={revokeBusy} onClick={revoke} variant="danger">
                {revokeBusy ? "Revoking…" : "Revoke key"}
              </Button>
            </>
          }
          onClose={() => setRevokeTarget(null)}
          title="Revoke ingestion key"
        >
          <p className="modal-copy">
            Events submitted with <b>{revokeTarget.name}</b> will be rejected immediately. Existing
            evidence is retained. This cannot be undone.
          </p>
        </Modal>
      ) : null}
    </div>
  );
}
