# =============================================================================
# mcp_desktop.py
# Universal MCP Desktop Client
# Copyright 2026 - Volkan Kücükbudak
# Apache License V. 2 + ESOL 1.1
# Repo: https://github.com/VolkanSah/Universal-MCP-Hub-sandboxed
# =============================================================================
# USAGE:
#   pip install PySide6 httpx mcp
#   python mcp_desktop.py
#
# CONNECT:
#   1. Enter HF Token (hf_...)
#   2. Enter Hub URL (https://your-space.hf.space)
#   3. Click Connect
# =============================================================================

import sys
import json
import asyncio
import httpx
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QTextEdit, QLabel, QTabWidget,
    QStatusBar, QComboBox, QSplitter, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont, QColor, QPalette, QIcon

# =============================================================================
# Config — local ~/.mcp_desktop.json
# =============================================================================
CONFIG_PATH = Path.home() / ".mcp_desktop.json"

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    return {"hf_token": "", "hub_url": "", "last_model": ""}

def save_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    except Exception:
        pass

# =============================================================================
# Async Worker — runs coroutines in background thread
# =============================================================================
class AsyncWorker(QObject):
    result  = Signal(str)
    error   = Signal(str)
    log     = Signal(str)
    tools   = Signal(dict)
    status  = Signal(str)

    def __init__(self, hub_url: str, hf_token: str):
        super().__init__()
        self.hub_url   = hub_url.rstrip("/")
        self.hf_token  = hf_token
        self.headers   = {"Authorization": f"Bearer {hf_token}"}

    def _run(self, coro):
        """Run coroutine in new event loop."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def health_check(self):
        async def _do():
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.get(
                        f"{self.hub_url}/",
                        headers=self.headers,
                        timeout=10
                    )
                    data = r.json()
                    self.status.emit(f"● connected — uptime: {data.get('uptime_seconds', '?')}s")
                    self.log.emit(f"[health] {json.dumps(data)}")
            except Exception as e:
                self.status.emit(f"✗ disconnected")
                self.error.emit(f"Health check failed: {e}")
        self._run(_do())

    def fetch_tools(self):
        async def _do():
            try:
                async with httpx.AsyncClient() as client:
                    # Call list_active_tools via /api
                    r = await client.post(
                        f"{self.hub_url}/api",
                        headers={**self.headers, "Content-Type": "application/json"},
                        json={"tool": "list_active_tools", "params": {}},
                        timeout=15
                    )
                    data = r.json()
                    self.tools.emit(data)
                    self.log.emit(f"[tools] {json.dumps(data)}")
            except Exception as e:
                self.error.emit(f"Fetch tools failed: {e}")
        self._run(_do())

    def llm_complete(self, prompt: str, model: str = None):
        async def _do():
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.post(
                        f"{self.hub_url}/api",
                        headers={**self.headers, "Content-Type": "application/json"},
                        json={
                            "tool":   "llm_complete",
                            "params": {
                                "prompt":     prompt,
                                "model":      model or "",
                                "max_tokens": 1024,
                            }
                        },
                        timeout=60
                    )
                    data = r.json()
                    response = data.get("result", data.get("error", str(data)))
                    self.result.emit(response)
                    self.log.emit(f"[llm] prompt: {prompt[:50]}...")
            except Exception as e:
                self.error.emit(f"LLM call failed: {e}")
        self._run(_do())

    def web_search(self, query: str):
        async def _do():
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.post(
                        f"{self.hub_url}/api",
                        headers={**self.headers, "Content-Type": "application/json"},
                        json={
                            "tool":   "web_search",
                            "params": {"query": query, "max_results": 5}
                        },
                        timeout=30
                    )
                    data = r.json()
                    response = data.get("result", data.get("error", str(data)))
                    self.result.emit(response)
                    self.log.emit(f"[search] query: {query}")
            except Exception as e:
                self.error.emit(f"Search failed: {e}")
        self._run(_do())


# =============================================================================
# Worker Thread
# =============================================================================
class WorkerThread(QThread):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        self.fn()


# =============================================================================
# Main Window
# =============================================================================
class MCPDesktop(QMainWindow):

    STYLE = """
        QMainWindow, QWidget {
            background-color: #0d1117;
            color: #e6edf3;
            font-family: 'JetBrains Mono', 'Consolas', monospace;
            font-size: 13px;
        }
        QTabWidget::pane {
            border: 1px solid #21262d;
            background: #0d1117;
        }
        QTabBar::tab {
            background: #161b22;
            color: #8b949e;
            padding: 8px 20px;
            border: 1px solid #21262d;
            border-bottom: none;
        }
        QTabBar::tab:selected {
            background: #0d1117;
            color: #58a6ff;
            border-bottom: 2px solid #58a6ff;
        }
        QTabBar::tab:hover {
            color: #e6edf3;
        }
        QLineEdit {
            background: #161b22;
            border: 1px solid #21262d;
            border-radius: 4px;
            padding: 6px 10px;
            color: #e6edf3;
        }
        QLineEdit:focus {
            border-color: #58a6ff;
        }
        QTextEdit {
            background: #161b22;
            border: 1px solid #21262d;
            border-radius: 4px;
            padding: 8px;
            color: #e6edf3;
            font-family: 'JetBrains Mono', 'Consolas', monospace;
        }
        QPushButton {
            background: #21262d;
            color: #e6edf3;
            border: 1px solid #30363d;
            border-radius: 4px;
            padding: 6px 16px;
            font-weight: bold;
        }
        QPushButton:hover {
            background: #30363d;
            border-color: #58a6ff;
            color: #58a6ff;
        }
        QPushButton:pressed {
            background: #161b22;
        }
        QPushButton#connect_btn {
            background: #238636;
            border-color: #2ea043;
            color: #ffffff;
        }
        QPushButton#connect_btn:hover {
            background: #2ea043;
        }
        QPushButton#send_btn {
            background: #1f6feb;
            border-color: #388bfd;
            color: #ffffff;
            min-width: 80px;
        }
        QPushButton#send_btn:hover {
            background: #388bfd;
        }
        QComboBox {
            background: #161b22;
            border: 1px solid #21262d;
            border-radius: 4px;
            padding: 6px 10px;
            color: #e6edf3;
        }
        QComboBox::drop-down {
            border: none;
        }
        QComboBox QAbstractItemView {
            background: #161b22;
            border: 1px solid #30363d;
            color: #e6edf3;
            selection-background-color: #21262d;
        }
        QStatusBar {
            background: #161b22;
            color: #8b949e;
            border-top: 1px solid #21262d;
            font-size: 12px;
        }
        QLabel#section_label {
            color: #8b949e;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        QLabel#status_dot {
            color: #3fb950;
            font-size: 16px;
        }
        QSplitter::handle {
            background: #21262d;
        }
    """

    def __init__(self):
        super().__init__()
        self.cfg    = load_config()
        self.worker = None

        self.setWindowTitle("Universal MCP Desktop")
        self.setMinimumSize(900, 650)
        self.setStyleSheet(self.STYLE)

        self._build_ui()
        self._status("✗ not connected")

    # =========================================================================
    # UI Build
    # =========================================================================
    def _build_ui(self):
        central = QWidget()
        layout  = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Header ---
        header = self._build_header()
        layout.addWidget(header)

        # --- Tabs ---
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_connect(),  "⚡ Connect")
        self.tabs.addTab(self._tab_chat(),     "💬 Chat")
        self.tabs.addTab(self._tab_tools(),    "🛠 Tools")
        self.tabs.addTab(self._tab_logs(),     "📋 Logs")
        layout.addWidget(self.tabs)

        self.setCentralWidget(central)

        # --- Status Bar ---
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(48)
        header.setStyleSheet("background: #161b22; border-bottom: 1px solid #21262d;")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 0, 16, 0)

        title = QLabel("⬡ Universal MCP Desktop")
        title.setStyleSheet("color: #58a6ff; font-size: 15px; font-weight: bold;")
        layout.addWidget(title)

        layout.addStretch()

        self.status_label = QLabel("✗ not connected")
        self.status_label.setStyleSheet("color: #8b949e; font-size: 12px;")
        layout.addWidget(self.status_label)

        return header

    # =========================================================================
    # Tab: Connect
    # =========================================================================
    def _tab_connect(self) -> QWidget:
        tab    = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        layout.addWidget(self._section("HuggingFace Token"))
        self.token_input = QLineEdit(self.cfg.get("hf_token", ""))
        self.token_input.setPlaceholderText("hf_...")
        self.token_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.token_input)

        layout.addWidget(self._section("Hub URL"))
        self.url_input = QLineEdit(self.cfg.get("hub_url", ""))
        self.url_input.setPlaceholderText("https://your-space.hf.space")
        layout.addWidget(self.url_input)

        btn_row = QHBoxLayout()
        connect_btn = QPushButton("🔌 Connect")
        connect_btn.setObjectName("connect_btn")
        connect_btn.clicked.connect(self._connect)
        btn_row.addWidget(connect_btn)

        health_btn = QPushButton("❤ Health Check")
        health_btn.clicked.connect(self._health_check)
        btn_row.addWidget(health_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addStretch()

        # Info box
        info = QTextEdit()
        info.setReadOnly(True)
        info.setMaximumHeight(120)
        info.setPlainText(
            "Token and URL are saved locally in ~/.mcp_desktop.json\n"
            "Token is required for private HuggingFace Spaces.\n"
            "Hub URL format: https://owner-space-name.hf.space"
        )
        info.setStyleSheet("color: #8b949e; background: #0d1117; border: none; font-size: 12px;")
        layout.addWidget(info)

        return tab

    # =========================================================================
    # Tab: Chat
    # =========================================================================
    def _tab_chat(self) -> QWidget:
        tab    = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # Model selector
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model:"))
        self.model_select = QComboBox()
        self.model_select.addItem("default (from .pyfun)")
        self.model_select.setMinimumWidth(250)
        model_row.addWidget(self.model_select)
        model_row.addStretch()
        layout.addLayout(model_row)

        # Chat output
        self.chat_output = QTextEdit()
        self.chat_output.setReadOnly(True)
        self.chat_output.setPlaceholderText("Responses appear here...")
        layout.addWidget(self.chat_output)

        # Input row
        input_row = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Enter prompt...")
        self.chat_input.returnPressed.connect(self._send_chat)
        input_row.addWidget(self.chat_input)

        send_btn = QPushButton("Send ▶")
        send_btn.setObjectName("send_btn")
        send_btn.clicked.connect(self._send_chat)
        input_row.addWidget(send_btn)
        layout.addLayout(input_row)

        return tab

    # =========================================================================
    # Tab: Tools
    # =========================================================================
    def _tab_tools(self) -> QWidget:
        tab    = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("↻ Refresh Tools")
        refresh_btn.clicked.connect(self._fetch_tools)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.tools_output = QTextEdit()
        self.tools_output.setReadOnly(True)
        self.tools_output.setPlaceholderText("Connect to hub first, then refresh...")
        layout.addWidget(self.tools_output)

        return tab

    # =========================================================================
    # Tab: Logs
    # =========================================================================
    def _tab_logs(self) -> QWidget:
        tab    = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("🗑 Clear Logs")
        clear_btn.clicked.connect(lambda: self.log_output.clear())
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("Logs appear here...")
        layout.addWidget(self.log_output)

        return tab

    # =========================================================================
    # Helpers
    # =========================================================================
    def _section(self, text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setObjectName("section_label")
        label.setStyleSheet("color: #8b949e; font-size: 11px; margin-top: 8px;")
        return label

    def _status(self, text: str):
        self.status_label.setText(text)
        self.status_bar.showMessage(text)
        if "connected" in text and "not" not in text:
            self.status_label.setStyleSheet("color: #3fb950; font-size: 12px;")
        else:
            self.status_label.setStyleSheet("color: #f85149; font-size: 12px;")

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_output.append(f"[{ts}] {msg}")

    def _make_worker(self) -> AsyncWorker:
        return AsyncWorker(
            hub_url=self.url_input.text().strip(),
            hf_token=self.token_input.text().strip(),
        )

    def _run_in_thread(self, fn):
        t = WorkerThread(fn)
        t.start()
        self._thread = t  # keep reference

    # =========================================================================
    # Actions
    # =========================================================================
    def _connect(self):
        token = self.token_input.text().strip()
        url   = self.url_input.text().strip()

        if not token or not url:
            self._status("✗ token and URL required!")
            return

        # Save config
        self.cfg["hf_token"] = token
        self.cfg["hub_url"]  = url
        save_config(self.cfg)

        self._status("… connecting")
        self._log(f"Connecting to {url}...")

        w = self._make_worker()
        w.status.connect(self._status)
        w.error.connect(lambda e: self._log(f"ERROR: {e}"))
        w.log.connect(self._log)
        self._run_in_thread(w.health_check)

    def _health_check(self):
        w = self._make_worker()
        w.status.connect(self._status)
        w.error.connect(lambda e: self._log(f"ERROR: {e}"))
        w.log.connect(self._log)
        self._run_in_thread(w.health_check)

    def _fetch_tools(self):
        w = self._make_worker()
        w.tools.connect(self._on_tools)
        w.error.connect(lambda e: self._log(f"ERROR: {e}"))
        w.log.connect(self._log)
        self._run_in_thread(w.fetch_tools)

    def _on_tools(self, data: dict):
        self.tools_output.setPlainText(json.dumps(data, indent=2))

        # Populate model selector
        models = data.get("available_models", [])
        self.model_select.clear()
        self.model_select.addItem("default (from .pyfun)")
        for m in models:
            self.model_select.addItem(m)
        self._log(f"Tools loaded: {data.get('active_tools', [])}")

    def _send_chat(self):
        prompt = self.chat_input.text().strip()
        if not prompt:
            return

        model = self.model_select.currentText()
        if "default" in model:
            model = None

        self.chat_output.append(f"\n▶ You: {prompt}")
        self.chat_input.clear()
        self._log(f"Sending prompt: {prompt[:50]}...")

        w = self._make_worker()
        w.result.connect(lambda r: self.chat_output.append(f"⬡ Hub: {r}\n"))
        w.error.connect(lambda e: self.chat_output.append(f"✗ Error: {e}\n"))
        w.log.connect(self._log)
        self._run_in_thread(lambda: w.llm_complete(prompt, model))


# =============================================================================
# Entry Point
# =============================================================================
if __name__ == "__main__":
    app    = QApplication(sys.argv)
    window = MCPDesktop()
    window.show()
    sys.exit(app.exec())
