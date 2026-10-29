import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import AppLayout from "./components/Layout";
import { SystemProvider, useAuth } from "./hooks";
import AgentDetailPage from "./pages/AgentDetail";
import AgentsPage from "./pages/Agents";
import DetectionRulesPage from "./pages/DetectionRules";
import IncidentDetailPage from "./pages/IncidentDetail";
import IncidentsPage from "./pages/Incidents";
import IntegrationsPage from "./pages/Integrations";
import LoginPage from "./pages/Login";
import OverviewPage from "./pages/Overview";
import SessionDetailPage from "./pages/SessionDetail";
import SessionsPage from "./pages/Sessions";
import SettingsPage from "./pages/Settings";

function Protected({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  const location = useLocation();
  if (!token) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <SystemProvider>{children}</SystemProvider>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <Protected>
            <AppLayout />
          </Protected>
        }
      >
        <Route index element={<OverviewPage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="agents/:agentId" element={<AgentDetailPage />} />
        <Route path="sessions" element={<SessionsPage />} />
        <Route path="sessions/:sessionId" element={<SessionDetailPage />} />
        <Route path="incidents" element={<IncidentsPage />} />
        <Route path="incidents/:incidentId" element={<IncidentDetailPage />} />
        <Route path="detection" element={<DetectionRulesPage />} />
        <Route path="integrations" element={<IntegrationsPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
