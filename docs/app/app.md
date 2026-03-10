## Datei: `app/app.py`

**Beschreibung:** Dies ist der **Orchestrator** der gesamten Sandbox-Anwendung. Die Datei fungiert als zentrale Schaltstelle, die den Webserver (Quart/Hypercorn) startet, die internen Module initialisiert und die Kommunikation nach außen (API & MCP) verwaltet.

### Hauptfunktionen:

* **`start_application()`**: Die Haupt-Einstiegsfunktion. Sie wird vom "Guardian" (`main.py`) aufgerufen und nimmt die injizierten Basis-Dienste (`fundaments`) entgegen. Hier wird entschieden, welche Features (Verschlüsselung, Auth, DB) basierend auf der Verfügbarkeit dieser Dienste aktiviert werden.
* **API-Endpoints**:
* **`/` (Health Check)**: Liefert Uptime und Status für Monitoring-Systeme (wichtig für HuggingFace Spaces).
* **`/api`**: Ein generischer REST-Einstiegspunkt, um Tools direkt via JSON-POST anzusprechen (z. B. für Systemabfragen oder manuelle Tool-Tests).
* **`/mcp`**: Der kritische Pfad für den **MCP SSE Transport**. Hier fließen alle Protokoll-Daten des Model Context Protocols durch.


* **Server-Management**: Nutzt **Hypercorn** (ein asynchroner ASGI-Server), um die Quart-App performant und nativ asynchron zu betreiben.

### Kern-Logik:

Die `app.py` setzt die **Sandbox-Regeln** strikt durch. Sie ist der einzige Ort, an dem die globalen `fundaments` (wie der PostgreSQL-Zugriff oder Verschlüsselungs-Keys) kurzzeitig existieren. Sie werden jedoch **nicht** an Untermodule wie `providers.py` oder `tools.py` weitergereicht. Diese Untermodule müssen autark arbeiten und ihre eigene Konfiguration aus der `.pyfun` beziehen.
