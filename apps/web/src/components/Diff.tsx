import { useMemo } from "react";
import { diffWords } from "../lib/diff";

/** Word-level diff between the agent's draft and the user's edit. */
export function Diff({ before, after }: { before: string; after: string }) {
  const ops = useMemo(() => diffWords(before, after), [before, after]);
  const changed = ops.some((o) => o.kind !== "same");
  return (
    <div>
      <p className="label" style={{ marginBottom: 6 }}>
        Your changes <span className="muted">(green added, red removed)</span>
      </p>
      <div className="diff" data-testid="diff" aria-label="Diff between the draft and your edit">
        {changed ? (
          ops.map((o, i) =>
            o.kind === "add" ? (
              <ins key={i}>{o.text}</ins>
            ) : o.kind === "del" ? (
              <del key={i}>{o.text}</del>
            ) : (
              <span key={i}>{o.text}</span>
            ),
          )
        ) : (
          <span className="muted">No changes yet.</span>
        )}
      </div>
    </div>
  );
}
