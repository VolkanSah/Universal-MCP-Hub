## Universal MCP Desktop Client
#### Perfect for private & non-public HuggingFace Spaces

A standalone PySide6 desktop client is included: `hub.py`

```bash
pip install PySide6 httpx
# optional file handling:
pip install Pillow PyPDF2 pandas openpyxl
python mcp_desktop.py
```

### Features

**💬 Multi-Chat**
- Multiple chat sessions — sorted by date, persistent across restarts
- Create, switch and delete chats via dropdown
- Full history saved locally in `~/.mcp_desktop.json`

**🛠 Tool Selector**
- Select any active Hub tool directly in the header bar: `llm_complete`, `summarize`, `translate`, `code_review`, `db_query` and more
- Tools, Providers and Models are loaded automatically after connect
- No `@tool` syntax needed — just select and type

**📎 File Attachments**
- Attach files directly to your prompt
- Supported: Images (jpg, png), Text & Code (py, php, js, html, css...), PDF, CSV, Excel, ZIP
- ZIP files are extracted and all readable text files are passed to the Hub
- File content is prepended to your prompt automatically

**⚙ Settings (separate from Connect!)**
- HF Token + Hub URL — saved locally, never sent anywhere except your own Hub
- Default Provider + Model override (optional)
- Font size — applies immediately

**🔌 Connect Tab**
- Health Check + auto-load Tools/Providers/Models in one click
- Token status indicator

**📋 Logs**
- All requests, responses and errors — timestamped

### Quick Start
1. Open **⚙ Settings** — enter HF Token + Hub URL → Save
2. Open **🔌 Connect** → Connect
3. Tools/Providers/Models load automatically into header dropdowns
4. Select Tool → type prompt → Send ▶

### Notes
- Token never leaves your machine except to your own Hub
- Works on Windows, Linux, macOS
- Config saved to `~/.mcp_desktop.json`
- Optional dependencies degrade gracefully — app runs without Pillow/PyPDF2/pandas

---

> **About this GUI**
> 
> Built after an extremely long session with Claude AI — teaching it what a *real* MCP server looks like. Inspired by ShellMaster (2022/2023) which gave browsers shell access before MCP was even a concept.
> 
> This is not a prompt collection dressed up as an MCP server. This is the real thing.
> 
> Share love & security — read the license files! 🛡️
