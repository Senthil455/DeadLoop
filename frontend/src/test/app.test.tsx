import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import App from "../App";
import { AuthProvider } from "../hooks";
import {
  agent,
  dismissedIncident,
  health,
  incidentDetail,
  incidentSummary,
  overview,
  resolvedIncident,
  session,
} from "./fixtures";

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

type Handler = (url: URL, init: RequestInit) => Response | Promise<Response> | undefined;

function installApi(handler: Handler) {
  const mock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const url = new URL(raw, "http://localhost");
    const response = await handler(url, init);
    if (!response) throw new Error(`Unhandled API request: ${init.method ?? "GET"} ${url.pathname}${url.search}`);
    return response;
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function renderApp(route: string, authenticated = true) {
  if (authenticated) window.localStorage.setItem("deadloop.adminToken", "test-admin-token");
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("DEADLOOP console", () => {
  it("rejects an invalid admin token, then signs in and loads the overview", async () => {
    const user = userEvent.setup();
    installApi((url, init) => {
      if (url.pathname === "/api/v1/auth/check") {
        const token = new Headers(init.headers).get("X-Admin-Token");
        return token === "test-admin-token"
          ? json({ ok: true, role: "admin" })
          : json({ detail: "Invalid administrator token." }, 401);
      }
      if (url.pathname === "/api/v1/health") return json(health);
      if (url.pathname === "/api/v1/stats/overview") return json(overview);
      return undefined;
    });

    renderApp("/login", false);
    expect(screen.getByRole("heading", { name: /enter the console/i })).toBeInTheDocument();

    await user.type(screen.getByLabelText(/administrator token/i), "wrong-token");
    await user.click(screen.getByRole("button", { name: /open console/i }));
    expect(await screen.findByText("Invalid administrator token.")).toBeInTheDocument();
    expect(window.localStorage.getItem("deadloop.adminToken")).toBeNull();

    await user.clear(screen.getByLabelText(/administrator token/i));
    await user.type(screen.getByLabelText(/administrator token/i), "test-admin-token");
    await user.click(screen.getByRole("button", { name: /open console/i }));

    expect(await screen.findByRole("heading", { name: "Execution health" })).toBeInTheDocument();
    expect(window.localStorage.getItem("deadloop.adminToken")).toBe("test-admin-token");
  });

  it("redirects an unauthenticated deep link to the login screen", () => {
    installApi(() => undefined);
    renderApp("/incidents", false);
    expect(screen.getByRole("heading", { name: /enter the console/i })).toBeInTheDocument();
    expect(screen.queryByText("Incident queue")).not.toBeInTheDocument();
  });

  it("renders overview metrics, incident feed, and navigates to the fleet", async () => {
    const user = userEvent.setup();
    installApi((url) => {
      if (url.pathname === "/api/v1/health") return json(health);
      if (url.pathname === "/api/v1/stats/overview") return json(overview);
      if (url.pathname === "/api/v1/agents") return json([agent]);
      return undefined;
    });

    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Execution health" })).toBeInTheDocument();
    expect(screen.getByText("Loop detections")).toBeInTheDocument();
    expect(screen.getByText(incidentSummary.title)).toBeInTheDocument();
    expect(screen.getAllByText("Support Agent").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("link", { name: /^Agents$/i }));
    expect(await screen.findByRole("heading", { name: "Agent fleet" })).toBeInTheDocument();
    expect(await screen.findByText("langgraph")).toBeInTheDocument();
  });

  it("filters incidents by status and search text", async () => {
    const user = userEvent.setup();
    installApi((url) => {
      if (url.pathname === "/api/v1/health") return json(health);
      if (url.pathname === "/api/v1/incidents") {
        return json([incidentSummary, resolvedIncident, dismissedIncident]);
      }
      if (url.pathname === "/api/v1/agents") return json([agent]);
      return undefined;
    });

    renderApp("/incidents");
    expect(await screen.findByText(incidentSummary.title)).toBeInTheDocument();
    expect(screen.getByText(resolvedIncident.title)).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /resolved/i }));
    expect(screen.getByText(resolvedIncident.title)).toBeInTheDocument();
    expect(screen.queryByText(incidentSummary.title)).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /^all/i }));
    await user.type(screen.getByLabelText("Search incidents"), "oscillation");
    expect(screen.getByText(dismissedIncident.title)).toBeInTheDocument();
    expect(screen.queryByText(resolvedIncident.title)).not.toBeInTheDocument();
  });

  it("sends session filters to the API and shows the trace evidence", async () => {
    const user = userEvent.setup();
    const mock = installApi((url) => {
      if (url.pathname === "/api/v1/health") return json(health);
      if (url.pathname === "/api/v1/sessions/sess-1") return json(session);
      return undefined;
    });

    renderApp("/sessions/sess-1");
    expect(await screen.findByRole("heading", { name: "Session evidence" })).toBeInTheDocument();
    expect(screen.getByText("Search for a fix")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Event status"), "failure");
    await waitFor(() => {
      expect(
        mock.mock.calls.some(([input]) => String(input).includes("/sessions/sess-1?") && String(input).includes("status=failure")),
      ).toBe(true);
    });
  });

  it("resolves an incident through the confirmation dialog and sends an audit note", async () => {
    const user = userEvent.setup();
    const mock = installApi((url, init) => {
      if (url.pathname === "/api/v1/health") return json(health);
      if (url.pathname === "/api/v1/incidents/inc-1/status" && init.method === "POST") {
        return json({ ...incidentDetail, status: "RESOLVED", resolved_at: "2026-10-29T10:10:00Z" });
      }
      if (url.pathname === "/api/v1/incidents/inc-1") return json(incidentDetail);
      return undefined;
    });

    renderApp("/incidents/inc-1");
    expect(await screen.findByRole("heading", { name: incidentDetail.title })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Resolve" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("Why is this decision being made?"), "Verified no further retries.");
    await user.click(screen.getByRole("button", { name: "Resolve incident" }));

    expect(await screen.findByText("RESOLVED")).toBeInTheDocument();
    await waitFor(() => {
      const statusCall = mock.mock.calls.find(
        ([input, init]) => String(input).endsWith("/incidents/inc-1/status") && init?.method === "POST",
      );
      expect(statusCall).toBeTruthy();
      expect(String(statusCall?.[1]?.body)).toContain("Verified no further retries.");
      expect(String(statusCall?.[1]?.body)).toContain("RESOLVED");
    });
  });

  it("shows an error state when the agents API fails", async () => {
    installApi((url) => {
      if (url.pathname === "/api/v1/health") return json(health);
      if (url.pathname === "/api/v1/agents") return json({ detail: "Database unavailable." }, 500);
      return undefined;
    });

    renderApp("/agents");
    expect(await screen.findByText("Request failed")).toBeInTheDocument();
    expect(screen.getByText("Database unavailable.")).toBeInTheDocument();
  });

  it("renders an empty fleet state", async () => {
    installApi((url) => {
      if (url.pathname === "/api/v1/health") return json(health);
      if (url.pathname === "/api/v1/agents") return json([]);
      return undefined;
    });

    renderApp("/agents");
    expect(await screen.findByText("No agents connected")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Connect agent/i })).toBeInTheDocument();
  });
});
