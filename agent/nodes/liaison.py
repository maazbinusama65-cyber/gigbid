"""Client Liaison nodes (conversation graph): read, classify, draft, approve, send."""
from __future__ import annotations

import re

from langgraph.types import interrupt
from pydantic import BaseModel

from agent.guardrails import detect_injection, strip_injection, wrap_untrusted
from agent.handoffs import ApprovalDecision, ApprovalRequest, ComplianceVerdict, IntentResult
from agent.nodes.common import Ctx, first_sentences
from agent.prompts import load_prompt

_INTERVIEW = re.compile(r"\b(interview|call|meet(ing)?|zoom|google meet|availab(le|ility)|schedule|slot|chat live)\b", re.I)
_NEGOTIATE = re.compile(r"\b(rate|price|budget|discount|cheaper|lower|negotiat|offer|quote|cost|\$\s?\d+|\d+\s?(usd|dollars))\b", re.I)


class _LiaisonOut(BaseModel):
    intent: str
    confidence: float = 0.6
    reply: str = ""


def classify_heuristic(text: str, ctx: Ctx) -> IntentResult:
    flags = ctx.policy.scam_flags(text)
    inj = bool(detect_injection(text))
    if set(flags) & {"off_platform_contact", "payment_upfront", "credential_phishing", "unpaid_trial"}:
        return IntentResult(intent="scam_signal", confidence=0.85, injection_detected=inj)
    if _INTERVIEW.search(text):
        return IntentResult(intent="interview_request", confidence=0.75, injection_detected=inj)
    if _NEGOTIATE.search(text):
        return IntentResult(intent="negotiation", confidence=0.7, injection_detected=inj)
    if "?" in text:
        return IntentResult(intent="question", confidence=0.7, injection_detected=inj)
    return IntentResult(intent="other", confidence=0.5, injection_detected=inj)


async def load_messages(state: dict, ctx: Ctx) -> dict:
    res = await ctx.call("client_liaison", "list_messages", {"thread_id": state["marketplace_thread_id"]})
    msgs = res.get("messages", res) if isinstance(res, dict) else res
    client_msgs = [m for m in msgs if m.get("sender") in ("client", "them")]
    if not client_msgs or msgs[-1].get("sender") not in ("client", "them"):
        return {"messages": msgs, "status": "skipped", "status_reason": "no unanswered client message"}
    return {"messages": msgs, "last_message": client_msgs[-1], "status": "running"}


async def classify(state: dict, ctx: Ctx) -> dict:
    text = state["last_message"]["body"]
    intent = classify_heuristic(text, ctx)
    if ctx.use_llm("client_liaison") and intent.intent in ("other", "question") and not intent.injection_detected:
        _, system = load_prompt("client_liaison")
        res = await ctx.llm.chat("client_liaison", system, wrap_untrusted(text, "client message"),
                                 schema=_LiaisonOut, max_tokens=250)
        if res.parsed and res.parsed.intent in IntentResult.model_fields["intent"].annotation.__args__:
            intent = IntentResult(intent=res.parsed.intent, confidence=res.parsed.confidence)
    return {"intent": intent.model_dump()}


async def draft_reply(state: dict, ctx: Ctx) -> dict:
    msg = state["last_message"]["body"]
    intent = state["intent"]["intent"]
    st = state.get("settings", {}) or {}
    safe = strip_injection(msg)
    slots: list[dict] = []
    reply = ""
    if intent == "interview_request":
        res = await ctx.call("client_liaison", "get_free_slots", {"days": 5, "duration_minutes": 30})
        slots = (res.get("slots", res) if isinstance(res, dict) else res)[:3]
        opts = "; ".join(s["start"] if isinstance(s, dict) else str(s) for s in slots)
        reply = f"Thanks for reaching out. I'd be glad to talk. I'm free at: {opts}. Let me know which suits you."
    elif intent == "negotiation":
        floor = st.get("min_project_budget_usd") or 0
        nums = [float(n) for n in re.findall(r"\$?\s?(\d+(?:\.\d+)?)", safe)]
        offered = max(nums) if nums else None
        if offered is not None and floor and offered < floor:
            reply = (f"Thank you for the offer. Given the scope, I can't go below {floor:.0f} USD and still deliver at the "
                     f"quality we discussed. I can narrow the scope to fit a smaller budget if that helps.")
        else:
            reply = "Thanks, that works as a starting point. I can confirm the scope and milestones in writing here on the platform."
    elif intent == "scam_signal":
        reply = ("Thank you for your message. I keep all communication and payment on the platform, so I can't move to "
                 "other channels or work without a funded contract.")
    else:
        res = await ctx.call("client_liaison", "search_evidence", {"requirement": safe[:300], "k": 3,
                             **({"portfolio_id": state["persona_id"]} if state.get("persona_id") else {})})
        items = res.get("items", res) if isinstance(res, dict) else res
        if items:
            reply = f"Good question. {first_sentences(items[0].get('text', ''), 2, 300)} [{items[0]['id']}]"
        else:
            reply = "Good question. I'll check the details and come back with a precise answer."
    if ctx.use_llm("client_liaison") and intent in ("question", "other"):
        _, system = load_prompt("client_liaison")
        res2 = await ctx.llm.chat("client_liaison", system,
                                  wrap_untrusted(safe, "client message") + f"\nEVIDENCE: {reply}\nSLOTS: {slots}\nFLOOR: {st.get('min_project_budget_usd')}",
                                  schema=_LiaisonOut, max_tokens=350, temperature=0.4)
        if res2.parsed and res2.parsed.reply:
            reply = res2.parsed.reply
    cleaned, red = ctx.policy.clean(reply)
    blocked = intent != "scam_signal" and bool(ctx.policy.check(cleaned) and [v for v in ctx.policy.check(cleaned) if v.action == "block" and v.rule_id not in ("min_words",)])
    verdict = ComplianceVerdict(ok=not blocked, blocked=blocked, redactions=red, cleaned_text=cleaned)
    return {"reply_draft": {"text": cleaned, "intent": intent}, "slots": slots, "compliance_verdict": verdict.model_dump()}


async def approve_reply(state: dict, ctx: Ctx) -> dict:
    req = ApprovalRequest(kind="message", thread_id=state["thread_id"], job_id=state.get("job_id"),
                          draft={**state["reply_draft"], "slots": state.get("slots", []),
                                 "client_message": state["last_message"]["body"]},
                          compliance=ComplianceVerdict(**state["compliance_verdict"]))
    dec = ApprovalDecision.model_validate(interrupt(req.model_dump(mode="json")))
    rec = {"action": dec.action, "reason": dec.reason, "kind": "message"}
    if dec.action == "reject":
        return {"approval_status": "rejected", "approvals": [rec], "status": "rejected",
                "status_reason": dec.reason or "rejected by user"}
    if dec.action == "edit" and dec.edited_text:
        orig = state["reply_draft"]["text"]
        ctx.memory.record_edit(state.get("user_id", "anon"), state.get("job_id") or state["thread_id"], orig, dec.edited_text)
        cleaned, red = ctx.policy.clean(dec.edited_text)
        return {"approval_status": "edited", "approvals": [rec | {"redactions": red}],
                "reply_draft": {**state["reply_draft"], "text": cleaned}}
    return {"approval_status": "approved", "approvals": [rec]}


async def send_reply(state: dict, ctx: Ctx) -> dict:
    if state.get("approval_status") not in ("approved", "edited"):
        raise RuntimeError("refusing to send without human approval")
    if state.get("sent"):
        return {"status": "submitted"}
    last_id = state["last_message"].get("message_id", "m")
    sent = await ctx.call("client_liaison", "send_message", {
        "thread_id": state["marketplace_thread_id"], "body": state["reply_draft"]["text"],
        "idempotency_key": f"{state['thread_id']}:{last_id}"})
    extra: dict = {}
    intent = state["intent"]["intent"]
    if intent == "interview_request" and state.get("slots"):
        slot = state["slots"][0]
        hold = await ctx.call("client_liaison", "create_interview_hold", {
            "slot": slot, "client": state["last_message"].get("sender_name", "client"), "job_id": state.get("job_id") or ""})
        extra["hold"] = hold
    stage = {"interview_request": "interview", "negotiation": "replied", "question": "replied"}.get(intent, "replied")
    return {"sent": {"message": sent, **extra}, "pipeline_stage": stage, "status": "submitted"}
