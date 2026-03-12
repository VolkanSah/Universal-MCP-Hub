---
title: Multi-LLM API Gateway
emoji: 🛡️
colorFrom: indigo
colorTo: red
sdk: docker
pinned: false
license: apache-2.0
short_description: 'Multi-LLM API Gateway with MCP'
---

# Multi-LLM API Gateway with MCP interface
— or Universal MCP Hub (Sandboxed)  
— or universal AI Wrapper over SSE + Quart with some tools on a solid fundament

aka: a clean, secure starting point for your own projects.
Pick the description that fits your use case. They're all correct.

> A production-grade - **the-thing** -  that actually thinks about security.  
> Built on [PyFundaments](PyFundaments.md) — running on **simpleCity**.

```
No key → no tool → no crash → no exposed secrets
```

:warning:   Most MCP servers are prompts dressed up as servers. This one has a real architecture.

---

## Why this exists

While building this, we kept stumbling over the same problem — the AI (+mcp)
ecosystem is full of servers with hardcoded keys, `os.environ` scattered 
everywhere, zero sandboxing. One misconfigured fork and your API keys are gone.

This is exactly the kind of negligence (and worse — outright fraud) that 
[Wall of Shames](https://github.com/Wall-of-Shames) documents: a 
community project exposing fake "AI tools" that exploit non-technical users 
— API wrappers dressed up as custom models, Telegram payment funnels, 
bought stars. If you build on open source, you should know this exists.

This hub was built as the antidote:

- **Structural sandboxing** — `app/*` can never touch `fundaments/` or `.env`. Not by convention. By design.
- **Guardian pattern** — `main.py` is the only process that reads secrets. It injects validated services as a dict. `app/*` never sees the raw environment.
- **Graceful degradation** — No key? Tool doesn't register. Server still starts. No crash, no error, no empty `None` floating around.
- **Single source of truth** — All tool/provider/model config lives in `app/.pyfun`. Adding a provider = edit one file. No code changes.

---

## Architecture

```
main.py (Guardian)
│
│  reads .env / HF Secrets
│  initializes fundaments/* conditionally
│  injects validated services as dict
│
└──► app/app.py (Orchestrator, sandboxed)
     │
     │  unpacks fundaments ONCE, at startup, never stores globally
     │  starts hypercorn (async ASGI)
     │  routes: GET / | POST /api | GET+POST /mcp
     │
     ├── app/mcp.py         ← FastMCP + SSE handler
     ├── app/tools.py       ← Tool registry (key-gated)
     ├── app/provider.py    ← LLM + Search execution + fallback chain
     ├── app/models.py      ← Model limits, costs, capabilities
     ├── app/config.py      ← .pyfun parser (single source of truth)
     └── app/db_sync.py     ← Internal SQLite IPC (app/* state only)
                              ≠ fundaments/postgresql.py (Guardian-only)
```

**The sandbox is structural:**

```python
# app/app.py — fundaments are unpacked ONCE, NEVER stored globally
async def start_application(fundaments: Dict[str, Any]) -> None:
    config_service         = fundaments["config"]
    db_service             = fundaments["db"]          # None if not configured
    encryption_service     = fundaments["encryption"]  # None if keys missing
    access_control_service = fundaments["access_control"]
    ...
    # From here: app/* reads its own config from app/.pyfun only.
    # fundaments are never passed into other app/* modules.
```

`app/app.py` never calls `os.environ`. Never imports from `fundaments/`. Never reads `.env`.  
This isn't documentation. It's enforced by the import structure.

### Why Quart + hypercorn?

MCP over SSE needs a proper async HTTP stack. The choice here is deliberate:

**Quart** is async Flask — same API, same routing, but fully `async/await` native. This matters because FastMCP's SSE handler is async, and mixing sync Flask with async MCP would require thread hacks or `asyncio.run()` gymnastics. With Quart, the `/mcp` route hands off directly to `mcp.handle_sse(request)` — no bridging, no blocking.

**hypercorn** is an ASGI server (vs. waitress/gunicorn which are WSGI). WSGI servers handle one request per thread — fine for traditional web apps, wrong for SSE where a connection stays open for minutes. hypercorn handles SSE connections as long-lived async streams without tying up threads. It also runs natively on HuggingFace Spaces without extra config.

The `/mcp` route in `app.py` is also the natural interception point — auth checks, rate limiting, payload logging can all be added there before the request ever reaches FastMCP. That's not possible when FastMCP runs standalone.

---

## Two Databases — One Architecture

This hub runs **two completely separate databases** with distinct responsibilities. This is not redundancy — it's a deliberate performance and security decision.

```
┌─────────────────────────────────────────────────────────────┐
│  Guardian Layer (fundaments/*)                              │
│                                                             │
│  postgresql.py   → Cloud DB (e.g. Neon, Supabase)          │
│                    asyncpg pool, SSL enforced               │
│                    Neon-specific quirks handled             │
│                    (statement_timeout stripped, keepalives) │
│                                                             │
│  user_handler.py → SQLite (users + sessions tables)        │
│                    PBKDF2-SHA256 password hashing           │
│                    Session validation incl. IP + UserAgent  │
│                    Account lockout after 5 failed attempts  │
│                    Path: SQLITE_PATH env var or app/        │
│                                                             │
└──────────────────────┬──────────────────────────────────────┘
                       │ inject as fundaments dict
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  App Layer (app/*)                                          │
│                                                             │
│  db_sync.py  → SQLite (hub_state + tool_cache tables)      │
│                aiosqlite (async, non-blocking)              │
│                NEVER touches users/sessions tables          │
│                Relocated to /tmp/ on HF Spaces auto        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Why two SQLite databases?**

`user_handler.py` (Guardian) owns `users` and `sessions` — authentication state that must be isolated from the app layer. `db_sync.py` (app/*) owns `hub_state` and `tool_cache` — fast, async IPC between tools that doesn't need to leave the process, let alone hit a cloud endpoint.

A tool caching a previous LLM response or storing intermediate state between pipeline steps should never wait on a round-trip to Neon. Local SQLite is microseconds. Cloud PostgreSQL is 50-200ms per query. For tool-to-tool communication, that difference matters.

**Table ownership — hard rule:**

| Table | Owner | Access |
| :--- | :--- | :--- |
| `users` | `fundaments/user_handler.py` | Guardian only |
| `sessions` | `fundaments/user_handler.py` | Guardian only |
| `hub_state` | `app/db_sync.py` | app/* only |
| `tool_cache` | `app/db_sync.py` | app/* only |

`db_sync.py` uses the same SQLite path (`SQLITE_PATH`) as `user_handler.py` — same file, different tables, zero overlap. The `db_query` MCP tool exposes SELECT-only access to `hub_state` and `tool_cache`. It cannot reach `users` or `sessions`.

**Cloud DB (postgresql.py):**

Handles the heavy cases — persistent storage, workflow tool results that need to survive restarts, anything that benefits from a real relational DB. Neon-specific quirks are handled automatically: `statement_timeout` is stripped from the DSN (e.g. Neon doesn't support it), SSL is enforced at `require` minimum, keepalives are set, and terminated connections trigger an automatic pool restart.

If no `DATABASE_URL` is set, the entire cloud DB layer is skipped cleanly. The app runs without it.

---

## Tools

Tools register themselves at startup — only if the required API key exists in the environment. No key, no tool. The server always starts.

| ENV Secret | Tool | Notes |
| :--- | :--- | :--- |
| `ANTHROPIC_API_KEY` | `llm_complete` | Claude Haiku / Sonnet / Opus |
| `GEMINI_API_KEY` | `llm_complete` | Gemini 2.0 / 2.5 / 3.x Flash & Pro |
| `OPENROUTER_API_KEY` | `llm_complete` | 100+ models via OpenRouter |
| `HF_TOKEN` | `llm_complete` | HuggingFace Inference API |
| `BRAVE_API_KEY` | `web_search` | Independent web index |
| `TAVILY_API_KEY` | `web_search` | AI-optimized search with synthesized answers |
| `DATABASE_URL` | `cloud DB` | e.g. NEON_DB
| *(always)* | `list_active_tools` | Shows key names only — never values |
| *(always)* | `health_check` | Status + uptime |
| *(always)* | `get_model_info` | Limits, costs, capabilities per model |

for more key values see [`.pyfun](app/.pyfun) file

**Configured in `.pyfun` — not hardcoded: your Prompts**

##### example
```ini
[TOOL.code_review]
active           = "true"
description      = "Review code for bugs, security issues and improvements"
provider_type    = "llm"
default_provider = "anthropic"
timeout_sec      = "60"
system_prompt    = "You are an expert code reviewer. Analyze the given code for bugs, security issues, and improvements. Be specific and concise."
[TOOL.code_review_END]
```

Current built-in tools: `llm_complete`, `code_review`, `summarize`, `translate`, `web_search`, `db_query`  
Future hooks (commented, ready): `image_gen`, `code_exec`, `shellmaster_2.0`, Discord, GitHub webhooks

---

## LLM Fallback Chain

All LLM providers share one `llm_complete` tool. If a provider fails, the hub automatically walks the fallback chain defined in `.pyfun`:

```
e.g. anthropic → gemini → openrouter → huggingface
```

Fallbacks are configured per-provider, not hardcoded:

```ini
[LLM_PROVIDER.anthropic]
fallback_to = "gemini"
[LLM_PROVIDER.anthropic_END]

[LLM_PROVIDER.gemini]
fallback_to = "openrouter"
[LLM_PROVIDER.gemini_END]
```

Same pattern applies to search providers (`brave → tavily`) aand your owns.

---

## Quick Start

### HuggingFace Spaces (recommended) or similar

1. Fork / duplicate this Space/Repo
2. Go to **Settings → Variables and secrets**
3. Add the API keys you have (any subset works)
4. Space starts automatically — only tools with valid keys register

That's it. No config editing. No code changes.

[→ Live SSE-Demo Space](https://huggingface.co/spaces/codey-lab/Multi-LLM-API-Gateway) (no LLM keys set!)

### Local / Docker

```bash
git clone https://github.com/VolkanSah/Multi-LLM-API-Gateway
cd Multi-LLM-API-Gateway
cp example-mcp___.env .env
# fill in your keys
pip install -r requirements.txt
python main.py
```

Minimum required ENV vars (everything else is optional):

```env
PYFUNDAMENTS_DEBUG=""
LOG_LEVEL="INFO"
LOG_TO_TMP=""
ENABLE_PUBLIC_LOGS="true"
HF_TOKEN=""
HUB_SPACE_URL=""
MCP_TRANSPORT="sse"
```

---

## Connect an MCP Client

### Claude Desktop / any SSE-compatible client
> CD - have never use it, please feedback!

```json
{
  "mcpServers": {
    "universal-mcp-hub": {
      "url": "https://YOUR_USERNAME-universal-mcp-hub.hf.space/sse"
    }
  }
}
```

### Private Space (with HF token)

```json
{
  "mcpServers": {
    "universal-mcp-hub": {
      "url": "https://YOUR_USERNAME-universal-mcp-hub.hf.space/sse",
      "headers": {
        "Authorization": "Bearer hf_..."
      }
    }
  }
}
```

---

## Desktop Client
###### (experementiel ~80 % AI generated)

A full PySide6 desktop client is included in `DESKTOP_CLIENT/hub.py` — ideal for private or non-public Spaces where you don't want to expose the SSE endpoint.

```bash
pip install PySide6 httpx
# optional file handling:
pip install Pillow PyPDF2 pandas openpyxl
python DESKTOP_CLIENT/hub.py
```

**Features:**
- Multi-chat with persistent history (`~/.mcp_desktop.json`)
- Tool/Provider/Model selector loaded live from your Hub
- File attachments: images, PDF, CSV, Excel, ZIP, source code
- Connect tab with health check + auto-load
- Settings: HF Token + Hub URL saved locally, never sent anywhere except your own Hub
- Full request/response log with timestamps
- Runs on Windows, Linux, macOS

[→ Desktop Client docs](DESKTOP_CLIENT/README.md)

---

## Configuration (.pyfun)

`app/.pyfun` is the single source of truth for all app behavior. Three tiers — use what you need:

```
LAZY:       [HUB] + one [LLM_PROVIDER.*]                    → works
NORMAL:     + [SEARCH_PROVIDER.*] + [MODELS.*]              → works better  
PRODUCTIVE: + [TOOLS] + [HUB_LIMITS] + [DB_SYNC]           → full power
```

Adding a new LLM provider requires two steps — `.pyfun` + one line in `providers.py`:

```ini
# 1. app/.pyfun — add provider block
[LLM_PROVIDER.mistral]
active        = "true"
base_url      = "https://api.mistral.ai/v1"
env_key       = "MISTRAL_API_KEY"
default_model = "mistral-large-latest"
models        = "mistral-large-latest, mistral-small-latest, codestral-latest"
fallback_to   = ""
[LLM_PROVIDER.mistral_END]
```

```python
# 2. app/providers.py — uncomment the dummy + register it
_PROVIDER_CLASSES = {
    ...
    "mistral": MistralProvider,   # ← uncomment to activate
}
```

`providers.py` ships with ready-to-use commented dummy classes for OpenAI, Mistral, and xAI/Grok — each with the matching `.pyfun` block right above it. Most OpenAI-compatible APIs need zero changes to the class itself, just a different `base_url` and `env_key`. Search providers (Brave, Tavily) follow the same pattern and are next on the roadmap.

Model limits, costs, and capabilities are also configured here — `get_model_info` reads directly from `.pyfun`:

```ini
[MODEL.claude-sonnet-4-6]
provider           = "anthropic"
context_tokens     = "200000"
max_output_tokens  = "16000"
requests_per_min   = "50"
cost_input_per_1k  = "0.003"
cost_output_per_1k = "0.015"
capabilities       = "text, code, analysis, vision"
[MODEL.claude-sonnet-4-6_END]
```

---

## Dependencies

```
# PyFundaments Core (always required)
asyncpg          — async PostgreSQL pool (Guardian/cloud DB)
python-dotenv    — .env loading
passlib          — PBKDF2 password hashing in user_handler.py
cryptography     — encryption layer in fundaments/

# MCP Hub
fastmcp          — MCP protocol + tool registration
httpx            — async HTTP for all provider API calls
quart            — async Flask (ASGI) — needed for SSE + hypercorn
hypercorn        — ASGI server — long-lived SSE connections, HF Spaces native
requests         — sync HTTP for tool workers

# Optional (uncomment in requirements.txt as needed)
# aiofiles       — async file ops (ML pipelines, file uploads)
# discord.py     — Discord bot integration (app/discord_api.py, planned)
# PyNaCl         — Discord signature verification
# psycopg2-binary — alternative PostgreSQL driver
```

The core stack is intentionally lean. `asyncpg` + `quart` + `hypercorn` + `fastmcp` + `httpx` covers the full MCP server. Everything else is opt-in.

---

## Security Design

- API keys live in HF Secrets / `.env` — never in `.pyfun`, never in code
- `list_active_tools` returns key **names** only — never values
- `db_query` is SELECT-only, enforced at application level (not just docs)
- `app/*` has zero import access to `fundaments/` internals
- Direct execution of `app/app.py` is blocked by design — prints a warning and uses a null-fundaments dict
- `fundaments/` is initialized conditionally — missing services degrade gracefully, they don't crash

> PyFundaments is not perfect. But it's more secure than most of what runs in production today. 

[→ Full Security Policy](SECURITY.md)

---

## Foundation

This hub is built on [PyFundaments](PyFundaments.md) — a security-first Python boilerplate providing:

- `config_handler.py` — env loading with validation
- `postgresql.py` — async DB pool (Guardian-only)
- `encryption.py` — key-based encryption layer
- `access_control.py` — role/permission management
- `user_handler.py` — user lifecycle management  
- `security.py` — unified security manager composing the above

None of these are accessible from `app/*`. They are injected as a validated dict by `main.py`.

[→ PyFundaments Function Overview](PyFundaments%20–%20Function%20Overview.md)  
[→ Module Docs](docs/app/)
[→ Source of this REPO](https://github.com/VolkanSah/Multi-LLM-API-Gateway)

---

## History

[ShellMaster](https://github.com/VolkanSah/ChatGPT-ShellMaster) (2023, MIT) was the precursor — browser-accessible shell for ChatGPT with session memory via `/tmp/shellmaster_brain.log`, built before MCP was even a concept. Universal MCP Hub is its natural evolution.

---

## License

Dual-licensed:

- [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)
- [Ethical Security Operations License v1.1 (ESOL)](ESOL) — mandatory, non-severable

By using this software you agree to all ethical constraints defined in ESOL v1.1.

---

*Architecture, security decisions, and PyFundaments by Volkan Kücükbudak.*  
*Built with Claude (Anthropic) as a typing assistant for docs (in code, too) & the occasional bug.*

> crafted with passion — just wanted to understand how it works, don't actually need it, have a CLI 😄
