import type {
  Agent,
  AiExplanationResult,
  AiStatus,
  ApiKey,
  ApiKeyCreated,
  DemoScenarioResult,
  DetectionSettings,
  GeneralSettings,
  Health,
  IncidentDetail,
  IncidentStatus,
  IncidentSummary,
  IncidentNote,
  Intervention,
  Overview,
  SessionDetail,
  SessionSummary,
  TraceEvent,
} from "./types";

const TOKEN_KEY = "deadloop.adminToken";
const BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function getStoredToken(): string {
  try {
    return window.localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function storeToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}

function errorMessage(status: number, detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          const location = "loc" in item && Array.isArray(item.loc) ? item.loc.slice(1).join(".") : "";
          return `${location ? `${location}: ` : ""}${String(item.msg)}`;
        }
        return JSON.stringify(item);
      })
      .join("; ");
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  return `Request failed with HTTP ${status}.`;
}

async function rawRequest<T>(
  path: string,
  options: RequestInit & { token?: string } = {},
): Promise<T> {
  const token = options.token ?? getStoredToken();
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("X-Admin-Token", token);
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { ...options, headers });
  } catch {
    throw new ApiError("The DEADLOOP API is unreachable. Is the backend running?", 0, null);
  }
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? (body as { detail: unknown }).detail
        : body;
    if (response.status === 401 && !options.token) {
      window.dispatchEvent(new CustomEvent("deadloop:unauthorized"));
    }
    throw new ApiError(errorMessage(response.status, detail), response.status, detail);
  }
  return body as T;
}

export async function verifyAdminToken(token: string): Promise<void> {
  const result = await rawRequest<{ ok: boolean }>("/auth/check", { token });
  if (!result.ok) throw new ApiError("Token verification failed.", 401, null);
}

function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  });
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

export function apiGet<T>(path: string): Promise<T> {
  return rawRequest<T>(path);
}

export const api = {
  health: () => rawRequest<Health>("/health"),
  overview: () => rawRequest<Overview>("/stats/overview"),
  agents: () => rawRequest<Agent[]>("/agents"),
  agent: (id: string) => rawRequest<Agent>(`/agents/${encodeURIComponent(id)}`),
  patchAgent: (
    id: string,
    payload: Partial<Pick<Agent, "name" | "description" | "framework" | "configuration">>,
  ) =>
    rawRequest<Agent>(`/agents/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  agentEvents: (id: string, page = 1, pageSize = 50) =>
    rawRequest<TraceEvent[]>(
      `/agents/${encodeURIComponent(id)}/events${query({ page, page_size: pageSize })}`,
    ),
  sessions: (params: { agent_id?: string; status?: string; limit?: number } = {}) =>
    rawRequest<SessionSummary[]>(`/sessions${query(params)}`),
  session: (id: string, params: Record<string, string | number | undefined> = {}) =>
    rawRequest<SessionDetail>(`/sessions/${encodeURIComponent(id)}${query(params)}`),
  incidents: (
    params: {
      status?: string;
      severity?: string;
      category?: string;
      agent_id?: string;
      q?: string;
      limit?: number;
    } = {},
  ) => rawRequest<IncidentSummary[]>(`/incidents${query(params)}`),
  incident: (id: string) => rawRequest<IncidentDetail>(`/incidents/${encodeURIComponent(id)}`),
  updateIncidentStatus: (id: string, status: IncidentStatus, note?: string) =>
    rawRequest<IncidentDetail>(`/incidents/${encodeURIComponent(id)}/status`, {
      method: "POST",
      body: JSON.stringify({ status, note: note || undefined }),
    }),
  addNote: (id: string, body: string) =>
    rawRequest<IncidentDetail>(`/incidents/${encodeURIComponent(id)}/notes`, {
      method: "POST",
      body: JSON.stringify({ body }),
    }),
  explain: (id: string) =>
    rawRequest<AiExplanationResult>(`/incidents/${encodeURIComponent(id)}/explain`, {
      method: "POST",
    }),
  requestIntervention: (id: string) =>
    rawRequest<Intervention>(`/incidents/${encodeURIComponent(id)}/interventions`, {
      method: "POST",
      body: JSON.stringify({ action: "pause" }),
    }),
  approveIntervention: (id: string, note?: string) =>
    rawRequest<Intervention>(`/interventions/${encodeURIComponent(id)}/approve`, {
      method: "POST",
      body: JSON.stringify({ note: note || undefined }),
    }),
  rejectIntervention: (id: string, note?: string) =>
    rawRequest<Intervention>(`/interventions/${encodeURIComponent(id)}/reject`, {
      method: "POST",
      body: JSON.stringify({ note: note || undefined }),
    }),
  detectionSettings: () => rawRequest<DetectionSettings>("/settings/detection"),
  detectionDefaults: () => rawRequest<DetectionSettings>("/settings/detection/defaults"),
  saveDetectionSettings: (payload: DetectionSettings) =>
    rawRequest<DetectionSettings>("/settings/detection", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  settings: () => rawRequest<GeneralSettings>("/settings"),
  updateSettings: (payload: Partial<GeneralSettings>) =>
    rawRequest<GeneralSettings>("/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  aiStatus: () => rawRequest<AiStatus>("/settings/ai-status"),
  apiKeys: () => rawRequest<ApiKey[]>("/api-keys"),
  createApiKey: (name: string) =>
    rawRequest<ApiKeyCreated>("/api-keys", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  revokeApiKey: (id: string) =>
    rawRequest<ApiKey>(`/api-keys/${encodeURIComponent(id)}`, { method: "DELETE" }),
  demo: (scenario: string) =>
    rawRequest<DemoScenarioResult>(`/demo/scenarios/${encodeURIComponent(scenario)}`, {
      method: "POST",
    }),
  resetDemo: () =>
    rawRequest<Record<string, number>>("/demo/reset", {
      method: "POST",
      body: JSON.stringify({ confirm: true }),
    }),
  prune: () => rawRequest<Record<string, unknown>>("/maintenance/prune", { method: "POST" }),
};

export type { IncidentNote };

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  }).format(date);
}

export function formatShortDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function timeAgo(value: string | null | undefined): string {
  if (!value) return "never";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "unknown";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(value);
}
