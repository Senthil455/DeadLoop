import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { formatNumber, timeAgo } from "../api";
import { useApi, useDocumentTitle } from "../hooks";
import type { Agent } from "../types";
import {
  AgentStatusDot,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Icon,
  PageHeader,
  SkeletonRows,
  Stat,
} from "../components/ui";

const STATUSES = ["all", "active", "degraded", "stale", "offline", "unknown"];

export default function AgentsPage() {
  const { data, loading, error, reload } = useApi<Agent[]>("/agents");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  useDocumentTitle("Agents");

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (data ?? []).filter((agent) => {
      if (status !== "all" && agent.status !== status) return false;
      if (!needle) return true;
      return [agent.name, agent.id, agent.framework, agent.description]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle));
    });
  }, [data, query, status]);

  const totals = useMemo(() => {
    const items = data ?? [];
    return {
      active: items.filter((agent) => agent.status === "active").length,
      sessions: items.reduce((sum, agent) => sum + agent.session_count, 0),
      open: items.reduce((sum, agent) => sum + agent.open_incidents, 0),
    };
  }, [data]);

  return (
    <div className="page">
      <PageHeader
        eyebrow="Monitor / agents"
        title="Agent fleet"
        description="Every process that has reported events, with its latest activity and unresolved incidents."
        actions={
          <Link className="button button-primary button-md" to="/integrations">
            <Icon name="plug" size={16} /> Connect agent
          </Link>
        }
      />

      {error ? <ErrorState message={error} retry={reload} /> : null}

      <div className="stat-grid stat-grid-three">
        <Stat detail={`${data?.length ?? 0} registered`} icon="bot" label="Active agents" value={totals.active} />
        <Stat detail="across the fleet" icon="layers" label="Recorded sessions" value={formatNumber(totals.sessions)} />
        <Stat
          detail="open or acknowledged"
          icon="alert"
          label="Unresolved incidents"
          tone={totals.open ? "amber" : "default"}
          value={formatNumber(totals.open)}
        />
      </div>

      <Card
        actions={
          <div className="filter-row">
            <label className="search-box">
              <Icon name="search" size={15} />
              <input
                aria-label="Search agents"
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search name, framework, id"
                value={query}
              />
            </label>
            <select
              aria-label="Filter by agent status"
              className="select compact"
              onChange={(event) => setStatus(event.target.value)}
              value={status}
            >
              {STATUSES.map((value) => (
                <option key={value} value={value}>
                  {value === "all" ? "All statuses" : value}
                </option>
              ))}
            </select>
            <Button icon="refresh" onClick={reload} size="sm">
              Refresh
            </Button>
          </div>
        }
        eyebrow="Inventory"
        flush
        title="Registered agents"
      >
        {loading && !data ? <SkeletonRows rows={5} /> : null}
        {!loading && !filtered.length ? (
          <EmptyState
            action={
              data?.length ? (
                <Button icon="refresh" onClick={() => { setQuery(""); setStatus("all"); }} size="sm">
                  Clear filters
                </Button>
              ) : (
                <Link className="text-link" to="/integrations">
                  Open integration guide <Icon name="arrow-right" size={14} />
                </Link>
              )
            }
            description={
              data?.length
                ? "No agent matches the current search and status filter."
                : "Send the first event with a write-only ingestion key. The agent is registered automatically."
            }
            icon="bot"
            title={data?.length ? "No matching agents" : "No agents connected"}
          />
        ) : null}
        {filtered.length ? (
          <div className="table-scroll">
            <table className="data-table agent-table">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Status</th>
                  <th>Framework</th>
                  <th className="num">Sessions</th>
                  <th className="num">Events</th>
                  <th className="num">Open</th>
                  <th>Last seen</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {filtered.map((agent) => (
                  <tr key={agent.id}>
                    <td>
                      <Link className="agent-identity" to={`/agents/${agent.id}`}>
                        <span className="agent-glyph"><Icon name="bot" size={16} /></span>
                        <span>
                          <strong>{agent.name}</strong>
                          <small>{agent.is_demo ? "demo · " : ""}{agent.id}</small>
                        </span>
                      </Link>
                    </td>
                    <td><AgentStatusDot status={agent.status} /></td>
                    <td className="muted-cell">{agent.framework ?? "—"}</td>
                    <td className="num">{formatNumber(agent.session_count)}</td>
                    <td className="num">{formatNumber(agent.event_count)}</td>
                    <td className="num">
                      {agent.open_incidents ? (
                        <span className="count-badge warn">{agent.open_incidents}</span>
                      ) : (
                        <span className="muted-cell">0</span>
                      )}
                    </td>
                    <td className="muted-cell" title={agent.last_seen_at ?? undefined}>{timeAgo(agent.last_seen_at)}</td>
                    <td className="row-action">
                      <Link aria-label={`Open ${agent.name}`} className="icon-button" to={`/agents/${agent.id}`}>
                        <Icon name="chevron-right" size={16} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>

      <div className="footnote">
        <Icon name="activity" size={15} />
        Agent status is derived from last-seen time: active under 5 minutes, degraded under 30, stale under 24 hours.
      </div>
    </div>
  );
}
