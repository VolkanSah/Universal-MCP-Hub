# =============================================================================
# app/providers.py
# 09.03.20026
# LLM + Search Provider Registry + Fallback Chain
# Universal MCP Hub (Sandboxed) - based on PyFundaments Architecture
# Copyright 2026 - Volkan Kücükbudak
# Apache License V. 2 + ESOL 1.1
# Repo: https://github.com/VolkanSah/Universal-MCP-Hub-sandboxed
# =============================================================================
# ARCHITECTURE NOTE:
#   This file lives exclusively in app/ and is ONLY started by app/app.py.
#   NO direct access to fundaments/*, .env, or Guardian (main.py).
#   All config comes from app/.pyfun via app/config.py.
#
# PROVIDER PRINCIPLE:
#   No key = no provider = no tool = no crash.
#   Server always starts, just with fewer providers.
#   Adding a new provider = update .pyfun + add class here. Never touch mcp.py!
#
# FALLBACK CHAIN:
#   Defined in .pyfun per provider via fallback_to field.
#   anthropic → fails → openrouter → fails → RuntimeError
#   Visited set prevents infinite loops.
#
# DEPENDENCY CHAIN (app/* only, no fundaments!):
#   config.py    → parses app/.pyfun — single source of truth
#   providers.py → LLM + Search registry + fallback chain
#   tools.py     → calls providers.llm_complete() / providers.search()
#   mcp.py       → calls providers.list_active_llm() / list_active_search()
# =============================================================================

import os
import logging
import httpx

from . import config
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("providers")


# =============================================================================
# SECTION 1 — Base Provider
# Shared HTTP logic — implemented ONCE, reused by all providers.
# =============================================================================

class BaseProvider:
    """
    Base class for all LLM providers.
    Subclasses only implement complete() — HTTP logic lives here.
    """
    def __init__(self, name: str, cfg: dict):
        self.name     = name
        self.key      = os.getenv(cfg.get("env_key", ""))
        self.base_url = cfg.get("base_url", "")
        self.fallback = cfg.get("fallback_to", "")
        self.timeout  = int(config.get_limits().get("REQUEST_TIMEOUT_SEC", "60"))
        self.model    = cfg.get("default_model", "")

    async def complete(self, prompt: str, model: str, max_tokens: int) -> str:
        """Override in each provider subclass."""
        raise NotImplementedError

    async def _post(self, url: str, headers: dict, payload: dict) -> dict:
        """
        Shared HTTP POST — used by all providers.
        Raises httpx.HTTPStatusError on non-2xx responses.
        """
        safe_url = url.split("?")[0]  # strip query params from logs
        logger.debug(f"POST → {safe_url}")
        async with httpx.AsyncClient() as client:
            r = await client.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()



# =============================================================================
# SECTION 2 — LLM Provider Implementations
# Only the API-specific parsing logic differs per provider.
# =============================================================================

class AnthropicProvider(BaseProvider):
    """Anthropic Claude API — Messages endpoint."""

    async def complete(self, prompt: str, model: str = None, max_tokens: int = 1024) -> str:
        cfg  = config.get_active_llm_providers().get("anthropic", {})
        data = await self._post(
            f"{self.base_url}/messages",
            headers={
                "x-api-key":         self.key,
                "anthropic-version": cfg.get("api_version_header", "2023-06-01"),
                "content-type":      "application/json",
            },
            payload={
                "model":      model or self.model,
                "max_tokens": max_tokens,
                "messages":   [{"role": "user", "content": prompt}],
            },
        )
        return data["content"][0]["text"]


class GeminiProvider(BaseProvider):
    """Google Gemini API — generateContent endpoint."""

    async def complete(self, prompt: str, model: str = None, max_tokens: int = 1024) -> str:
        m = model or self.model
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.base_url}/models/{m}:generateContent",
                params={"key": self.key},
                json={
                    "contents":        [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": max_tokens},
                },
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]


class OpenRouterProvider(BaseProvider):
    """OpenRouter API — OpenAI-compatible chat completions endpoint."""

    async def complete(self, prompt: str, model: str = None, max_tokens: int = 1024) -> str:
        data = await self._post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.key}",
                "HTTP-Referer":  os.getenv("APP_URL", "https://huggingface.co"),
                "content-type":  "application/json",
            },
            payload={
                "model":      model or self.model,
                "max_tokens": max_tokens,
                "messages":   [{"role": "user", "content": prompt}],
            },
        )
        return data["choices"][0]["message"]["content"]


class HuggingFaceProvider(BaseProvider):
    """HuggingFace Inference API — chat completions endpoint."""

    async def complete(self, prompt: str, model: str = None, max_tokens: int = 512) -> str:
        m    = model or self.model
        data = await self._post(
            f"{self.base_url}/{m}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.key}",
                "content-type":  "application/json",
            },
            payload={
                "model":      m,
                "max_tokens": max_tokens,
                "messages":   [{"role": "user", "content": prompt}],
            },
        )
        return data["choices"][0]["message"]["content"]


# =============================================================================
# SECTION 3 — Provider Registry
# Built from .pyfun [LLM_PROVIDERS] at initialize().
# Maps provider names to classes — add new providers here.
# =============================================================================

_PROVIDER_CLASSES = {
    "anthropic":   AnthropicProvider,
    "gemini":      GeminiProvider,
    "openrouter":  OpenRouterProvider,
    "huggingface": HuggingFaceProvider,
}

_registry: dict = {}


def initialize() -> None:
    """
    Build provider registry from .pyfun [LLM_PROVIDERS].
    Called once by mcp.py during startup sequence.
    Skips providers with missing ENV keys — no crash, just fewer tools.
    """
    global _registry
    active = config.get_active_llm_providers()

    for name, cfg in active.items():
        env_key = cfg.get("env_key", "")
        if not env_key or not os.getenv(env_key):
            logger.info(f"Provider '{name}' skipped — ENV key not set.")
            continue
        cls = _PROVIDER_CLASSES.get(name)
        if not cls:
            logger.info(f"Provider '{name}' has no handler yet — skipped.")
            continue
        _registry[name] = cls(name, cfg)
        logger.info(f"Provider registered: {name}")


# =============================================================================
# SECTION 4 — LLM Execution + Fallback Chain
# =============================================================================

async def llm_complete(
    prompt: str,
    provider_name: str = None,
    model: str = None,
    max_tokens: int = 1024,
) -> str:
    """
    Send prompt to LLM provider with automatic fallback chain.
    Fallback order is defined in .pyfun via fallback_to field.
    Raises RuntimeError if all providers in the chain fail.

    Args:
        prompt:        Input text to send to the model.
        provider_name: Provider name override. Defaults to default_provider
                       from .pyfun [TOOL.llm_complete].
        model:         Model name override. Defaults to provider's default_model.
        max_tokens:    Max tokens in response. Default: 1024.

    Returns:
        Model response as plain text string.
    """
    # Default provider from .pyfun [TOOL.llm_complete] → default_provider
    if not provider_name:
        tools_cfg     = config.get_active_tools()
        provider_name = tools_cfg.get("llm_complete", {}).get("default_provider", "anthropic")

    visited = set()
    current = provider_name

    while current and current not in visited:
        visited.add(current)
        provider = _registry.get(current)

        if not provider:
            logger.warning(f"Provider '{current}' not in registry — trying fallback.")
        else:
            try:
                result = await provider.complete(prompt, model, max_tokens)
                logger.info(f"Response from provider: '{current}'")
                return f"[{current}] {result}"
            except Exception as e:
                logger.warning(f"Provider '{current}' failed: {e} — trying fallback.")

        # Next in fallback chain from .pyfun
        cfg     = config.get_active_llm_providers().get(current, {})
        current = cfg.get("fallback_to", "")

    raise RuntimeError("All providers failed — no fallback available.")


# Alias — used internally by tools.py
complete = llm_complete


# =============================================================================
# SECTION 5 — Search Execution
# Search providers not yet implemented — returns placeholder.
# Add BraveProvider, TavilyProvider here when ready.
# =============================================================================

async def search(
    query: str,
    provider_name: str = None,
    max_results: int = 5,
) -> str:
    """
    Search the web via configured search provider.
    Search providers not yet implemented — placeholder until BraveProvider ready.

    Args:
        query:         Search query string.
        provider_name: Provider name override (e.g. 'brave', 'tavily').
        max_results:   Maximum number of results. Default: 5.

    Returns:
        Formatted search results as plain text string.
    """
    # TODO: implement BraveProvider, TavilyProvider
    # Same pattern as LLM providers — add class + register in _SEARCH_REGISTRY
    logger.info(f"web_search called — query: '{query}' — search providers not yet active.")
    return f"Search not yet implemented. Query was: {query}"


# =============================================================================
# SECTION 6 — Registry Helpers
# Used by mcp.py for tool registration decisions.
# =============================================================================

def list_active_llm() -> list:
    """
    List all active LLM provider names.
    Used by mcp.py to decide whether to register llm_complete tool.

    Returns:
        List of active LLM provider name strings.
    """
    return list(_registry.keys())


def list_active_search() -> list:
    """
    List all active search provider names.
    Used by mcp.py to decide whether to register web_search tool.
    Returns empty list until search providers are implemented.

    Returns:
        List of active search provider name strings.
    """
    # TODO: return list(_search_registry.keys()) when search providers are ready
    return []


def get(name: str) -> BaseProvider:
    """
    Get a specific provider instance by name.

    Args:
        name: Provider name (e.g. 'anthropic', 'huggingface').

    Returns:
        Provider instance, or None if not registered.
    """
    return _registry.get(name)


# =============================================================================
# Direct execution guard
# =============================================================================

if __name__ == "__main__":
    print("WARNING: Run via main.py → app.py, not directly.")
