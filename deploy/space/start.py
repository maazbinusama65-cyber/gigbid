"""Container entry point for the single-container demo (Hugging Face Space or any Docker host).

Starts the GigSim stand-in marketplace on localhost, then runs the GigBid API on $PORT. The API also serves the built
web app (GIGBID_STATIC_DIR), so one port is the whole product. The deployed model profile is `stub` (deterministic,
no LLM calls, no API key): the demo shows the workflow, retrieval, safety checks and the approval gate, not LLM prose.

Nothing needs configuring. Optional environment overrides: APP_SECRET_KEY, REVIEWER_EMAIL, REVIEWER_PASSWORD.
"""
from __future__ import annotations

import atexit
import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import yaml

SIM_PORT = 8081
PORT = int(os.environ.get("PORT", "7860"))
RUNTIME = Path(os.environ.get("GIGBID_RUNTIME_DIR", "/tmp/gigbid"))
DEMO_EMAIL = "reviewer@gigbid.demo"
DEMO_PASSWORD = "gigbid-demo"       # public demo credentials, deliberately
SIM_ADVANCE_HOURS = 24 * 75          # move the simulated clock past the last scheduled job so the whole feed is visible


def log(msg: str) -> None:
    print(f"[start] {msg}", flush=True)


def build_environment() -> dict[str, str]:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    from agent.config_loader import load_config

    # A demo served from one process does not need the polite 20 requests/minute marketplace limiter.
    cfg = load_config(overrides={"marketplace.max_requests_per_minute": 3000})
    config_path = RUNTIME / "config.yaml"
    config_path.write_text(yaml.safe_dump(dict(cfg)), encoding="utf-8")
    token = os.environ.get("GIGSIM_API_TOKEN") or secrets.token_hex(16)
    if not os.environ.get("APP_SECRET_KEY"):
        log("APP_SECRET_KEY is not set: generating one for this run (sessions are invalidated on restart)")
    # The demo account is public on purpose (it is shown on the Space page): the deployment runs the offline `stub`
    # model on synthetic data, so there is nothing to protect. Real secrets set on the host still win.
    os.environ.setdefault("REVIEWER_EMAIL", DEMO_EMAIL)
    os.environ.setdefault("REVIEWER_PASSWORD", DEMO_PASSWORD)
    persona = os.environ.get("REVIEWER_PERSONA", "ai_ml")
    return {
        "APP_ENV": "production",
        "APP_SECRET_KEY": os.environ.get("APP_SECRET_KEY") or secrets.token_hex(32),
        "REVIEWER_EMAIL": os.environ["REVIEWER_EMAIL"],
        "REVIEWER_PASSWORD": os.environ["REVIEWER_PASSWORD"],
        "GIGBID_SERVICES": "real",
        "MODEL_PROFILE": os.environ.get("MODEL_PROFILE", "stub"),
        "GIGBID_CONFIG": str(config_path),
        "MARKETPLACE_MODE": "gigsim",
        "GIGSIM_API_TOKEN": token,
        "GIGSIM_PORT": str(SIM_PORT),
        "GIGSIM_BASE_URL": f"http://127.0.0.1:{SIM_PORT}",
        "GIGSIM_STATE_PATH": str(RUNTIME / "gigsim_state.json"),
        "GIGSIM_RATE_LIMIT_RPM": "100000",
        "MARKETPLACE_DEFAULT_USER": persona,
        "MARKETPLACE_STATE_DIR": str(RUNTIME / "mcp_state"),
        "PORTFOLIO_ID": persona,
        "DATABASE_URL": f"sqlite:///{RUNTIME}/api.db",
        "CHECKPOINT_DB": str(RUNTIME / "checkpoints.sqlite"),
        "REAL_STORE_DB": str(RUNTIME / "real_store.sqlite"),
        "HF_HUB_OFFLINE": "1",            # the embedding model is baked into the image
        "GIGBID_STATIC_DIR": os.environ.get("GIGBID_STATIC_DIR", str(Path(__file__).parent / "web_dist")),
    }


def start_simulator(env: dict[str, str]) -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "-m", "gigsim"], env={**os.environ, **env},
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    atexit.register(proc.terminate)
    for _ in range(150):
        if proc.poll() is not None:
            raise RuntimeError("GigSim exited during start-up")
        try:
            if httpx.get(f"http://127.0.0.1:{SIM_PORT}/health", timeout=1).status_code == 200:
                break
        except httpx.TransportError:
            time.sleep(0.2)
    else:
        raise RuntimeError("GigSim did not become healthy")
    headers = {"Authorization": f"Bearer {env['GIGSIM_API_TOKEN']}", "X-Freelancer-Id": env["MARKETPLACE_DEFAULT_USER"]}
    try:
        httpx.post(f"http://127.0.0.1:{SIM_PORT}/v1/sim/tick", json={"steps": SIM_ADVANCE_HOURS}, headers=headers, timeout=30)
    except httpx.HTTPError as exc:                                  # the feed still works, only with fewer jobs visible
        log(f"could not advance the simulator clock: {exc}")
    log(f"GigSim ready on :{SIM_PORT}")
    return proc


def warm_retrieval() -> None:
    """Load the embedding model and the persona indexes now so the first approval is not a 60 s wait."""
    try:
        from rag import config
        from rag.retriever import build_index

        for persona in ("ai_ml", "fullstack", "data_analyst"):
            build_index(persona, personas_dir=config.personas_root(), index_root=config.index_root())
        log("retrieval indexes warm")
    except Exception as exc:  # noqa: BLE001 - warming is an optimisation, never a reason to refuse to start
        log(f"retrieval warm-up skipped: {exc}")


def main() -> None:
    env = build_environment()
    os.environ.update(env)
    start_simulator(env)
    threading.Thread(target=warm_retrieval, daemon=True).start()
    import uvicorn

    log(f"serving on 0.0.0.0:{PORT}")
    uvicorn.run("apps.api.main:app", host="0.0.0.0", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
