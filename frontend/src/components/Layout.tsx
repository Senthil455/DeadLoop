import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { timeAgo } from "../api";
import { useAuth, useSystem } from "../hooks";
import { Icon, LogoMark, type IconName } from "./ui";

const NAV: Array<{ section: string; items: Array<{ to: string; label: string; icon: IconName; end?: boolean }> }> = [
  {
    section: "Monitor",
    items: [
      { to: "/", label: "Overview", icon: "grid", end: true },
      { to: "/agents", label: "Agents", icon: "bot" },
      { to: "/sessions", label: "Sessions", icon: "layers" },
      { to: "/incidents", label: "Incidents", icon: "alert" },
    ],
  },
  {
    section: "Configure",
    items: [
      { to: "/detection", label: "Detection rules", icon: "sliders" },
      { to: "/integrations", label: "Integrations", icon: "plug" },
      { to: "/settings", label: "Settings", icon: "settings" },
    ],
  },
];

function pageName(pathname: string): string {
  if (pathname === "/") return "Overview";
  if (pathname.startsWith("/agents/")) return "Agent detail";
  if (pathname.startsWith("/agents")) return "Agents";
  if (pathname.startsWith("/sessions/")) return "Session trace";
  if (pathname.startsWith("/sessions")) return "Sessions";
  if (pathname.startsWith("/incidents/")) return "Incident detail";
  if (pathname.startsWith("/incidents")) return "Incidents";
  if (pathname.startsWith("/detection")) return "Detection rules";
  if (pathname.startsWith("/integrations")) return "Integrations";
  if (pathname.startsWith("/settings")) return "Settings";
  return "Console";
}

export default function AppLayout() {
  const { logout } = useAuth();
  const { health, error } = useSystem();
  const navigate = useNavigate();
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    setDrawerOpen(false);
    window.scrollTo({ top: 0 });
  }, [location.pathname]);

  const online = health?.status === "ok" && health.database === "ok";

  return (
    <div className="shell">
      <div
        aria-hidden="true"
        className={`drawer-scrim ${drawerOpen ? "visible" : ""}`}
        onClick={() => setDrawerOpen(false)}
      />
      <aside className={`sidebar ${drawerOpen ? "open" : ""}`}>
        <div className="brand">
          <span className="brand-mark">
            <LogoMark size={34} />
          </span>
          <span className="brand-text">
            <strong>DEADLOOP</strong>
            <small>agent reliability</small>
          </span>
          <button
            aria-label="Close navigation"
            className="icon-button sidebar-close"
            onClick={() => setDrawerOpen(false)}
          >
            <Icon name="x" />
          </button>
        </div>

        <nav className="nav">
          {NAV.map((group) => (
            <div className="nav-group" key={group.section}>
              <div className="nav-label">{group.section}</div>
              {group.items.map((item) => (
                <NavLink
                  className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
                  end={item.end}
                  key={item.to}
                  to={item.to}
                >
                  <Icon name={item.icon} size={17} />
                  <span>{item.label}</span>
                  <span className="nav-rail" />
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="system-card">
            <div className="system-line">
              <span className={`live-dot ${online ? "ok" : "bad"}`} />
              <strong>{online ? "Collector online" : error ? "API unreachable" : "Connecting"}</strong>
            </div>
            <div className="system-meta">
              <span>{health?.environment ?? "unknown env"}</span>
              <span>v{health?.version ?? "—"}</span>
            </div>
            {health ? (
              <div className="system-meta">
                <span>last check</span>
                <span>{timeAgo(health.time)}</span>
              </div>
            ) : null}
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar-left">
            <button
              aria-label="Open navigation"
              className="icon-button menu-button"
              onClick={() => setDrawerOpen(true)}
            >
              <Icon name="menu" />
            </button>
            <span className="crumb-root">console</span>
            <span className="crumb-sep">/</span>
            <span className="crumb-current">{pageName(location.pathname)}</span>
          </div>
          <div className="topbar-right">
            {health?.demo_mode ? <span className="env-tag demo">SIMULATED DATA</span> : null}
            <span className="env-tag">{health?.intervention_mode?.replaceAll("_", " ") ?? "policy loading"}</span>
            <span className={`top-status ${online ? "online" : "offline"}`}>
              <span className="dot" />
              {online ? "live" : "degraded"}
            </span>
            <button
              className="icon-button"
              onClick={() => {
                logout();
                navigate("/login");
              }}
              title="Sign out"
              aria-label="Sign out"
            >
              <Icon name="external" />
            </button>
          </div>
        </header>

        <main className="content">
          <Outlet />
        </main>
        <footer className="app-foot">
          <span>DEADLOOP · deterministic detection, human control</span>
          <span>API v1 · timestamps UTC</span>
        </footer>
      </div>
    </div>
  );
}
