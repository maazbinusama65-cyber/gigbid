"""Conversation graph (one thread per client conversation).

    load_messages -> classify -> draft_reply -> approve_reply (interrupt) -> send_reply (idempotent)
"""
from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from agent.nodes import liaison as L
from agent.nodes.common import Ctx, instrument, route_unless_halted
from agent.state import ConversationState


def build_conversation_graph(ctx: Ctx, checkpointer: BaseCheckpointSaver | None = None):
    g = StateGraph(ConversationState)
    for name, fn in {"load_messages": L.load_messages, "classify": L.classify, "draft_reply": L.draft_reply,
                     "approve_reply": L.approve_reply, "send_reply": L.send_reply}.items():
        g.add_node(name, instrument(name, ctx, fn))
    g.add_edge(START, "load_messages")
    g.add_conditional_edges("load_messages", route_unless_halted("classify"), ["classify", END])
    g.add_edge("classify", "draft_reply")
    g.add_conditional_edges("draft_reply", _after_draft, ["approve_reply", END])
    g.add_conditional_edges("approve_reply", _after_approve, ["send_reply", END])
    g.add_edge("send_reply", END)
    return g.compile(checkpointer=checkpointer)


def _after_draft(state: dict) -> str:
    v = state.get("compliance_verdict", {})
    return END if v.get("blocked") else "approve_reply"


def _after_approve(state: dict) -> str:
    return END if state.get("approval_status") == "rejected" else "send_reply"
