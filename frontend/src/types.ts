export type Severity = "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type IncidentStatus = "OPEN" | "ACKNOWLEDGED" | "RESOLVED" | "DISMISSED";
export type InterventionMode = "observe" | "notify" | "approval_required" | "automatic";

export interface Agent {
  id: string;
  name: string;
  description: string | null;
  framework: string | null;
  status: "active" | "degraded" | "stale" | "offline" | "unknown";
  is_demo: boolean;
  configuration: Record<string, unknown> | null;
  created_at: string;
  last_seen_at: string | null;
  session_count: number;
  event_count: number;
  open_incidents: number;
  last_session_id: string | null;
}

export interface SessionSummary {
  id: string;
  agent_id: string;
  agent_name: string | null;
  status: string;
  started_at: string;
  ended_at: string | null;
  event_count: number;
  metadata: Record<string, unknown> | null;
  open_incidents: number;
}

export interface TraceEvent {
  id: string;
  agent_id: string;
  session_id: string;
  timestamp: string;
  received_at: string;
  tool_name: string;
  action: string | null;
  status: "success" | "failure" | "unknown";
  duration_ms: number | null;
  error_category: string | null;
  retry_count: number;
  tokens: number | null;
  cost_usd: number | null;
  task: string | null;
  parent_event_id: string | null;
  correlation_id: string | null;
  metadata: Record<string, unknown> | null;
  progress: Record<string, unknown> | null;
  model_id: string | null;
  normalized_input_hash: string;
  sanitized_input: unknown;
  sanitized_output: unknown;
}

export interface Detection {
  id: string;
  agent_id: string;
  session_id: string;
  category: string;
  severity: Severity;
  risk_score: number;
  confidence: number;
  evidence: {
    event_ids: string[];
    sequence?: Array<Record<string, unknown>>;
    metrics?: Record<string, unknown>;
    confidence_basis?: string;
    uncertainty?: string;
  };
  explanation: string;
  recommended_action: string;
  first_seen_at: string;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
  ai_explanation: AiExplanationResult | null;
  ai_generated_at: string | null;
}

export interface SessionDetail extends SessionSummary {
  events: TraceEvent[];
  incidents: IncidentSummary[];
  total_events: number;
  page: number;
  page_size: number;
  pages: number;
  tools: string[];
}

export interface IncidentSummary {
  id: string;
  title: string;
  status: IncidentStatus;
  severity: Severity;
  risk_score: number;
  agent_id: string;
  session_id: string;
  agent_name: string | null;
  detection_id: string;
  detection_category: string | null;
  confidence: number | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  evidence_event_count: number;
  evidence_event_ids: string[];
}

export interface IncidentNote {
  id: string;
  author: string;
  body: string;
  created_at: string;
}

export interface Intervention {
  id: string;
  incident_id: string;
  agent_id: string;
  session_id: string;
  requested_action: string;
  policy_mode: string;
  approval_status: string;
  execution_status: string;
  initiated_by: string;
  requested_at: string;
  completed_at: string | null;
  simulated: boolean;
  result: Record<string, unknown> | null;
}

export interface AuditEntry {
  id: string;
  actor: string;
  action: string;
  resource_type: string;
  resource_id: string;
  timestamp: string;
  details: Record<string, unknown> | null;
}

export interface IncidentDetail extends IncidentSummary {
  detection: Detection;
  notes: IncidentNote[];
  interventions: Intervention[];
  audit: AuditEntry[];
}

export interface EventPoint {
  bucket: string;
  events: number;
}

export interface Overview {
  total_agents: number;
  active_sessions: number;
  open_incidents: number;
  high_severity_incidents: number;
  repetition_detections: number;
  failed_tool_calls: number;
  recent_interventions: Intervention[];
  recent_activity: Agent[];
  incident_feed: IncidentSummary[];
  event_series: EventPoint[];
  demo_mode: boolean;
  generated_at: string;
}

export interface ExactRepetitionConfig {
  enabled: boolean;
  min_occurrences: number;
  window: number;
  require_no_progress: boolean;
}
export interface SemanticRepetitionConfig {
  enabled: boolean;
  min_occurrences: number;
  window: number;
  similarity_threshold: number;
}
export interface OscillationConfig {
  enabled: boolean;
  min_cycles: number;
  window: number;
}
export interface RepeatedFailureConfig {
  enabled: boolean;
  min_failures: number;
  window: number;
}
export interface NoProgressConfig {
  enabled: boolean;
  min_events: number;
  window: number;
}
export interface BudgetConfig {
  enabled: boolean;
  max_tool_calls: number;
  max_duration_seconds: number;
  max_consecutive_failures: number;
  max_tokens: number | null;
  max_cost_usd: number | null;
}
export interface DetectionSettings {
  exact_repetition: ExactRepetitionConfig;
  semantic_repetition: SemanticRepetitionConfig;
  oscillation: OscillationConfig;
  repeated_failure: RepeatedFailureConfig;
  no_progress: NoProgressConfig;
  budget: BudgetConfig;
}

export interface GeneralSettings {
  retention_days: number;
  redaction_enabled: boolean;
  redaction_keys: string[];
  intervention_mode: InterventionMode;
  ai_enabled: boolean;
  ai_base_url: string;
  ai_model: string;
  ai_api_key_configured: boolean;
  ai_active: boolean;
  ai_provider: string;
  ai_config_source: string;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface ApiKeyCreated extends ApiKey {
  api_key: string;
  note: string;
}

export interface Health {
  status: string;
  database: string;
  version: string;
  environment: string;
  ai_enabled: boolean;
  intervention_mode: InterventionMode;
  demo_mode: boolean;
  time: string;
}

export interface DemoScenarioResult {
  scenario: string;
  agent_id: string;
  session_id: string;
  events_created: number;
  detections_created: number;
  incident_ids: string[];
  detections: string[];
  note: string;
}

export interface AiExplanation {
  summary: string;
  observed_facts: string[];
  hypotheses: string[];
  why_unproductive: string;
  progress_assessment: string;
  next_steps: string[];
  recommended_intervention: string;
  referenced_event_ids: string[];
  generated_by: string;
}

export interface AiExplanationResult {
  source: "ai" | "deterministic";
  available: boolean;
  provider: string;
  model: string;
  explanation: AiExplanation;
  fallback: boolean;
  message: string | null;
  error: string | null;
}

export interface AiStatus {
  enabled: boolean;
  configured: boolean;
  base_url: string;
  model: string;
  api_key_configured: boolean;
  provider: string;
  data_flow: string;
}
