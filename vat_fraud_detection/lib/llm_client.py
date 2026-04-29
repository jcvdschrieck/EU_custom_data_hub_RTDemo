"""Provider-agnostic LLM client for the VAT Fraud Detection agent.

The fraud-detection pipeline needs a small, fixed surface — given a
system prompt, a list of `{"role": ..., "content": ...}` messages,
a model identifier, max tokens and temperature, return the assistant's
text content. This module hides the provider differences behind a
single `chat(...)` call so the rest of the codebase doesn't care
whether we're talking to a local LM Studio server or to a cloud API.

Provider selected by the `LLM_PROVIDER` env var:
  lmstudio   — local LM Studio (OpenAI-compatible). Default. No key.
  openai     — OpenAI cloud. Requires OPENAI_API_KEY.
  anthropic  — Anthropic Claude. Requires ANTHROPIC_API_KEY.
  azure      — Azure-hosted OpenAI. Requires AZURE_OPENAI_API_KEY,
               AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT.

Generic env vars (used as fallbacks across providers):
  LLM_MODEL        — default model identifier (provider-specific format)
  LLM_API_KEY      — used if no provider-specific key is set
  LLM_BASE_URL     — endpoint override (e.g. for self-hosted proxies)

Back-compat: when LLM_PROVIDER is unset, behaves exactly like the
old LM Studio code path (LM_STUDIO_BASE_URL / LM_STUDIO_MODEL).
"""
from __future__ import annotations

import os
from typing import Protocol


# ── Public interface ────────────────────────────────────────────────────

class LLMClient(Protocol):
    """Minimum surface every provider adapter exposes."""

    def chat(self, *, messages: list[dict],
             model: str | None = None,
             max_tokens: int = 1024,
             temperature: float = 0.0,
             system: str | None = None) -> str: ...


# ── Adapters ────────────────────────────────────────────────────────────

class LMStudioAdapter:
    """LM Studio's local server. OpenAI-compatible — same shape as
    OpenAIAdapter, but with the no-auth `api_key="lm-studio"` placeholder
    and a guard around the system role: many Mistral chat templates
    loaded in LM Studio reject `role="system"`, so we merge the system
    text into the first user turn (legacy behaviour preserved)."""

    def __init__(self, base_url: str, model_default: str):
        self.base_url = base_url
        self.model_default = model_default
        self._client = None

    def _lazy(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(base_url=self.base_url,
                                   api_key="lm-studio")
        return self._client

    def chat(self, *, messages, model=None, max_tokens=1024,
             temperature=0.0, system=None) -> str:
        msgs = list(messages)
        if system:
            # Merge into the first user turn for Mistral-template safety.
            if msgs and msgs[0].get("role") == "user":
                msgs[0] = {
                    "role": "user",
                    "content": f"{system}\n\n-----\n\n{msgs[0]['content']}",
                }
            else:
                msgs.insert(0, {"role": "user", "content": system})
        resp = self._lazy().chat.completions.create(
            model=model or self.model_default,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip()


class OpenAIAdapter:
    """OpenAI cloud (api.openai.com) — or any OpenAI-compatible endpoint
    when `base_url` is overridden (e.g. Together, Groq, Mistral cloud)."""

    def __init__(self, api_key: str, base_url: str | None = None,
                 model_default: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.base_url = base_url
        self.model_default = model_default
        self._client = None

    def _lazy(self):
        if self._client is None:
            from openai import OpenAI
            kwargs: dict = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def chat(self, *, messages, model=None, max_tokens=1024,
             temperature=0.0, system=None) -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) \
                + list(messages)
        resp = self._lazy().chat.completions.create(
            model=model or self.model_default,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip()


class AnthropicAdapter:
    """Anthropic Claude. Their API uses a top-level `system` field
    (rather than a system message inside `messages`) so the adapter
    handles the conversion."""

    def __init__(self, api_key: str,
                 model_default: str = "claude-sonnet-4-6"):
        self.api_key = api_key
        self.model_default = model_default
        self._client = None

    def _lazy(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def chat(self, *, messages, model=None, max_tokens=1024,
             temperature=0.0, system=None) -> str:
        kwargs: dict = {
            "model": model or self.model_default,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": list(messages),
        }
        if system:
            kwargs["system"] = system
        resp = self._lazy().messages.create(**kwargs)
        # `resp.content` is a list of content blocks; the demo only
        # ever asks for plain-text output, so concatenating any text
        # blocks is sufficient.
        parts: list[str] = []
        for block in resp.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts).strip()


class AzureOpenAIAdapter:
    """Azure-hosted OpenAI. Same chat-completions shape as OpenAI but
    the SDK has its own client class and uses a *deployment* name in
    place of a model name."""

    def __init__(self, api_key: str, endpoint: str, deployment: str,
                 api_version: str = "2024-02-15-preview"):
        self.api_key = api_key
        self.endpoint = endpoint
        self.deployment = deployment
        self.api_version = api_version
        self._client = None

    def _lazy(self):
        if self._client is None:
            from openai import AzureOpenAI
            self._client = AzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=self.endpoint,
                api_version=self.api_version,
            )
        return self._client

    def chat(self, *, messages, model=None, max_tokens=1024,
             temperature=0.0, system=None) -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) \
                + list(messages)
        # Azure: pass the deployment as `model`.
        resp = self._lazy().chat.completions.create(
            model=self.deployment,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip()


# ── Factory ─────────────────────────────────────────────────────────────

def get_llm_client() -> LLMClient:
    """Build the adapter from environment variables. Raises a clear
    RuntimeError when the required keys are missing — better to fail
    loud at startup than to fall back silently to "uncertain" later."""
    provider = os.getenv("LLM_PROVIDER", "lmstudio").strip().lower()
    generic_key   = os.getenv("LLM_API_KEY")
    generic_base  = os.getenv("LLM_BASE_URL")
    generic_model = os.getenv("LLM_MODEL")

    if provider == "lmstudio":
        return LMStudioAdapter(
            base_url=(generic_base
                      or os.getenv("LM_STUDIO_BASE_URL",
                                    "http://localhost:1234/v1")),
            model_default=(generic_model
                           or os.getenv("LM_STUDIO_ANALYSIS_MODEL")
                           or os.getenv("LM_STUDIO_MODEL",
                                         "mistralai/mistral-7b-instruct-v0.3")),
        )

    if provider == "openai":
        key = os.getenv("OPENAI_API_KEY") or generic_key
        if not key:
            raise RuntimeError(
                "LLM_PROVIDER=openai requires OPENAI_API_KEY (or LLM_API_KEY).")
        return OpenAIAdapter(
            api_key=key,
            base_url=os.getenv("OPENAI_BASE_URL") or generic_base,
            model_default=generic_model or "gpt-4o-mini",
        )

    if provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY") or generic_key
        if not key:
            raise RuntimeError(
                "LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY (or LLM_API_KEY).")
        return AnthropicAdapter(
            api_key=key,
            model_default=generic_model or "claude-sonnet-4-6",
        )

    if provider == "azure":
        key        = os.getenv("AZURE_OPENAI_API_KEY") or generic_key
        endpoint   = os.getenv("AZURE_OPENAI_ENDPOINT")
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        if not (key and endpoint and deployment):
            raise RuntimeError(
                "LLM_PROVIDER=azure requires AZURE_OPENAI_API_KEY, "
                "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT.")
        return AzureOpenAIAdapter(
            api_key=key, endpoint=endpoint, deployment=deployment,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION",
                                    "2024-02-15-preview"),
        )

    raise RuntimeError(
        f"Unknown LLM_PROVIDER='{provider}'. "
        f"Use one of: lmstudio, openai, anthropic, azure.")


# ── Diagnostic helper ───────────────────────────────────────────────────

def describe_active_provider() -> str:
    """Return a short, log-safe summary of the configured provider —
    useful for printing during install / startup so the user can see
    which path the agent will take. Never includes the API key."""
    provider = os.getenv("LLM_PROVIDER", "lmstudio").strip().lower()
    if provider == "lmstudio":
        url   = os.getenv("LLM_BASE_URL") or os.getenv(
            "LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
        model = (os.getenv("LLM_MODEL")
                 or os.getenv("LM_STUDIO_ANALYSIS_MODEL")
                 or os.getenv("LM_STUDIO_MODEL",
                               "mistralai/mistral-7b-instruct-v0.3"))
        return f"LM Studio @ {url} · model {model}"
    if provider == "openai":
        return (f"OpenAI cloud · model "
                f"{os.getenv('LLM_MODEL', 'gpt-4o-mini')}")
    if provider == "anthropic":
        return (f"Anthropic · model "
                f"{os.getenv('LLM_MODEL', 'claude-sonnet-4-6')}")
    if provider == "azure":
        return (f"Azure OpenAI @ "
                f"{os.getenv('AZURE_OPENAI_ENDPOINT', '?')} · deployment "
                f"{os.getenv('AZURE_OPENAI_DEPLOYMENT', '?')}")
    return f"unknown provider '{provider}'"
