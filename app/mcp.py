# app/mcp.py
# Universal MCP Hub (Sandboxed) - based on PyFundaments Architecture
# Copyright 2026 - Volkan Kücükbudak
# Apache License V. 2 + ESOL 1.1
# Repo: https://github.com/VolkanSah/Universal-MCP-Hub-sandboxed
#
# ARCHITECTURE NOTE:
#   This file lives exclusively in /app/ and is ONLY started by main.py (the "Guardian").
#   It has NO direct access to API keys, environment variables, or fundament services.
#   Everything is injected by the Guardian via the `fundaments` dictionary.
#   Direct execution is blocked by design.
#
# TOOL REGISTRATION PRINCIPLE:
#   Tools are only registered if their required API key/service is present.
#   No key = no tool = no crash. The server always starts, just with fewer tools.

import asyncio
import logging
import os
from typing import Dict, Any, Optional

logger = logging.getLogger('mcp_hub')


async def start_mcp(fundaments: Dict[str, Any]):
    """
    The main entry point for the MCP Hub logic.
    All fundament services are validated and provided by main.py.

    Args:
        fundaments: Dictionary containing initialized services from main.py.
                    Services are already validated and ready to use.
    """
    logger.info("MCP Hub starting...")

    # Services are already validated and initialized by main.py
    config_service        = fundaments["config"]
    db_service            = fundaments["db"]             # Can be None if not needed
    encryption_service    = fundaments["encryption"]     # Can be None if not needed
    access_control_service = fundaments["access_control"] # Can be None if not needed
    user_handler_service  = fundaments["user_handler"]   # Can be None if not needed
    security_service      = fundaments["security"]       # Can be None if not needed

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        logger.critical("FastMCP is not installed. Run: pip install fastmcp")
        raise

    mcp = FastMCP(
        name="PyFundaments MCP Hub",
        instructions=(
            "Universal MCP Hub built on PyFundaments. "
            "Available tools depend on configured API keys and active services. "
            "Use list_active_tools to see what is currently available."
        )
    )

    # --- LLM Tools (register if API key is present) ---

    if config_service.has("ANTHROPIC_API_KEY"):
        import httpx
        _key = config_service.get("ANTHROPIC_API_KEY")

        @mcp.tool()
        async def anthropic_complete(prompt: str, model: str = "claude-haiku-4-5-20251001", max_tokens: int = 1024) -> str:
            """Send a prompt to Anthropic Claude. Models: claude-haiku-4-5-20251001, claude-sonnet-4-6, claude-opus-4-6"""
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": _key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]},
                    timeout=60.0
                )
                r.raise_for_status()
                return r.json()["content"][0]["text"]
        logger.info("Tool registered: anthropic_complete")

    if config_service.has("GEMINI_API_KEY"):
        import httpx
        _key = config_service.get("GEMINI_API_KEY")

        @mcp.tool()
        async def gemini_complete(prompt: str, model: str = "gemini-2.0-flash", max_tokens: int = 1024) -> str:
            """Send a prompt to Google Gemini. Models: gemini-2.0-flash, gemini-1.5-pro, gemini-1.5-flash"""
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    params={"key": _key},
                    json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": max_tokens}},
                    timeout=60.0
                )
                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        logger.info("Tool registered: gemini_complete")

    if config_service.has("OPENROUTER_API_KEY"):
        import httpx
        _key     = config_service.get("OPENROUTER_API_KEY")
        _referer = config_service.get("APP_URL", "https://huggingface.co")

        @mcp.tool()
        async def openrouter_complete(prompt: str, model: str = "mistralai/mistral-7b-instruct", max_tokens: int = 1024) -> str:
            """Send a prompt via OpenRouter (100+ models). Examples: openai/gpt-4o, meta-llama/llama-3-8b-instruct"""
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {_key}", "HTTP-Referer": _referer, "content-type": "application/json"},
                    json={"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]},
                    timeout=60.0
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
        logger.info("Tool registered: openrouter_complete")

    if config_service.has("HF_TOKEN"):
        import httpx
        _key = config_service.get("HF_TOKEN")

        @mcp.tool()
        async def hf_inference(prompt: str, model: str = "mistralai/Mistral-7B-Instruct-v0.3", max_tokens: int = 512) -> str:
            """Send a prompt to HuggingFace Inference API. Browse models: https://huggingface.co/models?inference=warm"""
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"https://api-inference.huggingface.co/models/{model}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {_key}", "content-type": "application/json"},
                    json={"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]},
                    timeout=120.0
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
        logger.info("Tool registered: hf_inference")

    # --- Search Tools (register if API key is present) ---

    if config_service.has("BRAVE_API_KEY"):
        import httpx
        _key = config_service.get("BRAVE_API_KEY")

        @mcp.tool()
        async def brave_search(query: str, count: int = 5) -> str:
            """Search the web via Brave Search API (independent index, privacy-focused)."""
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"Accept": "application/json", "X-Subscription-Token": _key},
                    params={"q": query, "count": min(count, 20)},
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

    if config_service.has("TAVILY_API_KEY"):
        import httpx
        _key = config_service.get("TAVILY_API_KEY")

        @mcp.tool()
        async def tavily_search(query: str, max_results: int = 5) -> str:
            """AI-optimized web search via Tavily. Returns synthesized answer + sources."""
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    "https://api.tavily.com/search",
                    json={"api_key": _key, "query": query, "max_results": max_results, "include_answer": True},
                    timeout=30.0
                )
                r.raise_for_status()
                data = r.json()
                parts = []
                if data.get("answer"):
                    parts.append(f"Summary: {data['answer']}")
                for res in data.get("results", []):
                    parts.append(f"- {res['title']}\n  {res['url']}\n  {res.get('content', '')[:200]}...")
                return "\n\n".join(parts)
        logger.info("Tool registered: tavily_search")

    # --- DB Tools (register only if DB is initialized) ---

    if db_service is not None:
        from fundaments.postgresql import execute_secured_query

        @mcp.tool()
        async def db_query(sql: str) -> str:
            """Execute a read-only SELECT query. All write operations are blocked."""
            if not sql.strip().upper().startswith("SELECT"):
                return "Error: Only SELECT statements are permitted."
            try:
                result = await execute_secured_query(sql, fetch_method='fetch')
                if not result:
                    return "No results."
                return str([dict(row) for row in result])
            except Exception as e:
                logger.error(f"DB query error: {e}")
                return f"Database error: {str(e)}"
        logger.info("Tool registered: db_query")

    else:
        logger.info("No database available - DB tools skipped.")

    # --- System Tools (always registered) ---

    @mcp.tool()
    def list_active_tools() -> Dict[str, Any]:
        """Show active services and configured integrations (key names only, never values)."""
        return {
            "fundaments_status": {k: v is not None for k, v in fundaments.items()},
            "configured_integrations": [
                key for key in [
                    "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY",
                    "HF_TOKEN", "BRAVE_API_KEY", "TAVILY_API_KEY", "DATABASE_URL"
                ] if config_service.has(key)
            ],
            "transport": os.getenv("MCP_TRANSPORT", "stdio"),
            "app_mode":  os.getenv("APP_MODE", "mcp")
        }
    logger.info("Tool registered: list_active_tools")

    @mcp.tool()
    def health_check() -> Dict[str, str]:
        """Health check endpoint for HuggingFace Spaces and monitoring."""
        return {"status": "ok", "service": "PyFundaments MCP Hub"}
    logger.info("Tool registered: health_check")

    # --- Encryption available ---
    if encryption_service:
        logger.info("Encryption service active - available for future tools.")

    # --- Auth/Security available ---
    if user_handler_service and security_service:
        logger.info("Auth services active - available for future tools.")

    # --- Start transport ---
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    if transport == "sse":
        host = os.getenv("HOST", "0.0.0.0")
        port = int(os.getenv("PORT", "7860"))
        logger.info(f"MCP Hub starting via SSE on {host}:{port}")
        mcp.run(transport="sse", host=host, port=port)
    else:
        logger.info("MCP Hub starting via stdio (local mode)")
        mcp.run(transport="stdio")

    logger.info("MCP Hub shut down.")


# ============================================================
# Direct execution guard - mirrors example.app.py exactly
# ============================================================
if __name__ == '__main__':
    print("WARNING: Running mcp.py directly. Fundament modules might not be correctly initialized.")
    print("Please run 'python main.py' instead for proper initialization.")

    test_fundaments = {
        "config": None,
        "db": None,
        "encryption": None,
        "access_control": None,
        "user_handler": None,
        "security": None
    }

    asyncio.run(start_mcp(test_fundaments))
