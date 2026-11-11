import { useState } from "react";
import { Link } from "react-router-dom";
import { ApprovalPanel, draftText } from "../components/ApprovalPanel";
import { Async, EmptyState } from "../components/States";
import { useApprovals } from "../lib/queries";

export default function Approvals() {
  const q = useApprovals();
  const [showDone, setShowDone] = useState(false);
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Human in the loop</p>
          <h1>Approval queue</h1>
          <p className="lede">Every proposal, message and Connects spend waits here. This list comes from the server, so a refresh never loses anything.</p>
        </div>
        <label className="inline-check">
          <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} />
          Show decided
        </label>
      </header>
      <Async
        query={q}
        empty={(d) =>
          d.pending_count === 0 && !showDone ? (
            <EmptyState title="Nothing waiting on you" action={<Link className="btn" to="/">Back to the job inbox</Link>}>
              New drafts appear here after the agents finish a run.
            </EmptyState>
          ) : null
        }
      >
        {(d) => (
          <div className="stack" data-testid="approval-list">
            {d.approvals
              .filter((a) => showDone || a.status === "pending")
              .map((a) => (
                <div key={a.approval_id} className="cols" style={{ alignItems: "start" }}>
                  <section className="panel soft">
                    <p className="eyebrow">{a.request.kind === "message" ? "Suggested reply" : "Proposal draft"}</p>
                    <p style={{ whiteSpace: "pre-wrap", fontFamily: "var(--font-display)" }}>{draftText(a.request)}</p>
                    <div className="btn-row">
                      {a.request.kind === "proposal" && a.request.job_id ? (
                        <Link className="btn sm" to={`/studio/${a.request.job_id}`}>Open in studio</Link>
                      ) : null}
                      {a.request.kind === "message" ? <Link className="btn sm" to={`/messages/${a.request.thread_id}`}>Open thread</Link> : null}
                      {a.run_id ? <Link className="btn sm ghost" to={`/runs/${a.run_id}`}>View run</Link> : null}
                    </div>
                  </section>
                  <aside style={{ position: "static" }}>
                    <ApprovalPanel item={a} />
                  </aside>
                </div>
              ))}
          </div>
        )}
      </Async>
    </div>
  );
}
