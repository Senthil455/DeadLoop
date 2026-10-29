import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { useAuth, useDocumentTitle, errorText } from "../hooks";
import { Button, Icon, LogoMark } from "../components/ui";

export default function LoginPage() {
  const { token, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [visible, setVisible] = useState(false);
  useDocumentTitle("Operator sign in");

  const from = (location.state as { from?: string } | null)?.from ?? "/";

  useEffect(() => {
    if (token) navigate(from, { replace: true });
  }, [token, from, navigate]);

  if (token) return <Navigate to={from} replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!value.trim()) {
      setError("Enter the administrator token.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await login(value);
      navigate(from, { replace: true });
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <section className="login-visual">
        <div className="login-brand">
          <span className="brand-mark large">
            <LogoMark size={44} />
          </span>
          <div>
            <strong>DEADLOOP</strong>
            <span>agent reliability monitor</span>
          </div>
        </div>

        <div className="login-thesis">
          <div className="eyebrow">Forensic loop detection</div>
          <h1>Agents fail quietly.<br />Loops do not.</h1>
          <p>
            Catch exact repetition, oscillation, repeated failure, and stalled progress.
            Every finding is backed by event evidence and kept behind human approval.
          </p>
        </div>

        <div className="signal-grid" aria-hidden="true">
          <div className="signal-cell">
            <span>01 / DETECT</span>
            <strong>Deterministic</strong>
            <p>No model in the detection path. Same evidence, same verdict.</p>
          </div>
          <div className="signal-cell">
            <span>02 / EXPLAIN</span>
            <strong>Evidence first</strong>
            <p>Risk score, event IDs, and the observed sequence, not vibes.</p>
          </div>
          <div className="signal-cell">
            <span>03 / ACT</span>
            <strong>Human control</strong>
            <p>Pause requests need approval. Unsupported runtimes fail closed.</p>
          </div>
        </div>

        <div className="login-visual-foot">
          <span><Icon name="shield" size={15} /> Secrets stay server-side</span>
          <span><Icon name="activity" size={15} /> Write-only ingestion keys</span>
        </div>
      </section>

      <section className="login-panel">
        <form className="login-form" onSubmit={submit}>
          <div className="login-form-head">
            <span className="login-kicker">Operator access</span>
            <h2>Enter the console</h2>
            <p>Authenticate with the administrator token configured on this DEADLOOP server.</p>
          </div>

          <label className="field" htmlFor="admin-token">
            <span className="field-label">Administrator token</span>
            <span className="input-with-action">
              <input
                autoComplete="current-password"
                autoFocus
                id="admin-token"
                onChange={(event) => setValue(event.target.value)}
                placeholder="Administrator token"
                type={visible ? "text" : "password"}
                value={value}
              />
              <button
                className="input-action"
                onClick={() => setVisible((current) => !current)}
                type="button"
              >
                {visible ? "Hide" : "Show"}
              </button>
            </span>
            <span className="field-hint">
              The token is stored in this browser and sent only to this DEADLOOP server.
            </span>
          </label>

          {error ? (
            <div className="inline-error" role="alert">
              <Icon name="alert" size={16} />
              <span>{error}</span>
            </div>
          ) : null}

          <Button className="login-submit" disabled={busy} type="submit" variant="primary">
            {busy ? "Verifying…" : "Open console"}
            {!busy ? <Icon name="arrow-right" size={16} /> : null}
          </Button>

          <div className="login-note">
            <Icon name="shield" size={15} />
            <span>
              The dashboard never receives the API key for your AI provider. Configure it with
              <code>DEADLOOP_AI_API_KEY</code> on the server.
            </span>
          </div>
        </form>
        <div className="login-foot">
          <span>DEADLOOP v0.1</span>
          <span>Local-first · self-hosted</span>
        </div>
      </section>
    </div>
  );
}
