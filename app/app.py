# =============================================================================
# app/app.py
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

from quart import Quart, request, jsonify  # async Flask — required for async providers + Neon DB
import logging
from waitress import serve                  # WSGI server — keeps HTTP non-blocking alongside asyncio
import threading                            # bank-pattern: each blocking service gets its own thread
import requests                             # sync HTTP for health check worker
import time
from datetime import datetime
import asyncio
from typing import Dict, Any, Optional

# =============================================================================
# Import app/* modules — MINIMAL BUILD (uncomment when module is ready)
# Each module reads its own config from app/.pyfun independently.
# NO fundaments passed into these modules!
# =============================================================================
from . import mcp                   # MCP transport layer (stdio / SSE)
from . import config as app_config  # app/.pyfun parser — used only in app/*
# from . import providers    # API provider registry — reads app/.pyfun
# from . import models       # Model config + token/rate limits — reads app/.pyfun
# from . import tools        # MCP tool definitions + provider mapping — reads app/.pyfun
# from . import db_sync      # Internal SQLite IPC — app/* state & communication
#                            # db_sync ≠ postgresql.py! Cloud DB is Guardian-only.

# Future modules (uncomment when ready):
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
# logger_tools     = logging.getLogger('tools')
# logger_providers = logging.getLogger('providers')
# logger_models    = logging.getLogger('models')
# logger_db_sync   = logging.getLogger('db_sync')

# =============================================================================
# Quart app instance
# =============================================================================
app = Quart(__name__)
START_TIME = datetime.utcnow()

# =============================================================================
# Background workers
# =============================================================================
def start_mcp_in_thread() -> None:
    """
    Starts the MCP Hub (stdio or SSE) in its own thread with its own event loop.
    Mirrors the bank-thread pattern from the Discord bot architecture.
    mcp.py reads its own config from app/.pyfun — no fundaments passed in.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(mcp.start_mcp())
    finally:
        loop.close()


def health_check_worker(port: int) -> None:
    """
    Periodic self-ping to keep the app alive on hosting platforms (e.g. HuggingFace).
    Runs in its own daemon thread — does not block the main loop.
    Port passed directly — no global state needed.
    """
    while True:
        time.sleep(3600)
        try:
            response = requests.get(f"http://127.0.0.1:{port}/")
            logger.info(f"Health check ping: {response.status_code}")
        except Exception as e:
            logger.error(f"Health check failed: {e}")


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
    """
    Generic REST API endpoint for direct tool invocation.
    Accepts JSON: { "tool": "tool_name", "params": { ... } }
    Auth and validation handled by tools layer.
    """
    # TODO: implement tool dispatch via tools.invoke()
    data = await request.get_json()
    return jsonify({"status": "not_implemented", "received": data}), 501


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
    # db_sync.initialize()    # SQLite IPC store for app/* — unrelated to postgresql.py
    # providers.initialize()  # reads app/.pyfun [LLM_PROVIDERS] [SEARCH_PROVIDERS]
    # models.initialize()     # reads app/.pyfun [MODELS]
    # tools.initialize()      # reads app/.pyfun [TOOLS]

    # --- Read PORT from app/.pyfun [HUB] ---
    port = int(app_config.get_hub().get("HUB_PORT", "7860"))

    # --- Start MCP Hub in its own thread ---
    mcp_thread = threading.Thread(target=start_mcp_in_thread, daemon=True)
    mcp_thread.start()
    logger.info("MCP Hub thread started.")

    await asyncio.sleep(1)

    # --- Start health check worker ---
    health_thread = threading.Thread(
        target=health_check_worker,
        args=(port,),
        daemon=True
    )
    health_thread.start()

    # --- Start Quart via Waitress in its own thread ---
    def run_server():
        serve(app, host="0.0.0.0", port=port)

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    logger.info(f"HTTP server started on port {port}.")

    logger.info("All services running. Entering heartbeat loop...")

    # --- Heartbeat loop — keeps Guardian's async context alive ---
    try:
        while True:
            await asyncio.sleep(60)
            logger.debug("Heartbeat.")
    except KeyboardInterrupt:
        logger.info("Shutdown signal received.")


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
