import { useState, type ReactNode } from "react";

import { api } from "../api";
import { errorText, useApi, useDocumentTitle } from "../hooks";
import type { DetectionSettings } from "../types";
import {
  Button,
  ErrorState,
  Field,
  Icon,
  Loading,
  PageHeader,
  Toggle,
} from "../components/ui";

function RuleCard({
  index,
  name,
  code,
  description,
  enabled,
  onToggle,
  children,
}: {
  index: string;
  name: string;
  code: string;
  description: string;
  enabled: boolean;
  onToggle: (value: boolean) => void;
  children: ReactNode;
}) {
  return (
    <section className={`rule-card ${enabled ? "" : "disabled"}`.trim()}>
      <div className="rule-card-head">
        <span className="rule-index mono">{index}</span>
        <div className="rule-title">
          <h3>{name}</h3>
          <code>{code}</code>
        </div>
        <Toggle checked={enabled} label="Enabled" onChange={onToggle} />
      </div>
      <p className="rule-description">{description}</p>
      <div className="rule-fields">{children}</div>
    </section>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step,
  disabled,
  onChange,
  suffix,
}: {
  label: string;
  value: number | null;
  min: number;
  max?: number;
  step?: number;
  disabled: boolean;
  onChange: (value: number | null) => void;
  suffix?: string;
}) {
  return (
    <Field label={label}>
      <span className="input-with-suffix">
        <input
          disabled={disabled}
          max={max}
          min={min}
          onChange={(event) => onChange(event.target.value === "" ? null : Number(event.target.value))}
          step={step ?? 1}
          type="number"
          value={value ?? ""}
        />
        {suffix ? <span>{suffix}</span> : null}
      </span>
    </Field>
  );
}

function DetectionForm({ initial, onSaved }: { initial: DetectionSettings; onSaved: (value: DetectionSettings) => void }) {
  const [settings, setSettings] = useState<DetectionSettings>(() => structuredClone(initial));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [defaultBusy, setDefaultBusy] = useState(false);

  function update<K extends keyof DetectionSettings>(key: K, patch: Partial<DetectionSettings[K]>) {
    setSettings((current) => ({ ...current, [key]: { ...current[key], ...patch } }));
    setSuccess("");
  }

  async function save() {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const saved = await api.saveDetectionSettings(settings);
      setSettings(saved);
      onSaved(saved);
      setSuccess("Detection policy saved. New rules apply to subsequent ingested batches.");
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function loadDefaults() {
    setDefaultBusy(true);
    setError("");
    try {
      const defaults = await api.detectionDefaults();
      setSettings(defaults);
      setSuccess("Defaults loaded into the editor. Save to apply them.");
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setDefaultBusy(false);
    }
  }

  const exact = settings.exact_repetition;
  const semantic = settings.semantic_repetition;
  const oscillation = settings.oscillation;
  const failure = settings.repeated_failure;
  const progress = settings.no_progress;
  const budget = settings.budget;

  return (
    <>
      <div className="rule-stack">
        <RuleCard
          code="EXACT_REPETITION"
          description="Fires when the same normalized tool call appears repeatedly inside the window and there is no explicit progress signal. Normalization ignores volatile fields such as timestamps and request IDs."
          enabled={exact.enabled}
          index="01"
          name="Exact repetition"
          onToggle={(value) => update("exact_repetition", { enabled: value })}
        >
          <NumberField disabled={!exact.enabled} label="Minimum occurrences" max={25} min={2} onChange={(value) => update("exact_repetition", { min_occurrences: value ?? 2 })} value={exact.min_occurrences} />
          <NumberField disabled={!exact.enabled} label="Window" max={200} min={5} onChange={(value) => update("exact_repetition", { window: value ?? 5 })} suffix="events" value={exact.window} />
          <Toggle
            checked={exact.require_no_progress}
            description="Only fire when progress is absent or explicitly false."
            disabled={!exact.enabled}
            label="Require no progress evidence"
            onChange={(value) => update("exact_repetition", { require_no_progress: value })}
          />
        </RuleCard>

        <RuleCard
          code="SEMANTIC_REPETITION"
          description="Groups calls by normalized tool and action text, then measures token-overlap similarity. Useful when an agent rephrases the same failing request."
          enabled={semantic.enabled}
          index="02"
          name="Semantic repetition"
          onToggle={(value) => update("semantic_repetition", { enabled: value })}
        >
          <NumberField disabled={!semantic.enabled} label="Minimum occurrences" max={25} min={3} onChange={(value) => update("semantic_repetition", { min_occurrences: value ?? 3 })} value={semantic.min_occurrences} />
          <NumberField disabled={!semantic.enabled} label="Window" max={200} min={5} onChange={(value) => update("semantic_repetition", { window: value ?? 5 })} suffix="events" value={semantic.window} />
          <NumberField disabled={!semantic.enabled} label="Similarity threshold" max={1} min={0.5} onChange={(value) => update("semantic_repetition", { similarity_threshold: value ?? 0.9 })} step={0.05} value={semantic.similarity_threshold} />
        </RuleCard>

        <RuleCard
          code="OSCILLATION"
          description="Detects alternating call pairs — A, B, A, B — that repeat beyond the configured cycle count without resolution."
          enabled={oscillation.enabled}
          index="03"
          name="Oscillation"
          onToggle={(value) => update("oscillation", { enabled: value })}
        >
          <NumberField disabled={!oscillation.enabled} label="Minimum cycles" max={12} min={2} onChange={(value) => update("oscillation", { min_cycles: value ?? 2 })} value={oscillation.min_cycles} />
          <NumberField disabled={!oscillation.enabled} label="Window" max={200} min={6} onChange={(value) => update("oscillation", { window: value ?? 6 })} suffix="events" value={oscillation.window} />
        </RuleCard>

        <RuleCard
          code="REPEATED_FAILURE"
          description="Fires when multiple failed tool calls accumulate in the window, even if the calls are not identical. This catches an agent flailing across several tools."
          enabled={failure.enabled}
          index="04"
          name="Repeated failure"
          onToggle={(value) => update("repeated_failure", { enabled: value })}
        >
          <NumberField disabled={!failure.enabled} label="Minimum failures" max={25} min={2} onChange={(value) => update("repeated_failure", { min_failures: value ?? 2 })} value={failure.min_failures} />
          <NumberField disabled={!failure.enabled} label="Window" max={200} min={5} onChange={(value) => update("repeated_failure", { window: value ?? 5 })} suffix="events" value={failure.window} />
        </RuleCard>

        <RuleCard
          code="NO_PROGRESS"
          description="Uses explicit progress signals from your instrumentation. If events carry no progress field, this detector stays conservative and does not guess."
          enabled={progress.enabled}
          index="05"
          name="No progress"
          onToggle={(value) => update("no_progress", { enabled: value })}
        >
          <NumberField disabled={!progress.enabled} label="Minimum events" max={100} min={4} onChange={(value) => update("no_progress", { min_events: value ?? 4 })} value={progress.min_events} />
          <NumberField disabled={!progress.enabled} label="Window" max={200} min={5} onChange={(value) => update("no_progress", { window: value ?? 5 })} suffix="events" value={progress.window} />
        </RuleCard>

        <RuleCard
          code="SESSION_BUDGET"
          description="Tracks per-session resource usage. Budget findings are informational and do not replace behavioral loop detection."
          enabled={budget.enabled}
          index="06"
          name="Session budget"
          onToggle={(value) => update("budget", { enabled: value })}
        >
          <NumberField disabled={!budget.enabled} label="Max tool calls" max={10000} min={5} onChange={(value) => update("budget", { max_tool_calls: value ?? 5 })} value={budget.max_tool_calls} />
          <NumberField disabled={!budget.enabled} label="Max duration" max={86400} min={60} onChange={(value) => update("budget", { max_duration_seconds: value ?? 60 })} suffix="sec" value={budget.max_duration_seconds} />
          <NumberField disabled={!budget.enabled} label="Consecutive failures" max={100} min={2} onChange={(value) => update("budget", { max_consecutive_failures: value ?? 2 })} value={budget.max_consecutive_failures} />
          <NumberField disabled={!budget.enabled} label="Max tokens (optional)" min={1000} onChange={(value) => update("budget", { max_tokens: value })} value={budget.max_tokens} />
          <NumberField disabled={!budget.enabled} label="Max cost USD (optional)" min={0.01} onChange={(value) => update("budget", { max_cost_usd: value })} step={0.01} value={budget.max_cost_usd} />
        </RuleCard>
      </div>

      {error ? <div className="inline-error"><Icon name="alert" size={16} />{error}</div> : null}
      {success ? <div className="inline-success"><Icon name="check" size={16} />{success}</div> : null}

      <div className="save-bar">
        <div>
          <strong>Configuration is explicit</strong>
          <span>Invalid thresholds are rejected by the API. Detection never runs with a partial policy.</span>
        </div>
        <div className="button-row">
          <Button disabled={defaultBusy} icon="refresh" onClick={loadDefaults} variant="ghost">
            {defaultBusy ? "Loading…" : "Load defaults"}
          </Button>
          <Button disabled={busy} icon="check" onClick={save} variant="primary">
            {busy ? "Saving…" : "Save policy"}
          </Button>
        </div>
      </div>
    </>
  );
}

export default function DetectionRulesPage() {
  const settings = useApi<DetectionSettings>("/settings/detection");
  useDocumentTitle("Detection rules");

  return (
    <div className="page">
      <PageHeader
        eyebrow="Configure / detection"
        title="Detection rules"
        description="Deterministic thresholds applied at ingestion. There is no model in the detection path."
      />

      {settings.loading && !settings.data ? <Loading label="Loading detection policy" /> : null}
      {settings.error ? <ErrorState message={settings.error} retry={settings.reload} /> : null}
      {settings.data ? (
        <>
          <div className="config-banner">
            <span className="config-icon"><Icon name="sliders" size={20} /></span>
            <div>
              <strong>How rules are evaluated</strong>
              <p>
                Every batch is evaluated against the session window. Findings are deduplicated per
                session and detector. Changing a rule affects new batches; existing incidents remain
                as auditable historical evidence.
              </p>
            </div>
            <code>PRECEDENCE · exact → oscillation → repeated failure → no progress → budget</code>
          </div>
          <DetectionForm initial={settings.data} onSaved={() => settings.reload()} />
        </>
      ) : null}
    </div>
  );
}
