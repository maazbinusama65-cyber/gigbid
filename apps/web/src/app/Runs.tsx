import { Link } from "react-router-dom";
import { RunStatusChip } from "../components/Badges";
import { Async, EmptyState } from "../components/States";
import { ms, timeAgo, usd } from "../lib/format";
import { useRuns } from "../lib/queries";

export default function Runs() {
  const q = useRuns();
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Agent runs</p>
          <h1>What the agents did</h1>
          <p className="lede">Every run is traced end to end. Open one to watch it live or replay it node by node.</p>
        </div>
      </header>
      <Async query={q} empty={(d) => (d.runs.length === 0 ? <EmptyState title="No runs yet">Analyze a job from the inbox to start one.</EmptyState> : null)}>
        {(d) => (
          <ul className="run-list" data-testid="run-list">
            {d.runs.map((r) => (
              <li key={r.run_id}>
                <div>
                  <Link to={`/runs/${r.run_id}`}>
                    <strong>{r.title || r.run_id}</strong>
                  </Link>
                  <div className="muted mono" style={{ fontSize: "0.78rem" }}>
                    {r.run_id} · {timeAgo(r.started_at)} · {ms(r.latency_ms)} · {r.total_tokens} tok · {usd(r.cost_usd)}
                  </div>
                </div>
                <RunStatusChip status={r.status} />
              </li>
            ))}
          </ul>
        )}
      </Async>
    </div>
  );
}
