# =============================================================================
# app/mcp.py
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
# TOOL REGISTRATION PRINCIPLE:
#   Tools are only registered if their required ENV key exists.
#   No key = no tool = no crash. Server always starts, just with fewer tools.
#   ENV key NAMES come from app/.pyfun — values are never touched here.
# =============================================================================

import asyncio
import logging
import os
from typing import Dict, Any

from . import config as app_config  # reads app/.pyfun — only config source for app/*

logger = logging.getLogger('mcp')


async def start_mcp() -> None:
    """
    Main entry point for the MCP Hub.
    Called by app/app.py in its own thread/event loop.
    Reads all config from app/.pyfun via app/config.py.
    NO fundaments passed in — sandboxed.
    """
    logger.info("MCP Hub starting...")

    # --- Load transport config from app/.pyfun [HUB] ---
    hub_cfg   = app_config.get_hub()
    transport = os.getenv("MCP_TRANSPORT", hub_cfg.get("HUB_TRANSPORT", "stdio")).lower()
    host      = os.getenv("HOST", hub_cfg.get("HUB_HOST", "0.0.0.0"))
    port      = int(os.getenv("PORT", hub_cfg.get("HUB_PORT", "7860")))

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        logger.critical("FastMCP not installed. Run: pip install mcp")
        raise

    mcp = FastMCP(
        name=hub_cfg.get("HUB_NAME", "Universal MCP Hub"),
        instructions=(
            f"{hub_cfg.get('HUB_DESCRIPTION', 'Universal MCP Hub on PyFundaments')} "
            "Use list_active_tools to see what is currently available."
        )
    )

    # =========================================================================
    # Tool Registration — MINIMAL BUILD
    # Tools register only if their ENV key exists (value never read here!).
    # Key NAMES come from app/.pyfun [LLM_PROVIDERS] / [SEARCH_PROVIDERS].
    # =========================================================================

    # --- LLM Tools ---
    _register_llm_tools(mcp)

    # --- Search Tools ---
    _register_search_tools(mcp)

    # --- DB Tools --- (disabled until db_sync is ready)
    # _register_db_tools(mcp)

    # --- System Tools (always registered) ---
    _register_system_tools(mcp)

    # =========================================================================
    # Start transport
    # =========================================================================
    if transport == "sse":
        logger.info(f"MCP Hub starting via SSE on {host}:{port}")
        await mcp.run_sse_async(host=host, port=port)
    else:
        logger.info("MCP Hub starting via stdio (local mode)")
        await mcp.run_stdio_async()

    logger.info("MCP Hub shut down.")


# =============================================================================
# Tool registration helpers
# =============================================================================

def _register_llm_tools(mcp) -> None:
    """Register LLM tools based on active providers in app/.pyfun + ENV key check."""
    active = app_config.get_active_llm_providers()

    for name, cfg in active.items():
        env_key = cfg.get("env_key", "")
        if not env_key or not os.getenv(env_key):
            logger.info(f"LLM provider '{name}' skipped — ENV key '{env_key}' not set.")
            continue

        # Anthropic
        if name == "anthropic":
            import httpx
            _key        = os.getenv(env_key)
            _api_ver    = cfg.get("api_version_header", "2023-06-01")
            _base_url   = cfg.get("base_url", "https://api.anthropic.com/v1")
            _def_model  = cfg.get("default_model", "claude-haiku-4-5-20251001")

            @mcp.tool()
            async def anthropic_complete(
                prompt: str,
                model: str = _def_model,
                max_tokens: int = 1024
            ) -> str:
                """Send a prompt to Anthropic Claude."""
                async with httpx.AsyncClient() as client:
                    r = await client.post(
                        f"{_base_url}/messages",
                        headers={
                            "x-api-key": _key,
                            "anthropic-version": _api_ver,
                            "content-type": "application/json"
                        },
                        json={
                            "model": model,
                            "max_tokens": max_tokens,
                            "messages": [{"role": "user", "content": prompt}]
                        },
                        timeout=60.0
                    )
                    r.raise_for_status()
                    return r.json()["content"][0]["text"]

            logger.info(f"Tool registered: anthropic_complete (model: {_def_model})")

        # Gemini
        elif name == "gemini":
            import httpx
            _key        = os.getenv(env_key)
            _base_url   = cfg.get("base_url", "https://generativelanguage.googleapis.com/v1beta")
            _def_model  = cfg.get("default_model", "gemini-2.0-flash")

            @mcp.tool()
            async def gemini_complete(
                prompt: str,
                model: str = _def_model,
                max_tokens: int = 1024
            ) -> str:
                """Send a prompt to Google Gemini."""
                async with httpx.AsyncClient() as client:
                    r = await client.post(
                        f"{_base_url}/models/{model}:generateContent",
                        params={"key": _key},
                        json={
                            "contents": [{"parts": [{"text": prompt}]}],
                            "generationConfig": {"maxOutputTokens": max_tokens}
                        },
                        timeout=60.0
                    )
                    r.raise_for_status()
                    return r.json()["candidates"][0]["content"]["parts"][0]["text"]

            logger.info(f"Tool registered: gemini_complete (model: {_def_model})")

        # OpenRouter
        elif name == "openrouter":
            import httpx
            _key        = os.getenv(env_key)
            _base_url   = cfg.get("base_url", "https://openrouter.ai/api/v1")
            _def_model  = cfg.get("default_model", "mistralai/mistral-7b-instruct")
            _referer    = os.getenv("APP_URL", "https://huggingface.co")

            @mcp.tool()
            async def openrouter_complete(
                prompt: str,
                model: str = _def_model,
                max_tokens: int = 1024
            ) -> str:
                """Send a prompt via OpenRouter (100+ models)."""
                async with httpx.AsyncClient() as client:
                    r = await client.post(
                        f"{_base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {_key}",
                            "HTTP-Referer": _referer,
                            "content-type": "application/json"
                        },
                        json={
                            "model": model,
                            "max_tokens": max_tokens,
                            "messages": [{"role": "user", "content": prompt}]
                        },
                        timeout=60.0
                    )
                    r.raise_for_status()
                    return r.json()["choices"][0]["message"]["content"]

            logger.info(f"Tool registered: openrouter_complete (model: {_def_model})")

        # HuggingFace
        elif name == "huggingface":
            import httpx
            _key        = os.getenv(env_key)
            _base_url   = cfg.get("base_url", "https://api-inference.huggingface.co/models")
            _def_model  = cfg.get("default_model", "mistralai/Mistral-7B-Instruct-v0.3")

            @mcp.tool()
            async def hf_inference(
                prompt: str,
                model: str = _def_model,
                max_tokens: int = 512
            ) -> str:
                """Send a prompt to HuggingFace Inference API."""
                async with httpx.AsyncClient() as client:
                    r = await client.post(
                        f"{_base_url}/{model}/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {_key}",
                            "content-type": "application/json"
                        },
                        json={
                            "model": model,
                            "max_tokens": max_tokens,
                            "messages": [{"role": "user", "content": prompt}]
                        },
                        timeout=120.0
                    )
                    r.raise_for_status()
                    return r.json()["choices"][0]["message"]["content"]

            logger.info(f"Tool registered: hf_inference (model: {_def_model})")

        else:
            logger.info(f"LLM provider '{name}' has no tool handler yet — skipped.")


def _register_search_tools(mcp) -> None:
    """Register search tools based on active providers in app/.pyfun + ENV key check."""
    active = app_config.get_active_search_providers()

    for name, cfg in active.items():
        env_key = cfg.get("env_key", "")
        if not env_key or not os.getenv(env_key):
            logger.info(f"Search provider '{name}' skipped — ENV key '{env_key}' not set.")
            continue

        # Brave
        if name == "brave":
            import httpx
            _key         = os.getenv(env_key)
            _base_url    = cfg.get("base_url", "https://api.search.brave.com/res/v1/web/search")
            _def_results = int(cfg.get("default_results", "5"))
            _max_results = int(cfg.get("max_results", "20"))

            @mcp.tool()
            async def brave_search(query: str, count: int = _def_results) -> str:
                """Search the web via Brave Search API."""
                async with httpx.AsyncClient() as client:
                    r = await client.get(
                        _base_url,
                        headers={
                            "Accept": "application/json",
                            "X-Subscription-Token": _key
                        },
                        params={"q": query, "count": min(count, _max_results)},
                        timeout=30.0
                    )
                    r.raise_for_status()
                    results = r.json().get("web", {}).get("results", [])
                    if not results:
                        return "No results found."
                    return "\n\n".join([
                        f"{i}. {res.get('title', '')}\n   {res.get('url', '')}\n   {res.get('description', '')}"
                        for i, res in enumerate(results, 1)
                    ])

            logger.info("Tool registered: brave_search")

        # Tavily
        elif name == "tavily":
            import httpx
            _key            = os.getenv(env_key)
            _base_url       = cfg.get("base_url", "https://api.tavily.com/search")
            _def_results    = int(cfg.get("default_results", "5"))
            _incl_answer    = cfg.get("include_answer", "true").lower() == "true"

            @mcp.tool()
            async def tavily_search(query: str, max_results: int = _def_results) -> str:
                """AI-optimized web search via Tavily."""
                async with httpx.AsyncClient() as client:
                    r = await client.post(
                        _base_url,
                        json={
                            "api_key": _key,
                            "query": query,
                            "max_results": max_results,
                            "include_answer": _incl_answer
                        },
                        timeout=30.0
                    )
                    r.raise_for_status()
                    data = r.json()
                    parts = []
                    if data.get("answer"):
                        parts.append(f"Summary: {data['answer']}")
                    for res in data.get("results", []):
                        parts.append(
                            f"- {res['title']}\n  {res['url']}\n  {res.get('content', '')[:200]}..."
                        )
                    return "\n\n".join(parts)

            logger.info("Tool registered: tavily_search")

        else:
            logger.info(f"Search provider '{name}' has no tool handler yet — skipped.")


def _register_system_tools(mcp) -> None:
    """System tools — always registered, no ENV key required."""

    @mcp.tool()
    def list_active_tools() -> Dict[str, Any]:
        """Show active providers and configured integrations (key names only, never values)."""
        llm     = app_config.get_active_llm_providers()
        search  = app_config.get_active_search_providers()
        hub     = app_config.get_hub()
        return {
            "hub": hub.get("HUB_NAME", "Universal MCP Hub"),
            "version": hub.get("HUB_VERSION", ""),
            "active_llm_providers": [
                name for name, cfg in llm.items()
                if os.getenv(cfg.get("env_key", ""))
            ],
            "active_search_providers": [
                name for name, cfg in search.items()
                if os.getenv(cfg.get("env_key", ""))
            ],
        }
    logger.info("Tool registered: list_active_tools")

    @mcp.tool()
    def health_check() -> Dict[str, str]:
        """Health check for monitoring and HuggingFace Spaces."""
        return {"status": "ok", "service": "Universal MCP Hub"}
    logger.info("Tool registered: health_check")


# =============================================================================
# Direct execution guard
# =============================================================================
if __name__ == '__main__':
    print("WARNING: Run via main.py, not directly.")
