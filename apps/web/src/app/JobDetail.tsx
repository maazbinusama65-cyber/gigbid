import { Link, useNavigate, useParams } from "react-router-dom";
import { Chip, FitMeter, Recommendation, RiskBadges } from "../components/Badges";
import { RequirementMatrix } from "../components/RequirementMatrix";
import { Async } from "../components/States";
import { ApiError } from "../lib/client";
import { budgetLabel, money, pct, timeAgo } from "../lib/format";
import { useAnalyzeJob, useJob, useSkipJob } from "../lib/queries";
import type { JobDetail } from "../lib/types";

function Detail({ d }: { d: JobDetail }) {
  const navigate = useNavigate();
  const analyze = useAnalyzeJob();
  const skip = useSkipJob();
  const { job, client, spec, risk, fit, price, decision } = d;
  const analyzed = spec && fit;
  const startAnalysis = () => analyze.mutate(job.job_id, { onSuccess: (r) => navigate(`/runs/${r.run_id}`) });

  return (
    <div className="page">
      <Link to="/" className="back">
        ← Job inbox
      </Link>
      <header className="page-head">
        <div>
          <p className="eyebrow">
            {job.category} · posted {timeAgo(job.posted_at)} · <span className="mono">{job.job_id}</span>
          </p>
          <h1>{job.title}</h1>
          <div className="chip-row" style={{ marginTop: 12 }}>
            <Chip>{budgetLabel(job.budget)}</Chip>
            {job.duration_days ? <Chip>{job.duration_days} days</Chip> : null}
            <Chip>{job.connects_cost} Connects</Chip>
            <Chip tone={d.status === "drafted" ? "accent" : ""}>{d.status}</Chip>
          </div>
        </div>
        <FitMeter score={fit?.score ?? null} />
      </header>

      <div className="cols">
        <div>
          <section className="panel" aria-labelledby="post-h">
            <h2 id="post-h">The job post</h2>
            <p className="hint">Untrusted client text, shown verbatim. GigBid treats it as data and never follows instructions inside it.</p>
            <blockquote style={{ margin: 0, padding: "4px 0 4px 16px", borderLeft: "4px solid var(--rule)" }} data-testid="job-description">
              {job.description}
            </blockquote>
            {d.sanitized_notes.length ? (
              <div className="callout bad" style={{ marginTop: 16 }} data-testid="sanitized-notes">
                <strong>Handled safely</strong>
                <ul className="ul">
                  {d.sanitized_notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </section>

          {analyzed ? (
            <>
              <section className="panel" aria-labelledby="spec-h">
                <h2 id="spec-h">What the client actually wants</h2>
                <div className="grid-2">
                  <div>
                    <p className="label">Deliverables</p>
                    <ul className="ul">{spec.deliverables.map((x) => <li key={x}>{x}</li>)}</ul>
                  </div>
                  <div>
                    <p className="label">Hidden needs inferred</p>
                    {spec.hidden_needs.length ? (
                      <ul className="ul">{spec.hidden_needs.map((x) => <li key={x}>{x}</li>)}</ul>
                    ) : (
                      <p className="muted">None detected.</p>
                    )}
                  </div>
                </div>
              </section>
              <section className="panel" aria-labelledby="matrix-h">
                <h2 id="matrix-h">Requirement to evidence</h2>
                <p className="hint">Hover or focus an evidence chip to read the portfolio item behind it. Gaps stay visible and will not be claimed.</p>
                <RequirementMatrix fit={fit} evidence={d.evidence} />
                {fit.missing_skills.length ? (
                  <p style={{ marginTop: 12 }}>
                    <span className="label">Missing: </span>
                    {fit.missing_skills.map((s) => (
                      <Chip key={s} tone="bad">
                        {s}
                      </Chip>
                    ))}
                  </p>
                ) : null}
              </section>
            </>
          ) : (
            <section className="panel soft" data-testid="not-analyzed">
              <h2>Not analysed yet</h2>
              <p>Run the agents to get the requirement matrix, risk report, price rationale and a bid-or-skip decision. It takes a few seconds and you can watch every step.</p>
            </section>
          )}
        </div>

        <aside>
          <section className="panel" aria-labelledby="decision-h">
            <h2 id="decision-h">Recommendation</h2>
            <p style={{ margin: "0 0 8px" }}>
              <Recommendation value={decision?.decision ?? null} />
              {!decision ? <span className="muted">Run the analysis for a decision.</span> : null}
            </p>
            {decision ? (
              <ul className="ul" data-testid="decision-reasons">
                {decision.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            ) : null}
            <div className="btn-row" style={{ marginTop: 16 }}>
              {d.status === "drafted" ? (
                <Link className="btn primary" to={`/studio/${job.job_id}`} data-testid="open-studio">
                  Open proposal studio
                </Link>
              ) : (
                <button className="btn primary" onClick={startAnalysis} disabled={analyze.isPending || d.status === "analyzing"} data-testid="run-analysis">
                  {analyzed ? "Re-run analysis" : "Run analysis"}
                </button>
              )}
              {d.latest_run_id ? (
                <Link className="btn" to={`/runs/${d.latest_run_id}`}>
                  View last run
                </Link>
              ) : null}
              {d.status !== "skipped" && d.status !== "drafted" ? (
                <button className="btn ghost" onClick={() => skip.mutate({ jobId: job.job_id, reason: "skipped from job detail" }, { onSuccess: () => navigate("/") })}>
                  Skip job
                </button>
              ) : null}
            </div>
            {analyze.error ? (
              <p className="field-error" role="alert">
                {analyze.error instanceof ApiError ? analyze.error.message : "Could not start the run."}
              </p>
            ) : null}
          </section>

          {risk ? (
            <section className="panel" aria-labelledby="risk-h">
              <h2 id="risk-h">Risk report</h2>
              <RiskBadges risk={risk} />
              <p style={{ marginTop: 10 }}>{risk.explanation}</p>
              <dl className="kv">
                <dt>Client quality</dt>
                <dd>{pct(risk.client_quality)}</dd>
              </dl>
            </section>
          ) : null}

          {price ? (
            <section className="panel" aria-labelledby="price-h">
              <h2 id="price-h">Price</h2>
              <p className="price" style={{ margin: 0 }}>{money(price.amount, price.currency)}</p>
              <dl className="kv" style={{ marginTop: 8 }}>
                <dt>Fair band</dt>
                <dd>
                  {money(price.band_low)} – {money(price.band_high)}
                </dd>
                <dt>Connects</dt>
                <dd>
                  {price.connects_cost} {price.worth_connects ? "(worth it)" : "(not worth it)"}
                </dd>
              </dl>
              <p className="hint" style={{ marginTop: 8 }}>{price.rationale}</p>
            </section>
          ) : null}

          {client ? (
            <section className="panel soft" aria-labelledby="client-h">
              <h2 id="client-h">{client.name}</h2>
              <dl className="kv">
                <dt>Payment verified</dt>
                <dd>{client.payment_verified ? "Yes" : "No"}</dd>
                <dt>Total spent</dt>
                <dd>{money(client.total_spent)}</dd>
                <dt>Hire rate</dt>
                <dd>{pct(client.hire_rate)}</dd>
                <dt>Rating</dt>
                <dd>{client.avg_rating ?? "none"}</dd>
                <dt>Country</dt>
                <dd>{client.country}</dd>
              </dl>
            </section>
          ) : null}
        </aside>
      </div>
    </div>
  );
}

export default function JobDetailPage() {
  const { id = "" } = useParams();
  const q = useJob(id);
  return <Async query={q}>{(d) => <Detail d={d} />}</Async>;
}
