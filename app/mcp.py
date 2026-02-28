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
# SANDBOX RULE:
#   app/* has NO direct access to .env or fundaments/*.
#   Config for app/* lives in app/.pyfun (provider URLs, models, tool settings).
#   Secrets stay in .env → Guardian reads them → injects what app/* needs.
# =============================================================================

from quart import Quart, request, jsonify  # async Flask — required for async cloud providers + Neon DB
import logging
from waitress import serve                  # WSGI server — keeps Flask non-blocking alongside asyncio
import threading                            # bank-pattern: each blocking service gets its own thread
import requests                             # sync HTTP for health check worker
import time
from datetime import datetime
import asyncio
import sys
from typing import Dict, Any, Optional

# =============================================================================
# Import app/* modules
# Config/settings for all modules below live in app/.pyfun — not in .env!
# =============================================================================
from . import mcp          # MCP transport layer (stdio / SSE)
from . import providers    # API provider registry (LLM, Search, Web)
from . import models       # Model config + token/rate limits
from . import tools        # MCP tool definitions + provider mapping
from . import db_sync      # Internal SQLite IPC — app/* state & communication
                           # db_sync ≠ cloud DB! Cloud DB is Guardian-only via main.py.

# Future modules (soon uncommented when ready):
# from . import discord_api  # Discord bot integration
# from . import hf_hooks     # HuggingFace Space hooks
# from . import git_hooks    # GitHub/GitLab webhook handler
# from . import web_api      # Generic REST API handler

# =============================================================================
# Loggers — one per module for clean log filtering
# =============================================================================
logger          = logging.getLogger('application')
#logger          = logging.getLogger('config')
# logger_mcp      = logging.getLogger('mcp')
# logger_tools    = logging.getLogger('tools')
# logger_providers = logging.getLogger('providers')
# logger_models   = logging.getLogger('models')
# logger_db_sync  = logging.getLogger('db_sync')

# =============================================================================
# Flask app instance
# =============================================================================
app = Quart(__name__)
START_TIME = datetime.utcnow()

# =============================================================================
# Global service references (set during initialize_services)
# =============================================================================
_fundaments: Optional[Dict[str, Any]] = None
PORT = None

# =============================================================================
# Service initialization
# =============================================================================
def initialize_services(fundaments: Dict[str, Any]) -> None:
    """
    Initializes all app/* services with injected fundaments from Guardian.
    Called once during start_application — sets global service references.
    """
    global _fundaments, PORT

    _fundaments = fundaments
    PORT = fundaments["config"].get_int("PORT", 7860)

    # Initialize internal SQLite state store for app/* IPC
    db_sync.initialize()

    # Initialize provider registry from app/.pyfun + ENV key presence check
    providers.initialize(fundaments["config"])

    # Initialize model registry from app/.pyfun
    models.initialize()

    # Initialize tool registry — tools only register if their provider is active
    tools.initialize(providers, models, fundaments)

    logger.info("app/* services initialized.")


# =============================================================================
# Background workers
# =============================================================================
def start_mcp_in_thread() -> None:
    """
    Starts the MCP Hub (stdio or SSE) in its own thread with its own event loop.
    Mirrors the bank-thread pattern from the Discord bot architecture.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(mcp.start_mcp(_fundaments))
    finally:
        loop.close()


def health_check_worker() -> None:
    """
    Periodic self-ping to keep the app alive on hosting platforms (e.g. HuggingFace).
    Runs in its own daemon thread — does not block the main loop.
    """
    while True:
        time.sleep(3600)
        try:
            response = requests.get(f"http://127.0.0.1:{PORT}/")
            logger.info(f"Health check ping: {response.status_code}")
        except Exception as e:
            logger.error(f"Health check failed: {e}")


# =============================================================================
# Flask Routes
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
        "active_providers": providers.get_active_names() if providers else [],
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
    Payload is decrypted via fundaments/encryption.py (injected by Guardian).
    Only active if encryption_service is available in fundaments.
    """
    encryption_service = _fundaments.get("encryption") if _fundaments else None
    if not encryption_service:
        return jsonify({"error": "Encryption service not available"}), 503

    # TODO: decrypt payload, dispatch, re-encrypt response
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
# Main entry point — called by Guardian (main.py)
# =============================================================================
async def start_application(fundaments: Dict[str, Any]) -> None:
    """
    Main entry point for the sandboxed app layer.
    Called exclusively by main.py after all fundament services are initialized.

    Args:
        fundaments: Dictionary of initialized services from Guardian (main.py).
                    All services already validated — may be None if not configured.
    """
    logger.info("Application starting...")

    # --- Unpack fundament services (read-only references) ---
    config_service          = fundaments["config"]
    db_service              = fundaments["db"]              # None if no DB configured
    encryption_service      = fundaments["encryption"]      # None if keys not set
    access_control_service  = fundaments["access_control"]  # None if no DB
    user_handler_service    = fundaments["user_handler"]    # None if no DB
    security_service        = fundaments["security"]        # None if deps missing

    # --- Initialize all app/* services ---
    initialize_services(fundaments)

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

    # --- Start MCP Hub in its own thread (stdio or SSE) ---
    mcp_thread = threading.Thread(target=start_mcp_in_thread, daemon=True)
    mcp_thread.start()
    logger.info("MCP Hub thread started.")

    # Allow MCP to initialize before Flask comes up
    await asyncio.sleep(1)

    # --- Start health check worker ---
    health_thread = threading.Thread(target=health_check_worker, daemon=True)
    health_thread.start()

    # --- Start Flask/Quart via Waitress in its own thread ---
    def run_server():
        serve(app, host="0.0.0.0", port=PORT)

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    logger.info(f"HTTP server started on port {PORT}.")

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
