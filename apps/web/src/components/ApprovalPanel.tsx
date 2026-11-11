import { Link } from "react-router-dom";
import { ApiError } from "../lib/client";
import { money } from "../lib/format";
import { useDecideApproval, useHealth } from "../lib/queries";
import type { ApprovalItem, ApprovalRequest, DecisionResult } from "../lib/types";
import { useState } from "react";
import { Chip, RiskBadges } from "./Badges";
import { DecisionControls } from "./DecisionControls";

export function draftText(request: ApprovalRequest): string {
  const d = request.draft as { cover_letter?: unknown; text?: unknown };
  if (typeof d.cover_letter === "string") return d.cover_letter;
  if (typeof d.text === "string") return d.text;
  return "";
}

const STATUS_TONE = { pending: "accent", approved: "ok", edited: "ok", rejected: "bad" } as const;

/** Everything the human needs in one place before a proposal leaves the building (R4). */
export function ApprovalPanel({ item }: { item: ApprovalItem }) {
  const { request } = item;
  const decide = useDecideApproval();
  const health = useHealth();
  const [result, setResult] = useState<DecisionResult | null>(null);
  const pending = item.status === "pending" && !result;
  const marketplaceDown = health.data ? !health.data.marketplace.ok : false;
  const errorText = decide.error instanceof ApiError ? decide.error.message : decide.error ? "Could not save your decision." : "";

  const submit = (decision: Parameters<typeof decide.mutate>[0]["decision"]) =>
    decide.mutate({ approvalId: item.approval_id, decision }, { onSuccess: (r) => setResult(r) });

  return (
    <section className="panel approval" aria-labelledby={`appr-${item.approval_id}`} data-testid="approval-panel" data-status={result?.status ?? item.status}>
      <header>
        <p className="eyebrow">Needs your decision · {request.kind}</p>
        <h2 id={`appr-${item.approval_id}`} style={{ fontSize: "1.2rem" }}>
          {item.title || "Approval"}
        </h2>
        <p style={{ marginTop: 6 }}>
          <Chip tone={STATUS_TONE[result?.status ?? item.status]}>
            <span data-testid="approval-status">{result?.status ?? item.status}</span>
          </Chip>
        </p>
      </header>

      {request.price ? (
        <dl className="kv" data-testid="price-block">
          <dt>Bid</dt>
          <dd>{money(request.price.amount, request.price.currency)}</dd>
          <dt>Fair band</dt>
          <dd>
            {money(request.price.band_low)} – {money(request.price.band_high)}
          </dd>
          <dt>Connects cost</dt>
          <dd data-testid="connects-cost">
            {request.price.connects_cost}
            {request.price.worth_connects ? "" : " (not worth it)"}
          </dd>
        </dl>
      ) : null}
      {request.price?.rationale ? <p className="hint" data-testid="price-rationale">{request.price.rationale}</p> : null}

      {request.risk ? (
        <div>
          <p className="label">Risk</p>
          <RiskBadges risk={request.risk} />
          {request.risk.explanation ? <p className="hint" style={{ marginTop: 6 }}>{request.risk.explanation}</p> : null}
        </div>
      ) : null}

      {request.critic ? (
        <div data-testid="critic-block">
          <p className="label">
            Critic <Chip tone={request.critic.ok ? "ok" : "bad"}>{request.critic.ok ? "pass" : "send back"}</Chip>{" "}
            <span className="mono">{request.critic.score.toFixed(2)}</span>
          </p>
          <ul className="ul">
            {request.critic.issues.map((i) => (
              <li key={i}>{i}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {request.compliance ? (
        <div data-testid="compliance-block">
          <p className="label">
            Compliance <Chip tone={request.compliance.blocked ? "bad" : request.compliance.violations.length ? "warn" : "ok"}>
              {request.compliance.blocked ? "blocked" : request.compliance.violations.length ? "fixed" : "clean"}
            </Chip>
          </p>
          {request.compliance.violations.length + request.compliance.redactions.length === 0 ? (
            <p className="hint">No policy violations found.</p>
          ) : (
            <ul className="ul">
              {request.compliance.violations.map((v) => (
                <li key={v}>{v}</li>
              ))}
              {request.compliance.redactions.map((r) => (
                <li key={r}>Redacted: {r}</li>
              ))}
            </ul>
          )}
        </div>
      ) : null}

      {request.dry_run ? (
        <details open data-testid="dry-run">
          <summary>Dry run: exactly what will be sent</summary>
          <p className="hint">
            Costs <strong>{request.dry_run.connects_cost} Connects</strong>
            {request.dry_run.balance_after != null ? `; balance after: ${request.dry_run.balance_after}` : ""}. Nothing is persisted by a dry run.
          </p>
          <pre>{JSON.stringify(request.dry_run.payload, null, 2)}</pre>
        </details>
      ) : null}

      {pending ? (
        <>
          {marketplaceDown ? (
            <p className="callout" role="status">
              Marketplace is unavailable. If you approve, the send is queued and retried automatically.
            </p>
          ) : null}
          <DecisionControls
            originalText={draftText(request)}
            busy={decide.isPending}
            approveLabel={`Approve and send${request.price ? ` (${request.price.connects_cost} Connects)` : ""}`}
            onApprove={() => submit({ action: "approve" })}
            onEdit={(text) => submit({ action: "edit", edited_text: text })}
            onReject={(reason) => submit({ action: "reject", reason })}
          />
          {errorText ? (
            <p className="field-error" role="alert">
              {errorText}
            </p>
          ) : null}
        </>
      ) : (
        <div role="status" aria-live="polite" data-testid="decision-result">
          <p className="status-big">
            {result ? (result.queued ? "Approved and queued" : result.status === "rejected" ? "Rejected" : "Sent") : item.status}
          </p>
          {result?.message ? <p>{result.message}</p> : null}
          {item.decision?.reason ? <p className="hint">Reason: {item.decision.reason}</p> : null}
          {request.job_id ? (
            <Link to="/pipeline" className="btn sm">
              See it on the pipeline
            </Link>
          ) : null}
        </div>
      )}
    </section>
  );
}
