import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from sentinel.config import settings


# Approximate per-1M token pricing (USD) for observability cost estimation
MODEL_PRICING_PER_1M = {
    "gemini-3.5-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-3.8-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
}


class LocalTelemetryCallbackHandler(BaseCallbackHandler):
    """
    Production-grade local LLMOps telemetry callback handler.
    Captures latency, token consumption, model routing, and estimated cost per LLM invocation,
    and writes structured JSONL trace logs even when external Langfuse keys are not configured.
    """

    def __init__(self, project_id: str = "sentinel-run", trace_file: Optional[Path] = None):
        super().__init__()
        self.project_id = project_id
        self.trace_file = trace_file or Path("logs/traces.jsonl")
        self._start_times: Dict[UUID, float] = {}
        self._models: Dict[UUID, str] = {}

        self.llm_calls: int = 0
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0
        self.total_latency_seconds: float = 0.0
        self.errors: int = 0
        self.events: List[Dict[str, Any]] = []

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self._start_times[run_id] = time.perf_counter()
        invocation_params = kwargs.get("invocation_params", {})
        model_name = (
            invocation_params.get("model")
            or invocation_params.get("model_name")
            or serialized.get("kwargs", {}).get("model")
            or settings.model_name
            or "unknown"
        )
        self._models[run_id] = str(model_name)

    def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[Any]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self.on_llm_start(serialized, [], run_id=run_id, **kwargs)

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        start = self._start_times.pop(run_id, None)
        model_name = self._models.pop(run_id, settings.model_name or "unknown")
        latency_s = round(time.perf_counter() - start, 3) if start else 0.0

        in_tok = 0
        out_tok = 0
        tot_tok = 0

        # 1. Extract from LangChain AIMessage.usage_metadata (Gemini, OpenAI, Anthropic modern SDKs)
        for gen_list in response.generations:
            for gen in gen_list:
                msg = getattr(gen, "message", None)
                usage = getattr(msg, "usage_metadata", None) if msg else None
                if isinstance(usage, dict):
                    in_tok += int(usage.get("input_tokens", 0) or 0)
                    out_tok += int(usage.get("output_tokens", 0) or 0)
                    tot_tok += int(usage.get("total_tokens", 0) or 0)

        # 2. Fallback to llm_output.token_usage
        if tot_tok == 0 and response.llm_output:
            token_usage = response.llm_output.get("token_usage") or response.llm_output.get("usage_metadata") or {}
            in_tok = int(token_usage.get("prompt_tokens", token_usage.get("input_tokens", 0)) or 0)
            out_tok = int(token_usage.get("completion_tokens", token_usage.get("output_tokens", 0)) or 0)
            tot_tok = int(token_usage.get("total_tokens", in_tok + out_tok) or 0)

        if tot_tok == 0:
            tot_tok = in_tok + out_tok

        self.llm_calls += 1
        self.prompt_tokens += in_tok
        self.completion_tokens += out_tok
        self.total_tokens += tot_tok
        self.total_latency_seconds = round(self.total_latency_seconds + latency_s, 3)

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "project_id": self.project_id,
            "run_id": str(run_id),
            "model": model_name,
            "status": "ok",
            "latency_seconds": latency_s,
            "prompt_tokens": in_tok,
            "completion_tokens": out_tok,
            "total_tokens": tot_tok,
        }
        self.events.append(event)
        self._persist_event(event)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        start = self._start_times.pop(run_id, None)
        model_name = self._models.pop(run_id, settings.model_name or "unknown")
        latency_s = round(time.perf_counter() - start, 3) if start else 0.0
        self.errors += 1

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "project_id": self.project_id,
            "run_id": str(run_id),
            "model": model_name,
            "status": "error",
            "latency_seconds": latency_s,
            "error": str(error),
        }
        self.events.append(event)
        self._persist_event(event)

    def _persist_event(self, event: Dict[str, Any]) -> None:
        try:
            self.trace_file.parent.mkdir(parents=True, exist_ok=True)
            with self.trace_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except Exception:
            pass

    def estimate_cost_usd(self) -> float:
        total_cost = 0.0
        for ev in self.events:
            if ev.get("status") != "ok":
                continue
            model = str(ev.get("model", "")).lower()
            pricing = {"input": 0.10, "output": 0.40}
            for key, rates in MODEL_PRICING_PER_1M.items():
                if key in model:
                    pricing = rates
                    break
            in_cost = (ev.get("prompt_tokens", 0) / 1_000_000) * pricing["input"]
            out_cost = (ev.get("completion_tokens", 0) / 1_000_000) * pricing["output"]
            total_cost += in_cost + out_cost
        return round(total_cost, 6)

    def get_summary(self) -> Dict[str, Any]:
        return {
            "llm_calls": self.llm_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "total_latency_seconds": self.total_latency_seconds,
            "errors": self.errors,
            "estimated_cost_usd": self.estimate_cost_usd(),
            "trace_log_path": str(self.trace_file),
        }


def get_langfuse_callback_handler() -> Optional[Any]:
    """
    Returns a configured Langfuse CallbackHandler (Langfuse v5+ compatible)
    when credentials are configured in settings or environment variables.
    Gracefully falls back to None if unconfigured.
    """
    public_key = settings.langfuse_public_key or os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = settings.langfuse_secret_key or os.getenv("LANGFUSE_SECRET_KEY")
    host = settings.langfuse_host or os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        return None

    try:
        # Ensure environment variables are populated for Langfuse v5 OTEL singleton
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", public_key)
        os.environ.setdefault("LANGFUSE_SECRET_KEY", secret_key)
        os.environ.setdefault("LANGFUSE_HOST", host)

        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler

        Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        return CallbackHandler(public_key=public_key)
    except ImportError:
        try:
            from langfuse.callback import CallbackHandler as LegacyHandler
            return LegacyHandler(public_key=public_key, secret_key=secret_key, host=host)
        except Exception:
            return None
    except Exception:
        return None


def get_run_callbacks(project_id: str = "sentinel-run") -> Tuple[List[BaseCallbackHandler], LocalTelemetryCallbackHandler]:
    """
    Creates the full observability callback stack for a SentinelAI workflow run:
    - Always attaches LocalTelemetryCallbackHandler for token/latency/cost tracking
    - Conditionally attaches Langfuse CallbackHandler if keys are configured
    """
    local_telemetry = LocalTelemetryCallbackHandler(project_id=project_id)
    callbacks: List[BaseCallbackHandler] = [local_telemetry]

    langfuse_cb = get_langfuse_callback_handler()
    if langfuse_cb is not None:
        callbacks.append(langfuse_cb)

    return callbacks, local_telemetry
