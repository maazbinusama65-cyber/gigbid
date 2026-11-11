"""LLM layer: per-node model routing from config, fallback, retries, caching, usage/cost tracking.

Providers: any OpenAI-compatible endpoint (Groq, OpenRouter, Together, Ollama, vLLM) and `stub`
(deterministic offline mode, where nodes fall back to their heuristic implementation).
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from agent.config_loader import ROOT, Config, load_config
from agent.guardrails import mask_pii

log = logging.getLogger("gigbid.llm")


class LLMUnavailable(RuntimeError):
    """All models for a node failed (after retries and fallback)."""


@dataclass
class LLMResult:
    text: str = ""
    parsed: Any = None
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    fallback_used: bool = False
    cached: bool = False
    stub: bool = False


@dataclass
class NodeUsage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    cached_calls: int = 0


class UsageTracker:
    """Per-run token/cost/latency accounting by node (R8)."""

    def __init__(self) -> None:
        self.by_node: dict[str, NodeUsage] = {}
        self._lock = threading.Lock()

    def add(self, node: str, r: LLMResult) -> None:
        with self._lock:
            u = self.by_node.setdefault(node, NodeUsage())
            u.calls += 1
            u.prompt_tokens += r.prompt_tokens
            u.completion_tokens += r.completion_tokens
            u.cost_usd += r.cost_usd
            u.latency_s += r.latency_s
            u.cached_calls += int(r.cached)

    @property
    def total_tokens(self) -> int:
        return sum(u.prompt_tokens + u.completion_tokens for u in self.by_node.values())

    @property
    def total_cost(self) -> float:
        return sum(u.cost_usd for u in self.by_node.values())

    def snapshot(self) -> dict:
        return {
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost, 6),
            "by_node": {
                k: {**vars(v), "cost_usd": round(v.cost_usd, 6), "latency_s": round(v.latency_s, 3)}
                for k, v in self.by_node.items()
            },
        }


_current_tracker: contextvars.ContextVar[UsageTracker | None] = contextvars.ContextVar(
    "gigbid_usage", default=None
)


def set_tracker(t: UsageTracker | None):
    return _current_tracker.set(t)


def reset_tracker(token) -> None:
    try:
        _current_tracker.reset(token)
    except (ValueError, LookupError):  # token from another context (parallel branches)
        _current_tracker.set(None)


class _Cache:
    """On-disk response cache: cuts cost and makes eval reruns reproducible (E5 optimisation)."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("create table if not exists c (k text primary key, v text)")
        self._lock = threading.Lock()

    def get(self, k: str) -> dict | None:
        with self._lock:
            row = self._db.execute("select v from c where k=?", (k,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, k: str, v: dict) -> None:
        with self._lock:
            self._db.execute("insert or replace into c values (?,?)", (k, json.dumps(v)))
            self._db.commit()


_THINK = re.compile(r"<think>.*?</think>", re.S)


def _extract_json(text: str) -> Any:
    text = _THINK.sub("", text).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
        if start < 0:
            raise
        opener = text[start]
        closer = "}" if opener == "{" else "]"
        end = text.rfind(closer)
        return json.loads(text[start : end + 1])


class LLM:
    """Config-driven client. Never names a model in code: `node` -> config."""

    def __init__(self, cfg: Config | None = None, profile: str | None = None, cache: bool = True):
        self.cfg = cfg or load_config()
        self.profile_name = profile or self.cfg.profile
        prof = self.cfg["models"]["profiles"][self.profile_name]
        self.profile = prof
        self.provider = prof.get("provider", "stub")
        self.base_url = os.getenv("LLM_BASE_URL") or prof.get("base_url", "")
        self.api_key = os.getenv(prof.get("api_key_env", "")) if prof.get("api_key_env") else None
        self.nodes = prof.get("nodes", {})
        self.prices = prof.get("pricing_usd_per_mtok", {})
        self.tpm = int(prof.get("tokens_per_minute", 5500))
        self._window: list[tuple[float, int]] = []
        self._sem = asyncio.Semaphore(int(prof.get("concurrency", 2)))
        self._cache = _Cache(ROOT / "data" / "processed" / "llm_cache.sqlite") if cache else None
        self._client: httpx.AsyncClient | None = None

    # -- helpers ---------------------------------------------------------------------------
    @property
    def available(self) -> bool:
        if self.provider == "stub":
            return False
        if self.provider == "ollama":
            return True
        return bool(self.api_key)

    def model_for(self, node: str) -> dict:
        n = self.nodes.get(node) or self.nodes.get("default")
        if not n:
            raise LLMUnavailable(f"no model configured for node '{node}' in profile {self.profile_name}")
        return n

    def _price(self, model: str, pt: int, ct: int) -> float:
        p = self.prices.get(model)
        if not p:
            return 0.0
        return (pt * p[0] + ct * p[1]) / 1_000_000

    async def _throttle(self, est_tokens: int) -> None:
        now = time.monotonic()
        self._window = [(t, n) for t, n in self._window if now - t < 60]
        used = sum(n for _, n in self._window)
        if used + est_tokens > self.tpm and self._window:
            wait = 60 - (now - self._window[0][0]) + 0.2
            await asyncio.sleep(min(max(wait, 0.2), 61))
        self._window.append((time.monotonic(), est_tokens))

    async def _post(self, model: str, messages: list[dict], max_tokens: int, temperature: float,
                    json_mode: bool) -> dict:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(90.0))
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature,
                                "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if "gpt-oss" in model:
            body["reasoning_effort"] = "low"
        if "qwen3" in model:
            body["reasoning_effort"] = "none"
        url = self.base_url.rstrip("/") + "/chat/completions"
        r = await self._client.post(url, headers=headers, json=body)
        if r.status_code == 400 and json_mode:  # model without json mode
            body.pop("response_format", None)
            r = await self._client.post(url, headers=headers, json=body)
        if r.status_code == 400 and "reasoning_effort" in body:
            body.pop("reasoning_effort", None)
            r = await self._client.post(url, headers=headers, json=body)
        if r.status_code == 429 or r.status_code >= 500:
            ra = r.headers.get("retry-after")
            raise _Retry(float(ra) if ra and ra.replace(".", "").isdigit() else None, r.status_code)
        r.raise_for_status()
        return r.json()

    # -- public ----------------------------------------------------------------------------
    async def chat(self, node: str, system: str, user: str, *, schema: type[BaseModel] | None = None,
                   temperature: float = 0.2, max_tokens: int = 900, use_cache: bool = True) -> LLMResult:
        if not self.available:
            return LLMResult(stub=True, model="stub")
        spec = self.model_for(node)
        models = [spec["model"]] + ([spec["fallback"]] if spec.get("fallback") else [])
        sys_text = system
        if schema is not None:
            sys_text += ("\n\nReturn ONLY a JSON object that validates against this JSON schema, "
                         "no prose:\n" + json.dumps(schema.model_json_schema()))
        messages = [{"role": "system", "content": sys_text}, {"role": "user", "content": user}]
        key = hashlib.sha256(json.dumps([models[0], messages, temperature], sort_keys=True).encode()).hexdigest()
        if self._cache and use_cache:
            hit = self._cache.get(key)
            if hit:
                res = LLMResult(**{**hit, "cached": True, "latency_s": 0.0})
                if schema is not None and res.text:
                    res.parsed = schema.model_validate(_extract_json(res.text))
                self._track(node, res)
                return res
        last_err: Exception | None = None
        for mi, model in enumerate(models):
            for attempt in range(4):
                try:
                    async with self._sem:
                        await self._throttle(sum(len(m["content"]) for m in messages) // 3 + max_tokens // 2)
                        t0 = time.monotonic()
                        data = await self._post(model, messages, max_tokens, temperature, schema is not None)
                        dt = time.monotonic() - t0
                    text = _THINK.sub("", data["choices"][0]["message"].get("content") or "").strip()
                    usage = data.get("usage", {})
                    pt, ct = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
                    res = LLMResult(text=text, model=model, prompt_tokens=pt, completion_tokens=ct,
                                    cost_usd=self._price(model, pt, ct), latency_s=dt, fallback_used=mi > 0)
                    if schema is not None:
                        try:
                            res.parsed = schema.model_validate(_extract_json(text))
                        except (ValueError, ValidationError) as e:  # repair once by retrying
                            last_err = e
                            if attempt < 1:
                                messages = messages + [{"role": "user", "content": "Invalid JSON. Reply with ONLY valid JSON for the schema."}]
                                continue
                            raise
                    if self._cache and use_cache:
                        self._cache.put(key, {k: v for k, v in vars(res).items() if k not in ("parsed", "cached")})
                    self._track(node, res)
                    log.debug("llm node=%s model=%s tokens=%s+%s", node, model, pt, ct)
                    return res
                except _Retry as e:
                    last_err = e
                    await asyncio.sleep(min(e.retry_after or (1.5 * (2 ** attempt)), 45))
                except (httpx.TransportError, httpx.HTTPStatusError) as e:
                    last_err = e
                    await asyncio.sleep(1.0 * (attempt + 1))
                except (ValueError, ValidationError) as e:
                    last_err = e
                    break
            log.warning("model %s failed for node %s: %s", model, node, mask_pii(str(last_err)))
        raise LLMUnavailable(f"node {node}: {last_err}")

    def _track(self, node: str, res: LLMResult) -> None:
        t = _current_tracker.get()
        if t is not None:
            t.add(node, res)

    async def aclose(self) -> None:
        if self._client:
            await self._client.aclose()


class _Retry(Exception):
    def __init__(self, retry_after: float | None, status: int):
        super().__init__(f"retryable {status}")
        self.retry_after = retry_after
        self.status = status

