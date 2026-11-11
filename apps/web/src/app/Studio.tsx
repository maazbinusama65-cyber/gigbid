import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApprovalPanel } from "../components/ApprovalPanel";
import { Chip } from "../components/Badges";
import { ClaimParagraph } from "../components/EvidenceHover";
import { Async, EmptyState, ErrorState } from "../components/States";
import { api, ApiError, unwrap } from "../lib/client";
import { qk, useApprovals, useStudio } from "../lib/queries";
import type { ProposalStudio } from "../lib/types";

function Paragraph({ index, text, studio, evidence, locked }: { index: number; text: string; studio: ProposalStudio; evidence: Map<string, ProposalStudio["evidence"][number]>; locked: boolean }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [asking, setAsking] = useState(false);
  const regen = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/proposals/{job_id}/regenerate", {
          params: { path: { job_id: studio.job_id } },
          body: { paragraph_index: index, instruction: note },
        }),
      ),
    onSuccess: (data) => {
      qc.setQueryData(qk.studio(studio.job_id), data);
      void qc.invalidateQueries({ queryKey: qk.approvals });
      setAsking(false);
      setNote("");
    },
  });
  return (
    <div className="para" data-testid="paragraph">
      <p>
        <ClaimParagraph text={text} claims={studio.draft.claims} evidence={evidence} />
      </p>
      {!locked ? (
        <div className="para-tools">
          {asking ? (
            <>
              <label className="sr-only" htmlFor={`note-${index}`}>
                Instruction for paragraph {index + 1}
              </label>
              <input id={`note-${index}`} className="input" style={{ maxWidth: 320 }} placeholder="optional: shorter, mention pgvector…" value={note} onChange={(e) => setNote(e.target.value)} />
              <button className="btn sm" onClick={() => regen.mutate()} disabled={regen.isPending} data-testid="regen-confirm">
                {regen.isPending ? "Rewriting…" : "Rewrite"}
              </button>
              <button className="btn sm ghost" onClick={() => setAsking(false)}>
                Cancel
              </button>
            </>
          ) : (
            <button className="btn sm ghost" onClick={() => setAsking(true)} data-testid="regen-btn" aria-label={`Regenerate paragraph ${index + 1}`}>
              Regenerate this paragraph
            </button>
          )}
          {regen.error ? (
            <span className="field-error" role="alert">
              {regen.error instanceof ApiError ? regen.error.message : "Could not regenerate."}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function StudioView({ studio }: { studio: ProposalStudio }) {
  const approvals = useApprovals();
  const evidence = useMemo(() => new Map(studio.evidence.map((e) => [e.id, e])), [studio.evidence]);
  const item = approvals.data?.approvals.find((a) => a.approval_id === studio.approval_id);
  const locked = !item || item.status !== "pending";
  const removed = studio.draft.claims.filter((c) => c.removed);
  const kept = studio.draft.claims.filter((c) => !c.removed);

  return (
    <div className="page">
      <Link to={`/jobs/${studio.job_id}`} className="back">
        ← Job detail
      </Link>
      <header className="page-head">
        <div>
          <p className="eyebrow">Proposal studio · revision {studio.draft.revision}</p>
          <h1>{studio.job_title}</h1>
        </div>
        {studio.critic ? <Chip tone={studio.critic.ok ? "ok" : "warn"}>critic {studio.critic.score.toFixed(2)}</Chip> : null}
      </header>
      <div className="cols">
        <div>
          <section className="panel" aria-labelledby="letter-h">
            <h2 id="letter-h">Cover letter</h2>
            <div className="legend" style={{ marginBottom: 12 }}>
              <span><span className="claim supported">supported</span></span>
              <span><span className="claim partly_supported">partly supported</span></span>
              <span>Hover or focus a highlighted claim to see its evidence.</span>
            </div>
            <div className="letter" data-testid="letter">
              {studio.paragraphs.map((p, i) => (
                <Paragraph key={`${studio.draft.revision}-${i}`} index={i} text={p} studio={studio} evidence={evidence} locked={locked} />
              ))}
            </div>
          </section>

          {studio.draft.screening_answers.some(Boolean) ? (
            <section className="panel" aria-labelledby="qa-h">
              <h2 id="qa-h">Screening answers</h2>
              {studio.screening_questions.map((q, i) => (
                <div key={q} style={{ marginBottom: 12 }}>
                  <p className="label">{q}</p>
                  <p>{studio.draft.screening_answers[i]}</p>
                </div>
              ))}
            </section>
          ) : null}

          <section className="panel soft" aria-labelledby="claims-h">
            <h2 id="claims-h">Claim check</h2>
            <p className="hint">Every factual sentence is verified against your portfolio before it can reach the client.</p>
            <ul className="ul" data-testid="claim-list">
              {kept.map((c) => (
                <li key={c.text}>
                  <Chip tone={c.label === "supported" ? "ok" : "warn"}>{c.label.replace("_", " ")}</Chip> {c.rewritten ? `Softened to: “${c.rewritten}”` : c.text}
                  <span className="mono muted"> [{c.evidence_ids.join(", ")}]</span>
                </li>
              ))}
              {removed.map((c) => (
                <li key={c.text} data-testid="removed-claim">
                  <Chip tone="bad">removed</Chip> <span className="removed">{c.text}</span>{" "}
                  <span className="muted">No evidence in your portfolio, so it was cut.</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
        <aside>
          {item ? (
            <ApprovalPanel key={item.approval_id} item={item} />
          ) : approvals.isPending ? null : (
            <EmptyState title="No approval pending">This draft is not waiting on you.</EmptyState>
          )}
        </aside>
      </div>
    </div>
  );
}

export default function Studio() {
  const { id = "" } = useParams();
  const q = useStudio(id);
  if (q.error && q.error instanceof ApiError && q.error.status === 404) {
    return (
      <div className="page">
        <EmptyState title="No draft for this job yet" action={<Link className="btn primary" to={`/jobs/${id}`}>Go to the job and run the analysis</Link>}>
          The proposal studio opens once the agents have written a draft.
        </EmptyState>
      </div>
    );
  }
  if (q.error) return <div className="page"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div>;
  return <Async query={q}>{(s) => <StudioView studio={s} />}</Async>;
}
