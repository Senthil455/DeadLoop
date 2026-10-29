import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { formatShortDate, timeAgo } from "../api";
import { useApi, useDocumentTitle } from "../hooks";
import type { Agent, SessionSummary } from "../types";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Icon,
  PageHeader,
  SkeletonRows,
  Stat,
} from "../components/ui";

export default function SessionsPage() {
  const [agentId, setAgentId] = useState("");
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const agents = useApi<Agent[]>("/agents");
  const path = `/sessions?limit=100${agentId ? `&agent_id=${encodeURIComponent(agentId)}` : ""}${status ? `&status=${encodeURIComponent(status)}` : ""}`;
  const sessions = useApi<SessionSummary[]>(path);
  useDocumentTitle("Sessions");

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return sessions.data ?? [];
    return (sessions.data ?? []).filter((session) =>
      [session.id, session.agent_name, session.status]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle)),
    );
  }, [sessions.data, query]);

  const active = (sessions.data ?? []).filter((session) => session.status === "active").length;
  const paused = (sessions.data ?? []).filter((session) => session.status === "paused").length;
  const incidents = (sessions.data ?? []).reduce((sum, session) => sum + session.open_incidents, 0);

  return (
    <div className="page">
      <PageHeader
        eyebrow="Monitor / sessions"
        title="Execution sessions"
        description="Groups of tool calls from one agent run. Open a session to inspect its full evidence timeline."
      />

      <div className="stat-grid stat-grid-three">
        <Stat detail="in the current view" icon="activity" label="Active sessions" value={active} />
        <Stat detail="awaiting recovery" icon="pause" label="Paused sessions" value={paused} tone={paused ? "mint" : "default"} />
        <Stat detail="linked to these sessions" icon="alert" label="Open incidents" value={incidents} tone={incidents ? "amber" : "default"} />
      </div>

      <Card
        actions={
          <div className="filter-row">
            <label className="search-box">
              <Icon name="search" size={15} />
              <input
                aria-label="Search sessions"
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Session id or agent"
                value={query}
              />
            </label>
            <select
              aria-label="Filter by agent"
              className="select compact"
              onChange={(event) => setAgentId(event.target.value)}
              value={agentId}
            >
              <option value="">All agents</option>
              {(agents.data ?? []).map((agent) => (
                <option key={agent.id} value={agent.id}>{agent.name}</option>
              ))}
            </select>
            <select
              aria-label="Filter by session status"
              className="select compact"
              onChange={(event) => setStatus(event.target.value)}
              value={status}
            >
              <option value="">All states</option>
              <option value="active">active</option>
              <option value="paused">paused</option>
              <option value="completed">completed</option>
              <option value="failed">failed</option>
            </select>
            <Button icon="refresh" onClick={sessions.reload} size="sm">Refresh</Button>
          </div>
        }
        eyebrow="Timeline"
        flush
        title={sessions.data ? `${filtered.length} session${filtered.length === 1 ? "" : "s"}` : "Sessions"}
      >
        {sessions.error ? <ErrorState message={sessions.error} retry={sessions.reload} /> : null}
        {sessions.loading && !sessions.data ? <SkeletonRows rows={6} /> : null}
        {!sessions.loading && !filtered.length ? (
          <EmptyState
            action={
              <Link className="text-link" to="/integrations">
                Send a test event <Icon name="arrow-right" size={14} />
              </Link>
            }
            description={
              sessions.data?.length
                ? "No session matches the current filters."
                : "Sessions are created automatically when an agent sends its first event."
            }
            icon="layers"
            title={sessions.data?.length ? "No matching sessions" : "No sessions yet"}
          />
        ) : null}
        {filtered.length ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Session</th><th>Agent</th><th>State</th><th className="num">Events</th>
                  <th className="num">Open</th><th>Started</th><th>Ended</th><th aria-label="Open" />
                </tr>
              </thead>
              <tbody>
                {filtered.map((session) => (
                  <tr key={session.id}>
                    <td>
                      <Link className="mono link-cell" to={`/sessions/${session.id}`}>
                        {session.id.length > 22 ? `${session.id.slice(0, 22)}…` : session.id}
                      </Link>
                      <span className="sub-cell">{session.metadata && typeof session.metadata === "object" ? String(session.metadata.task ?? session.metadata.name ?? "run") : "run"}</span>
                    </td>
                    <td>
                      {session.agent_name ? (
                        <Link className="link-cell" to={`/agents/${session.agent_id}`}>{session.agent_name}</Link>
                      ) : <span className="muted-cell">unknown</span>}
                    </td>
                    <td><span className={`session-state state-${session.status}`}>{session.status}</span></td>
                    <td className="num">{session.event_count}</td>
                    <td className="num">{session.open_incidents ? <span className="count-badge warn">{session.open_incidents}</span> : "—"}</td>
                    <td className="muted-cell nowrap" title={session.started_at}>{formatShortDate(session.started_at)}</td>
                    <td className="muted-cell nowrap">{session.ended_at ? timeAgo(session.ended_at) : "—"}</td>
                    <td className="row-action"><Link aria-label="Open session" className="icon-button" to={`/sessions/${session.id}`}><Icon name="chevron-right" size={16} /></Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>
    </div>
  );
}
