import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { RunStatusChip, runStatusInfo } from "../components/Badges";
import { RunTimeline } from "../components/RunTimeline";
import { Async, ErrorState } from "../components/States";
import { ms, usd } from "../lib/format";
import { useRun, useTrace } from "../lib/queries";
import { useRunStream } from "../lib/sse";
import type { RunDetail, RunStatus } from "../lib/types";

function Viewer({ run }: { run: RunDetail }) {
  const runId = run.summary.run_id;
  const qc = useQueryClient();
  const { events, state, retry } = useRunStream(runId);
  const [showTrace, setShowTrace] = useState(false);
  const trace = useTrace(runId, showTrace);

  const done = [...events].reverse().find((e) => e.type === "done");
  const interrupt = events.find((e) => e.type === "interrupt");
  const status: RunStatus = (done?.data as { status?: RunStatus } | undefined)?.status ?? run.summary.status;
  const approvalId = (interrupt?.data as { approval_id?: string } | undefined)?.approval_id ?? run.approval_id;
  const reason = (done?.data as { reason?: string } | undefined)?.reason;

  useEffect(() => {
    if (state === "ended") {
      for (const k of ["run", "runs", "approvals", "jobs", "job"]) void qc.invalidateQueries({ queryKey: [k] });
    }
  }, [state, qc]);

  const live = state === "streaming" || state === "connecting";
  const info = runStatusInfo(status);

  return (
    <div className="page">
      <Link to="/runs" className="back">
        ← All runs
      </Link>
      <header className="page-head">
        <div>
          <p className="eyebrow">
            Agent run · <span className="mono">{runId}</span>
          </p>
          <h1>{run.summary.title}</h1>
          <p className="lede" data-testid="run-state-help">
            {live && !done ? "Streaming live from the graph. You never need to wait on a spinner: each node reports as it finishes." : info.help}
          </p>
        </div>
        <div style={{ textAlign: "right" }}>
          <span data-testid="run-status">
            <RunStatusChip status={status} />
          </span>
          <p className="mono muted" style={{ margin: "8px 0 0" }}>
            {ms(run.summary.latency_ms)} · {run.summary.total_tokens} tok · {usd(run.summary.cost_usd)}
          </p>
        </div>
      </header>

      {state === "error" ? (
        <div style={{ marginBottom: 16 }}>
          <ErrorState error={new Error("The live stream dropped. History is still available.")} onRetry={retry} />
        </div>
      ) : null}

      <div className="cols">
        <section className="panel" aria-labelledby="tl-h">
          <h2 id="tl-h">Node by node</h2>
          <RunTimeline steps={run.steps} events={events} state={state} />
        </section>
        <aside>
          {status === "awaiting_approval" && approvalId ? (
            <section className="panel" data-testid="interrupt-card" style={{ borderColor: "var(--accent)" }}>
              <p className="eyebrow">Interrupt</p>
              <h2>Paused for your decision</h2>
              <p>The graph is checkpointed and waiting. Approving resumes this exact thread; a refresh loses nothing.</p>
              <Link
                className="btn primary"
                data-testid="review-approval"
                to={run.summary.job_id ? `/studio/${run.summary.job_id}` : "/approvals"}
              >
                Review the draft
              </Link>
            </section>
          ) : null}
          {reason || run.notes.length ? (
            <section className="panel soft">
              <h2>Notes</h2>
              <ul className="ul">
                {[...new Set([...(reason ? [reason] : []), ...run.notes])].map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </section>
          ) : null}
          <section className="panel soft" aria-labelledby="trace-h">
            <h2 id="trace-h">Trace</h2>
            <p className="mono" style={{ wordBreak: "break-all" }}>trace id {run.summary.trace_id}</p>
            <div className="btn-row">
              <a className="btn sm" href={run.trace_url} target="_blank" rel="noreferrer" data-testid="trace-link">
                Open full trace
              </a>
              <button className="btn sm" onClick={() => setShowTrace((s) => !s)} aria-expanded={showTrace}>
                {showTrace ? "Hide spans" : "Show spans"}
              </button>
            </div>
            {showTrace ? (
              <div style={{ marginTop: 12 }}>
                <Async query={trace}>
                  {(t) => (
                    <div className="table-wrap">
                      <table className="matrix" data-testid="trace-spans">
                        <thead>
                          <tr>
                            <th>Span</th>
                            <th>ms</th>
                            <th>Tokens</th>
                            <th>Cost</th>
                          </tr>
                        </thead>
                        <tbody>
                          {t.spans.map((s) => (
                            <tr key={s.span_id}>
                              <td>
                                <span className="mono">{s.kind}</span> {s.name}
                              </td>
                              <td className="num">{s.duration_ms}</td>
                              <td className="num">{s.tokens_in + s.tokens_out || ""}</td>
                              <td className="num">{s.cost_usd ? usd(s.cost_usd) : ""}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </Async>
              </div>
            ) : null}
          </section>
        </aside>
      </div>
    </div>
  );
}

export default function RunViewer() {
  const { id = "" } = useParams();
  const q = useRun(id);
  return <Async query={q}>{(run) => <Viewer key={id} run={run} />}</Async>;
}

