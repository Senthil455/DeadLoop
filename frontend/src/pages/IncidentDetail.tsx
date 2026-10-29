import { useMemo, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api, formatDate, timeAgo } from "../api";
import { errorText, useApi, useDocumentTitle, useSystem } from "../hooks";
import type { IncidentDetail, IncidentStatus, Intervention } from "../types";
import {
  Button,
  Card,
  CopyButton,
  EmptyState,
  ErrorState,
  Field,
  Icon,
  InterventionChip,
  Loading,
  MetaList,
  Modal,
  PageHeader,
  SeverityChip,
  StatusChip,
} from "../components/ui";

function valueText(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function ActionModal({
  title,
  description,
  confirmLabel,
  requireNote = false,
  danger = false,
  onClose,
  onConfirm,
}: {
  title: string;
  description: string;
  confirmLabel: string;
  requireNote?: boolean;
  danger?: boolean;
  onClose: () => void;
  onConfirm: (note: string) => Promise<void>;
}) {
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (requireNote && !note.trim()) {
      setError("A note is required.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await onConfirm(note.trim());
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
          <Button disabled={busy} onClick={() => void submit({ preventDefault: () => undefined } as FormEvent)} variant={danger ? "danger" : "primary"}>
            {busy ? "Working…" : confirmLabel}
          </Button>
        </>
      }
      onClose={onClose}
      title={title}
    >
      <div className="form-stack">
        <p className="modal-copy">{description}</p>
        <Field hint="Optional context is written to the incident audit log." label="Operator note">
          <textarea
            autoFocus
            maxLength={1000}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Why is this decision being made?"
            rows={4}
            value={note}
          />
        </Field>
        {error ? <div className="inline-error"><Icon name="alert" size={16} />{error}</div> : null}
      </div>
    </Modal>
  );
}

function InterventionRow({
  intervention,
  onApprove,
  onReject,
  busy,
}: {
  intervention: Intervention;
  onApprove: () => void;
  onReject: () => void;
  busy: boolean;
}) {
  return (
    <div className="intervention-card">
      <div className="intervention-card-head">
        <span className="intervention-icon"><Icon name="pause" size={16} /></span>
        <div>
          <strong>Pause request</strong>
          <span>{intervention.policy_mode.replaceAll("_", " ")} · {timeAgo(intervention.requested_at)}</span>
        </div>
        <InterventionChip intervention={intervention} />
      </div>
      <div className="intervention-card-meta">
        <span><b>Approval</b> {intervention.approval_status.replaceAll("_", " ")}</span>
        <span><b>Execution</b> {intervention.execution_status.replaceAll("_", " ")}</span>
        <span><b>Runtime</b> {String(intervention.result?.runtime ?? "—")}</span>
      </div>
      {intervention.result?.message ? (
        <p className="intervention-result">{String(intervention.result.message)}</p>
      ) : null}
      {intervention.simulated ? (
        <p className="simulated-note"><Icon name="spark" size={14} /> Simulated runtime — no external process was controlled.</p>
      ) : null}
      {intervention.approval_status === "PENDING" ? (
        <div className="button-row">
          <Button disabled={busy} icon="check" onClick={onApprove} size="sm" variant="primary">Approve pause</Button>
          <Button disabled={busy} icon="x" onClick={onReject} size="sm" variant="ghost">Reject</Button>
        </div>
      ) : null}
    </div>
  );
}

export default function IncidentDetailPage() {
  const { incidentId = "" } = useParams();
  const incident = useApi<IncidentDetail>(incidentId ? `/incidents/${encodeURIComponent(incidentId)}` : null);
  const { health } = useSystem();
  const [statusAction, setStatusAction] = useState<IncidentStatus | null>(null);
  const [interventionAction, setInterventionAction] = useState<{ id: string; action: "approve" | "reject" } | null>(null);
  const [requestingPause, setRequestingPause] = useState(false);
  const [explaining, setExplaining] = useState(false);
  const [explainError, setExplainError] = useState("");
  const [interventionError, setInterventionError] = useState("");
  const [noteBody, setNoteBody] = useState("");
  const [noteError, setNoteError] = useState("");
  const [noteBusy, setNoteBusy] = useState(false);
  useDocumentTitle(incident.data?.title ?? "Incident detail");

  const pendingIntervention = useMemo(
    () => incident.data?.interventions.find((item) => item.approval_status === "PENDING"),
    [incident.data],
  );
  const acknowledgedIntervention = useMemo(
    () => incident.data?.interventions.find((item) => item.execution_status === "ACKNOWLEDGED"),
    [incident.data],
  );

  if (incident.loading && !incident.data) return <div className="page"><Loading label="Loading incident" /></div>;
  if (incident.error && !incident.data) return <div className="page"><ErrorState message={incident.error} retry={incident.reload} /></div>;
  if (!incident.data) return null;
  const data = incident.data;
  const detection = data.detection;
  const closed = data.status === "RESOLVED" || data.status === "DISMISSED";
  const canRequestPause = !closed && !pendingIntervention && !acknowledgedIntervention && health !== null;
  const policyPermitsPause = health?.intervention_mode === "approval_required" || health?.intervention_mode === "automatic";
  const confidence = detection.confidence <= 1 ? detection.confidence * 100 : detection.confidence;
  const ai = detection.ai_explanation;

  async function changeStatus(note: string) {
    if (!statusAction) return;
    const updated = await api.updateIncidentStatus(data.id, statusAction, note || undefined);
    incident.setData(updated);
    setStatusAction(null);
  }

  async function requestPause() {
    setRequestingPause(true);
    setInterventionError("");
    try {
      await api.requestIntervention(data.id);
      incident.reload();
    } catch (reason) {
      setInterventionError(errorText(reason));
    } finally {
      setRequestingPause(false);
    }
  }

  async function decideIntervention(note: string) {
    if (!interventionAction) return;
    if (interventionAction.action === "approve") {
      await api.approveIntervention(interventionAction.id, note || undefined);
    } else {
      await api.rejectIntervention(interventionAction.id, note || undefined);
    }
    setInterventionAction(null);
    incident.reload();
  }

  async function explain() {
    setExplaining(true);
    setExplainError("");
    try {
      await api.explain(data.id);
      incident.reload();
    } catch (reason) {
      setExplainError(errorText(reason));
    } finally {
      setExplaining(false);
    }
  }

  async function addNote(event: FormEvent) {
    event.preventDefault();
    if (!noteBody.trim()) {
      setNoteError("Write a note first.");
      return;
    }
    setNoteBusy(true);
    setNoteError("");
    try {
      const updated = await api.addNote(data.id, noteBody.trim());
      incident.setData(updated);
      setNoteBody("");
    } catch (reason) {
      setNoteError(errorText(reason));
    } finally {
      setNoteBusy(false);
    }
  }

  return (
    <div className="page">
      <div className="back-link-row">
        <Link className="back-link" to="/incidents"><Icon name="arrow-left" size={14} /> Incident queue</Link>
      </div>

      <PageHeader
        eyebrow="Monitor / incidents / detail"
        title={data.title}
        description={
          <span>
            {detection.category.replaceAll("_", " ")} · detected {formatDate(data.created_at)} · agent{" "}
            <Link className="link-cell" to={`/agents/${data.agent_id}`}>{data.agent_name ?? data.agent_id}</Link>
          </span>
        }
        actions={
          <>
            <SeverityChip severity={data.severity} />
            <StatusChip status={data.status} />
            <CopyButton label="Copy ID" value={data.id} />
            {data.status === "OPEN" ? (
              <Button icon="check" onClick={() => setStatusAction("ACKNOWLEDGED")}>Acknowledge</Button>
            ) : null}
            {!closed ? (
              <>
                <Button icon="check" onClick={() => setStatusAction("RESOLVED")} variant="primary">Resolve</Button>
                <Button icon="x" onClick={() => setStatusAction("DISMISSED")} variant="ghost">Dismiss</Button>
              </>
            ) : null}
          </>
        }
      />

      <div className="incident-banner">
        <div className="risk-block">
          <span className="risk-label">Risk score</span>
          <strong>{detection.risk_score}<small>/100</small></strong>
          <span className="risk-track"><span style={{ width: `${Math.min(100, detection.risk_score)}%` }} /></span>
        </div>
        <div className="incident-banner-facts">
          <div><span>Severity</span><SeverityChip severity={data.severity} /></div>
          <div><span>Confidence</span><strong>{confidence.toFixed(0)}%</strong></div>
          <div><span>Evidence events</span><strong>{data.evidence_event_count}</strong></div>
          <div><span>First seen</span><strong>{timeAgo(detection.first_seen_at)}</strong></div>
          <div><span>Last seen</span><strong>{timeAgo(detection.last_seen_at)}</strong></div>
        </div>
      </div>

      <div className="detail-grid">
        <div className="detail-main">
          <Card eyebrow="Finding" title="What was observed">
            <p className="prose">{detection.explanation}</p>
            <div className="recommendation">
              <span className="recommendation-label"><Icon name="shield" size={15} /> Recommended action</span>
              <p>{detection.recommended_action}</p>
            </div>
            {detection.evidence.confidence_basis || detection.evidence.uncertainty ? (
              <div className="confidence-notes">
                {detection.evidence.confidence_basis ? (
                  <p><b>Confidence basis</b>{detection.evidence.confidence_basis}</p>
                ) : null}
                {detection.evidence.uncertainty ? (
                  <p><b>Uncertainty</b>{detection.evidence.uncertainty}</p>
                ) : null}
              </div>
            ) : null}
          </Card>

          <Card
            actions={<span className="map-caption">{data.evidence_event_count} cited events</span>}
            eyebrow="Evidence"
            title="Detection record"
          >
            <div className="metrics-grid">
              <div className="metric-box">
                <span>Detector</span>
                <strong>{detection.category.replaceAll("_", " ")}</strong>
              </div>
              <div className="metric-box">
                <span>Risk</span>
                <strong>{detection.risk_score} / 100</strong>
              </div>
              <div className="metric-box">
                <span>Confidence</span>
                <strong>{confidence.toFixed(0)}%</strong>
              </div>
              <div className="metric-box">
                <span>Events cited</span>
                <strong>{data.evidence_event_count}</strong>
              </div>
            </div>

            {detection.evidence.metrics && Object.keys(detection.evidence.metrics).length ? (
              <div className="evidence-section">
                <span className="payload-label">Measured metrics</span>
                <div className="evidence-metrics">
                  {Object.entries(detection.evidence.metrics).map(([key, value]) => (
                    <span className="evidence-metric" key={key}>
                      <b>{key.replaceAll("_", " ")}</b>
                      {valueText(value)}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}

            {detection.evidence.sequence?.length ? (
              <div className="evidence-section">
                <span className="payload-label">Observed sequence</span>
                <div className="sequence-list">
                  {detection.evidence.sequence.map((item, index) => (
                    <div className="sequence-item" key={`${String(item.event_id ?? index)}-${index}`}>
                      <span className="sequence-index mono">{String(index + 1).padStart(2, "0")}</span>
                      <div>
                        <strong>{valueText(item.tool_name ?? item.tool ?? "tool call")}</strong>
                        <span>
                          {valueText(item.status ?? "unknown")}
                          {item.error_category ? ` · ${valueText(item.error_category)}` : ""}
                          {item.event_id ? ` · ${String(item.event_id).slice(0, 18)}…` : ""}
                        </span>
                      </div>
                      {item.made_progress !== undefined ? (
                        <span className={`mini-tag ${item.made_progress ? "success" : "danger"}`}>
                          {item.made_progress ? "progress" : "no progress"}
                        </span>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="evidence-section">
              <span className="payload-label">Cited event IDs</span>
              <div className="id-cloud">
                {data.evidence_event_ids.length ? data.evidence_event_ids.map((eventId) => (
                  <Link className="id-chip mono" key={eventId} to={`/sessions/${data.session_id}`} title="Open the session trace">
                    {eventId.slice(0, 20)}{eventId.length > 20 ? "…" : ""}
                  </Link>
                )) : <span className="muted-copy">No event IDs recorded.</span>}
              </div>
              <Link className="text-link" to={`/sessions/${data.session_id}`}>
                Inspect full session trace <Icon name="arrow-right" size={14} />
              </Link>
            </div>
          </Card>

          <Card
            actions={
              ai ? <span className="chip tone-mint">{ai.source === "ai" ? "AI ASSISTED" : "DETERMINISTIC"}</span> : null
            }
            eyebrow="Narrative"
            title="Explanation"
          >
            {ai ? (
              <div className="ai-explanation">
                <p className="prose strong-prose">{ai.explanation.summary}</p>
                {ai.fallback ? (
                  <div className="fallback-note">
                    <Icon name="shield" size={15} />
                    <span>
                      AI was unavailable, so this explanation was generated deterministically from the detection record.
                      {ai.error ? ` Provider note: ${ai.error}` : ""}
                    </span>
                  </div>
                ) : null}
                <div className="two-col-list">
                  <div>
                    <span className="payload-label">Observed facts</span>
                    <ul className="clean-list">{ai.explanation.observed_facts.map((fact) => <li key={fact}>{fact}</li>)}</ul>
                  </div>
                  <div>
                    <span className="payload-label">Hypotheses</span>
                    <ul className="clean-list">{ai.explanation.hypotheses.map((item) => <li key={item}>{item}</li>)}</ul>
                  </div>
                </div>
                <div>
                  <span className="payload-label">Next steps</span>
                  <ol className="clean-list numbered">{ai.explanation.next_steps.map((step) => <li key={step}>{step}</li>)}</ol>
                </div>
                <div className="explain-footer">
                  <span>{ai.provider} · {ai.model}</span>
                  <span>Generated {formatDate(detection.ai_generated_at)}</span>
                </div>
              </div>
            ) : (
              <EmptyState
                action={
                  <Button disabled={explaining} icon="spark" onClick={explain} variant="primary">
                    {explaining ? "Generating…" : "Explain this finding"}
                  </Button>
                }
                description="Generate a structured narrative from the recorded evidence. If no AI provider is configured, DEADLOOP returns a deterministic explanation and never blocks triage."
                icon="spark"
                title="No explanation generated yet"
              />
            )}
            {explainError ? <div className="inline-error"><Icon name="alert" size={16} />{explainError}</div> : null}
            {ai ? (
              <div className="button-row">
                <Button disabled={explaining} icon="refresh" onClick={explain} size="sm">
                  {explaining ? "Generating…" : "Regenerate"}
                </Button>
                <span className="muted-copy">AI reads sanitized evidence only. It cannot change the finding or execute actions.</span>
              </div>
            ) : null}
          </Card>

          <Card
            actions={<span className="map-caption">{data.notes.length} operator note{data.notes.length === 1 ? "" : "s"}</span>}
            eyebrow="Investigation"
            title="Notes"
          >
            <form className="note-form" onSubmit={addNote}>
              <textarea
                aria-label="Investigation note"
                maxLength={2000}
                onChange={(event) => setNoteBody(event.target.value)}
                placeholder="Record what you checked, what you changed, or why this is safe to close…"
                rows={3}
                value={noteBody}
              />
              <div className="note-form-foot">
                <span>{noteBody.length} / 2000</span>
                <Button disabled={noteBusy || !noteBody.trim()} icon="check" type="submit">
                  {noteBusy ? "Adding…" : "Add note"}
                </Button>
              </div>
              {noteError ? <div className="inline-error"><Icon name="alert" size={16} />{noteError}</div> : null}
            </form>
            {data.notes.length ? (
              <div className="notes-list">
                {data.notes.map((note) => (
                  <div className="note-item" key={note.id}>
                    <div className="note-head"><strong>{note.author}</strong><span>{formatDate(note.created_at)}</span></div>
                    <p>{note.body}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted-copy">No investigation notes yet.</p>
            )}
          </Card>
        </div>

        <aside className="detail-side">
          <Card eyebrow="Control" title="Intervention">
            {!policyPermitsPause && health ? (
              <div className="policy-note">
                <Icon name="shield" size={15} />
                <span>
                  Current policy is <b>{health.intervention_mode.replaceAll("_", " ")}</b>. Pause requests are blocked.
                  Change the policy in Settings first.
                </span>
              </div>
            ) : null}
            {canRequestPause ? (
              <>
                <p className="muted-copy">
                  Request a pause for this session. With <b>approval required</b>, nothing executes until an operator approves.
                </p>
                <Button
                  className="full-width"
                  disabled={requestingPause || !policyPermitsPause}
                  icon="pause"
                  onClick={requestPause}
                  variant="primary"
                >
                  {requestingPause ? "Requesting…" : "Request pause"}
                </Button>
                <p className="field-hint">
                  Only the demo simulator can acknowledge a pause. Real-agent continuations are reported as unsupported.
                </p>
              </>
            ) : null}
            {acknowledgedIntervention ? (
              <div className="paused-note">
                <Icon name="check" size={16} />
                <span>Session paused by {acknowledgedIntervention.simulated ? "the simulator" : "the runtime"}.</span>
              </div>
            ) : null}
            {pendingIntervention ? (
              <div className="paused-note pending">
                <Icon name="clock" size={16} />
                <span>Pause request awaiting operator approval.</span>
              </div>
            ) : null}
            {closed ? <p className="muted-copy">This incident is closed; new interventions are blocked.</p> : null}
            {interventionError ? <div className="inline-error"><Icon name="alert" size={16} />{interventionError}</div> : null}
            <div className="side-stack">
              {data.interventions.map((item) => (
                <InterventionRow
                  busy={Boolean(interventionAction)}
                  intervention={item}
                  key={item.id}
                  onApprove={() => setInterventionAction({ id: item.id, action: "approve" })}
                  onReject={() => setInterventionAction({ id: item.id, action: "reject" })}
                />
              ))}
              {!data.interventions.length ? <p className="muted-copy">No interventions requested.</p> : null}
            </div>
          </Card>

          <Card eyebrow="Attribution" title="Incident record">
            <MetaList
              items={[
                { label: "Incident", value: <span className="mono small break-all">{data.id}</span> },
                { label: "Agent", value: <Link className="link-cell" to={`/agents/${data.agent_id}`}>{data.agent_name ?? data.agent_id}</Link> },
                { label: "Session", value: <Link className="mono small link-cell break-all" to={`/sessions/${data.session_id}`}>{data.session_id}</Link> },
                { label: "Detection", value: <span className="mono small break-all">{data.detection_id}</span> },
                { label: "Created", value: formatDate(data.created_at) },
                { label: "Updated", value: formatDate(data.updated_at) },
                { label: "Resolved", value: data.resolved_at ? formatDate(data.resolved_at) : "—" },
              ]}
            />
          </Card>

          <Card eyebrow="Trace" flush title="Audit log">
            {data.audit.length ? (
              <div className="audit-list">
                {data.audit.map((entry) => (
                  <div className="audit-item" key={entry.id}>
                    <span className="audit-dot" />
                    <div>
                      <strong>{entry.action.replaceAll(".", " · ")}</strong>
                      <span>{entry.actor} · {formatDate(entry.timestamp)}</span>
                      {entry.details && Object.keys(entry.details).length ? (
                        <code>{JSON.stringify(entry.details)}</code>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="card-pad"><p className="muted-copy">No audit entries.</p></div>
            )}
          </Card>
        </aside>
      </div>

      {statusAction ? (
        <ActionModal
          confirmLabel={statusAction === "ACKNOWLEDGED" ? "Acknowledge incident" : statusAction === "RESOLVED" ? "Resolve incident" : "Dismiss incident"}
          danger={statusAction === "DISMISSED"}
          description={
            statusAction === "ACKNOWLEDGED"
              ? "Acknowledge that an operator is investigating. The incident remains open and visible in the queue."
              : statusAction === "RESOLVED"
                ? "Close this incident as resolved. Evidence and audit history are retained."
                : "Close this incident without a fix. The finding and evidence remain available for later review."
          }
          onClose={() => setStatusAction(null)}
          onConfirm={changeStatus}
          title={statusAction === "ACKNOWLEDGED" ? "Acknowledge incident" : statusAction === "RESOLVED" ? "Resolve incident" : "Dismiss incident"}
        />
      ) : null}

      {interventionAction ? (
        <ActionModal
          confirmLabel={interventionAction.action === "approve" ? "Approve pause" : "Reject pause"}
          danger={interventionAction.action === "reject"}
          description={
            interventionAction.action === "approve"
              ? "Approving executes the pause through the connected runtime adapter. An unsupported runtime will be recorded honestly and will not be reported as paused."
              : "Rejecting cancels this pause request. No runtime command will be sent."
          }
          onClose={() => setInterventionAction(null)}
          onConfirm={decideIntervention}
          title={interventionAction.action === "approve" ? "Approve intervention" : "Reject intervention"}
        />
      ) : null}
    </div>
  );
}
