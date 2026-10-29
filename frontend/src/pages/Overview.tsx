import { useEffect } from "react";
import { Link } from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatNumber, formatShortDate, timeAgo } from "../api";
import { useApi, useDocumentTitle, useSystem } from "../hooks";
import type { Overview } from "../types";
import {
  AgentStatusDot,
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

function bucketLabel(bucket: string): string {
  const date = new Date(bucket);
  if (Number.isNaN(date.getTime())) return bucket;
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(date);
}

export default function OverviewPage() {
  const { data, loading, error, reload } = useApi<Overview>("/stats/overview");
  const { health } = useSystem();
  useDocumentTitle("Overview");

  useEffect(() => {
    const timer = window.setInterval(reload, 30_000);
    return () => window.clearInterval(timer);
  }, [reload]);

  const openFeed = data?.incident_feed.filter(
    (incident) => incident.status === "OPEN" || incident.status === "ACKNOWLEDGED",
  );

  return (
    <div className="page">
      <PageHeader
        eyebrow="Operations / overview"
        title="Execution health"
        description="Loop risk across every connected agent, grounded in recorded tool-call evidence."
        actions={
          <>
            <span className="freshness">
              <span className="live-dot ok" />
              {data ? `updated ${timeAgo(data.generated_at)}` : "collecting"}
            </span>
            <Button icon="refresh" onClick={reload}>
              Refresh
            </Button>
          </>
        }
      />

      {error && !data ? <ErrorState message={error} retry={reload} /> : null}

      {!data && loading ? (
        <div className="overview-skeleton">
          <SkeletonRows rows={6} />
        </div>
      ) : null}

      {data ? (
        <>
          <div className="stat-grid">
            <Stat
              detail={`${data.high_severity_incidents} high or critical`}
              icon="alert"
              label="Open incidents"
              tone={data.open_incidents > 0 ? "amber" : "default"}
              value={formatNumber(data.open_incidents)}
            />
            <Stat
              detail="exact + semantic detections"
              icon="activity"
              label="Loop detections"
              tone={data.repetition_detections > 0 ? "red" : "default"}
              value={formatNumber(data.repetition_detections)}
            />
            <Stat
              detail={`${formatNumber(data.active_sessions)} sessions active`}
              icon="bot"
              label="Connected agents"
              value={formatNumber(data.total_agents)}
            />
            <Stat
              detail="recorded failure status"
              icon="layers"
              label="Failed tool calls"
              value={formatNumber(data.failed_tool_calls)}
            />
          </div>

          <div className="overview-rail">
            <Card
              actions={<span className="map-caption">24 hours · UTC</span>}
              className="chart-card"
              eyebrow="Telemetry"
              title="Event volume"
            >
              {data.event_series.some((point) => point.events > 0) ? (
                <div className="chart-wrap">
                  <ResponsiveContainer height={252} width="100%">
                    <AreaChart data={data.event_series} margin={{ top: 10, right: 8, left: -22, bottom: 0 }}>
                      <defs>
                        <linearGradient id="eventFill" x1="0" x2="0" y1="0" y2="1">
                          <stop offset="0%" stopColor="#6fe7c7" stopOpacity={0.28} />
                          <stop offset="100%" stopColor="#6fe7c7" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke="#1d2729" strokeDasharray="2 5" vertical={false} />
                      <XAxis
                        axisLine={false}
                        dataKey="bucket"
                        interval={5}
                        tick={{ fill: "#6c7b7d", fontSize: 10 }}
                        tickFormatter={bucketLabel}
                        tickLine={false}
                      />
                      <YAxis
                        allowDecimals={false}
                        axisLine={false}
                        tick={{ fill: "#6c7b7d", fontSize: 10 }}
                        tickLine={false}
                        width={42}
                      />
                      <Tooltip
                        contentStyle={{
                          background: "#0b1011",
                          border: "1px solid #2a393c",
                          borderRadius: 6,
                          color: "#dfe9e8",
                          fontSize: 12,
                        }}
                        labelFormatter={(label) => bucketLabel(String(label))}
                        cursor={{ stroke: "#3e5659", strokeDasharray: "3 4" }}
                      />
                      <Area
                        dataKey="events"
                        fill="url(#eventFill)"
                        name="events"
                        stroke="#6fe7c7"
                        strokeWidth={1.8}
                        type="monotone"
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <EmptyState
                  description="Run a simulator scenario or send events from an agent to populate the timeline."
                  icon="activity"
                  title="No events in the last 24 hours"
                />
              )}
            </Card>

            <Card
              actions={
                <Link className="text-link" to="/incidents">
                  All incidents <Icon name="arrow-right" size={14} />
                </Link>
              }
              className="attention-card"
              eyebrow="Triage"
              title="Needs attention"
            >
              {openFeed && openFeed.length > 0 ? (
                <div className="attention-list">
                  {openFeed.slice(0, 5).map((incident) => (
                    <Link className="attention-item" key={incident.id} to={`/incidents/${incident.id}`}>
                      <div className="attention-marks">
                        <SeverityChip severity={incident.severity} />
                        <StatusChip status={incident.status} />
                      </div>
                      <strong>{incident.title}</strong>
                      <span>
                        {incident.agent_name ?? "unknown agent"} · {timeAgo(incident.created_at)}
                      </span>
                    </Link>
                  ))}
                </div>
              ) : (
                <EmptyState
                  description={
                    data.total_agents > 0
                      ? "No unresolved findings. Keep the collector running."
                      : "Nothing has reported yet. Connect an agent to start monitoring."
                  }
                  icon="shield"
                  title={data.total_agents > 0 ? "No open incidents" : "No agents connected"}
                  action={
                    data.total_agents === 0 ? (
                      <Link className="text-link" to="/integrations">
                        Connect your first agent <Icon name="arrow-right" size={14} />
                      </Link>
                    ) : undefined
                  }
                />
              )}
            </Card>
          </div>

          <div className="overview-lower">
            <Card
              actions={
                <Link className="text-link" to="/agents">
                  View all <Icon name="arrow-right" size={14} />
                </Link>
              }
              eyebrow="Fleet"
              flush
              title="Recent agents"
            >
              {data.recent_activity.length ? (
                <div className="table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Agent</th>
                        <th>Status</th>
                        <th className="num">Sessions</th>
                        <th className="num">Events</th>
                        <th>Last seen</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.recent_activity.map((agent) => (
                        <tr key={agent.id}>
                          <td>
                            <Link className="primary-cell" to={`/agents/${agent.id}`}>
                              {agent.name}
                            </Link>
                            <span className="sub-cell">{agent.framework ?? "framework unknown"}</span>
                          </td>
                          <td><AgentStatusDot status={agent.status} /></td>
                          <td className="num">{formatNumber(agent.session_count)}</td>
                          <td className="num">{formatNumber(agent.event_count)}</td>
                          <td className="muted-cell">{timeAgo(agent.last_seen_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState description="Agents are created automatically on first event ingestion." icon="bot" title="No agents yet" />
              )}
            </Card>

            <Card eyebrow="Control" flush title="Recent interventions">
              {data.recent_interventions.length ? (
                <div className="intervention-list">
                  {data.recent_interventions.map((item) => (
                    <Link className="intervention-item" key={item.id} to={`/incidents/${item.incident_id}`}>
                      <span className={`intervention-icon ${item.execution_status === "ACKNOWLEDGED" ? "ok" : ""}`}>
                        <Icon name="pause" size={16} />
                      </span>
                      <div>
                        <strong>{item.requested_action} · {item.agent_id.slice(0, 14)}…</strong>
                        <span>
                          {item.approval_status.replaceAll("_", " ")} → {item.execution_status}
                          {item.simulated ? " · simulated" : ""}
                        </span>
                      </div>
                      <time>{timeAgo(item.requested_at)}</time>
                    </Link>
                  ))}
                </div>
              ) : (
                <EmptyState description="Pause requests and their outcomes appear here." icon="pause" title="No interventions yet" />
              )}
            </Card>
          </div>

          <div className="overview-note">
            <Icon name="shield" size={15} />
            <span>
              Detectors require explicit failure or no-progress evidence. A repeated call that advances
              the task is not, by itself, an incident.
            </span>
            <span className="sep" />
            <span>Environment: {health?.environment ?? "unknown"}</span>
            <span>First event: {formatShortDate(data.recent_activity[0]?.created_at)}</span>
          </div>
        </>
      ) : null}
    </div>
  );
}
