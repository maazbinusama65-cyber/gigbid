import { useState } from "react";
import { Diff } from "./Diff";

const QUICK_REASONS = ["Tone too formal", "Price too high", "Claim not in portfolio", "Wrong client fit"];

interface Props {
  originalText: string;
  busy: boolean;
  approveLabel?: string;
  onApprove: () => void;
  onEdit: (text: string) => void;
  onReject: (reason: string) => void;
}

type Mode = "idle" | "edit" | "reject";

/** Approve / edit (with diff) / reject-with-reason. Nothing leaves the app until one of these is pressed. */
export function DecisionControls({ originalText, busy, approveLabel = "Approve and send", onApprove, onEdit, onReject }: Props) {
  const [mode, setMode] = useState<Mode>("idle");
  const [text, setText] = useState(originalText);
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState("");

  const startEdit = () => {
    setText(originalText);
    setMode("edit");
  };

  if (mode === "edit") {
    const unchanged = text.trim() === originalText.trim();
    return (
      <div className="stack" data-testid="edit-mode">
        <div className="field" style={{ marginBottom: 0 }}>
          <label htmlFor="edit-text">Edit the draft</label>
          <textarea id="edit-text" className="textarea" data-testid="edit-text" value={text} onChange={(e) => setText(e.target.value)} />
        </div>
        <Diff before={originalText} after={text} />
        <div className="btn-row">
          <button
            className="btn primary"
            data-testid="save-edit-btn"
            disabled={busy || unchanged || !text.trim()}
            onClick={() => onEdit(text)}
          >
            Save edit and send
          </button>
          <button className="btn ghost" onClick={() => setMode("idle")} disabled={busy}>
            Cancel
          </button>
        </div>
        {unchanged ? <p className="hint">Change something to enable saving.</p> : null}
      </div>
    );
  }

  if (mode === "reject") {
    return (
      <div className="stack" data-testid="reject-mode">
        <div className="field" style={{ marginBottom: 0 }}>
          <label htmlFor="reject-reason">Why are you rejecting it? (required)</label>
          <textarea
            id="reject-reason"
            className="textarea"
            style={{ minHeight: 90 }}
            data-testid="reject-reason"
            value={reason}
            aria-invalid={reasonError ? true : undefined}
            aria-describedby={reasonError ? "reason-error" : undefined}
            onChange={(e) => {
              setReason(e.target.value);
              if (reasonError) setReasonError("");
            }}
          />
          {reasonError ? (
            <span id="reason-error" className="field-error" role="alert" data-testid="reason-error">
              {reasonError}
            </span>
          ) : (
            <span className="hint">The reason feeds your rejection analytics and, once promoted, your memory.</span>
          )}
        </div>
        <div className="chip-row">
          {QUICK_REASONS.map((r) => (
            <button key={r} type="button" className="btn sm" onClick={() => setReason(r)}>
              {r}
            </button>
          ))}
        </div>
        <div className="btn-row">
          <button
            className="btn danger"
            data-testid="confirm-reject-btn"
            disabled={busy}
            onClick={() => {
              if (!reason.trim()) {
                setReasonError("Enter a reason before rejecting.");
                return;
              }
              onReject(reason.trim());
            }}
          >
            Reject draft
          </button>
          <button className="btn ghost" onClick={() => setMode("idle")} disabled={busy}>
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="decision-bar">
      <button className="btn primary" data-testid="approve-btn" onClick={onApprove} disabled={busy}>
        {busy ? <span className="spinner" aria-hidden="true" /> : null}
        {approveLabel}
      </button>
      <div className="btn-row">
        <button className="btn" data-testid="edit-btn" onClick={startEdit} disabled={busy}>
          Edit
        </button>
        <button className="btn danger" data-testid="reject-btn" onClick={() => setMode("reject")} disabled={busy}>
          Reject
        </button>
      </div>
    </div>
  );
}
