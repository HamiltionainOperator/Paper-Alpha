"""OpenRouter client restricted to free models, with budget control and model learning.

Models are discovered from GET /api/v1/models at runtime (nothing is hard-coded) and
filtered by price, modality, context and expiry. Among eligible models, selection uses
Thompson sampling over each model's observed usefulness (valid JSON, and the fraction of
its alpha candidates that pass the static validator), so the engine learns which free
model works best for this task.
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import requests

from ..store import Store
from ..util import console
from .jsonx import extract_json, salvage_list


class LLMError(Exception):
    pass


class BudgetExhausted(LLMError):
    pass


@dataclass
class ModelInfo:
    id: str
    name: str = ""
    context: int = 0
    max_completion: int | None = None
    params: set = field(default_factory=set)
    reasoning: dict | None = None
    expiration: str | None = None


@dataclass
class LLMResult:
    obj: object
    model: str
    raw: str
    usage: dict | None = None
    messages: list | None = None


def _is_free(pricing: dict) -> bool:
    try:
        return float(pricing.get("prompt", 1)) == 0 and float(pricing.get("completion", 1)) == 0
    except (TypeError, ValueError):
        return False


class OpenRouter:
    def __init__(self, cfg, store: Store, api_key: str | None, log=console.print):
        self.cfg = cfg
        self.store = store
        self.key = api_key
        self.log = log
        llm = cfg.section("llm")
        self.base = llm.get("base_url", "https://openrouter.ai/api/v1").rstrip("/")
        self.free_only = llm.get("free_only", True)
        self.min_context = int(llm.get("min_context", 32000))
        self.exclude = [re.compile(p, re.I) for p in llm.get("exclude_patterns", [])]
        self.prefer = [re.compile(p, re.I) for p in llm.get("prefer_patterns", [])]
        self.daily_budget = int(llm.get("daily_request_budget", 45))
        self.per_minute = int(llm.get("per_minute_limit", 15))
        self.temperature = float(llm.get("temperature", 0.6))
        self.max_tokens = int(llm.get("max_tokens", 12000))
        self.effort = str(llm.get("reasoning_effort", "medium")).lower()
        self.timeout = float(llm.get("timeout_s", 240))
        self.title = llm.get("app_title", "paper2alpha")
        self.cooldown: dict[str, float] = {}

    # -- model discovery -------------------------------------------------------
    def models(self, refresh: bool = False) -> list[ModelInfo]:
        raw = None if refresh else self.store.kv_get("openrouter_models", max_age_s=6 * 3600)
        if raw is None:
            r = requests.get(f"{self.base}/models", timeout=60)
            r.raise_for_status()
            raw = r.json().get("data", [])
            self.store.kv_set("openrouter_models", raw)
        today = date.today().isoformat()
        blocked = self.store.kv_get("openrouter_blocked") or {}
        out = []
        for m in raw:
            mid = m.get("id", "")
            if mid in blocked:
                continue
            arch = m.get("architecture") or {}
            outputs = set(arch.get("output_modalities") or ["text"])
            inputs = set(arch.get("input_modalities") or ["text"])
            ctx = int(m.get("context_length") or (m.get("top_provider") or {}).get("context_length") or 0)
            if self.free_only and not _is_free(m.get("pricing") or {}):
                continue
            if outputs != {"text"} or "text" not in inputs:
                continue
            if ctx and ctx < self.min_context:
                continue
            exp = m.get("expiration_date")
            if exp and str(exp) < today:
                continue
            if any(p.search(mid) or p.search(m.get("name", "")) for p in self.exclude):
                continue
            out.append(ModelInfo(id=mid, name=m.get("name", mid), context=ctx or 128000,
                                 max_completion=(m.get("top_provider") or {}).get("max_completion_tokens"),
                                 params=set(m.get("supported_parameters") or []), reasoning=m.get("reasoning"),
                                 expiration=exp))
        return out

    def _prior(self, m: ModelInfo) -> tuple[float, float]:
        a, b = 1.0, 1.0
        if {"structured_outputs", "response_format"} & m.params:
            a += 0.5
        size = re.search(r"(\d+(?:\.\d+)?)b(?:\b|-)", m.id.lower())
        if size:
            billions = float(size.group(1))
            if billions < 10:
                b += 1.5
            elif billions >= 100:
                a += 0.5
        if m.context >= 200_000:
            a += 0.25
        return a, b

    def ranked(self, min_context: int = 0) -> list[ModelInfo]:
        now = time.time()
        ms = [m for m in self.models() if m.context >= min_context and self.cooldown.get(m.id, 0) <= now]
        by_id = {m.id: m for p in reversed(self.prefer) for m in ms if p.search(m.id)}
        preferred = [by_id[i] for i in dict.fromkeys(m.id for p in self.prefer for m in ms if p.search(m.id))]
        rest = [m for m in ms if m not in preferred]
        scored = []
        for m in rest:
            st = self.store.model_stat(m.id)
            a0, b0 = self._prior(m)
            scored.append((random.betavariate(a0 + st["alpha"], b0 + st["beta"]), m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return preferred + [m for _, m in scored]

    def scoreboard(self) -> list[dict]:
        rows = []
        for m in self.models():
            st = self.store.model_stat(m.id)
            a0, b0 = self._prior(m)
            a, b = a0 + st["alpha"], b0 + st["beta"]
            rows.append({"model": m.id, "context": m.context, "mean": a / (a + b), "calls": st["calls"],
                         "failures": st["failures"], "last_error": st.get("last_error")})
        return sorted(rows, key=lambda r: r["mean"], reverse=True)

    # -- budget -------------------------------------------------------------------
    def budget_day_start(self) -> float:
        """Start of the provider's quota day (OpenRouter resets free-model limits at 00:00 UTC, not local midnight)."""
        tz = timezone(timedelta(hours=float(self.cfg.get("llm.budget_reset_utc_offset_h", 0) or 0)))
        return datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def budget_used(self) -> int:
        return self.store.llm_calls_since(self.budget_day_start())

    def budget_left(self) -> int:
        return self.daily_budget - self.budget_used()

    def _wait_for_budget(self) -> None:
        if self.budget_left() <= 0:
            raise BudgetExhausted(f"daily LLM request budget ({self.daily_budget}) used; resets at 00:00 UTC "
                                  "(raise llm.daily_request_budget if your OpenRouter tier allows more)")
        while self.store.llm_calls_since(time.time() - 60) >= self.per_minute:
            time.sleep(5)

    def block(self, model: str, reason: str) -> None:
        blocked = self.store.kv_get("openrouter_blocked") or {}
        blocked[model] = reason
        self.store.kv_set("openrouter_blocked", blocked)
        self.log(f"  [dim]{model} is not usable with this key; skipping it from now on[/dim]")

    def reward(self, model: str, value: float) -> None:
        self.store.update_model_stat(model, max(0.0, min(1.0, value)))

    # -- chat ---------------------------------------------------------------------
    def chat_json(self, messages: list[dict], purpose: str, schema: dict | None = None, min_context: int = 0,
                  max_attempts: int = 3, temperature: float | None = None, auto_reward: bool = True,
                  check=None) -> LLMResult:
        if not self.key:
            raise LLMError("OPENROUTER_API_KEY is not set (put it in .env)")
        attempts, tries, errors = 0, 0, []
        for m in self.ranked(min_context):
            if attempts >= max_attempts or tries >= max_attempts * 3:
                break
            optional = True
            while True:
                self._wait_for_budget()
                attempts += 1
                tries += 1
                body = {"model": m.id, "messages": messages,
                        "temperature": self.temperature if temperature is None else temperature,
                        "max_tokens": min(self.max_tokens, m.max_completion or self.max_tokens)}
                if optional:
                    if schema and "structured_outputs" in m.params:
                        body["response_format"] = {"type": "json_schema",
                                                   "json_schema": {"name": purpose, "strict": False, "schema": schema}}
                    elif "response_format" in m.params:
                        body["response_format"] = {"type": "json_object"}
                    if self.effort != "none" and "reasoning" in m.params:
                        body["reasoning"] = {"effort": self.effort, "exclude": True}
                t0 = time.time()
                err, data = None, None
                try:
                    r = requests.post(f"{self.base}/chat/completions", json=body, timeout=self.timeout,
                                      headers={"Authorization": f"Bearer {self.key}", "X-Title": self.title})
                    status = r.status_code
                    text = r.text
                    if status < 400:
                        data = r.json()
                except (requests.RequestException, ValueError) as e:
                    status, text = 0, str(e)
                latency = time.time() - t0
                if data is not None and isinstance(data.get("error"), dict):
                    status, text = int(data["error"].get("code") or 502), str(data["error"].get("message"))
                    data = None
                if data is None:
                    err = f"HTTP {status}: {text[:240]}"
                    self.store.record_llm_call(m.id, purpose, False, 0.0, err, None, latency)
                    errors.append(f"{m.id}: {err}")
                    if status == 429:
                        if re.search(r"per[- ]day|daily", text, re.I):
                            raise BudgetExhausted(f"OpenRouter daily free-model limit reached: {text[:200]}")
                        self.cooldown[m.id] = time.time() + 90
                        attempts -= 1  # transient upstream limit: try another model without using up an attempt
                        break
                    if status in (403, 404) and re.search(r"only available|not available|no endpoints|not found", text, re.I):
                        self.block(m.id, text[:200])  # permanent for this key: never pick it again
                        attempts -= 1
                        break
                    if status == 400 and optional:
                        optional = False  # retry once without response_format / reasoning
                        continue
                    self.store.update_model_stat(m.id, 0.0, err)
                    break
                msg = (data.get("choices") or [{}])[0].get("message") or {}
                content = msg.get("content") or ""
                if isinstance(content, list):
                    content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
                obj = extract_json(content)
                problem = None if obj is not None else "response was not valid JSON"
                if problem is None and check is not None:
                    problem = check(obj)
                if problem:  # e.g. output cut off at max_tokens: keep the complete items
                    salvaged = salvage_list(content)
                    if salvaged is not None and (check is None or check(salvaged) is None):
                        obj, problem = salvaged, None
                        self.log(f"  [dim]{m.id}: response was truncated; salvaged "
                                 f"{len(next(iter(salvaged.values())))} complete item(s)[/dim]")
                if problem:
                    self.store.record_llm_call(m.id, purpose, False, 0.0, problem, data.get("usage"), latency)
                    self.store.update_model_stat(m.id, 0.0, problem)
                    errors.append(f"{m.id}: {problem}")
                    break
                self.store.record_llm_call(m.id, purpose, True, 1.0, None, data.get("usage"), latency)
                if auto_reward:
                    self.reward(m.id, 1.0)
                self.log(f"  [dim]LLM {purpose}: {m.id} ({latency:.0f}s, budget left {self.budget_left()})[/dim]")
                return LLMResult(obj=obj, model=m.id, raw=content, usage=data.get("usage"),
                                 messages=messages + [{"role": "assistant", "content": content}])
        raise LLMError("no free model produced a usable answer: " + " | ".join(errors[-4:]))
