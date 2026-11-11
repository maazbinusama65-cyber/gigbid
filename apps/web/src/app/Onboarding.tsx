import { useQueryClient } from "@tanstack/react-query";
import { useState, type ChangeEvent, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Async } from "../components/States";
import { useAuth } from "../lib/auth";
import { api, ApiError, authHeaders, unwrap } from "../lib/client";
import { qk, useCompleteOnboarding, useConnections, useOnboarding } from "../lib/queries";
import type { OnboardingState } from "../lib/types";

type Marketplace = "gigsim" | "upwork";

function OnboardingForm({ state }: { state: OnboardingState }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { refresh, signOut } = useAuth();
  const complete = useCompleteOnboarding();
  const connections = useConnections();
  const [persona, setPersona] = useState<string>(state.persona_id ?? "ai_ml");
  const [ownName, setOwnName] = useState("");
  const [ownHeadline, setOwnHeadline] = useState("");
  const [ownSkills, setOwnSkills] = useState("");
  const [marketplace, setMarketplace] = useState<Marketplace>(state.marketplace);
  const [rate, setRate] = useState(String(state.hourly_rate_usd ?? 65));
  const [minBudget, setMinBudget] = useState(String(state.min_budget_usd ?? 300));
  const [connects, setConnects] = useState(String(state.weekly_connects_budget ?? 60));
  const [uploadMsg, setUploadMsg] = useState("");
  const [uploadErr, setUploadErr] = useState("");
  const [error, setError] = useState("");

  const own = persona === "own";
  const connected = connections.data?.connections.find((c) => c.provider === marketplace)?.connected ?? false;

  const upload = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadErr("");
    setUploadMsg("");
    const body = new FormData();
    body.append("file", file);
    try {
      const res = await fetch("/api/onboarding/portfolio", { method: "POST", body, headers: authHeaders() });
      if (!res.ok) {
        const err = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(err.detail ?? `Upload failed (${res.status})`);
      }
      setUploadMsg(`Uploaded ${file.name}`);
      await qc.invalidateQueries({ queryKey: qk.onboarding });
    } catch (err) {
      setUploadErr(err instanceof Error ? err.message : "Upload failed");
    } finally {
      e.target.value = "";
    }
  };

  const connect = async () => {
    // GigSim's OAuth is simulated: a throwaway dev token stands in for the consent screen result.
    const token = `dev-${crypto.randomUUID()}`;
    try {
      await unwrap(
        api.PUT("/api/settings/connections/{provider}", {
          params: { path: { provider: marketplace } },
          body: { access_token: token, scopes: "jobs:read proposals:write" },
        }),
      );
      await qc.invalidateQueries({ queryKey: qk.connections });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not connect.");
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (own && !ownName.trim()) {
      setError("Tell us your name for your own profile.");
      return;
    }
    try {
      await complete.mutateAsync({
        persona_id: own ? null : persona,
        own_profile: own
          ? { display_name: ownName.trim(), headline: ownHeadline.trim(), skills: ownSkills.split(",").map((s) => s.trim()).filter(Boolean) }
          : null,
        marketplace,
        hourly_rate_usd: Number(rate),
        min_budget_usd: Number(minBudget),
        weekly_connects_budget: Number(connects),
      });
      await refresh();
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save your setup.");
    }
  };

  return (
    <form onSubmit={(e) => void submit(e)} aria-label="Onboarding">
      <fieldset>
        <legend className="label" style={{ marginBottom: 12 }}>1. Whose portfolio should GigBid argue from?</legend>
        <div className="choice-grid" role="radiogroup" aria-label="Persona">
          {state.personas.map((p) => (
            <label className="choice" key={p.persona_id}>
              <input type="radio" name="persona" value={p.persona_id} checked={persona === p.persona_id} onChange={() => setPersona(p.persona_id)} />
              <strong>{p.display_name}</strong>
              <span>{p.headline}</span>
              <span className="mono" style={{ display: "block", marginTop: 6 }}>
                {p.skills.join(" · ")}
              </span>
            </label>
          ))}
          <label className="choice">
            <input type="radio" name="persona" value="own" checked={own} onChange={() => setPersona("own")} />
            <strong>My own profile</strong>
            <span>Describe yourself and upload your portfolio below.</span>
          </label>
        </div>
        {own ? (
          <div className="grid-2" style={{ marginTop: 16 }}>
            <div className="field">
              <label htmlFor="own-name">Name</label>
              <input id="own-name" className="input" value={ownName} onChange={(e) => setOwnName(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="own-headline">Headline</label>
              <input id="own-headline" className="input" value={ownHeadline} onChange={(e) => setOwnHeadline(e.target.value)} />
            </div>
            <div className="field span-2">
              <label htmlFor="own-skills">Skills (comma separated)</label>
              <input id="own-skills" className="input" value={ownSkills} onChange={(e) => setOwnSkills(e.target.value)} />
            </div>
          </div>
        ) : null}
      </fieldset>

      <fieldset>
        <legend className="label" style={{ marginBottom: 12 }}>2. Marketplace</legend>
        <div className="choice-grid" role="radiogroup" aria-label="Marketplace">
          <label className="choice">
            <input type="radio" name="marketplace" value="gigsim" checked={marketplace === "gigsim"} onChange={() => setMarketplace("gigsim")} />
            <strong>GigSim</strong>
            <span>The simulated marketplace. Safe for demos and evaluation.</span>
          </label>
          <label className="choice">
            <input type="radio" name="marketplace" value="upwork" checked={marketplace === "upwork"} onChange={() => setMarketplace("upwork")} />
            <strong>Upwork (OAuth)</strong>
            <span>Live account through the official API only. No scraping.</span>
          </label>
        </div>
        <div className="btn-row" style={{ marginTop: 12, alignItems: "center" }}>
          <button type="button" className="btn" onClick={() => void connect()} disabled={connected} data-testid="connect-btn">
            {connected ? "Connected" : `Connect ${marketplace === "gigsim" ? "GigSim" : "Upwork"}`}
          </button>
          <span className="hint" role="status">
            {connected ? "Token stored encrypted. It is never shown again." : "You can also do this later in Settings."}
          </span>
        </div>
      </fieldset>

      <fieldset>
        <legend className="label" style={{ marginBottom: 12 }}>3. Upload portfolio</legend>
        <div className="field">
          <label htmlFor="portfolio">CV, case studies or repo notes (.pdf .md .txt .json .zip)</label>
          <input id="portfolio" type="file" className="input" onChange={(e) => void upload(e)} data-testid="portfolio-input" />
          {uploadMsg ? (
            <span className="hint" role="status" data-testid="upload-ok">
              {uploadMsg}
            </span>
          ) : null}
          {uploadErr ? (
            <span className="field-error" role="alert">
              {uploadErr}
            </span>
          ) : null}
        </div>
        {state.portfolio_files.length ? (
          <ul className="file-list" data-testid="portfolio-files">
            {state.portfolio_files.map((f) => (
              <li key={f.file_id}>
                <span>{f.filename}</span>
                <span className="mono">{f.status}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </fieldset>

      <fieldset>
        <legend className="label" style={{ marginBottom: 12 }}>4. Rates and Connects budget</legend>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="rate">Hourly rate (USD)</label>
            <input id="rate" type="number" min={0} className="input" value={rate} onChange={(e) => setRate(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="minb">Minimum project budget (USD)</label>
            <input id="minb" type="number" min={0} className="input" value={minBudget} onChange={(e) => setMinBudget(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="connects">Weekly Connects budget</label>
            <input id="connects" type="number" min={0} className="input" value={connects} onChange={(e) => setConnects(e.target.value)} />
          </div>
        </div>
      </fieldset>

      {error ? (
        <p className="field-error" role="alert" data-testid="onboarding-error">
          {error}
        </p>
      ) : null}
      <div className="btn-row">
        <button className="btn primary" type="submit" disabled={complete.isPending} data-testid="finish-onboarding">
          Finish setup
        </button>
        <button type="button" className="btn ghost" onClick={() => void signOut().then(() => navigate("/sign-in"))}>
          Sign out
        </button>
      </div>
    </form>
  );
}

export default function Onboarding() {
  const q = useOnboarding();
  return (
    <main id="main" className="page" style={{ maxWidth: 860 }}>
      <header className="page-head">
        <div>
          <p className="eyebrow">Welcome</p>
          <h1>Set up your desk</h1>
          <p className="lede">Four quick choices. You can change all of them later in Settings.</p>
        </div>
      </header>
      <Async query={q}>{(state) => <OnboardingForm state={state} />}</Async>
    </main>
  );
}
