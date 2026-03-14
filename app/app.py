# =============================================================================
# root/app/app.py
# Universal MCP Hub (Sandboxed) - based on PyFundaments Architecture
# Copyright 2026 - Volkan Kücükbudak
# Apache License V. 2 + ESOL 1.1
# Repo: https://github.com/VolkanSah/Universal-MCP-Hub-sandboxed
# =============================================================================
# ARCHITECTURE NOTE:
#   This file is the Orchestrator of the sandboxed app/* layer.
#   It is ONLY started by main.py (the "Guardian").
#   All fundament services are injected via the `fundaments` dictionary.
#   Direct execution is blocked by design.
#
# SANDBOX RULES:
#   - fundaments dict is ONLY unpacked inside start_application()
#   - fundaments are NEVER stored globally or passed to other app/* modules
#   - app/* modules read their own config from app/.pyfun
#   - app/* internal state/IPC uses app/db_sync.py (SQLite) — NOT postgresql.py
#   - Secrets stay in .env → Guardian reads them → never touched by app/*
# =============================================================================
from quart import Quart, request, jsonify  # async Flask — ASGI compatible
import logging
from hypercorn.asyncio import serve        # ASGI server — async native, replaces waitress
from hypercorn.config import Config        # hypercorn config
import threading                           # for future tools that need own threads
import requests                            # sync HTTP for future tool workers
import time
from datetime import datetime
import asyncio
from typing import Dict, Any, Optional
# =============================================================================
# Import app/* modules — MINIMAL BUILD
# Each module reads its own config from app/.pyfun independently.
# NO fundaments passed into these modules!
# =============================================================================
from . import mcp                   # MCP transport layer (SSE via Quart route)
from . import config as app_config  # app/.pyfun parser — used only in app/*
from . import providers    # API provider registry — reads app/.pyfun
from . import models       # Model config + token/rate limits — reads app/.pyfun
from . import tools        # MCP tool definitions + provider mapping — reads app/.pyfun
from . import db_sync      # Internal SQLite IPC — app/* state & communication
#                          # db_sync ≠ postgresql.py! Cloud DB is Guardian-only.
# Future modules (will uncomment when ready):
# from . import discord_api  # Discord bot integration
# from . import hf_hooks     # HuggingFace Space hooks
# from . import git_hooks    # GitHub/GitLab webhook handler
# from . import web_api      # Generic REST API handler
# =============================================================================
# Loggers — one per module for clean log filtering
# =============================================================================
logger        = logging.getLogger('application')
logger_mcp    = logging.getLogger('mcp')
logger_config = logging.getLogger('config')
logger_tools     = logging.getLogger('tools')
logger_providers = logging.getLogger('providers')
logger_models    = logging.getLogger('models')
logger_db_sync   = logging.getLogger('db_sync')



# ── NEU: nach den Imports, vor app = Quart(__name__) ──────────────────────────

def _make_mount_middleware(outer_app, path_prefix: str, inner_app):
    """
    Minimale ASGI-Middleware: leitet Requests mit path_prefix an inner_app
    (FastMCP Streamable HTTP) weiter, alles andere geht an outer_app (Quart).
    Nur aktiv bei HUB_TRANSPORT = "streamable-http".
    """
    async def middleware(scope, receive, send):
        path = scope.get("path", "")
        if path == path_prefix or path.startswith(path_prefix + "/"):
            scope = dict(scope)
            stripped = path[len(path_prefix):] or "/"
            scope["path"] = stripped
            scope["raw_path"] = stripped.encode()
            await inner_app(scope, receive, send)
        else:
            await outer_app(scope, receive, send)
    return middleware

# =============================================================================
# Quart app instance
# =============================================================================
app = Quart(__name__)
START_TIME = datetime.utcnow()
# =============================================================================
# Quart Routes
# =============================================================================
@app.route("/", methods=["GET"])
async def health_check():
    """
    Health check endpoint.
    Used by HuggingFace Spaces and monitoring systems to verify the app is running.
    """
    uptime = datetime.utcnow() - START_TIME
    return jsonify({
        "status": "running",
        "service": "Universal MCP Hub",
        "uptime_seconds": int(uptime.total_seconds()),
    })


@app.route("/api", methods=["POST"])
async def api_endpoint():
    try:
        data      = await request.get_json()
        tool_name = data.get("tool")
        params    = data.get("params", {})

        # System tools — handle directly, no prompt needed!
        if tool_name == "list_active_tools":
            return jsonify({"result": {
                "active_tools":            tools.list_all(),
                "active_llm_providers":    providers.list_active_llm(),
                "active_search_providers": providers.list_active_search(),
                "available_models":        models.list_all(),
            }})

        if tool_name == "health_check":
            return jsonify({"result": {"status": "ok"}})

        # db_query — handled by db_sync directly, not tools.run()
        if tool_name == "db_query":
            sql    = params.get("sql", "")
            result = await db_sync.query(sql)
            return jsonify({"result": result})

        # rename 'provider' → 'provider_name' for tools.run()
        if "provider" in params:
            params["provider_name"] = params.pop("provider")

        result = await tools.run(tool_name, **params)
        return jsonify({"result": result})

    except Exception as e:
        logger.error(f"API error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/crypto", methods=["POST"])
async def crypto_endpoint():
    """
    Encrypted API endpoint.
    Encryption handled by app/* layer — no direct fundaments access here.
    """
    # TODO: implement via app/* encryption wrapper
    data = await request.get_json()
    return jsonify({"status": "not_implemented"}), 501


# Future routes (uncomment when ready):
# @app.route("/discord", methods=["POST"])
# async def discord_interactions():
#     """Discord interactions endpoint — signature verification via discord_api module."""
#     pass

# @app.route("/webhook/hf", methods=["POST"])
# async def hf_webhook():
#     """HuggingFace Space event hooks."""
#     pass

# @app.route("/webhook/git", methods=["POST"])
# async def git_webhook():
#     """GitHub / GitLab webhook handler."""
#     pass
# =============================================================================
# Main entry point — called exclusively by Guardian (main.py)
# =============================================================================
async def start_application(fundaments: Dict[str, Any]) -> None:
    """
    Main entry point for the sandboxed app layer.
    Called exclusively by main.py after all fundament services are initialized.

    Args:
        fundaments: Dictionary of initialized services from Guardian (main.py).
                    Services are unpacked here and NEVER stored globally or
                    passed into other app/* modules.
    """
    logger.info("Application starting...")

    # =========================================================================
    # Unpack fundaments — ONLY here, NEVER elsewhere in app/*
    # These are the 6 fundament services from fundaments/*
    # =========================================================================
    config_service          = fundaments["config"]          # fundaments/config_handler.py
    db_service              = fundaments["db"]              # fundaments/postgresql.py — None if not configured
    encryption_service      = fundaments["encryption"]      # fundaments/encryption.py — None if keys not set
    access_control_service  = fundaments["access_control"]  # fundaments/access_control.py — None if no DB
    user_handler_service    = fundaments["user_handler"]    # fundaments/user_handler.py — None if no DB
    security_service        = fundaments["security"]        # fundaments/security.py — None if deps missing

    # --- Log active fundament services ---
    if encryption_service:
        logger.info("Encryption service active.")

    if user_handler_service and security_service:
        logger.info("Auth services active (user_handler + security).")

    if access_control_service and security_service:
        logger.info("Access control active.")

    if db_service and not user_handler_service:
        logger.info("Database-only mode active (e.g. ML pipeline).")

    if not db_service:
        logger.info("Database-free mode active (e.g. Discord bot, API client).")

    # =========================================================================
    # Initialize app/* internal services — MINIMAL BUILD
    # Uncomment each line when the module is ready!
    # =========================================================================
    # await db_sync.initialize()    # SQLite IPC store for app/* — unrelated to postgresql.py
    # await providers.initialize()  # reads app/.pyfun [LLM_PROVIDERS] [SEARCH_PROVIDERS] # in mcp_init
    # await models.initialize()     # reads app/.pyfun [MODELS] # in mcp_init
    # await tools.initialize()      # reads app/.pyfun [TOOLS]

    # --- Initialize MCP (registers tools, prepares SSE handler) ---
    # db_sync only if cloud_DB used to! 
    # PSQL bridge — nur wenn Guardian DB-Service injiziert hat
    # app.py — bridge-Block:
    await db_sync.initialize()

    if db_service:
        # asyncpg Pool direkt nutzen — kein execute_secured_query nötig
        db_sync.set_psql_writer(db_service.execute)
        logger.info("PostgreSQL bridge active.")
    else:
        logger.info("PostgreSQL bridge inactive — no DATABASE_URL configured.")

    
    await mcp.initialize()

    # --- Transport-abhängiges MCP-Routing ---
    hub_cfg   = app_config.get_hub()
    transport = hub_cfg.get("HUB_TRANSPORT", "streamable-http").lower()

    if transport == "streamable-http":
        # ASGI-Mount: FastMCP übernimmt /mcp direkt — kein Quart-Overhead
        app.asgi_app = _make_mount_middleware(app.asgi_app, "/mcp", mcp.get_asgi_app())
        logger.info("MCP transport: Streamable HTTP → /mcp")
    else:
        # SSE legacy — Quart-Route dynamisch registrieren
        @app.route("/mcp", methods=["GET", "POST"])
        async def mcp_endpoint():
            """MCP SSE legacy transport — interceptor point für auth/logging."""
            return await mcp.handle_request(request)
        logger.info("MCP transport: SSE (legacy) → /mcp")


    # --- Read PORT from app/.pyfun [HUB] ---
    port = int(hub_cfg.get("HUB_PORT", "7860"))  # hub_cfg bereits gelesen, kein zweiter get_hub()-Call

    # --- Configure hypercorn ---
    config = Config()
    config.bind = [f"0.0.0.0:{port}"]

    logger.info(f"Starting hypercorn on port {port}...")
    logger.info("All services running.")

    # --- Run hypercorn — blocks until shutdown ---
    await serve(app, config)

# =============================================================================
# Direct execution guard
# =============================================================================
if __name__ == '__main__':
    print("WARNING: Running app.py directly. Fundament modules might not be correctly initialized.")
    print("Please run 'python main.py' instead for proper initialization.")

    test_fundaments = {
        "config":           None,
        "db":               None,
        "encryption":       None,
        "access_control":   None,
        "user_handler":     None,
        "security":         None,
    }

    asyncio.run(start_application(test_fundaments))
