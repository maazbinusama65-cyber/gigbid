import { Async } from "../components/States";
import { pct } from "../lib/format";
import { useAnalytics } from "../lib/queries";

export default function Analytics() {
  const q = useAnalytics();
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Analytics</p>
          <h1>What is working, and what it costs</h1>
        </div>
      </header>
      <Async query={q}>
        {(a) => {
          const maxConnects = Math.max(...a.connects_vs_outcomes.map((p) => p.connects_spent), 1);
          const maxReasons = Math.max(...a.top_rejection_reasons.map((r) => r.count), 1);
          return (
            <>
              {a.is_sample ? (
                <p className="callout info" data-testid="sample-banner" role="note">
                  <strong>Sample data.</strong> {a.sample_note}
                </p>
              ) : null}
              <div className="stat-grid">
                <div className="stat">
                  <b>{a.totals.proposals_sent}</b>
                  <span>proposals sent</span>
                </div>
                <div className="stat">
                  <b>{a.totals.replies}</b>
                  <span>replies</span>
                </div>
                <div className="stat">
                  <b>{a.totals.hires}</b>
                  <span>hires</span>
                </div>
                <div className="stat">
                  <b>{a.totals.connects_spent}</b>
                  <span>Connects spent</span>
                </div>
              </div>

              <section className="panel" aria-labelledby="cat-h">
                <h2 id="cat-h">Reply and hire rate by category</h2>
                <div className="bars" role="list">
                  {a.by_category.map((c) => (
                    <div className="bar-row" role="listitem" key={c.category}>
                      <span>{c.category}</span>
                      <div className="bar-track" aria-hidden="true">
                        <i style={{ width: `${c.reply_rate * 100}%` }} />
                        <i className="second" style={{ width: `${c.hire_rate * 100}%` }} />
                      </div>
                      <span className="mono">
                        {pct(c.reply_rate)} / {pct(c.hire_rate)}
                      </span>
                    </div>
                  ))}
                </div>
                <p className="hint" style={{ marginTop: 12 }}>
                  Orange bar: reply rate. Black bar: hire rate. Values at right: reply / hire.
                </p>
              </section>

              <section className="panel" aria-labelledby="con-h">
                <h2 id="con-h">Connects spent versus outcomes</h2>
                <div className="col-chart" role="img" aria-label="Connects spent per week">
                  {a.connects_vs_outcomes.map((p) => (
                    <div className="c" key={p.period} title={`${p.period}: ${p.connects_spent} Connects, ${p.replies} replies, ${p.hires} hires`}>
                      <span>{p.replies}r/{p.hires}h</span>
                      <i className={p.hires > 1 ? "hl" : ""} style={{ height: `${(p.connects_spent / maxConnects) * 100}%` }} />
                    </div>
                  ))}
                </div>
                <div className="axis">
                  {a.connects_vs_outcomes.map((p) => (
                    <span key={p.period}>{p.period}</span>
                  ))}
                </div>
                <p className="hint" style={{ marginTop: 8 }}>Bar height: Connects spent. Orange: weeks with 2+ hires. Label: replies (r) and hires (h).</p>
              </section>

              <div className="grid-2">
                <section className="panel" aria-labelledby="cost-h">
                  <h2 id="cost-h">Cost and latency</h2>
                  <dl className="kv">
                    <dt>Cost per proposal</dt>
                    <dd>${a.cost_latency.avg_cost_usd_per_proposal.toFixed(3)}</dd>
                    <dt>p50 latency</dt>
                    <dd>{a.cost_latency.p50_latency_s}s</dd>
                    <dt>p95 latency</dt>
                    <dd>{a.cost_latency.p95_latency_s}s</dd>
                    <dt>Cost per job analysed</dt>
                    <dd>${a.cost_latency.avg_cost_usd_per_job_analysed.toFixed(3)}</dd>
                    <dt>p95 per job analysed</dt>
                    <dd>{a.cost_latency.p95_latency_s_per_job_analysed}s</dd>
                    <dt>Proposals measured</dt>
                    <dd>{a.cost_latency.proposals_measured}</dd>
                  </dl>
                </section>
                <section className="panel" aria-labelledby="rej-h">
                  <h2 id="rej-h">Top rejection reasons</h2>
                  <div className="bars" data-testid="rejection-reasons">
                    {a.top_rejection_reasons.map((r) => (
                      <div className="bar-row" key={r.reason} style={{ gridTemplateColumns: "minmax(100px, 1fr) minmax(0, 1fr) 28px" }}>
                        <span>{r.reason}</span>
                        <div className="bar-track" aria-hidden="true">
                          <i style={{ width: `${(r.count / maxReasons) * 100}%` }} />
                        </div>
                        <span className="mono">{r.count}</span>
                      </div>
                    ))}
                  </div>
                </section>
              </div>
            </>
          );
        }}
      </Async>
    </div>
  );
}
