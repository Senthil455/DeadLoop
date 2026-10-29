import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { formatDate, formatDuration, formatNumber, formatShortDate } from "../api";
import { useApi, useDocumentTitle } from "../hooks";
import type { SessionDetail, TraceEvent } from "../types";
import {
  Card,
  EmptyState,
  ErrorState,
  Icon,
  Loading,
  MetaList,
  PageHeader,
  SeverityChip,
  StatusChip,
} from "../components/ui";

const CATEGORIES = [
  "exact_repetition",
  "semantic_repetition",
  "oscillation",
  "repeated_failure",
  "no_progress",
  "budget_exceeded",
];

function offsetLabel(timestamp: string, startedAt: string): string {
  const diff = (new Date(timestamp).getTime() - new Date(startedAt).getTime()) / 1000;
  if (!Number.isFinite(diff)) return "—";
  const sign = diff < 0 ? "-" : "+";
  const seconds = Math.abs(diff);
  if (seconds < 60) return `${sign}${seconds.toFixed(1)}s`;
  return `${sign}${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

function EventItem({ event, startedAt }: { event: TraceEvent; startedAt: string }) {
  const progress = event.progress?.made_progress;
  return (
    <details className={`trace-event status-${event.status}`}>
      <summary>
        <span className="trace-rail">
          <span className={`trace-node ${event.status}`} />
        </span>
        <span className="trace-offset mono">{offsetLabel(event.timestamp, startedAt)}</span>
        <span className="trace-body">
          <span className="trace-tool">{event.tool_name}</span>
          <span className="trace-action">{event.action ?? "No action label"}</span>
        </span>
        <span className="trace-tags">
          {event.retry_count > 0 ? <span className="mini-tag">retry {event.retry_count}</span> : null}
          {event.error_category ? <span className="mini-tag danger">{event.error_category}</span> : null}
          {progress === true ? <span className="mini-tag success">progress</span> : null}
          {progress === false ? <span className="mini-tag danger">no progress</span> : null}
          <span className={`event-status ${event.status}`}>{event.status}</span>
        </span>
        <span className="trace-duration mono">{formatDuration(event.duration_ms)}</span>
        <Icon className="trace-chevron" name="chevron-down" size={15} />
      </summary>
      <div className="trace-detail">
        <div className="trace-detail-meta">
          <span><b>Event</b> <code>{event.id}</code></span>
          <span><b>Timestamp</b> {formatDate(event.timestamp)}</span>
          <span><b>Received</b> {formatDate(event.received_at)}</span>
          <span><b>Task</b> {event.task ?? "—"}</span>
          <span><b>Model</b> {event.model_id ?? "—"}</span>
          <span><b>Tokens</b> {event.tokens !== null ? formatNumber(event.tokens) : "—"}</span>
          <span><b>Cost</b> {event.cost_usd !== null ? `$${event.cost_usd.toFixed(5)}` : "—"}</span>
          <span><b>Input hash</b> <code>{event.normalized_input_hash.slice(0, 24)}…</code></span>
          {event.correlation_id ? <span><b>Correlation</b> <code>{event.correlation_id}</code></span> : null}
          {event.parent_event_id ? <span><b>Parent event</b> <code>{event.parent_event_id}</code></span> : null}
        </div>
        <div className="payload-grid">
          <div>
            <span className="payload-label">Sanitized input</span>
            <pre className="json-view">{JSON.stringify(event.sanitized_input, null, 2) ?? "null"}</pre>
          </div>
          <div>
            <span className="payload-label">Sanitized output</span>
            <pre className="json-view">{JSON.stringify(event.sanitized_output, null, 2) ?? "null"}</pre>
          </div>
        </div>
        {event.progress ? (
          <div className="progress-note">
            <Icon name={progress === true ? "check" : "alert"} size={15} />
            Explicit progress evidence: {progress === true ? "task advanced" : "no advancement claimed"}.
          </div>
        ) : (
          <div className="progress-note plain">
            No explicit progress signal on this event. Repetition alone will not trigger a finding.
          </div>
        )}
        {event.metadata ? (
          <div>
            <span className="payload-label">Metadata</span>
            <pre className="json-view">{JSON.stringify(event.metadata, null, 2)}</pre>
          </div>
        ) : null}
      </div>
    </details>
  );
}

export default function SessionDetailPage() {
  const { sessionId = "" } = useParams();
  const [status, setStatus] = useState("");
  const [tool, setTool] = useState("");
  const [category, setCategory] = useState("");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const params = new URLSearchParams({ page: String(page), page_size: "40", order });
  if (status) params.set("status", status);
  if (tool) params.set("tool", tool);
  if (category) params.set("category", category);
  if (query.trim()) params.set("q", query.trim());
  const path = sessionId ? `/sessions/${encodeURIComponent(sessionId)}?${params.toString()}` : null;
  const session = useApi<SessionDetail>(path);
  useDocumentTitle("Session trace");

  function resetPage() {
    setPage(1);
  }

  function clearFilters() {
    setStatus("");
    setTool("");
    setCategory("");
    setQuery("");
    setOrder("asc");
    setPage(1);
  }

  if (session.loading && !session.data) return <div className="page"><Loading label="Loading session evidence" /></div>;
  if (session.error && !session.data) return <div className="page"><ErrorState message={session.error} retry={session.reload} /></div>;
  if (!session.data) return null;

  const data = session.data;
  const hasFilters = Boolean(status || tool || category || query || order !== "asc");

  return (
    <div className="page">
      <div className="back-link-row">
        <Link className="back-link" to="/sessions"><Icon name="arrow-left" size={14} /> All sessions</Link>
      </div>

      <PageHeader
        eyebrow="Monitor / sessions / trace"
        title="Session evidence"
        description={<span className="mono break-all">{data.id}</span>}
        actions={
          <>
            <span className={`session-state state-${data.status}`}>{data.status}</span>
            <button className="button button-secondary button-md" onClick={session.reload} type="button">
              <Icon name="refresh" size={16} /> Refresh
            </button>
          </>
        }
      />

      <div className="session-banner">
        <div className="session-banner-item">
          <span>Agent</span>
          {data.agent_name ? (
            <Link className="link-cell" to={`/agents/${data.agent_id}`}>{data.agent_name}</Link>
          ) : <strong>unknown</strong>}
        </div>
        <div className="session-banner-item"><span>Started</span><strong>{formatShortDate(data.started_at)}</strong></div>
        <div className="session-banner-item"><span>Ended</span><strong>{data.ended_at ? formatShortDate(data.ended_at) : "still open"}</strong></div>
        <div className="session-banner-item"><span>Filtered events</span><strong>{data.total_events}</strong></div>
        <div className="session-banner-item"><span>Session events</span><strong>{data.event_count}</strong></div>
        <div className="session-banner-item"><span>Incidents</span><strong className={data.open_incidents ? "warn-text" : ""}>{data.open_incidents} open</strong></div>
      </div>

      {data.incidents.length ? (
        <div className="session-incidents">
          {data.incidents.map((incident) => (
            <Link className="session-incident" key={incident.id} to={`/incidents/${incident.id}`}>
              <SeverityChip severity={incident.severity} />
              <StatusChip status={incident.status} />
              <strong>{incident.title}</strong>
              <span>{incident.detection_category?.replaceAll("_", " ")}</span>
              <Icon name="chevron-right" size={15} />
            </Link>
          ))}
        </div>
      ) : null}

      <div className="filters-bar">
        <label className="search-box">
          <Icon name="search" size={15} />
          <input
            aria-label="Search event fields"
            onChange={(event) => { setQuery(event.target.value); resetPage(); }}
            placeholder="Search tool, action, error…"
            value={query}
          />
        </label>
        <select className="select compact" aria-label="Event status" onChange={(event) => { setStatus(event.target.value); resetPage(); }} value={status}>
          <option value="">All statuses</option>
          <option value="success">success</option>
          <option value="failure">failure</option>
          <option value="unknown">unknown</option>
        </select>
        <select className="select compact" aria-label="Tool filter" onChange={(event) => { setTool(event.target.value); resetPage(); }} value={tool}>
          <option value="">All tools</option>
          {data.tools.map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
        <select className="select compact" aria-label="Detection category" onChange={(event) => { setCategory(event.target.value); resetPage(); }} value={category}>
          <option value="">All evidence</option>
          {CATEGORIES.map((name) => <option key={name} value={name}>{name.replaceAll("_", " ")}</option>)}
        </select>
        <select className="select compact" aria-label="Event order" onChange={(event) => { setOrder(event.target.value as "asc" | "desc"); resetPage(); }} value={order}>
          <option value="asc">Oldest first</option>
          <option value="desc">Newest first</option>
        </select>
        {hasFilters ? <button className="button button-ghost button-sm" onClick={clearFilters} type="button"><Icon name="x" size={14} /> Clear</button> : null}
      </div>

      <div className="detail-grid trace-grid">
        <div className="detail-main">
          <Card
            actions={<span className="map-caption">{data.total_events} matching · page {data.page} / {data.pages}</span>}
            eyebrow="Chronology"
            flush
            title="Tool-call trace"
          >
            {session.error ? <div className="inline-error"><Icon name="alert" size={16} />{session.error}</div> : null}
            {!data.events.length ? (
              <EmptyState
                action={hasFilters ? <button className="button button-secondary button-sm" onClick={clearFilters} type="button">Clear filters</button> : undefined}
                description={hasFilters ? "No event matches the current filters." : "This session has no recorded tool calls."}
                icon="activity"
                title={hasFilters ? "No matching evidence" : "Empty session"}
              />
            ) : (
              <div className="trace-list">
                {data.events.map((event) => <EventItem event={event} key={event.id} startedAt={data.started_at} />)}
              </div>
            )}
            {data.pages > 1 ? (
              <div className="pagination">
                <button className="button button-secondary button-sm" disabled={data.page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))} type="button">
                  <Icon name="arrow-left" size={14} /> Previous
                </button>
                <span>Page {data.page} of {data.pages}</span>
                <button className="button button-secondary button-sm" disabled={data.page >= data.pages} onClick={() => setPage((value) => value + 1)} type="button">
                  Next <Icon name="arrow-right" size={14} />
                </button>
              </div>
            ) : null}
          </Card>
        </div>

        <aside className="detail-side">
          <Card eyebrow="Session" title="Record">
            <MetaList
              items={[
                { label: "Status", value: <span className={`session-state state-${data.status}`}>{data.status}</span> },
                { label: "Agent", value: data.agent_name ?? data.agent_id },
                { label: "Started", value: formatDate(data.started_at) },
                { label: "Ended", value: data.ended_at ? formatDate(data.ended_at) : "—" },
                { label: "Events", value: data.event_count },
                { label: "Open incidents", value: data.open_incidents },
              ]}
            />
          </Card>

          <Card eyebrow="Metadata" title="Run context">
            {data.metadata && Object.keys(data.metadata).length ? (
              <pre className="json-view">{JSON.stringify(data.metadata, null, 2)}</pre>
            ) : (
              <p className="muted-copy">No session metadata was supplied.</p>
            )}
          </Card>

          <Card eyebrow="Detector logic" title="What triggers a finding?">
            <ul className="rule-list">
              <li><strong>Exact repetition</strong><span>Same normalized call repeated inside the window.</span></li>
              <li><strong>Oscillation</strong><span>Alternating calls cycle without an exit.</span></li>
              <li><strong>Repeated failure</strong><span>Distinct failing calls cross the threshold.</span></li>
              <li><strong>No progress</strong><span>Events explicitly report no advancement.</span></li>
            </ul>
            <Link className="text-link" to="/detection">Tune detection rules <Icon name="arrow-right" size={14} /></Link>
          </Card>
        </aside>
      </div>
    </div>
  );
}
