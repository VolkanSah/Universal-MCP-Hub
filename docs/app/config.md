## Datei: `app/config.py`

**Beschreibung:** Dieses Modul ist der zentrale Parser für die `.pyfun`-Datei. Es dient als **"Single Source of Truth"** für die gesamte App-Sandbox und wandelt die benutzerdefinierte Konfigurationsdatei in ein strukturiertes Python-Dictionary um.

### Hauptfunktionen:

* **`_parse()`**: Der interne Kern-Parser. Er liest die `.pyfun`-Datei Zeile für Zeile, ignoriert Kommentare und verarbeitet verschachtelte Sektionen (z. B. `[LLM_PROVIDER.anthropic]`).
* **Caching (`get()`)**: Lädt die Konfiguration beim ersten Aufruf in einen internen Speicher (`_cache`), um unnötige Festplattenzugriffe bei nachfolgenden Abfragen zu vermeiden.
* **Gefilterte Getter (`get_active_llm_providers`, `get_active_tools`, etc.)**: Diese Funktionen liefern gezielt nur die Einträge zurück, die in der Konfiguration explizit auf `active = "true"` gesetzt wurden.
* **Spezifische Sektions-Abfragen**: Funktionen wie `get_hub()`, `get_limits()` oder `get_db_sync()` ermöglichen einen schnellen Zugriff auf thematische Konfigurationsblöcke.

### Kern-Logik:

Die Datei implementiert eine robuste **String-Reinigung** (Entfernen von Anführungszeichen und Inline-Kommentaren) und unterstützt eine hierarchische Struktur. Ein besonderes Feature ist das automatische Entfernen von Provider-Präfixen (z. B. wird `anthropic.base_url` innerhalb des `anthropic`-Blocks einfach zu `base_url`), was die Konfiguration sehr übersichtlich macht.

