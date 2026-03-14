## File: `app/db_sync.py`

**Description:** This module manages the hub's internal state via a local SQLite database. It serves as a persistent IPC store for app-specific data and tool responses — completely separate from the Guardian-layer cloud database.

### Main Functions

- **`initialize()`**: Sets the database path (including special handling for HuggingFace Spaces where `/tmp/` must be used) and creates the required tables.
- **Key/Value store (`write`, `read`, `delete`)**: Allows other modules to store simple data (status messages, runtime state) JSON-serialized in the `hub_state` table.
- **Tool caching (`cache_write`, `cache_read`)**: Stores tool responses in `tool_cache` to avoid redundant API calls and reduce costs. Automatically enforces a configurable entry limit.
- **`query()`**: Exposes SQL query access but strictly limits it to **read-only** (`SELECT` only) to protect data integrity.

### Core Logic

The module enforces strict **table ownership**: it only manages `hub_state` and `tool_cache`. Access to system-critical tables (`users`, `sessions`) is not possible from this layer — those belong exclusively to `fundaments/user_handler.py`. All configuration comes from `config.py` — no direct environment variable access.




### Bald

Zwei Tabellen zum Testen:
- `hub_state` — key/value store
- `tool_cache` — gecachte Tool-Responses

Test-Fragen für den Showcase mit dem HUb

**hub_state testen:**
```
[db_query]: SELECT * FROM hub_state
[db_query]: SELECT key, value FROM hub_state WHERE key = 'test'
[db_query]: SELECT count(*) FROM hub_state
```

**tool_cache testen:**
```
[db_query]: SELECT * FROM tool_cache
[db_query]: SELECT tool_name, prompt, provider FROM tool_cache
[db_query]: SELECT count(*) FROM tool_cache
[db_query]: SELECT tool_name, count(*) as calls FROM tool_cache GROUP BY tool_name
[db_query]: SELECT * FROM tool_cache ORDER BY created_at DESC LIMIT 5
```

**Security Test (sollte REJECT geben):**
```
[db_query]: SELECT * FROM users
[db_query]: DROP TABLE hub_state
[db_query]: INSERT INTO hub_state VALUES ('hack', 'test', '2026')
[db_query]: from hub_state
```

Die letzten vier sind wichtig den es zeigt dass der Hub sich schützt! 

