import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link, NavLink, useParams } from "react-router-dom";
import { Chip } from "../components/Badges";
import { DecisionControls } from "../components/DecisionControls";
import { Async, EmptyState } from "../components/States";
import { api, ApiError, unwrap } from "../lib/client";
import { shortDateTime, timeAgo } from "../lib/format";
import { useInvalidateAfterDecision, useThread, useThreads } from "../lib/queries";
import type { ThreadDetail } from "../lib/types";

const INTENT_LABEL: Record<string, string> = {
  question: "Question",
  negotiation: "Negotiation",
  interview_request: "Interview request",
  scam_signal: "Scam signal",
  other: "Other",
};

function Conversation({ detail }: { detail: ThreadDetail }) {
  const invalidate = useInvalidateAfterDecision();
  const [slot, setSlot] = useState("");
  const [done, setDone] = useState("");
  const decide = useMutation({
    mutationFn: (body: { action: "approve" | "edit" | "reject"; edited_text?: string; reason?: string }) =>
      unwrap(
        api.POST("/api/messages/{thread_id}/decision", {
          params: { path: { thread_id: detail.thread.thread_id } },
          body: { ...body, slot_id: slot || null },
        }),
      ),
    onSuccess: (r) => {
      setDone(r.message || r.status);
      invalidate();
    },
  });
  const reply = detail.suggested_reply;
  return (
    <div>
      <header style={{ marginBottom: 16 }}>
        <p className="eyebrow">{detail.thread.job_title}</p>
        <h2>{detail.thread.client_name}</h2>
        <div className="chip-row" style={{ marginTop: 8 }}>
          <Chip tone={detail.thread.intent === "scam_signal" ? "bad" : "info"}>{INTENT_LABEL[detail.thread.intent]}</Chip>
          {detail.thread.injection_detected ? <Chip tone="bad">Injected instruction</Chip> : null}
        </div>
      </header>
      {detail.safety_note ? (
        <p className="callout bad" data-testid="safety-note">
          {detail.safety_note}
        </p>
      ) : null}
      <div className="bubbles" data-testid="bubbles" role="log" aria-label="Conversation">
        {detail.messages.map((m) => (
          <div key={m.message_id} className={`bubble ${m.sender === "freelancer" ? "me" : ""} ${m.flagged ? "flagged" : ""}`}>
            {m.body}
            <time>{m.sender === "client" ? detail.thread.client_name : "You"} · {timeAgo(m.ts)}</time>
          </div>
        ))}
      </div>

      {done ? (
        <p className="callout ok" role="status" data-testid="message-sent" style={{ marginTop: 16 }}>
          {done}
        </p>
      ) : null}

      {reply ? (
        <section className="panel" style={{ marginTop: 24 }} aria-labelledby="reply-h" data-testid="suggested-reply">
          <p className="eyebrow">Suggested reply · needs your approval</p>
          <h2 id="reply-h" style={{ fontSize: "1.1rem" }}>Draft</h2>
          <p style={{ whiteSpace: "pre-wrap", fontFamily: "var(--font-display)" }}>{reply.text}</p>
          <p className="hint">{reply.rationale}</p>
          {detail.slots.length ? (
            <fieldset>
              <legend className="label" style={{ marginBottom: 8 }}>Interview slots from your calendar (tentative hold on approval)</legend>
              <div className="slots">
                {detail.slots.map((s) => (
                  <label className="slot" key={s.slot_id}>
                    <input type="radio" name="slot" checked={slot === s.slot_id} onChange={() => setSlot(s.slot_id)} />
                    <span>{s.label}</span>
                  </label>
                ))}
              </div>
              <p className="hint">{slot ? `Selected ${shortDateTime(detail.slots.find((s) => s.slot_id === slot)?.start ?? "")}` : "Pick one to create a hold."}</p>
            </fieldset>
          ) : null}
          <DecisionControls
            originalText={reply.text}
            busy={decide.isPending}
            approveLabel="Approve and send reply"
            onApprove={() => decide.mutate({ action: "approve" })}
            onEdit={(t) => decide.mutate({ action: "edit", edited_text: t })}
            onReject={(r) => decide.mutate({ action: "reject", reason: r })}
          />
          {decide.error ? (
            <p className="field-error" role="alert">
              {decide.error instanceof ApiError ? decide.error.message : "Could not save your decision."}
            </p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function ThreadPane({ id }: { id: string }) {
  const q = useThread(id);
  return <Async query={q}>{(d) => <Conversation key={d.thread.thread_id} detail={d} />}</Async>;
}

export default function Messages() {
  const { threadId } = useParams();
  const threads = useThreads();
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Messages</p>
          <h1>Client threads</h1>
          <p className="lede">Replies are suggested, never sent on their own. Client messages are treated as untrusted text.</p>
        </div>
      </header>
      <div className={`msg-layout ${threadId ? "has-thread" : ""}`}>
        <div className="thread-pane">
          <Async
            query={threads}
            empty={(d) => (d.threads.length === 0 ? <EmptyState title="No conversations yet">Clients who reply to your proposals appear here.</EmptyState> : null)}
          >
            {(d) => (
              <ul className="thread-list" data-testid="thread-list">
                {d.threads.map((t) => (
                  <li key={t.thread_id}>
                    <NavLink to={`/messages/${t.thread_id}`}>
                      <strong>
                        {t.unread ? <span className="unread-dot" aria-label="unread" /> : null}
                        {t.client_name}
                      </strong>
                      <span className="muted" style={{ fontSize: "0.8rem" }}>{t.job_title}</span>
                      <span className="snippet">{t.last_message}</span>
                      <span className="chip-row" style={{ marginTop: 6 }}>
                        <Chip tone={t.intent === "scam_signal" ? "bad" : ""}>{INTENT_LABEL[t.intent]}</Chip>
                        {t.has_suggested_reply ? <Chip tone="accent">reply ready</Chip> : null}
                      </span>
                    </NavLink>
                  </li>
                ))}
              </ul>
            )}
          </Async>
        </div>
        <div className="detail-pane">
          {threadId ? (
            <>
              <Link to="/messages" className="back" style={{ display: "inline-block" }}>← All threads</Link>
              <ThreadPane id={threadId} />
            </>
          ) : (
            <EmptyState title="Select a thread">Pick a conversation to read it and review the suggested reply.</EmptyState>
          )}
        </div>
      </div>
    </div>
  );
}
