import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { formatShortDate, timeAgo } from "../api";
import { useApi, useDocumentTitle } from "../hooks";
import type { Agent, IncidentSummary } from "../types";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Icon,
  PageHeader,
  SeverityChip,
  SkeletonRows,
  Stat,
  StatusChip,
} from "../components/ui";

const STATUS_TABS = ["ALL", "OPEN", "ACKNOWLEDGED", "RESOLVED", "DISMISSED"] as const;
const SEVERITIES = ["", "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];
const CATEGORIES = [
  "",
  "exact_repetition",
  "semantic_repetition",
  "oscillation",
  "repeated_failure",
  "no_progress",
  "budget_exceeded",
];

export default function IncidentsPage() {
  const [params] = useSearchParams();
  const [status, setStatus] = useState<string>("ALL");
  const [severity, setSeverity] = useState("");
  const [category, setCategory] = useState("");
  const [agentId, setAgentId] = useState(params.get("agent_id") ?? "");
  const [query, setQuery] = useState("");
  const incidents = useApi<IncidentSummary[]>("/incidents?limit=200");
  const agents = useApi<Agent[]>("/agents");
  useDocumentTitle("Incidents");

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (incidents.data ?? []).filter((incident) => {
      if (status !== "ALL" && incident.status !== status) return false;
      if (severity && incident.severity !== severity) return false;
      if (category && incident.detection_category !== category) return false;
      if (agentId && incident.agent_id !== agentId) return false;
      if (!needle) return true;
      return [incident.title, incident.agent_name, incident.detection_category, incident.id]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle));
    });
  }, [incidents.data, status, severity, category, agentId, query]);

  const counts = useMemo(() => {
    const items = incidents.data ?? [];
    const byStatus = (value: string) => items.filter((incident) => incident.status === value).length;
    return {
      open: byStatus("OPEN"),
      acknowledged: byStatus("ACKNOWLEDGED"),
      high: items.filter(
        (incident) =>
          (incident.status === "OPEN" || incident.status === "ACKNOWLEDGED") &&
          (incident.severity === "HIGH" || incident.severity === "CRITICAL"),
      ).length,
      resolved: byStatus("RESOLVED"),
    };
  }, [incidents.data]);

  const hasFilters = Boolean(status !== "ALL" || severity || category || agentId || query);

  function clearFilters() {
    setStatus("ALL");
    setSeverity("");
    setCategory("");
    setAgentId("");
    setQuery("");
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="Monitor / incidents"
        title="Incident queue"
        description="Deterministic findings generated from recorded evidence. Triage, explain, and approve interventions."
        actions={<Button icon="refresh" onClick={() => { incidents.reload(); agents.reload(); }}>Refresh</Button>}
      />

      <div className="stat-grid stat-grid-four">
        <Stat detail="not yet acknowledged" icon="alert" label="Open" tone={counts.open ? "amber" : "default"} value={counts.open} />
        <Stat detail="being triaged" icon="clock" label="Acknowledged" value={counts.acknowledged} />
        <Stat detail="open + high severity" icon="shield" label="High risk" tone={counts.high ? "red" : "default"} value={counts.high} />
        <Stat detail="closed with evidence retained" icon="check" label="Resolved" value={counts.resolved} />
      </div>

      <Card eyebrow="Triage" flush title="All findings">
        <div className="incident-toolbar">
          <div className="tabs" role="tablist">
            {STATUS_TABS.map((tab) => (
              <button
                aria-selected={status === tab}
                className={`tab ${status === tab ? "active" : ""}`}
                key={tab}
                onClick={() => setStatus(tab)}
                role="tab"
                type="button"
              >
                {tab === "ALL" ? "All" : tab.toLowerCase()}
                {tab !== "ALL" && incidents.data ? (
                  <span>{incidents.data.filter((incident) => incident.status === tab).length}</span>
                ) : null}
              </button>
            ))}
          </div>
          <div className="filter-row">
            <label className="search-box">
              <Icon name="search" size={15} />
              <input aria-label="Search incidents" onChange={(event) => setQuery(event.target.value)} placeholder="Search title, agent…" value={query} />
            </label>
            <select aria-label="Filter by severity" className="select compact" onChange={(event) => setSeverity(event.target.value)} value={severity}>
              <option value="">All severities</option>
              {SEVERITIES.filter(Boolean).map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
            <select aria-label="Filter by category" className="select compact" onChange={(event) => setCategory(event.target.value)} value={category}>
              <option value="">All categories</option>
              {CATEGORIES.filter(Boolean).map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}
            </select>
            <select aria-label="Filter by agent" className="select compact" onChange={(event) => setAgentId(event.target.value)} value={agentId}>
              <option value="">All agents</option>
              {(agents.data ?? []).map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
            </select>
            {hasFilters ? <Button icon="x" onClick={clearFilters} size="sm" variant="ghost">Clear</Button> : null}
          </div>
        </div>

        {incidents.error ? <ErrorState message={incidents.error} retry={incidents.reload} /> : null}
        {incidents.loading && !incidents.data ? <SkeletonRows rows={6} /> : null}
        {!incidents.loading && !filtered.length ? (
          <EmptyState
            action={hasFilters ? <Button onClick={clearFilters} size="sm">Clear filters</Button> : (
              <Link className="text-link" to="/integrations">Run a simulator scenario <Icon name="arrow-right" size={14} /></Link>
            )}
            description={
              hasFilters
                ? "No incident matches the current filters."
                : "No findings have been recorded. Detection runs automatically after every ingested batch."
            }
            icon="shield"
            title={hasFilters ? "No matching incidents" : "Queue is clear"}
          />
        ) : null}
        {filtered.length ? (
          <div className="table-scroll">
            <table className="data-table incident-table">
              <thead>
                <tr>
                  <th>Severity</th><th>Incident</th><th>Agent</th><th>Category</th>
                  <th className="num">Evidence</th><th>Status</th><th>Detected</th><th aria-label="Open" />
                </tr>
              </thead>
              <tbody>
                {filtered.map((incident) => (
                  <tr key={incident.id}>
                    <td><SeverityChip severity={incident.severity} /></td>
                    <td>
                      <Link className="primary-cell" to={`/incidents/${incident.id}`}>{incident.title}</Link>
                      <span className="sub-cell mono">{incident.id}</span>
                    </td>
                    <td>{incident.agent_name ?? <span className="muted-cell">unknown</span>}</td>
                    <td><span className="category-label">{incident.detection_category?.replaceAll("_", " ") ?? "—"}</span></td>
                    <td className="num">
                      <span className="evidence-count"><Icon name="layers" size={13} /> {incident.evidence_event_count}</span>
                    </td>
                    <td><StatusChip status={incident.status} /></td>
                    <td className="muted-cell nowrap" title={formatShortDate(incident.created_at)}>{timeAgo(incident.created_at)}</td>
                    <td className="row-action"><Link aria-label="Open incident" className="icon-button" to={`/incidents/${incident.id}`}><Icon name="chevron-right" size={16} /></Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>

      <div className="footnote">
        <Icon name="shield" size={15} />
        Risk score combines detector confidence, severity, and evidence volume. It is not generated by a language model.
      </div>
    </div>
  );
}
