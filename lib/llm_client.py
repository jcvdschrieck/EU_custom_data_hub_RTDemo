"""
Shared LM Studio access — one asyncio semaphore + one HTTP client.

Why this exists:
  LM Studio serializes inference internally. With multiple agents firing
  into it from a single Python process, you'd otherwise get sporadic
  timeouts and head-of-line blocking that look like bugs but are really
  resource contention. Route every LLM call through this module and the
  contention becomes deterministic.

Two entry points:
  acquire_slot()        — async context manager. Wrap ANY call that hits
                          LM Studio (subprocess or in-process) so global
                          concurrency stays bounded by LM_STUDIO_SLOTS.
  LMStudioClient.chat() — in-process HTTP client for new agents.
                          Already acquires the slot internally.

Configuration (env first, then vat_fraud_detection/.env, then defaults):
  LM_STUDIO_BASE_URL    default http://localhost:1234/v1
  LM_STUDIO_MODEL       default ""  (some endpoints accept the empty model)
  LM_STUDIO_SLOTS       default 1   (raise only if LM Studio is configured
                                     for true parallel slots, e.g. multiple
                                     models loaded simultaneously)
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx


# ── Config resolution ────────────────────────────────────────────────────────

_VFD_DIR = Path(__file__).parent.parent / "vat_fraud_detection"


def _load_dotenv(path: Path) -> dict[str, str]:
    """Tiny .env parser. Does NOT override values already in os.environ."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, rest = line.partition("=")
        value = rest.split(" #")[0].split("\t#")[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        out[key.strip()] = value


    return out


_dotenv = _load_dotenv(_VFD_DIR / ".env")

LM_STUDIO_BASE_URL: str = (
    os.environ.get("LM_STUDIO_BASE_URL")
    or _dotenv.get("LM_STUDIO_BASE_URL")
    or "http://localhost:1234/v1"
)
LM_STUDIO_MODEL: str = (
    os.environ.get("LM_STUDIO_MODEL")
    or _dotenv.get("LM_STUDIO_MODEL")
    or ""
)
LM_STUDIO_SLOTS: int = int(os.environ.get("LM_STUDIO_SLOTS", "1"))


# ── Global semaphore ─────────────────────────────────────────────────────────
# Lazily initialised so it binds to the running event loop.

_sem: asyncio.Semaphore | None = None


def _get_sem() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(LM_STUDIO_SLOTS)
    return _sem


@asynccontextmanager
async def acquire_slot():
    """Acquire the shared LM Studio inference slot. Use around any call that
    hits LM Studio — including legacy subprocess agents — so all callers
    queue against the same semaphore."""
    sem = _get_sem()
    async with sem:
        yield


def slot_status() -> dict:
    """Snapshot the semaphore for observability endpoints."""
    sem = _get_sem()
    # asyncio.Semaphore.locked()/_value are stable enough for telemetry.
    return {
        "slots_total":     LM_STUDIO_SLOTS,
        "slots_available": getattr(sem, "_value", None),
        "locked":          sem.locked(),
    }


# ── In-process HTTP client (preferred for NEW agents) ───────────────────────

class LMStudioClient:
    """Thin httpx wrapper around LM Studio's /v1/chat/completions.

    Each call acquires the global slot, so two distinct agents sharing
    one client (or one each) cannot exceed LM_STUDIO_SLOTS concurrent
    inference calls in flight.
    """

    def __init__(
        self,
        base_url: str = LM_STUDIO_BASE_URL,
        model: str | None = None,
        timeout: float = 90.0,
    ) -> None:
        self.base_url = base_url
        self.default_model = model if model is not None else LM_STUDIO_MODEL
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        **kwargs,
    ) -> str:
        """Send a chat completion. Returns the assistant content string."""
        body = {
            "model":       model or self.default_model,
            "messages":    messages,
            "temperature": temperature,
            **kwargs,
        }
        async with acquire_slot():
            r = await self._http.post("/chat/completions", json=body)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]

    async def aclose(self) -> None:
        await self._http.aclose()
