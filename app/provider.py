# app/providers.py
from . import config
import os
import httpx
import logging

logger = logging.getLogger("providers")

# =============================================================================
# Base Provider — gemeinsame Logic EINMAL
# =============================================================================
class BaseProvider:
    def __init__(self, name: str, cfg: dict):
        self.name      = name
        self.key       = os.getenv(cfg.get("env_key", ""))
        self.base_url  = cfg.get("base_url", "")
        self.fallback  = cfg.get("fallback_to", "")
        self.timeout   = int(config.get_limits().get("REQUEST_TIMEOUT_SEC", "60"))
        self.model     = cfg.get("default_model", "")

    async def complete(self, prompt: str, model: str, max_tokens: int) -> str:
        raise NotImplementedError

    async def _post(self, url: str, headers: dict, payload: dict) -> dict:
        """EINMAL — alle Provider nutzen das!"""
        async with httpx.AsyncClient() as client:
            r = await client.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
            r.raise_for_status()
            return r.json()

# =============================================================================
# Provider Implementierungen — nur parse logic verschieden
# =============================================================================
class AnthropicProvider(BaseProvider):
    async def complete(self, prompt: str, model: str = None, max_tokens: int = 1024) -> str:
        cfg = config.get_active_llm_providers().get("anthropic", {})
        data = await self._post(
            f"{self.base_url}/messages",
            headers={
                "x-api-key":           self.key,
                "anthropic-version":   cfg.get("api_version_header", "2023-06-01"),
                "content-type":        "application/json",
            },
            payload={
                "model":      model or self.model,
                "max_tokens": max_tokens,
                "messages":   [{"role": "user", "content": prompt}],
            }
        )
        return data["content"][0]["text"]


class GeminiProvider(BaseProvider):
    async def complete(self, prompt: str, model: str = None, max_tokens: int = 1024) -> str:
        m = model or self.model
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.base_url}/models/{m}:generateContent",
                params={"key": self.key},
                json={
                    "contents":       [{"parts": [{"text": prompt}]}],
                    "generationConfig":{"maxOutputTokens": max_tokens},
                },
                timeout=self.timeout
            )
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]


class OpenRouterProvider(BaseProvider):
    async def complete(self, prompt: str, model: str = None, max_tokens: int = 1024) -> str:
        data = await self._post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.key}",
                "HTTP-Referer":  os.getenv("APP_URL", "https://huggingface.co"),
                "content-type":  "application/json",
            },
            payload={
                "model":    model or self.model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
        )
        return data["choices"][0]["message"]["content"]


class HuggingFaceProvider(BaseProvider):
    async def complete(self, prompt: str, model: str = None, max_tokens: int = 512) -> str:
        m = model or self.model
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
            }
        )
        return data["choices"][0]["message"]["content"]


# =============================================================================
# Provider Registry — gebaut aus .pyfun
# =============================================================================
_PROVIDER_CLASSES = {
    "anthropic":   AnthropicProvider,
    "gemini":      GeminiProvider,
    "openrouter":  OpenRouterProvider,
    "huggingface": HuggingFaceProvider,
}

_registry: dict = {}

def initialize() -> None:
    """Build provider registry from .pyfun — called by app.py"""
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


async def complete(
    prompt: str,
    provider_name: str = None,
    model: str = None,
    max_tokens: int = 1024
) -> str:
    """
    Complete with fallback chain from .pyfun.
    anthropic → fails → openrouter → fails → error
    """
    # default provider aus [TOOL.llm_complete] → default_provider
    if not provider_name:
        tools = config.get_active_tools()
        provider_name = tools.get("llm_complete", {}).get("default_provider", "anthropic")

    visited = set()
    current = provider_name

    while current and current not in visited:
        visited.add(current)
        provider = _registry.get(current)

        if not provider:
            logger.warning(f"Provider '{current}' not in registry — trying fallback.")
        else:
            try:
                return await provider.complete(prompt, model, max_tokens)
            except Exception as e:
                logger.warning(f"Provider '{current}' failed: {e} — trying fallback.")

        # Fallback aus .pyfun
        cfg = config.get_active_llm_providers().get(current, {})
        current = cfg.get("fallback_to", "")

    raise RuntimeError("All providers failed — no fallback available.")


def get(name: str) -> BaseProvider:
    """Get a specific provider by name."""
    return _registry.get(name)


def list_active() -> list:
    """List all active provider names."""
    return list(_registry.keys())
