import type { JobSummary, RunStatus, RiskReport } from "../lib/types";

type Tone = "ok" | "warn" | "bad" | "info" | "accent" | "";

export function Chip({ tone = "", children, title }: { tone?: Tone; children: React.ReactNode; title?: string }) {
  return (
    <span className={`chip ${tone}`} title={title}>
      {children}
    </span>
  );
}

interface RiskLike {
  score?: number | null;
  flags: string[];
  is_scam: boolean;
  injection_detected: boolean;
}

/** Risk badges: scam and injection get their own loud badge; flags follow; clean posts say so. */
export function RiskBadges({ risk }: { risk: RiskLike | RiskReport | JobSummary | null }) {
  if (!risk) return null;
  const score = "risk_score" in risk ? risk.risk_score : "score" in risk ? risk.score : null;
  const flags: string[] = "risk_flags" in risk ? risk.risk_flags : risk.flags;
  const clean = !risk.is_scam && !risk.injection_detected && flags.length === 0;
  return (
    <ul className="chip-row" style={{ listStyle: "none", margin: 0, padding: 0 }} aria-label="Risk signals" data-testid="risk-badges">
      {risk.is_scam ? (
        <li>
          <Chip tone="bad">Scam pattern</Chip>
        </li>
      ) : null}
      {risk.injection_detected ? (
        <li>
          <Chip tone="bad" title="An instruction was embedded in the post. It was treated as data.">
            Injected instruction
          </Chip>
        </li>
      ) : null}
      {flags.map((f) => (
        <li key={f}>
          <Chip tone="warn">{f}</Chip>
        </li>
      ))}
      {clean ? (
        <li>
          <Chip tone="ok">No risk flags</Chip>
        </li>
      ) : null}
      {score != null ? (
        <li>
          <Chip tone={score > 0.6 ? "bad" : score > 0.3 ? "warn" : "ok"}>risk {score.toFixed(2)}</Chip>
        </li>
      ) : null}
    </ul>
  );
}

export function Recommendation({ value }: { value: "bid" | "watch" | "skip" | null | undefined }) {
  if (!value) return null;
  const tone = value === "bid" ? "ok" : value === "watch" ? "warn" : "bad";
  return <Chip tone={tone}>{value === "bid" ? "Recommend bid" : value === "watch" ? "Watch" : "Skip"}</Chip>;
}

const RUN_STATUS: Record<RunStatus, { label: string; tone: Tone; help: string }> = {
  running: { label: "Running", tone: "info", help: "The graph is executing." },
  awaiting_approval: { label: "Awaiting your approval", tone: "accent", help: "Paused on an interrupt. Nothing is sent until you decide." },
  submitted: { label: "Submitted", tone: "ok", help: "Approved and sent through the marketplace tool." },
  skipped: { label: "Skipped", tone: "", help: "The agent decided not to bid; no Connects were spent." },
  rejected: { label: "Rejected", tone: "bad", help: "You rejected the draft. Nothing was sent." },
  blocked: { label: "Blocked", tone: "bad", help: "Compliance blocked the draft before approval." },
  needs_attention: { label: "Needs attention", tone: "warn", help: "A human should look at this run." },
  dead_letter: { label: "Dead letter", tone: "bad", help: "Retries were exhausted; the work item was parked." },
};

export function runStatusInfo(status: RunStatus) {
  return RUN_STATUS[status] ?? { label: status, tone: "" as Tone, help: "" };
}

export function RunStatusChip({ status }: { status: RunStatus }) {
  const info = runStatusInfo(status);
  return (
    <Chip tone={info.tone} title={info.help}>
      {info.label}
    </Chip>
  );
}

export function FitMeter({ score }: { score: number | null | undefined }) {
  if (score == null) return <div className="fit muted">not scored</div>;
  const tone = score >= 0.7 ? "ok" : score >= 0.5 ? "warn" : "bad";
  return (
    <div className="fit" aria-label={`Fit score ${Math.round(score * 100)} out of 100`}>
      <div className="fit-num">
        {Math.round(score * 100)}
        <small>/100</small>
      </div>
      <div className={`meter ${tone}`} aria-hidden="true">
        <span style={{ width: `${score * 100}%` }} />
      </div>
      <span className="eyebrow" style={{ margin: 0 }}>
        fit
      </span>
    </div>
  );
}
