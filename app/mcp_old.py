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
#   MCP SSE transport runs through Quart/hypercorn via /mcp route.
#   All MCP traffic can be intercepted, logged, and transformed in app.py
#   before reaching the MCP handler — this is by design.
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
# from . import polymarket

logger = logging.getLogger('mcp')

# Global MCP instance — initialized once via initialize()
_mcp = None


async def initialize() -> None:
    """
    Initializes the MCP instance and registers all tools.
    Called once by app/app.py during startup.
    No fundaments passed in — sandboxed.
    """
    global _mcp

    logger.info("MCP Hub initializing...")

    hub_cfg = app_config.get_hub()

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        logger.critical("FastMCP not installed. Run: pip install mcp")
        raise

    _mcp = FastMCP(
        name=hub_cfg.get("HUB_NAME", "Universal MCP Hub"),
        instructions=(
            f"{hub_cfg.get('HUB_DESCRIPTION', 'Universal MCP Hub on PyFundaments')} "
            "Use list_active_tools to see what is currently available."
        )
    )

    # --- Register tools ---
    _register_llm_tools(_mcp)
    _register_search_tools(_mcp)
    # _register_db_tools(_mcp)   # uncomment when db_sync is ready
    _register_system_tools(_mcp)
    _register_polymarket_tools(_mcp)

    logger.info("MCP Hub initialized.")


async def handle_request(request) -> None:
    """
    Handles incoming MCP SSE requests routed through Quart /mcp endpoint.
    This is the interceptor point — add auth, logging, rate limiting here.
    """
    if _mcp is None:
        logger.error("MCP not initialized — call initialize() first.")
        from quart import jsonify
        return jsonify({"error": "MCP not initialized"}), 503

    # --- Interceptor hooks (add as needed) ---
    # logger.debug(f"MCP request: {request.method} {request.path}")
    # await _check_auth(request)
    # await _rate_limit(request)
    # await _log_payload(request)

    # --- Forward to FastMCP SSE handler ---
    return await _mcp.handle_sse(request)


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

        if name == "anthropic":
            import httpx
            _key       = os.getenv(env_key)
            _api_ver   = cfg.get("api_version_header", "2023-06-01")
            _base_url  = cfg.get("base_url", "https://api.anthropic.com/v1")
            _def_model = cfg.get("default_model", "claude-haiku-4-5-20251001")

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

        elif name == "gemini":
            import httpx
            _key       = os.getenv(env_key)
            _base_url  = cfg.get("base_url", "https://generativelanguage.googleapis.com/v1beta")
            _def_model = cfg.get("default_model", "gemini-2.0-flash")

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

        elif name == "openrouter":
            import httpx
            _key       = os.getenv(env_key)
            _base_url  = cfg.get("base_url", "https://openrouter.ai/api/v1")
            _def_model = cfg.get("default_model", "mistralai/mistral-7b-instruct")
            _referer   = os.getenv("APP_URL", "https://huggingface.co")

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

        elif name == "huggingface":
            import httpx
            _key       = os.getenv(env_key)
            _base_url  = cfg.get("base_url", "https://api-inference.huggingface.co/models")
            _def_model = cfg.get("default_model", "mistralai/Mistral-7B-Instruct-v0.3")

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

        elif name == "tavily":
            import httpx
            _key         = os.getenv(env_key)
            _base_url    = cfg.get("base_url", "https://api.tavily.com/search")
            _def_results = int(cfg.get("default_results", "5"))
            _incl_answer = cfg.get("include_answer", "true").lower() == "true"

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
        llm    = app_config.get_active_llm_providers()
        search = app_config.get_active_search_providers()
        hub    = app_config.get_hub()
        return {
            "hub":                    hub.get("HUB_NAME", "Universal MCP Hub"),
            "version":                hub.get("HUB_VERSION", ""),
            "active_llm_providers":   [n for n, c in llm.items()    if os.getenv(c.get("env_key", ""))],
            "active_search_providers":[n for n, c in search.items() if os.getenv(c.get("env_key", ""))],
        }
    logger.info("Tool registered: list_active_tools")

    @mcp.tool()
    def health_check() -> Dict[str, str]:
        """Health check for monitoring and HuggingFace Spaces."""
        return {"status": "ok", "service": "Universal MCP Hub"}
    logger.info("Tool registered: health_check")



# 3. Neue Funktion — analog zu _register_search_tools():
def _register_polymarket_tools(mcp) -> None:
    """Polymarket tools — no ENV key needed, Gamma API is public."""

    @mcp.tool()
    async def get_markets(category: str = None, limit: int = 20) -> list:
        """Get active prediction markets, optional category filter."""
        return await polymarket.get_markets(category=category, limit=limit)

    @mcp.tool()
    async def trending_markets(limit: int = 10) -> list:
        """Get top trending markets by trading volume."""
        return await polymarket.trending_markets(limit=limit)

    @mcp.tool()
    async def analyze_market(market_id: str) -> dict:
        """LLM analysis of a single market. Fallback if no LLM key set."""
        return await polymarket.analyze_market(market_id)

    @mcp.tool()
    async def summary_report(category: str = None) -> dict:
        """Summary report for a category or all markets."""
        return await polymarket.summary_report(category=category)

    @mcp.tool()
    async def polymarket_cache_info() -> dict:
        """Cache status, available categories, LLM availability."""
        return await polymarket.get_cache_info()

    logger.info("Tools registered: polymarket (5 tools)")


# =============================================================================
# Direct execution guard
# =============================================================================
if __name__ == '__main__':
    print("WARNING: Run via main.py, not directly.")
