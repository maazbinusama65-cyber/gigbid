import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Chip, FitMeter, Recommendation, RiskBadges } from "../components/Badges";
import { Async, EmptyState } from "../components/States";
import { budgetLabel, money, timeAgo } from "../lib/format";
import { useAnalyzeJob, useApprovals, useJobs, useSkipJob, type JobFilters } from "../lib/queries";
import type { JobSummary } from "../lib/types";

function JobRow({ job }: { job: JobSummary }) {
  const navigate = useNavigate();
  const analyze = useAnalyzeJob();
  const skip = useSkipJob();
  const canAnalyze = job.status === "new" || job.status === "analyzed";
  return (
    <li className={`job-row reveal ${job.status === "skipped" ? "skipped" : ""}`} data-testid="job-row" data-job={job.job_id}>
      <FitMeter score={job.fit_score} />
      <div>
        <h2>
          <Link to={`/jobs/${job.job_id}`}>{job.title}</Link>
        </h2>
        <div className="job-meta">
          <span>{job.client_name}</span>
          <span>{job.category}</span>
          <span>{budgetLabel(job.budget)}</span>
          <span>{timeAgo(job.posted_at)}</span>
        </div>
        <RiskBadges risk={job} />
        <p className="muted" style={{ marginTop: 8, marginBottom: 0, fontSize: "0.85rem" }}>
          {job.top_skills.join(" · ")}
        </p>
      </div>
      <div className="job-side">
        <Recommendation value={job.recommendation} />
        {job.suggested_price ? <span className="price">{money(job.suggested_price)}</span> : null}
        <span className="mono muted">{job.connects_cost} Connects</span>
        {job.status !== "new" ? <Chip tone={job.status === "drafted" ? "accent" : ""}>{job.status}</Chip> : null}
        <div className="btn-row">
          {job.status === "drafted" ? (
            <Link className="btn sm primary" to={`/studio/${job.job_id}`}>
              Review draft
            </Link>
          ) : canAnalyze ? (
            <button
              className="btn sm"
              data-testid="analyze-btn"
              disabled={analyze.isPending}
              onClick={() => analyze.mutate(job.job_id, { onSuccess: (r) => navigate(`/runs/${r.run_id}`) })}
            >
              Analyze
            </button>
          ) : null}
          {job.status !== "skipped" && job.status !== "drafted" ? (
            <button className="btn sm ghost" disabled={skip.isPending} onClick={() => skip.mutate({ jobId: job.job_id, reason: "skipped from inbox" })}>
              Skip
            </button>
          ) : null}
        </div>
      </div>
    </li>
  );
}

export default function Inbox() {
  const [filters, setFilters] = useState<JobFilters>({ sort: "fit" });
  const [q, setQ] = useState("");
  const jobs = useJobs(filters);
  const approvals = useApprovals();
  const pending = approvals.data?.pending_count ?? 0;
  const set = (patch: Partial<JobFilters>) => setFilters((f) => ({ ...f, ...patch }));

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Job inbox</p>
          <h1>Today's jobs, ranked by fit</h1>
          <p className="lede">Scored against your portfolio. Scams and planted instructions are flagged before you spend a Connect.</p>
        </div>
      </header>

      {pending > 0 ? (
        <div className="approval-strip" data-testid="approval-strip">
          <span>
            <strong>{pending}</strong> item{pending === 1 ? "" : "s"} waiting for your approval.
          </span>
          <Link className="btn sm primary" to="/approvals">
            Review now
          </Link>
        </div>
      ) : null}

      <form
        className="filters"
        role="search"
        aria-label="Filter jobs"
        onSubmit={(e) => {
          e.preventDefault();
          set({ q: q.trim() || undefined });
        }}
      >
        <div className="field">
          <label htmlFor="q">Search</label>
          <input id="q" className="input" type="search" value={q} placeholder="title, skill, keyword" onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="cat">Category</label>
          <select id="cat" className="select" value={filters.category ?? ""} onChange={(e) => set({ category: e.target.value || undefined })}>
            <option value="">All</option>
            {(jobs.data?.categories ?? []).map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="fit">Minimum fit</label>
          <select id="fit" className="select" value={filters.min_fit ?? ""} onChange={(e) => set({ min_fit: e.target.value ? Number(e.target.value) : undefined })}>
            <option value="">Any</option>
            <option value="0.5">50+</option>
            <option value="0.7">70+</option>
            <option value="0.85">85+</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="sort">Sort by</label>
          <select id="sort" className="select" value={filters.sort} onChange={(e) => set({ sort: e.target.value as JobFilters["sort"] })}>
            <option value="fit">Best fit</option>
            <option value="posted">Newest</option>
            <option value="budget">Budget</option>
          </select>
        </div>
        <label className="inline-check">
          <input type="checkbox" checked={!!filters.include_skipped} onChange={(e) => set({ include_skipped: e.target.checked })} />
          Show skipped
        </label>
      </form>

      <Async
        query={jobs}
        empty={(d) =>
          d.jobs.length === 0 ? (
            <EmptyState
              title="No jobs match"
              action={
                <button className="btn" onClick={() => { setQ(""); setFilters({ sort: "fit" }); }}>
                  Clear filters
                </button>
              }
            >
              Try a broader search, or wait for the next scout run.
            </EmptyState>
          ) : null
        }
      >
        {(d) => (
          <ul className="job-list" data-testid="job-list" aria-label={`${d.total} jobs`}>
            {d.jobs.map((j) => (
              <JobRow key={j.job_id} job={j} />
            ))}
          </ul>
        )}
      </Async>
    </div>
  );
}
