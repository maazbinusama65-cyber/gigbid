"""Render both LangGraph graphs from code (docs/images/*.mmd, plus .png when mermaid.ink is reachable).

    python -m agent.render_graphs          # writes Mermaid sources (renders natively on GitHub)
"""
from __future__ import annotations

from agent.config_loader import ROOT, load_config
from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph
from agent.llm import LLM
from agent.memory.store import LongTermMemory
from agent.nodes.common import Ctx
from agent.policy import Policy


def _ctx() -> Ctx:
    cfg = load_config(overrides={"models.profile": "stub"})
    return Ctx(cfg=cfg, llm=LLM(cfg, cache=False), tools=None, memory=LongTermMemory(cfg=cfg), policy=Policy())


def main(png: bool = True) -> None:
    out = ROOT / "docs" / "images"
    out.mkdir(parents=True, exist_ok=True)
    ctx = _ctx()
    for name, graph in (("bid_graph", build_bid_graph(ctx)), ("conversation_graph", build_conversation_graph(ctx))):
        g = graph.get_graph()
        (out / f"{name}.mmd").write_text(g.draw_mermaid(), encoding="utf-8")
        print("wrote", out / f"{name}.mmd")
        if png:
            try:
                (out / f"{name}.png").write_bytes(g.draw_mermaid_png())
                print("wrote", out / f"{name}.png")
            except Exception as e:  # offline: the .mmd is the source of truth
                print(f"png skipped ({type(e).__name__}); the .mmd renders on GitHub")


if __name__ == "__main__":
    import sys

    # PNG export goes through the public mermaid.ink service, so it is opt-in (`--png`).
    main(png="--png" in sys.argv)
