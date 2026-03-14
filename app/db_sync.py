
# =============================================================================
# app/db_sync.py
# Internal SQLite IPC — app/* state & communication
# Universal MCP Hub (Sandboxed) - based on PyFundaments Architecture
# Copyright 2026 - Volkan Kücükbudak
# Apache License V. 2 + ESOL 1.1
# Repo: https://github.com/VolkanSah/Universal-MCP-Hub-sandboxed
# =============================================================================
# ARCHITECTURE NOTE:
#   This file lives exclusively in app/ and is ONLY started by app/app.py.
#   NO direct access to fundaments/*, .env, or Guardian (main.py).
#   DB path comes from app/.pyfun [DB_SYNC] → SQLITE_PATH via app/config.py.
#
# CRITICAL RULES:
#   - This is NOT postgresql.py — cloud DB is Guardian-only!
#   - db_sync ONLY manages its own tables (hub_state, tool_cache)
#   - NEVER touch Guardian tables (users, sessions) — those belong to user_handler.py
#   - SQLite path is shared with user_handler.py via SQLITE_PATH
#   - app/* modules call db_sync.write() / db_sync.read() — never aiosqlite directly
#
# TABLE OWNERSHIP:
#   users, sessions  → Guardian (fundaments/user_handler.py) — DO NOT TOUCH!
#   hub_state        → db_sync (app/* internal state)
#   tool_cache       → db_sync (app/* tool response cache)
# =============================================================================

import aiosqlite
import logging
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import config

logger = logging.getLogger("db_sync")

# =============================================================================
# Internal State
# =============================================================================
_db_path: Optional[str] = None
_initialized: bool = False


# =============================================================================
# Initialization — called by app/app.py (parameterless, sandboxed)
# =============================================================================

async def initialize() -> None:
    global _db_path, _initialized

    if _initialized:
        return

    db_cfg   = config.get_db_sync()
    raw_path = db_cfg.get("SQLITE_PATH", "app/.hub_state.db")
    
    # HF Spaces: SPACE_ID is set → filesystem is read-only except /tmp/
    import os
    if os.getenv("SPACE_ID"):
        filename = os.path.basename(raw_path)
        _db_path = f"/tmp/{filename}"
        logger.info(f"HF Space detected — SQLite relocated to {_db_path}")
    else:
        _db_path = raw_path

    await _init_tables()

    _initialized = True
    logger.info(f"db_sync initialized — path: {_db_path}")


# =============================================================================
# SECTION 1 — Table Setup (app/* tables only!)
# =============================================================================

async def _init_tables() -> None:
    """
    Creates app/* internal tables if they don't exist.
    NEVER modifies Guardian tables (users, sessions).
    """
    async with aiosqlite.connect(_db_path) as db:

        # hub_state — generic key/value store for app/* modules
        await db.execute("""
            CREATE TABLE IF NOT EXISTS hub_state (
                key        TEXT PRIMARY KEY,
                value      TEXT,
                updated_at TEXT
            )
        """)

        # tool_cache — cached tool responses to reduce API calls
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tool_cache (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name  TEXT NOT NULL,
                prompt     TEXT NOT NULL,
                response   TEXT NOT NULL,
                provider   TEXT,
                model      TEXT,
                created_at TEXT
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_tool_cache_tool
            ON tool_cache(tool_name)
        """)

        await db.commit()

    logger.info("db_sync tables ready.")


# =============================================================================
# SECTION 2 — Key/Value Store (hub_state table)
# =============================================================================

async def write(key: str, value: Any) -> None:
    """
    Write a value to hub_state key/value store.
    Value is JSON-serialized — supports dicts, lists, strings, numbers.

    Args:
        key:   Unique key string (e.g. 'scheduler.last_run').
        value: Any JSON-serializable value.
    """
    _check_init()
    now = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(_db_path) as db:
        await db.execute("""
            INSERT OR REPLACE INTO hub_state (key, value, updated_at)
            VALUES (?, ?, ?)
        """, (key, json.dumps(value), now))
        await db.commit()


async def read(key: str, default: Any = None) -> Any:
    """
    Read a value from hub_state key/value store.
    Returns default if key does not exist.

    Args:
        key:     Key string to look up.
        default: Default value if key not found. Default: None.

    Returns:
        Deserialized value, or default if not found.
    """
    _check_init()

    async with aiosqlite.connect(_db_path) as db:
        cursor = await db.execute(
            "SELECT value FROM hub_state WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()

    if row is None:
        return default

    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return row[0]


async def delete(key: str) -> None:
    """
    Delete a key from hub_state.

    Args:
        key: Key string to delete.
    """
    _check_init()

    async with aiosqlite.connect(_db_path) as db:
        await db.execute("DELETE FROM hub_state WHERE key = ?", (key,))
        await db.commit()


# =============================================================================
# SECTION 3 — Tool Cache (tool_cache table)
# =============================================================================

async def cache_write(
    tool_name: str,
    prompt: str,
    response: str,
    provider: str = None,
    model: str = None,
) -> None:
    """
    Cache a tool response to reduce redundant API calls.

    Args:
        tool_name: Tool name (e.g. 'llm_complete', 'web_search').
        prompt:    The input prompt/query that was used.
        response:  The response to cache.
        provider:  Provider name used (optional).
        model:     Model name used (optional).
    """
    _check_init()

    db_cfg      = config.get_db_sync()
    max_entries = int(db_cfg.get("MAX_CACHE_ENTRIES", "1000"))
    now         = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(_db_path) as db:
        await db.execute("""
            INSERT INTO tool_cache (tool_name, prompt, response, provider, model, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (tool_name, prompt, response, provider, model, now))

        # Enforce MAX_CACHE_ENTRIES — delete oldest if exceeded
        await db.execute("""
            DELETE FROM tool_cache WHERE id NOT IN (
                SELECT id FROM tool_cache ORDER BY created_at DESC LIMIT ?
            )
        """, (max_entries,))

        await db.commit()


async def cache_read(tool_name: str, prompt: str) -> Optional[str]:
    """
    Read a cached tool response.
    Returns None if no cache entry exists.

    Args:
        tool_name: Tool name to look up.
        prompt:    The exact prompt/query to match.

    Returns:
        Cached response string, or None if not found.
    """
    _check_init()

    async with aiosqlite.connect(_db_path) as db:
        cursor = await db.execute("""
            SELECT response FROM tool_cache
            WHERE tool_name = ? AND prompt = ?
            ORDER BY created_at DESC LIMIT 1
        """, (tool_name, prompt))
        row = await cursor.fetchone()

    return row[0] if row else None


# =============================================================================
# SECTION 4 — Read-Only Query (for mcp.py db_query tool)
# =============================================================================

async def query(sql: str) -> List[Dict]:
    """
    Execute a read-only SELECT query on the internal hub state database.
    Only SELECT statements are permitted — write operations are blocked.
    Called by mcp.py db_query tool when db_sync.py is active.

    Args:
        sql: SQL SELECT statement to execute.

    Returns:
        List of result rows as dicts.

    Raises:
        ValueError: If the query is not a SELECT statement.
    """
    _check_init()

    if not sql.strip().upper().startswith("SELECT"):
        raise ValueError("Only SELECT queries are permitted in db_query tool.")

    async with aiosqlite.connect(_db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(sql)
        rows   = await cursor.fetchall()
        return [dict(r) for r in rows]


# =============================================================================
# SECTION 5 — Helpers
# =============================================================================

def _check_init() -> None:
    """Raise RuntimeError if db_sync was not initialized."""
    if not _initialized or not _db_path:
        raise RuntimeError("db_sync not initialized — call initialize() first.")


def is_ready() -> bool:
    """Returns True if db_sync is initialized and ready."""
    return _initialized and _db_path is not None


# =============================================================================
# SECTION 6 — PostgreSQL Bridge (Guardian-injected, optional)
# =============================================================================
_psql_writer = None


def set_psql_writer(writer_fn) -> None:
    """
    Receives execute_secured_query callable from Guardian via app.py.
    Called once in start_application() if db_service is available.
    app/* never imports postgresql.py directly — this is the only bridge.
    """
    global _psql_writer
    _psql_writer = writer_fn
    logger.info("PostgreSQL writer registered.")


async def persist(table: str, data: dict) -> None:
    if not _psql_writer:
        raise RuntimeError("No PostgreSQL writer — DATABASE_URL not configured.")

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    # asyncpg Pool.execute() Signatur: execute(query, *args)
    # kein fetch_method Parameter — direkt aufrufen
    sql = f"INSERT INTO {table} (payload, created_at) VALUES ($1::jsonb, $2)"
    await _psql_writer(sql, json.dumps(data), now)
    logger.info(f"Persisted to PostgreSQL table '{table}'.")

# =============================================================================
# Direct execution guard
# =============================================================================

if __name__ == "__main__":
    print("WARNING: Run via main.py → app.py, not directly.")
