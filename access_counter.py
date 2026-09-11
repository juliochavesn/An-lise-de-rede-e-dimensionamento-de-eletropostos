"""Contagem local e anonimizada de acessos à interface Streamlit."""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path(__file__).resolve().parent / ".app_data" / "accesses.sqlite3"


def _header(headers: Any, name: str) -> str:
    if not headers:
        return ""
    try:
        return str(headers.get(name, headers.get(name.lower(), "")) or "")
    except (AttributeError, TypeError):
        return ""


def _client_identity(st: Any) -> str:
    """Cria uma impressão técnica sem salvar o endereço IP original."""
    context = getattr(st, "context", None)
    headers = getattr(context, "headers", {}) if context is not None else {}
    forwarded = _header(headers, "X-Forwarded-For").split(",", 1)[0].strip()
    remote_ip = str(getattr(context, "ip_address", "") or forwarded or "desconhecido")
    user_agent = _header(headers, "User-Agent") or "navegador-desconhecido"
    return f"{remote_ip}|{user_agent}"


def _database_path() -> Path:
    configured = os.environ.get("APP_ACCESS_DB", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_DB_PATH


def _prepare_database(connection: sqlite3.Connection) -> str:
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS access_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_hash TEXT NOT NULL,
            accessed_at TEXT NOT NULL,
            access_date TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_access_events_date ON access_events(access_date)"
    )
    row = connection.execute("SELECT value FROM settings WHERE key = 'hash_salt'").fetchone()
    if row:
        return str(row[0])
    salt = secrets.token_hex(32)
    connection.execute("INSERT INTO settings(key, value) VALUES ('hash_salt', ?)", (salt,))
    return salt


def register_access(st: Any) -> dict[str, int] | None:
    """Registra uma visita por sessão e devolve os contadores atuais."""
    session_key = "_anonymous_access_registered"
    cached_key = "_anonymous_access_metrics"
    if st.session_state.get(session_key):
        return st.session_state.get(cached_key)

    try:
        database_path = _database_path()
        database_path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now().astimezone()
        with sqlite3.connect(database_path, timeout=5) as connection:
            salt = _prepare_database(connection)
            visitor_hash = hashlib.sha256(
                f"{salt}|{_client_identity(st)}".encode("utf-8")
            ).hexdigest()
            connection.execute(
                "INSERT INTO access_events(visitor_hash, accessed_at, access_date) VALUES (?, ?, ?)",
                (visitor_hash, now.isoformat(timespec="seconds"), now.date().isoformat()),
            )
            total = connection.execute("SELECT COUNT(*) FROM access_events").fetchone()[0]
            devices = connection.execute(
                "SELECT COUNT(DISTINCT visitor_hash) FROM access_events"
            ).fetchone()[0]
            today = connection.execute(
                "SELECT COUNT(*) FROM access_events WHERE access_date = ?", (now.date().isoformat(),)
            ).fetchone()[0]
        metrics = {"total": int(total), "devices": int(devices), "today": int(today)}
        st.session_state[session_key] = True
        st.session_state[cached_key] = metrics
        return metrics
    except (OSError, sqlite3.Error):
        # A telemetria nunca deve impedir o uso da aplicação.
        return None


def render_access_footer(st: Any, metrics: dict[str, int] | None) -> None:
    if not metrics:
        return
    st.markdown(
        (
            "<div style='margin-top:.2rem;text-align:center;color:#8493a3;"
            "font-size:.7rem' title='Contagem anonimizada desde a última inicialização'>"
            f"Acessos: {metrics['total']:,} &nbsp;·&nbsp; "
            f"dispositivos estimados: {metrics['devices']:,} &nbsp;·&nbsp; "
            f"hoje: {metrics['today']:,}"
            "<br><span style='font-size:.62rem'>desde a última inicialização da aplicação</span></div>"
        ).replace(",", "."),
        unsafe_allow_html=True,
    )
