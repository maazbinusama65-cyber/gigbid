r"""Bid graph (one LangGraph thread per job), hand-written StateGraph.

    scout -> [ analyst | risk_assessor | fit_matcher ]  (parallel, via Send)
          -> decision -> skip/watch: END
          -> pricing -> writer -> verifier -> critic --(send back, max 2)--> writer
                                                    \-> compliance -> dry_run -> approval (interrupt)
          -> approve: submit (idempotent) | edit: compliance recheck -> approval | reject: END
"""
from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agent.nodes import approval as ap
from agent.nodes.analyst import analyst
from agent.nodes.common import HALT, Ctx, instrument, route_unless_halted
from agent.nodes.compliance import compliance
from agent.nodes.critic import critic, route_after_critic
from agent.nodes.decision import decide
from agent.nodes.matcher import fit_matcher
from agent.nodes.pricing import pricing
from agent.nodes.risk import risk_assessor
from agent.nodes.scout import scout
from agent.nodes.verifier import verifier
from agent.nodes.writer import writer
from agent.state import BidState

PARALLEL = ("analyst", "risk_assessor", "fit_matcher")


def fan_out(state: dict):
    """Job Analyst, Risk Assessor and Fit Matcher run in parallel (Send API)."""
    if state.get("status") in HALT:
        return END
    return [Send(n, state) for n in PARALLEL]


def build_bid_graph(ctx: Ctx, checkpointer: BaseCheckpointSaver | None = None):
    g = StateGraph(BidState)
    nodes = {
        "scout": scout, "analyst": analyst, "risk_assessor": risk_assessor, "fit_matcher": fit_matcher,
        "decision": decide, "pricing": pricing, "writer": writer, "verifier": verifier, "critic": critic,
        "compliance": compliance, "dry_run": ap.dry_run, "approval": ap.approval, "submit": ap.submit,
    }
    for name, fn in nodes.items():
        g.add_node(name, instrument(name, ctx, fn))
    g.add_edge(START, "scout")
    g.add_conditional_edges("scout", fan_out, [*PARALLEL, END])
    for n in PARALLEL:
        g.add_edge(n, "decision")
    g.add_conditional_edges("decision", route_unless_halted("pricing"), ["pricing", END])
    g.add_conditional_edges("pricing", route_unless_halted("writer"), ["writer", END])
    g.add_conditional_edges("writer", route_unless_halted("verifier"), ["verifier", END])
    g.add_conditional_edges("verifier", route_unless_halted("critic"), ["critic", END])
    g.add_conditional_edges("critic", _critic_route, ["writer", "compliance", END])
    g.add_conditional_edges("compliance", _after_compliance, ["dry_run", "approval", "submit", END])
    g.add_edge("dry_run", "approval")
    g.add_conditional_edges("approval", _after_approval, ["submit", "compliance", END])
    g.add_edge("submit", END)
    return g.compile(checkpointer=checkpointer)


def _critic_route(state: dict) -> str:
    if state.get("status") in HALT:
        return END
    return route_after_critic(state)


def _after_compliance(state: dict) -> str:
    if state.get("status") in HALT:
        return END
    if state.get("approval_status") == "edited":
        v = state.get("compliance_verdict", {})
        if v.get("redactions") or v.get("violations"):
            # compliance changed the user's edit: show the cleaned text for a fresh approval (max 2 loops)
            return "approval" if _edit_loops(state) < 2 else END
        return "submit"          # edit passed compliance untouched: the user's approval stands
    return "dry_run"


def _edit_loops(state: dict) -> int:
    return sum(1 for a in state.get("approvals", []) if a.get("action") == "edit")


def _after_approval(state: dict) -> str:
    r = ap.route_after_approval(state)
    if r == "end":
        return END
    if r == "recheck":
        return "compliance"
    return r
