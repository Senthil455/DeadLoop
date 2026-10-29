import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, formatDuration, formatShortDate, timeAgo } from "../api";
import { errorText, useApi, useDocumentTitle } from "../hooks";
import type { Agent, SessionSummary, TraceEvent } from "../types";
import {
  AgentStatusDot,
  Button,
  Card,
  CopyButton,
  EmptyState,
  ErrorState,
  Field,
  Icon,
  Loading,
  MetaList,
  Modal,
  PageHeader,
  SkeletonRows,
  StatusChip,
} from "../components/ui";

function EditAgentModal({
  agent,
  onClose,
  onSaved,
}: {
  agent: Agent;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(agent.name);
  const [framework, setFramework] = useState(agent.framework ?? "");
  const [description, setDescription] = useState(agent.description ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function save() {
    if (!name.trim()) {
      setError("Agent name cannot be empty.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.patchAgent(agent.id, {
        name: name.trim(),
        framework: framework.trim() || null,
        description: description.trim() || null,
      });
      onSaved();
      onClose();
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
          <Button disabled={busy} onClick={save} variant="primary">
            {busy ? "Saving…" : "Save changes"}
          </Button>
        </>
      }
      onClose={onClose}
      title="Edit agent"
    >
      <div className="form-stack">
        <Field label="Display name">
          <input maxLength={200} onChange={(event) => setName(event.target.value)} value={name} />
        </Field>
        <Field hint="Examples: LangGraph, CrewAI, custom Python runner." label="Framework">
          <input maxLength={100} onChange={(event) => setFramework(event.target.value)} value={framework} />
        </Field>
        <Field label="Description">
          <textarea
            maxLength={2000}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="What is this agent responsible for?"
            rows={4}
            value={description}
          />
        </Field>
        {error ? <div className="inline-error"><Icon name="alert" size={16} />{error}</div> : null}
      </div>
    </Modal>
  );
}

export default function AgentDetailPage() {
  const { agentId = "" } = useParams();
  const agent = useApi<Agent>(agentId ? `/agents/${encodeURIComponent(agentId)}` : null);
  const sessions = useApi<SessionSummary[]>(
    agentId ? `/sessions?agent_id=${encodeURIComponent(agentId)}&limit=20` : null,
  );
  const events = useApi<TraceEvent[]>(
    agentId ? `/agents/${encodeURIComponent(agentId)}/events?page=1&page_size=25` : null,
  );
  const [editing, setEditing] = useState(false);
  useDocumentTitle(agent.data?.name ?? "Agent detail");

  function refreshAll() {
    agent.reload();
    sessions.reload();
    events.reload();
  }

  if (agent.loading && !agent.data) return <div className="page"><Loading label="Loading agent" /></div>;
  if (agent.error) return <div className="page"><ErrorState message={agent.error} retry={agent.reload} /></div>;
  if (!agent.data) return null;
  const data = agent.data;

  return (
    <div className="page">
      <div className="back-link-row">
        <Link className="back-link" to="/agents"><Icon name="arrow-left" size={14} /> All agents</Link>
      </div>

      <PageHeader
        eyebrow="Monitor / agents / detail"
        title={data.name}
        description={data.description ?? "No description has been provided for this agent."}
        actions={
          <>
            <CopyButton label="Copy ID" value={data.id} />
            <Button icon="sliders" onClick={() => setEditing(true)}>Edit agent</Button>
          </>
        }
      />

      <div className="agent-banner">
        <div className="agent-banner-main">
          <span className="agent-avatar"><Icon name="bot" size={26} /></span>
          <div>
            <div className="agent-banner-meta">
              <AgentStatusDot status={data.status} />
              {data.is_demo ? <span className="chip tone-neutral">DEMO</span> : null}
              <span className="mono muted">{data.id}</span>
            </div>
            <strong>{data.framework ?? "Framework unknown"}</strong>
            <span>Registered {formatShortDate(data.created_at)} · last seen {timeAgo(data.last_seen_at)}</span>
          </div>
        </div>
        <div className="agent-banner-stats">
          <div><strong>{data.session_count}</strong><span>sessions</span></div>
          <div><strong>{data.event_count}</strong><span>events</span></div>
          <div><strong>{data.open_incidents}</strong><span>open incidents</span></div>
        </div>
      </div>

      <div className="detail-grid">
        <div className="detail-main">
          <Card
            actions={
              data.last_session_id ? (
                <Link className="text-link" to={`/sessions/${data.last_session_id}`}>
                  View session <Icon name="arrow-right" size={14} />
                </Link>
              ) : undefined
            }
            eyebrow="Activity"
            flush
            title="Recent sessions"
          >
            {sessions.loading && !sessions.data ? <SkeletonRows rows={4} /> : null}
            {sessions.error ? <ErrorState message={sessions.error} retry={sessions.reload} /> : null}
            {sessions.data && !sessions.data.length ? (
              <EmptyState description="Sessions appear when the agent sends its first event." icon="layers" title="No sessions recorded" />
            ) : null}
            {sessions.data?.length ? (
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr><th>Session</th><th>Status</th><th className="num">Events</th><th className="num">Open</th><th>Started</th></tr>
                  </thead>
                  <tbody>
                    {sessions.data.map((session) => (
                      <tr key={session.id}>
                        <td><Link className="mono link-cell" to={`/sessions/${session.id}`}>{session.id}</Link></td>
                        <td><span className={`session-state state-${session.status}`}>{session.status}</span></td>
                        <td className="num">{session.event_count}</td>
                        <td className="num">{session.open_incidents || "—"}</td>
                        <td className="muted-cell">{formatShortDate(session.started_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </Card>

          <Card eyebrow="Telemetry" flush title="Recent events">
            {events.error ? <ErrorState message={events.error} retry={events.reload} /> : null}
            {events.data && !events.data.length ? (
              <EmptyState description="No tool calls have been recorded for this agent." icon="activity" title="No events" />
            ) : null}
            {events.data?.length ? (
              <div className="table-scroll">
                <table className="data-table event-table">
                  <thead>
                    <tr>
                      <th>Time</th><th>Tool / action</th><th>Status</th><th className="num">Duration</th><th>Session</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.data.map((event) => (
                      <tr key={event.id}>
                        <td className="muted-cell nowrap">{formatShortDate(event.timestamp)}</td>
                        <td>
                          <span className="primary-cell">{event.tool_name}</span>
                          <span className="sub-cell">{event.action ?? "—"}</span>
                        </td>
                        <td><span className={`event-status ${event.status}`}>{event.status}</span></td>
                        <td className="num muted-cell">{formatDuration(event.duration_ms)}</td>
                        <td><Link className="mono link-cell small" to={`/sessions/${event.session_id}`}>{event.session_id.slice(0, 12)}…</Link></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </Card>
        </div>

        <aside className="detail-side">
          <Card eyebrow="Identity" title="Agent record">
            <MetaList
              items={[
                { label: "Status", value: <AgentStatusDot status={data.status} /> },
                { label: "Framework", value: data.framework ?? "—" },
                { label: "Agent ID", value: <span className="mono small break-all">{data.id}</span> },
                { label: "Registered", value: formatShortDate(data.created_at) },
                { label: "Last seen", value: timeAgo(data.last_seen_at) },
                { label: "Demo agent", value: data.is_demo ? "Yes" : "No" },
              ]}
            />
          </Card>

          {data.configuration && Object.keys(data.configuration).length ? (
            <Card eyebrow="Override" title="Configuration">
              <pre className="json-view">{JSON.stringify(data.configuration, null, 2)}</pre>
            </Card>
          ) : (
            <Card eyebrow="Override" title="Configuration">
              <p className="muted-copy">
                This agent uses the global detection policy. Per-agent overrides can be stored as
                <code> configuration.detection</code>.
              </p>
            </Card>
          )}

          <Card eyebrow="Triage" title="Latest incidents">
            {sessions.data?.length ? (
              <Link className="text-link" to={`/incidents?agent_id=${encodeURIComponent(data.id)}`}>
                Filter incidents for this agent <Icon name="arrow-right" size={14} />
              </Link>
            ) : (
              <span className="muted-copy">No linked incidents yet.</span>
            )}
            <div className="side-stack">
              {data.open_incidents > 0 ? <StatusChip status="OPEN" /> : null}
              <span className="muted-copy">{data.open_incidents} unresolved finding(s).</span>
            </div>
          </Card>
        </aside>
      </div>

      {editing ? (
        <EditAgentModal agent={data} onClose={() => setEditing(false)} onSaved={refreshAll} />
      ) : null}
    </div>
  );
}
