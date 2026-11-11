import { useMemo } from "react";
import { ms, usd } from "../lib/format";
import type { StreamState } from "../lib/sse";
import type { RunEvent, RunStep } from "../lib/types";

type NodeStatus = "pending" | "running" | "done" | "interrupted" | "failed" | "skipped";

interface NodeRow {
  node: string;
  label: string;
  status: NodeStatus;
  summary: string;
  duration_ms: number | null;
  tokens: number;
  cost: number;
  model: string | null;
}

const ICON: Record<NodeStatus, string> = { pending: "", running: "", done: "✓", interrupted: "!", failed: "×", skipped: "–" };

/** Merge the persisted steps with live stream events into one row per graph node. */
export function buildRows(steps: RunStep[], events: RunEvent[]): NodeRow[] {
  const rows = new Map<string, NodeRow>();
  const live = events.length > 0;
  for (const s of steps) {
    rows.set(s.node, {
      node: s.node,
      label: s.label || s.node,
      status: live ? "pending" : (s.status as NodeStatus),
      summary: live ? "" : s.summary,
      duration_ms: live ? null : (s.duration_ms ?? null),
      tokens: live ? 0 : s.tokens_in + s.tokens_out,
      cost: live ? 0 : s.cost_usd,
      model: s.model ?? null,
    });
  }
  for (const e of events) {
    if (!e.node) continue;
    const row = rows.get(e.node) ?? {
      node: e.node, label: e.node, status: "pending" as NodeStatus, summary: "", duration_ms: null, tokens: 0, cost: 0, model: null,
    };
    const d = e.data as Record<string, unknown>;
    if (e.type === "node_start") {
      row.status = "running";
      if (typeof d.label === "string") row.label = d.label;
    } else if (e.type === "node_end") {
      row.status = "done";
      row.duration_ms = typeof d.duration_ms === "number" ? d.duration_ms : row.duration_ms;
      row.tokens = Number(d.tokens_in ?? 0) + Number(d.tokens_out ?? 0);
      row.cost = Number(d.cost_usd ?? 0);
      row.summary = typeof d.summary === "string" ? d.summary : row.summary;
      row.model = typeof d.model === "string" ? d.model : row.model;
    } else if (e.type === "interrupt") {
      row.status = "interrupted";
      row.summary = "Paused: waiting for a human decision.";
    }
    rows.set(e.node, row);
  }
  return [...rows.values()];
}

interface Props {
  steps: RunStep[];
  events: RunEvent[];
  state: StreamState;
}

export function RunTimeline({ steps, events, state }: Props) {
  const rows = useMemo(() => buildRows(steps, events), [steps, events]);
  const tokenText = useMemo(
    () => events.filter((e) => e.type === "token").map((e) => String((e.data as { text?: string }).text ?? "")).join(""),
    [events],
  );
  const degraded = events.filter((e) => e.type === "degraded");
  const writerRunning = rows.find((r) => r.node === "writer")?.status === "running";

  return (
    <div data-testid="run-timeline">
      <div className="sr-only" role="status" aria-live="polite">
        {state === "streaming" ? "Run in progress" : state === "ended" ? "Run stream finished" : ""}
      </div>
      {degraded.map((e, i) => (
        <p key={i} className="callout" role="status" data-testid="run-degraded">
          <strong>Degraded:</strong> {String((e.data as { detail?: string }).detail ?? "a dependency is unavailable")}
        </p>
      ))}
      <ol className="timeline">
        {rows.map((r) => (
          <li key={r.node} className="node" data-status={r.status} data-node={r.node} data-testid={`node-${r.node}`}>
            <span className="node-dot" aria-hidden="true">
              {ICON[r.status]}
            </span>
            <div>
              <h3>
                {r.label} <span className="sr-only">{r.status}</span>
              </h3>
              {r.summary ? <p>{r.summary}</p> : null}
              {r.node === "writer" && tokenText ? (
                <div className={`tokens-box ${writerRunning ? "caret" : ""}`} data-testid="writer-tokens">
                  {tokenText}
                </div>
              ) : null}
            </div>
            <div className="node-metrics">
              {r.duration_ms != null ? <div>{ms(r.duration_ms)}</div> : null}
              {r.tokens ? <div>{r.tokens} tok</div> : null}
              {r.cost ? <div>{usd(r.cost)}</div> : null}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
