import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import type { Claim, EvidenceRef } from "../lib/types";

interface EvidenceHoverProps {
  evidence: EvidenceRef[];
  /** Heading inside the popover, e.g. the claim's verdict. */
  heading?: ReactNode;
  className?: string;
  popClassName?: string;
  testId?: string;
  children: ReactNode;
}

/** Hover or focus the trigger to see the portfolio evidence behind it. Esc dismisses. */
export function EvidenceHover({ evidence, heading, className = "", popClassName = "ev-pop", testId, children }: EvidenceHoverProps) {
  const [open, setOpen] = useState(false);
  const [flip, setFlip] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const popId = useId();

  useEffect(() => {
    if (!open || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    setFlip(rect.left + 380 > window.innerWidth);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <span
      ref={ref}
      className={`ev-wrap ${className}`}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      tabIndex={0}
      aria-describedby={open ? popId : undefined}
      data-testid={testId}
    >
      {children}
      {open ? (
        <span id={popId} role="tooltip" className={`${popClassName} ${flip ? "flip" : ""}`} data-testid="evidence-popover">
          {heading ? <h4>{heading}</h4> : null}
          {evidence.length === 0 ? (
            <span>No portfolio evidence supports this. It cannot be sent as written.</span>
          ) : (
            evidence.map((e) => (
              <span className="ev-item" key={e.id} style={{ display: "block" }}>
                <strong>{e.title || e.id}</strong>
                <span className="muted" style={{ display: "block", fontSize: "0.78rem" }}>
                  <span className="mono">{e.type}</span> · {e.source}
                  {e.outcome ? ` · outcome: ${e.outcome}` : ""}
                </span>
                <blockquote>{e.text}</blockquote>
              </span>
            ))
          )}
        </span>
      ) : null}
    </span>
  );
}

const CLAIM_LABEL: Record<Claim["label"], string> = {
  supported: "Supported by your portfolio",
  partly_supported: "Partly supported: softened by the verifier",
  unsupported: "Unsupported",
};

interface ParagraphProps {
  text: string;
  claims: Claim[];
  evidence: Map<string, EvidenceRef>;
}

/** Render a paragraph with every claim sentence highlighted and wired to its evidence. */
export function ClaimParagraph({ text, claims, evidence }: ParagraphProps) {
  const located = claims
    .filter((c) => !c.removed)
    .map((c) => ({ claim: c, at: text.indexOf(c.text) }))
    .filter((x) => x.at >= 0)
    .sort((a, b) => a.at - b.at);
  const parts: ReactNode[] = [];
  let cursor = 0;
  located.forEach(({ claim, at }, i) => {
    if (at < cursor) return;
    if (at > cursor) parts.push(text.slice(cursor, at));
    const ev = claim.evidence_ids.map((id) => evidence.get(id)).filter((e): e is EvidenceRef => !!e);
    parts.push(
      <EvidenceHover
        key={i}
        evidence={ev}
        heading={CLAIM_LABEL[claim.label]}
        popClassName="claim-pop"
        className=""
        testId="claim"
      >
        <span className={`claim ${claim.label}`}>
          <span>{claim.text}</span>
        </span>
      </EvidenceHover>,
    );
    cursor = at + claim.text.length;
  });
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts}</>;
}
