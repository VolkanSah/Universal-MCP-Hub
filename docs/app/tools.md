## Datei: `app/tools.py`

**Beschreibung:** Zentrales Tool-Registry-Modul, das als modularer Wrapper für den Universal MCP Hub fungiert. Es verwaltet die Konfiguration und Ausführung von Tools in einer isolierten Sandbox-Umgebung.

### Hauptfunktionen:

* **`initialize()`**: Lädt alle aktiven Tools aus der `.pyfun`-Konfiguration in ein internes Register (`_registry`).
* **`run()`**: Die zentrale Ausführungsschnittstelle. Sie prüft die Tool-Konfiguration, bereitet den Prompt auf und delegiert die Anfrage an den passenden Provider (LLM, Search oder DB).
* **Registry-Helper (`get`, `get_description`, etc.)**: Diverse Hilfsfunktionen zum Auslesen spezifischer Tool-Parameter (Beschreibungen, Timeouts, System-Prompts) direkt aus dem Register.
* **Listen-Funktionen (`list_all`, `list_by_type`)**: Gibt Übersichten über alle verfügbaren Tools oder filtert diese nach Typ (z. B. nur LLM-Tools).

### Kern-Logik:

Das Skript folgt dem **"Single Source of Truth"**-Prinzip: Tools werden ausschließlich über die externe Konfiguration definiert. Es findet keine direkte API-Kommunikation statt; `tools.py` dient rein als logische Schicht zwischen der Konfiguration (`config.py`) und der technischen Ausführung (`providers.py`).
