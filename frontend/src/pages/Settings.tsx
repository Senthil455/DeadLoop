import { useState, type FormEvent } from "react";

import { api, formatDate } from "../api";
import { errorText, useApi, useDocumentTitle, useSystem } from "../hooks";
import type { GeneralSettings, InterventionMode } from "../types";
import {
  Button,
  Card,
  ErrorState,
  Field,
  Icon,
  Loading,
  Modal,
  PageHeader,
  Toggle,
} from "../components/ui";

const MODES: Array<{ value: InterventionMode; label: string; description: string; tone: string }> = [
  {
    value: "observe",
    label: "Observe only",
    description: "Record findings. Pause requests are rejected by policy.",
    tone: "neutral",
  },
  {
    value: "notify",
    label: "Notify",
    description: "Surface incidents for humans. Pause requests remain blocked.",
    tone: "neutral",
  },
  {
    value: "approval_required",
    label: "Approval required",
    description: "Every pause request must be approved by an operator before execution.",
    tone: "mint",
  },
  {
    value: "automatic",
    label: "Automatic",
    description: "Pause executes immediately, still requiring a runtime acknowledgement.",
    tone: "amber",
  },
];

function SettingsForm({ initial, onSaved }: { initial: GeneralSettings; onSaved: () => void }) {
  const [retention, setRetention] = useState(initial.retention_days);
  const [redaction, setRedaction] = useState(initial.redaction_enabled);
  const [redactionKeys, setRedactionKeys] = useState(initial.redaction_keys.join("\n"));
  const [mode, setMode] = useState<InterventionMode>(initial.intervention_mode);
  const [aiEnabled, setAiEnabled] = useState(initial.ai_enabled);
  const [aiBaseUrl, setAiBaseUrl] = useState(initial.ai_base_url);
  const [aiModel, setAiModel] = useState(initial.ai_model);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [pruneOpen, setPruneOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [maintenanceBusy, setMaintenanceBusy] = useState(false);
  const [maintenanceMessage, setMaintenanceMessage] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const system = useSystem();

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await api.updateSettings({
        retention_days: retention,
        redaction_enabled: redaction,
        redaction_keys: redactionKeys
          .split(/[\n,]/)
          .map((value) => value.trim())
          .filter(Boolean),
        intervention_mode: mode,
        ai_enabled: aiEnabled,
        ai_base_url: aiBaseUrl.trim(),
        ai_model: aiModel.trim(),
      });
      setSuccess("Settings saved. The new policy is active for subsequent requests.");
      onSaved();
      system.refresh();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function prune() {
    setMaintenanceBusy(true);
    setMaintenanceMessage("");
    try {
      const result = await api.prune();
      setMaintenanceMessage(`Pruned ${String(result.deleted_sessions ?? 0)} expired session(s); retention is ${String(result.retention_days ?? retention)} days.`);
      setPruneOpen(false);
    } catch (reason) {
      setMaintenanceMessage(errorText(reason));
    } finally {
      setMaintenanceBusy(false);
    }
  }

  async function resetDemo() {
    setMaintenanceBusy(true);
    setMaintenanceMessage("");
    try {
      const result = await api.resetDemo();
      setMaintenanceMessage(`Demo data removed: ${String(result.agents ?? 0)} agents, ${String(result.sessions ?? 0)} sessions.`);
      setResetOpen(false);
      setConfirmText("");
      onSaved();
      system.refresh();
    } catch (reason) {
      setMaintenanceMessage(errorText(reason));
    } finally {
      setMaintenanceBusy(false);
    }
  }

  return (
    <>
      <form onSubmit={save}>
        <div className="settings-grid">
          <div className="settings-main">
            <Card eyebrow="Intervention policy" title="How much autonomy does DEADLOOP have?">
              <p className="muted-copy section-lead">
                Policy is enforced server-side. A pause is never reported as successful without an
                acknowledgement from a supported runtime.
              </p>
              <div className="mode-grid">
                {MODES.map((item) => (
                  <label className={`mode-card ${mode === item.value ? "selected" : ""} tone-${item.tone}`} key={item.value}>
                    <input
                      checked={mode === item.value}
                      name="intervention-mode"
                      onChange={() => setMode(item.value)}
                      type="radio"
                      value={item.value}
                    />
                    <span className="mode-radio" />
                    <strong>{item.label}</strong>
                    <span>{item.description}</span>
                    {item.value === "approval_required" ? <em>Recommended</em> : null}
                  </label>
                ))}
              </div>
            </Card>

            <Card eyebrow="Data handling" title="Retention and redaction">
              <div className="field-grid">
                <Field hint="Sessions older than this are eligible for pruning." label="Retention window">
                  <span className="input-with-suffix">
                    <input
                      max={365}
                      min={1}
                      onChange={(event) => setRetention(Number(event.target.value))}
                      type="number"
                      value={retention}
                    />
                    <span>days</span>
                  </span>
                </Field>
                <div>
                  <Toggle
                    checked={redaction}
                    description="Scrubs credential-shaped keys from inputs, outputs, and metadata before persistence."
                    label="Redact sensitive fields"
                    onChange={setRedaction}
                  />
                </div>
              </div>
              <Field
                hint="One key per line. Keys are normalized to lowercase. Built-in credential patterns are always redacted."
                label="Additional redaction keys"
              >
                <textarea
                  disabled={!redaction}
                  onChange={(event) => setRedactionKeys(event.target.value)}
                  placeholder={"customer_email\naccount_number"}
                  rows={5}
                  value={redactionKeys}
                />
              </Field>
            </Card>

            <Card eyebrow="AI explanations" title="Optional provider">
              <div className="ai-status-strip">
                <span className={`live-dot ${initial.ai_active && aiEnabled ? "ok" : "idle"}`} />
                <div>
                  <strong>
                    {aiEnabled
                      ? initial.ai_active
                        ? "AI explanations enabled"
                        : "AI enabled but not fully configured"
                      : "AI explanations disabled"}
                  </strong>
                  <span>
                    Detectors never call a model. AI is used only when an operator requests an explanation.
                  </span>
                </div>
                <span className={`chip ${initial.ai_api_key_configured ? "tone-mint" : "tone-neutral"}`}>
                  {initial.ai_api_key_configured ? "API KEY PRESENT" : "NO API KEY"}
                </span>
              </div>
              <Toggle
                checked={aiEnabled}
                description="Send sanitized incident evidence to an OpenAI-compatible endpoint when Explain is clicked."
                label="Enable AI-assisted explanations"
                onChange={setAiEnabled}
              />
              <div className="field-grid">
                <Field hint="Must include the /v1 path when required by your provider." label="OpenAI-compatible base URL">
                  <input
                    disabled={!aiEnabled}
                    onChange={(event) => setAiBaseUrl(event.target.value)}
                    placeholder="http://127.0.0.1:11434/v1"
                    type="url"
                    value={aiBaseUrl}
                  />
                </Field>
                <Field label="Model name">
                  <input
                    disabled={!aiEnabled}
                    onChange={(event) => setAiModel(event.target.value)}
                    placeholder="qwen2.5:7b"
                    value={aiModel}
                  />
                </Field>
              </div>
              <div className="privacy-note">
                <Icon name="shield" size={16} />
                <p>
                  The provider API key is never accepted by this form and never returned by the API.
                  Set <code>DEADLOOP_AI_API_KEY</code> in the server environment. Local endpoints keep
                  evidence on your network. With AI disabled or unavailable, explanations fall back
                  deterministically.
                </p>
              </div>
            </Card>

            <div className="settings-save">
              {error ? <div className="inline-error"><Icon name="alert" size={16} />{error}</div> : null}
              {success ? <div className="inline-success"><Icon name="check" size={16} />{success}</div> : null}
              <Button disabled={busy} icon="check" type="submit" variant="primary">
                {busy ? "Saving…" : "Save settings"}
              </Button>
            </div>
          </div>

          <aside className="settings-side">
            <Card eyebrow="Identity" title="Deployment">
              <dl className="meta-list">
                <div><dt>Environment</dt><dd>{system.health?.environment ?? "—"}</dd></div>
                <div><dt>Version</dt><dd>{system.health?.version ?? "—"}</dd></div>
                <div><dt>Database</dt><dd>{system.health?.database ?? "—"}</dd></div>
                <div><dt>Demo data</dt><dd>{system.health?.demo_mode ? "present" : "none"}</dd></div>
                <div><dt>AI provider</dt><dd>{initial.ai_provider}</dd></div>
              </dl>
            </Card>

            <Card eyebrow="Admin" title="Access model">
              <p className="muted-copy">
                Dashboard reads and actions require the <code>X-Admin-Token</code> header. Ingestion
                uses revocable write-only API keys and cannot read incidents.
              </p>
              <div className="security-facts">
                <span><Icon name="check" size={14} /> Tokens compared in constant time</span>
                <span><Icon name="check" size={14} /> API keys stored as hashes</span>
                <span><Icon name="check" size={14} /> Default token rejected in production</span>
              </div>
            </Card>

            <Card eyebrow="Maintenance" title="Data operations">
              <p className="muted-copy">Retention pruning removes expired sessions and their incidents as one unit, so evidence never dangles.</p>
              <div className="button-col">
                <Button icon="clock" onClick={() => setPruneOpen(true)}>Prune expired sessions</Button>
                <Button icon="refresh" onClick={() => setResetOpen(true)} variant="ghost">Reset demo data</Button>
              </div>
              {maintenanceMessage ? <div className="inline-info">{maintenanceMessage}</div> : null}
              <p className="field-hint last-seen">Settings loaded {formatDate(new Date().toISOString())}</p>
            </Card>
          </aside>
        </div>
      </form>

      {pruneOpen ? (
        <Modal
          footer={
            <>
              <Button onClick={() => setPruneOpen(false)} variant="ghost">Cancel</Button>
              <Button disabled={maintenanceBusy} onClick={prune} variant="primary">
                {maintenanceBusy ? "Pruning…" : "Prune now"}
              </Button>
            </>
          }
          onClose={() => setPruneOpen(false)}
          title="Prune expired sessions"
        >
          <p className="modal-copy">
            Sessions whose events are all older than the {retention}-day retention window will be
            deleted, together with their incidents and evidence. This cannot be undone.
          </p>
        </Modal>
      ) : null}

      {resetOpen ? (
        <Modal
          footer={
            <>
              <Button onClick={() => setResetOpen(false)} variant="ghost">Cancel</Button>
              <Button
                disabled={maintenanceBusy || confirmText !== "RESET"}
                onClick={resetDemo}
                variant="danger"
              >
                {maintenanceBusy ? "Resetting…" : "Remove demo data"}
              </Button>
            </>
          }
          onClose={() => setResetOpen(false)}
          title="Reset demo data"
        >
          <p className="modal-copy">
            This removes only agents marked as demo, including their sessions, events, incidents,
            and interventions. Real agents are untouched. Type <b>RESET</b> to confirm.
          </p>
          <Field label="Confirmation">
            <input onChange={(event) => setConfirmText(event.target.value)} placeholder="RESET" value={confirmText} />
          </Field>
        </Modal>
      ) : null}
    </>
  );
}

export default function SettingsPage() {
  const settings = useApi<GeneralSettings>("/settings");
  useDocumentTitle("Settings");

  return (
    <div className="page">
      <PageHeader
        eyebrow="Configure / settings"
        title="System settings"
        description="Intervention policy, retention, redaction, and optional explanation providers."
        actions={<Button icon="refresh" onClick={settings.reload}>Reload</Button>}
      />

      {settings.loading && !settings.data ? <Loading label="Loading settings" /> : null}
      {settings.error ? <ErrorState message={settings.error} retry={settings.reload} /> : null}
      {settings.data ? <SettingsForm initial={settings.data} onSaved={settings.reload} /> : null}
    </div>
  );
}
