# app/mcp.py
# Universal MCP Hub - based on PyFundaments Architecture
# Copyright 2025 - Volkan Kücükbudak
# Apache License V. 2 + ESOL 1.1
# Repo: https://github.com/VolkanSah/PyFundaments
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

import sys
import logging
import os
from typing import Dict, Any

logger = logging.getLogger('mcp_hub')


# ============================================================
# GUARD: Block direct execution - only main.py may call this
# ============================================================
if __name__ == "__main__":
    print("ERROR: app/mcp.py must not be executed directly.")
    print("Use: python main.py")
    sys.exit(1)


# ============================================================
# MCP SERVER FACTORY
# Receives fully initialized fundaments from the Guardian.
# Never reads os.environ or .env directly.
# ============================================================

def create_mcp_server(fundaments: Dict[str, Any]):
    """
    Builds and configures the MCP server based on available services.
    Called exclusively by main.py after all fundaments are initialized.

    Tool registration is conditional:
      - LLM tools    -> require API keys (ANTHROPIC_API_KEY, OPENROUTER_API_KEY, HF_TOKEN)
      - Search tools -> require API keys (BRAVE_API_KEY, TAVILY_API_KEY)
      - DB tools     -> require an active database connection from fundaments["db"]
      - System tools -> always registered (health check, status overview)

    Args:
        fundaments: Dict of initialized services provided by main.py.
                    Values are None if a service is unavailable.

    Returns:
        Configured FastMCP instance, ready to run.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        logger.critical("FastMCP is not installed. Run: pip install fastmcp")
        raise

    config = fundaments["config"]

    mcp = FastMCP(
        name="PyFundaments MCP Hub",
        instructions=(
            "Universal MCP Hub built on PyFundaments. "
            "Available tools depend on configured API keys and active services. "
            "All operations pass through the PyFundaments security layer. "
            "Use list_active_tools to see what is currently available."
        )
    )

    # Register tool groups - each checks its own prerequisites
    _register_llm_tools(mcp, config)
    _register_search_tools(mcp, config)
    _register_system_tools(mcp, config, fundaments)
    _register_db_tools(mcp, fundaments)

    logger.info("MCP Hub configured and ready.")
    return mcp


# ============================================================
# LLM TOOLS
# Registered only when the corresponding API key is present.
# Uses lazy imports so missing packages don't break startup.
# ============================================================

def _register_llm_tools(mcp, config):
    """
    Registers LLM completion tools based on available API keys.
    Each provider is independent - partial configuration is fine.
    """

    # --- Anthropic Claude ---
    if config.has("ANTHROPIC_API_KEY"):
        import httpx

        @mcp.tool()
        async def anthropic_complete(
            prompt: str,
            model: str = "claude-haiku-4-5-20251001",
            max_tokens: int = 1024
        ) -> str:
            """
            Send a prompt to the Anthropic API and return the response.

            Args:
                prompt:     The input text to send to Claude.
                model:      Claude model ID. Default: claude-haiku-4-5-20251001 (fast & cheap).
                            Use claude-sonnet-4-6 for more complex tasks.
                max_tokens: Maximum response length in tokens.

            Returns:
                Response text from Claude.
            """
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": config.get("ANTHROPIC_API_KEY"),
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    },
                    json={
                        "model": model,
                        "max_tokens": max_tokens,
                        "messages": [{"role": "user", "content": prompt}]
                    },
                    timeout=60.0
                )
                response.raise_for_status()
                return response.json()["content"][0]["text"]

        logger.info("Tool registered: anthropic_complete")

    # --- OpenRouter (100+ models via unified API) ---
    if config.has("OPENROUTER_API_KEY"):
        import httpx

        @mcp.tool()
        async def openrouter_complete(
            prompt: str,
            model: str = "mistralai/mistral-7b-instruct",
            max_tokens: int = 1024
        ) -> str:
            """
            Send a prompt via OpenRouter to access 100+ LLM models.

            Args:
                prompt:     The input text.
                model:      OpenRouter model ID.
                            Examples: 'openai/gpt-4o', 'google/gemini-flash-1.5',
                                      'meta-llama/llama-3-8b-instruct'
                max_tokens: Maximum response length in tokens.

            Returns:
                Response text from the selected model.
            """
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {config.get('OPENROUTER_API_KEY')}",
                        # HTTP-Referer is required by OpenRouter for usage tracking
                        "HTTP-Referer": config.get("APP_URL", "https://huggingface.co"),
                        "content-type": "application/json"
                    },
                    json={
                        "model": model,
                        "max_tokens": max_tokens,
                        "messages": [{"role": "user", "content": prompt}]
                    },
                    timeout=60.0
                )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]

        logger.info("Tool registered: openrouter_complete")

    # --- HuggingFace Inference API ---
    if config.has("HF_TOKEN"):
        import httpx

        @mcp.tool()
        async def hf_inference(
            prompt: str,
            model: str = "mistralai/Mistral-7B-Instruct-v0.3",
            max_tokens: int = 512
        ) -> str:
            """
            Send a prompt to the HuggingFace Inference API.
            Note: The model must support the Inference API (not all HF models do).

            Args:
                prompt:     The input text.
                model:      HuggingFace model ID.
                            Check https://huggingface.co/models?inference=warm for options.
                max_tokens: Maximum response length in tokens.

            Returns:
                Generated text from the model.
            """
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://api-inference.huggingface.co/models/{model}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {config.get('HF_TOKEN')}",
                        "content-type": "application/json"
                    },
                    json={
                        "model": model,
                        "max_tokens": max_tokens,
                        "messages": [{"role": "user", "content": prompt}]
                    },
                    timeout=120.0  # HF cold starts can be slow
                )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]

        logger.info("Tool registered: hf_inference")


# ============================================================
# SEARCH TOOLS
# Registered only when the corresponding API key is present.
# ============================================================

def _register_search_tools(mcp, config):
    """
    Registers web search tools based on available API keys.
    Multiple search providers can be active simultaneously.
    """

    # --- Brave Search ---
    if config.has("BRAVE_API_KEY"):
        import httpx

        @mcp.tool()
        async def brave_search(query: str, count: int = 5) -> str:
            """
            Search the web using the Brave Search API.
            Privacy-focused, independent index (not Google/Bing).

            Args:
                query: Search query string.
                count: Number of results to return (max 20).

            Returns:
                Formatted list of search results with title, URL, and description.
            """
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": config.get("BRAVE_API_KEY")
                    },
                    params={"q": query, "count": min(count, 20)},
                    timeout=30.0
                )
                response.raise_for_status()
                results = response.json().get("web", {}).get("results", [])

                if not results:
                    return "No results found."

                output = []
                for i, r in enumerate(results, 1):
                    output.append(
                        f"{i}. {r.get('title', 'No title')}\n"
                        f"   {r.get('url', '')}\n"
                        f"   {r.get('description', '')}"
                    )
                return "\n\n".join(output)

        logger.info("Tool registered: brave_search")

    # --- Tavily (AI-optimized search with answer synthesis) ---
    if config.has("TAVILY_API_KEY"):
        import httpx

        @mcp.tool()
        async def tavily_search(query: str, max_results: int = 5) -> str:
            """
            AI-optimized web search via Tavily API.
            Returns both a synthesized answer and individual source results.

            Args:
                query:       Search query string.
                max_results: Number of source results to include.

            Returns:
                Synthesized answer followed by individual sources with snippets.
            """
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": config.get("TAVILY_API_KEY"),
                        "query": query,
                        "max_results": max_results,
                        "include_answer": True  # request AI-synthesized summary
                    },
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()

                parts = []
                if data.get("answer"):
                    parts.append(f"Summary: {data['answer']}")
                for r in data.get("results", []):
                    parts.append(
                        f"- {r['title']}\n"
                        f"  {r['url']}\n"
                        f"  {r.get('content', '')[:200]}..."
                    )
                return "\n\n".join(parts)

        logger.info("Tool registered: tavily_search")


# ============================================================
# SYSTEM TOOLS
# Always registered - no prerequisites required.
# ============================================================

def _register_system_tools(mcp, config, fundaments):
    """
    Registers system-level tools that are always available.
    These provide introspection and health monitoring capabilities.
    """

    @mcp.tool()
    def list_active_tools() -> Dict[str, Any]:
        """
        List all active services and configured API integrations.
        Use this to check which tools are currently available before calling them.

        Returns:
            Dictionary with fundament service status and configured integrations.
            Note: Only key names are returned, never key values.
        """
        # Check which fundament services are initialized
        service_status = {
            name: obj is not None
            for name, obj in fundaments.items()
        }

        # Check which API keys are configured - names only, never values
        configured_keys = [
            key for key in [
                "ANTHROPIC_API_KEY",
                "OPENROUTER_API_KEY",
                "HF_TOKEN",
                "BRAVE_API_KEY",
                "TAVILY_API_KEY",
                "DATABASE_URL"
            ]
            if config.has(key)
        ]

        return {
            "fundaments_status": service_status,
            "configured_integrations": configured_keys,
            "transport": os.getenv("MCP_TRANSPORT", "stdio"),
            "app_mode": os.getenv("APP_MODE", "mcp")
        }

    logger.info("Tool registered: list_active_tools")

    @mcp.tool()
    def health_check() -> Dict[str, str]:
        """
        Health check endpoint for HuggingFace Spaces and external monitoring.
        Returns HTTP 200 with ok status if the server is running.

        Returns:
            Status dictionary with service name.
        """
        return {
            "status": "ok",
            "service": "PyFundaments MCP Hub"
        }

    logger.info("Tool registered: health_check")


# ============================================================
# DATABASE TOOLS
# Only registered when a live DB connection exists in fundaments.
# Read-only by design - SELECT only, no DDL/DML.
# ============================================================

def _register_db_tools(mcp, fundaments):
    """
    Registers database query tools if a database connection is available.
    Enforces read-only access at the application level (SELECT only).

    Security note: This application-level check is defense-in-depth.
    The database user should also be restricted to SELECT at the DB level.
    """

    if fundaments.get("db") is None:
        logger.info("No database available - skipping DB tool registration.")
        return

    # Import here to avoid errors when DB is not configured
    from fundaments.postgresql import execute_secured_query

    @mcp.tool()
    async def db_query(sql: str) -> str:
        """
        Execute a read-only SELECT query against the database.
        INSERT, UPDATE, DELETE, DROP and all write operations are blocked.

        Args:
            sql: A valid SQL SELECT statement.

        Returns:
            Query results as a list of row dictionaries, or an error message.
        """
        # Application-level guard: enforce read-only access.
        # This is defense-in-depth - the DB user should also be read-only.
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


# ============================================================
# TRANSPORT STARTER
# Entry point called by main.py - never call this directly.
# Supports stdio (local/Claude Desktop) and SSE (HuggingFace/remote).
# ============================================================

async def start_mcp(fundaments: Dict[str, Any]):
    """
    Start the MCP server in the configured transport mode.
    Called exclusively by main.py after fundaments are initialized.

    Transport modes (set via MCP_TRANSPORT env var):
        stdio  - For local use with Claude Desktop or CLI clients.
                 Default mode. No network exposure.
        sse    - For remote hosting on HuggingFace Spaces or any server.
                 HuggingFace requires PORT=7860. Set HOST/PORT as needed.

    Args:
        fundaments: Initialized services from main.py (the Guardian).
    """
    mcp = create_mcp_server(fundaments)

    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()

    if transport == "sse":
        host = os.getenv("HOST", "0.0.0.0")
        port = int(os.getenv("PORT", "7860"))
        logger.info(f"MCP Hub starting via SSE on {host}:{port}")
        mcp.run(transport="sse", host=host, port=port)
    else:
        logger.info("MCP Hub starting via stdio (local mode)")
        mcp.run(transport="stdio")
