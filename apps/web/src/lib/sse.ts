import { useEffect, useRef, useState } from "react";
import { authHeaders } from "./client";
import type { RunEvent } from "./types";

export type StreamState = "connecting" | "streaming" | "ended" | "error";

/** Parse an SSE byte stream into RunEvent objects. Uses fetch so the bearer token stays in a header. */
export async function readRunStream(
  runId: string,
  onEvent: (event: RunEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/stream`, {
    headers: { Accept: "text/event-stream", ...authHeaders() },
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`stream failed (${res.status})`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const data = block
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trimStart())
        .join("\n");
      if (data) onEvent(JSON.parse(data) as RunEvent);
      boundary = buffer.indexOf("\n\n");
    }
  }
}

const MAX_RETRIES = 3;

/** Live events for a run. The server replays history on reconnect, so a retry just restarts the list. */
export function useRunStream(runId: string | undefined) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [state, setState] = useState<StreamState>("connecting");
  const [attempt, setAttempt] = useState(0);
  const retries = useRef(0);

  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    setEvents([]);
    setState("connecting");
    const collected: RunEvent[] = [];
    readRunStream(
      runId,
      (e) => {
        collected.push(e);
        setState("streaming");
        setEvents([...collected]);
      },
      controller.signal,
    )
      .then(() => setState("ended"))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (retries.current < MAX_RETRIES) {
          retries.current += 1;
          window.setTimeout(() => setAttempt((n) => n + 1), 800 * retries.current);
        } else {
          setState("error");
        }
        void err;
      });
    return () => controller.abort();
  }, [runId, attempt]);

  return { events, state, retry: () => { retries.current = 0; setAttempt((n) => n + 1); } };
}
