import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api, ApiError, unwrap } from "../lib/client";
import { useAuth } from "../lib/auth";
import { ThemeToggle } from "../components/ThemeToggle";

type Mode = "login" | "register";

export default function SignIn() {
  const { user, signIn } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={user.onboarded ? "/" : "/onboarding"} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const res =
        mode === "login"
          ? await unwrap(api.POST("/api/auth/login", { body: { email, password } }))
          : await unwrap(api.POST("/api/auth/register", { body: { email, password, display_name: name } }));
      await signIn(res.access_token);
      navigate(res.user.onboarded ? "/" : "/onboarding", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-wrap">
      <section className="auth-pitch" aria-label="About GigBid">
        <div className="brand" style={{ color: "inherit" }}>
          Gig<i>Bid</i> <small>freelancer copilot</small>
        </div>
        <h1>
          Bid on the right jobs. <em>You</em> press send.
        </h1>
        <ol>
          <li>It reads each job, scores fit against your real portfolio and flags scams and planted instructions.</li>
          <li>Every sentence of a proposal carries the evidence behind it, or it does not get written.</li>
          <li>Nothing is submitted or spent until you approve, edit or reject it here.</li>
        </ol>
      </section>
      <main id="main" className="auth-form">
        <div className="btn-row" style={{ justifyContent: "flex-end", marginBottom: 16 }}>
          <ThemeToggle />
        </div>
        <div className="tabs" role="tablist" aria-label="Account">
          <button role="tab" aria-selected={mode === "login"} onClick={() => setMode("login")} data-testid="tab-login">
            Sign in
          </button>
          <button role="tab" aria-selected={mode === "register"} onClick={() => setMode("register")} data-testid="tab-register">
            Create account
          </button>
        </div>
        <form onSubmit={(e) => void submit(e)} noValidate aria-label={mode === "login" ? "Sign in" : "Create account"}>
          {mode === "register" ? (
            <div className="field">
              <label htmlFor="name">Your name</label>
              <input id="name" className="input" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
          ) : null}
          <div className="field">
            <label htmlFor="email">E-mail</label>
            <input id="email" type="email" className="input" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              className="input"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {mode === "register" ? <span className="hint">At least 8 characters.</span> : null}
          </div>
          {error ? (
            <p className="field-error" role="alert" data-testid="auth-error">
              {error}
            </p>
          ) : null}
          <button className="btn primary" type="submit" disabled={busy || !email || !password} data-testid="auth-submit">
            {busy ? <span className="spinner" aria-hidden="true" /> : null}
            {mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>
      </main>
    </div>
  );
}
