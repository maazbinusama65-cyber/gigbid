import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Chip } from "../components/Badges";
import { Async, EmptyState } from "../components/States";
import { api, ApiError, unwrap } from "../lib/client";
import { timeAgo } from "../lib/format";
import { qk, useConnections, useMemory, useSettings, useUpdateSettings } from "../lib/queries";
import type { SavedSearch, UserSettings } from "../lib/types";

const LEVELS: { id: UserSettings["autonomy_level"]; title: string; body: string }[] = [
  { id: "manual", title: "Manual", body: "Nothing runs until you press Analyze." },
  { id: "assist", title: "Assist", body: "Scout and draft automatically. You approve every send." },
  { id: "scout", title: "Scout", body: "Also auto-skip obvious scams and low fits. Sends still need approval." },
];

function SettingsForm({ initial }: { initial: UserSettings }) {
  const update = useUpdateSettings();
  const [s, setS] = useState(initial);
  const [saved, setSaved] = useState(false);
  useEffect(() => setS(initial), [initial]);
  const patch = (p: Partial<UserSettings>) => {
    setSaved(false);
    setS((cur) => ({ ...cur, ...p }));
  };
  const num = (v: string) => (v === "" ? 0 : Number(v));
  const addSearch = () =>
    patch({
      saved_searches: [...s.saved_searches, { search_id: `ss_${Date.now()}`, name: "New search", query: "", category: null, interval_minutes: 60, enabled: true }],
    });
  const editSearch = (id: string, p: Partial<SavedSearch>) =>
    patch({ saved_searches: s.saved_searches.map((x) => (x.search_id === id ? { ...x, ...p } : x)) });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        update.mutate(s, { onSuccess: () => setSaved(true) });
      }}
      aria-label="Settings"
    >
      <section className="panel" aria-labelledby="auto-h">
        <h2 id="auto-h">Autonomy level</h2>
        <div className="choice-grid" role="radiogroup" aria-label="Autonomy level">
          {LEVELS.map((l) => (
            <label className="choice" key={l.id}>
              <input type="radio" name="autonomy" checked={s.autonomy_level === l.id} onChange={() => patch({ autonomy_level: l.id })} />
              <strong>{l.title}</strong>
              <span>{l.body}</span>
            </label>
          ))}
        </div>
        <p className="hint" style={{ marginTop: 8 }}>No level ever submits a proposal, sends a message or spends Connects without your approval.</p>
      </section>

      <section className="panel" aria-labelledby="bud-h">
        <h2 id="bud-h">Budgets and thresholds</h2>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="wk">Weekly Connects budget</label>
            <input id="wk" type="number" min={0} className="input" value={s.weekly_connects_budget} onChange={(e) => patch({ weekly_connects_budget: num(e.target.value) })} />
          </div>
          <div className="field">
            <label htmlFor="per">Max Connects per proposal</label>
            <input id="per" type="number" min={0} className="input" value={s.max_connects_per_proposal} onChange={(e) => patch({ max_connects_per_proposal: num(e.target.value) })} />
          </div>
          <div className="field">
            <label htmlFor="rate">Hourly rate (USD)</label>
            <input id="rate" type="number" min={0} className="input" value={s.hourly_rate_usd} onChange={(e) => patch({ hourly_rate_usd: num(e.target.value) })} />
          </div>
          <div className="field">
            <label htmlFor="minb">Minimum budget (USD)</label>
            <input id="minb" type="number" min={0} className="input" value={s.min_budget_usd} onChange={(e) => patch({ min_budget_usd: num(e.target.value) })} />
          </div>
          <div className="field span-2">
            <label htmlFor="minfit">Minimum fit to draft: {Math.round(s.min_fit_score * 100)}</label>
            <div className="range">
              <input id="minfit" type="range" min={0} max={100} value={Math.round(s.min_fit_score * 100)} onChange={(e) => patch({ min_fit_score: Number(e.target.value) / 100 })} />
            </div>
          </div>
        </div>
      </section>

      <section className="panel" aria-labelledby="ss-h">
        <h2 id="ss-h">Saved searches</h2>
        {s.saved_searches.length === 0 ? <p className="muted">No saved searches. The scout has nothing to watch.</p> : null}
        <div className="stack">
          {s.saved_searches.map((x) => (
            <div key={x.search_id} className="grid-2" style={{ alignItems: "end" }} data-testid="saved-search">
              <div className="field" style={{ margin: 0 }}>
                <label htmlFor={`n-${x.search_id}`}>Name</label>
                <input id={`n-${x.search_id}`} className="input" value={x.name} onChange={(e) => editSearch(x.search_id, { name: e.target.value })} />
              </div>
              <div className="field" style={{ margin: 0 }}>
                <label htmlFor={`q-${x.search_id}`}>Query</label>
                <input id={`q-${x.search_id}`} className="input" value={x.query} onChange={(e) => editSearch(x.search_id, { query: e.target.value })} />
              </div>
              <div className="toolbar">
                <label className="inline-check">
                  <input type="checkbox" checked={x.enabled} onChange={(e) => editSearch(x.search_id, { enabled: e.target.checked })} />
                  every {x.interval_minutes} min
                </label>
                <button type="button" className="btn sm danger" onClick={() => patch({ saved_searches: s.saved_searches.filter((y) => y.search_id !== x.search_id) })}>
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
        <button type="button" className="btn sm" style={{ marginTop: 12 }} onClick={addSearch}>
          Add saved search
        </button>
      </section>

      <div className="btn-row" style={{ alignItems: "center" }}>
        <button className="btn primary" type="submit" disabled={update.isPending} data-testid="save-settings">
          Save settings
        </button>
        <span role="status" aria-live="polite" data-testid="settings-status">
          {saved ? "Saved." : ""}
          {update.error ? (update.error instanceof ApiError ? update.error.message : "Could not save.") : ""}
        </span>
      </div>
    </form>
  );
}

function Connections() {
  const q = useConnections();
  const qc = useQueryClient();
  const toggle = useMutation({
    mutationFn: async (v: { provider: "gigsim" | "upwork"; connect: boolean }) => {
      if (v.connect) {
        return unwrap(
          api.PUT("/api/settings/connections/{provider}", {
            params: { path: { provider: v.provider } },
            body: { access_token: `dev-${crypto.randomUUID()}`, scopes: "jobs:read proposals:write" },
          }),
        );
      }
      return unwrap(api.DELETE("/api/settings/connections/{provider}", { params: { path: { provider: v.provider } } }));
    },
    onSuccess: (data) => qc.setQueryData(qk.connections, data),
  });
  return (
    <section className="panel" aria-labelledby="acc-h">
      <h2 id="acc-h">Connected accounts</h2>
      <Async query={q}>
        {(d) => (
          <ul className="file-list" data-testid="connections">
            {d.connections.map((c) => (
              <li key={c.provider}>
                <span>
                  <strong>{c.provider === "gigsim" ? "GigSim" : "Upwork"}</strong>{" "}
                  {c.connected ? <Chip tone="ok">connected {c.connected_at ? timeAgo(c.connected_at) : ""}</Chip> : <Chip>not connected</Chip>}
                </span>
                <button className="btn sm" disabled={toggle.isPending} onClick={() => toggle.mutate({ provider: c.provider, connect: !c.connected })}>
                  {c.connected ? "Disconnect" : "Connect"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </Async>
      <p className="hint" style={{ marginTop: 8 }}>OAuth tokens are encrypted at rest and never displayed or logged.</p>
    </section>
  );
}

function MemoryViewer() {
  const q = useMemory();
  const qc = useQueryClient();
  const [msg, setMsg] = useState("");
  const del = useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/memory/{memory_id}", { params: { path: { memory_id: id } } })),
    onSuccess: () => {
      setMsg("Forgotten. GigBid will no longer use it.");
      void qc.invalidateQueries({ queryKey: qk.memory });
    },
  });
  return (
    <section className="panel" aria-labelledby="mem-h">
      <h2 id="mem-h">What GigBid has learned</h2>
      <p className="hint">
        Edits and outcomes become memory only through a promotion rule. Candidates are shown as “pending”. Delete anything you do not want remembered.
      </p>
      <p role="status" aria-live="polite" className="muted" data-testid="memory-status">{msg}</p>
      <Async query={q} empty={(d) => (d.items.length === 0 ? <EmptyState title="Nothing learned yet">Edit or reject a draft and candidates will appear here.</EmptyState> : null)}>
        {(d) => (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }} data-testid="memory-list">
            {d.items.map((m) => (
              <li key={m.memory_id} className="memory-item" data-testid="memory-item">
                <div>
                  <div className="chip-row" style={{ marginBottom: 4 }}>
                    <Chip tone="info">{m.kind}</Chip>
                    <Chip tone={m.promoted ? "ok" : "warn"}>{m.promoted ? "promoted" : "pending"}</Chip>
                  </div>
                  <p style={{ margin: 0, fontWeight: 600 }}>{m.text}</p>
                  <p className="hint" style={{ margin: 0 }}>
                    {m.source} · {timeAgo(m.created_at)} · confidence {Math.round(m.confidence * 100)}%
                  </p>
                </div>
                <button className="btn sm danger" onClick={() => del.mutate(m.memory_id)} disabled={del.isPending} aria-label={`Delete memory: ${m.text}`}>
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </Async>
    </section>
  );
}

export default function SettingsPage() {
  const q = useSettings();
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Settings</p>
          <h1>How much GigBid does on its own</h1>
        </div>
      </header>
      <Async query={q}>{(s) => <SettingsForm initial={s} />}</Async>
      <div style={{ marginTop: 16 }}>
        <Connections />
        <MemoryViewer />
      </div>
    </div>
  );
}
