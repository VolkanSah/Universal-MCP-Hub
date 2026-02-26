## PyFundaments – Funktionsliste

### `main.py`
| Funktion | Beschreibung |
|---|---|
| `initialize_fundaments()` | Async. Initialisiert alle Services konditionell anhand der vorhandenen ENV-Variablen. Gibt Dict mit allen Services zurück (nicht initialisierte = `None`) |
| `main()` | Entry Point – ruft `initialize_fundaments()`, bindet `app/app.py` ein, schließt DB-Pool beim Exit |

---

### `fundaments/config_handler.py` – `ConfigHandler`
| Funktion | Beschreibung |
|---|---|
| `__init__()` | Lädt `.env` via `python-dotenv` + alle System-ENV-Vars |
| `load_all_config()` | Speichert alle nicht-leeren ENV-Vars in `self.config` dict |
| `get(key)` | Gibt Wert als String zurück, `None` wenn nicht vorhanden |
| `get_bool(key, default)` | Parsed bool-Werte (true/1/yes/on) case-insensitive |
| `get_int(key, default)` | Gibt int-Wert, Fallback auf `default` bei Fehler |
| `has(key)` | Prüft ob Key vorhanden **und** nicht leer |
| `get_all()` | Gibt Kopie des gesamten Config-Dicts zurück |
| `config_service` | Globale Singleton-Instanz |

---

### `fundaments/postgresql.py`
| Funktion | Beschreibung |
|---|---|
| `enforce_cloud_security(dsn_url)` | Erzwingt `sslmode=require`, setzt Timeouts, entfernt Neon-inkompatible Optionen aus dem DSN |
| `mask_dsn(dsn_url)` | Entfernt User/Passwort aus DSN für sichere Log-Ausgabe |
| `ssl_runtime_check(conn)` | Prüft aktive SSL-Verbindung via `pg_stat_ssl`; cloud-tolerant für Neon/Supabase |
| `init_db_pool(dsn_url)` | Erstellt asyncpg Connection Pool (min=1, max=10), führt SSL-Check durch, gibt Pool zurück |
| `close_db_pool()` | Schließt Pool gracefully |
| `execute_secured_query(query, *params, fetch_method)` | Führt parametrisierten Query aus. `fetch_method`: `fetch` (liste), `fetchrow` (eine Zeile), `execute` (kein Return). Reconnect-Logik für Neon |

---

### `fundaments/encryption.py` – `Encryption`
| Funktion | Beschreibung |
|---|---|
| `generate_salt()` | Static – erzeugt kryptografisch sicheren 16-Byte Salt als Hex-String |
| `__init__(master_key, salt)` | Deriviert AES-256 Key via PBKDF2-SHA256 (480.000 Iterationen) aus master_key + hex-salt |
| `encrypt(data)` | Verschlüsselt String mit AES-256-GCM, gibt Dict `{data, nonce, tag}` zurück (alle base64/hex) |
| `decrypt(encrypted_data, nonce, tag)` | Entschlüsselt GCM-verschlüsselten String, wirft `InvalidTag` bei Manipulation |
| `encrypt_file(source_path, dest_path)` | Streaming-Datei-Verschlüsselung (8192-Byte Chunks), Nonce+Tag ins File geschrieben |
| `decrypt_file(source_path, dest_path)` | Streaming-Datei-Entschlüsselung, liest Nonce aus Header und Tag am Ende der Datei |

---

### `fundaments/access_control.py` – `AccessControl`
| Funktion | Beschreibung |
|---|---|
| `__init__(user_id)` | Initialisiert mit optionaler user_id |
| `has_permission(permission_name)` | Prüft ob User eine Berechtigung hat (via Role→Permission-Join) |
| `get_user_permissions()` | Gibt alle Permissions des Users als Liste zurück |
| `get_user_roles()` | Gibt alle Rollen des Users zurück |
| `assign_role(role_id)` | Weist dem User eine Rolle zu (INSERT in `user_role_assignments`) |
| `remove_role(role_id)` | Entfernt eine Rolle vom User |
| `get_all_roles()` | Gibt alle verfügbaren Rollen zurück |
| `get_all_permissions()` | Gibt alle verfügbaren Permissions zurück |
| `create_role(name, description)` | Erstellt neue Rolle, gibt neue ID zurück |
| `update_role_permissions(role_id, permission_ids)` | Ersetzt alle Permissions einer Rolle (Delete + Re-Insert) |
| `get_role_permissions(role_id)` | Gibt alle Permissions einer Rolle zurück |

---

### `fundaments/user_handler.py`
**`Database`-Klasse** (SQLite-Wrapper):

| Funktion | Beschreibung |
|---|---|
| `execute(query, params)` | Führt Query aus und committed |
| `fetchone(query, params)` | Gibt eine Zeile zurück |
| `fetchall(query, params)` | Gibt alle Zeilen zurück |
| `close()` | Schließt Connection |
| `setup_tables()` | Erstellt `users`- und `sessions`-Tabelle wenn nicht vorhanden |

**`Security`-Klasse** (Passwort-Utils):

| Funktion | Beschreibung |
|---|---|
| `hash_password(password)` | PBKDF2-SHA256 Hash via passlib |
| `verify_password(password, hashed)` | Verifiziert Passwort gegen Hash |
| `regenerate_session(session_id)` | Erstellt neue UUID als Session-ID (Anti Session-Fixation) |

**`UserHandler`-Klasse**:

| Funktion | Beschreibung |
|---|---|
| `login(username, password, request_data)` | Vollständiger Login: User-Lookup, Lock-Check, PW-Verify, Session anlegen, Session regenerieren |
| `logout()` | Löscht Session aus DB, leert In-Memory-Session |
| `is_logged_in()` | Prüft ob aktive Session in DB existiert |
| `is_admin()` | Prüft `is_admin`-Flag in der Session |
| `validate_session(request_data)` | Validiert Session gegen IP + User-Agent |
| `lock_account(username)` | Setzt `account_locked=1` für User |
| `reset_failed_attempts(username)` | Setzt `failed_login_attempts` auf 0 |
| `increment_failed_attempts(username)` | Erhöht Counter, sperrt Account ab 5 Fehlversuchen |

---

### `fundaments/security.py` – `Security` (Orchestrator)
| Funktion | Beschreibung |
|---|---|
| `__init__(services)` | Nimmt Dict mit `user_handler`, `access_control`, `encryption`; wirft RuntimeError wenn user_handler oder access_control fehlen |
| `user_login(username, password, request_data)` | Kombiniert `UserHandler.login()` + `validate_session()` |
| `check_permission(user_id, permission_name)` | Delegiert an `AccessControl.has_permission()` |
| `encrypt_data(data)` | Delegiert an `Encryption.encrypt()`, wirft RuntimeError wenn nicht initialisiert |
| `decrypt_data(encrypted_data, nonce, tag)` | Delegiert an `Encryption.decrypt()`, gibt `None` bei Fehler/nicht initialisiert |

---

### `fundaments/debug.py` – `PyFundamentsDebug`
| Funktion | Beschreibung |
|---|---|
| `__init__()` | Liest ENV: `PYFUNDAMENTS_DEBUG`, `LOG_LEVEL`, `LOG_TO_TMP`, `ENABLE_PUBLIC_LOGS` |
| `_setup_logger()` | Konfiguriert Logging (StreamHandler + optional RotatingFileHandler in `/tmp`) |
| `run()` | Wenn DEBUG aktiv: gibt Python-Version, CWD, sys.path aus; prüft alle fundament-Dateien auf Existenz und Lesbarkeit |

---

### `app/app.py`
| Funktion | Beschreibung |
|---|---|
| `start_application(fundaments)` | Empfängt fertiges Services-Dict von main.py, enthält Beispiel-Usage für alle Services. Hier kommt deine eigene App-Logik rein |

---

**Wichtige Architektur-Hinweise:**
- `UserHandler` nutzt **SQLite** intern – ist aber darauf ausgelegt, die asyncpg-DB aus `postgresql.py` zu bekommen (Inkonsistenz im aktuellen Stand? Nein Fundaments braucht die .py und app/* braucht die sqlite)
- `AccessControl` arbeitet direkt mit `postgresql.execute_secured_query` (async, PostgreSQL)
- `Security` in `security.py` ist der **Orchestrator** – nicht zu verwechseln mit der gleichnamigen `Security`-Klasse in `user_handler.py` (Passwort-Utils)
- Alle Services sind optional – die App läuft auch ohne DB/Encryption
