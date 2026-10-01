"""SQLite-backed conversation state for the Telegram Chat Automation bot.

Conversation modes, business-connection metadata, rate-limit windows, and short
AI histories are committed atomically. On Render, put this database under the
persistent disk mount (DATA_DIR=/var/data) to retain it across restarts/deploys.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ConversationMode:
    copy_enabled: bool = False
    autobot_enabled: bool = False
    mute_enabled: bool = False


@dataclass(frozen=True)
class ConnectionInfo:
    connection_id: str
    owner_id: int
    dc_id: int
    enabled: bool
    can_reply: bool
    can_delete_received_messages: bool | None = None


class StateStore:
    """Small, single-instance durable store; all writes use SQLite transactions."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(
            str(path),
            timeout=15,
            isolation_level=None,
            check_same_thread=False,
        )
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=15000")
        self._create_schema()
        self._restrict_file_permissions(path)
        self._expire_old_records()

    @staticmethod
    def _restrict_file_permissions(path: Path) -> None:
        try:
            path.chmod(0o600)
        except OSError:
            # Render's filesystem policy may not permit chmod; SQLite still
            # operates normally, and the persistent disk remains service-scoped.
            pass

    def _create_schema(self) -> None:
        with self._lock:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS business_connections (
                    connection_id TEXT PRIMARY KEY,
                    owner_id INTEGER NOT NULL,
                    dc_id INTEGER NOT NULL,
                    enabled INTEGER NOT NULL,
                    can_reply INTEGER NOT NULL,
                    can_delete_received_messages INTEGER,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversation_modes (
                    connection_id TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    copy_enabled INTEGER NOT NULL DEFAULT 0,
                    autobot_enabled INTEGER NOT NULL DEFAULT 0,
                    mute_enabled INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (connection_id, chat_id),
                    CHECK (copy_enabled = 0 OR autobot_enabled = 0)
                );

                CREATE TABLE IF NOT EXISTS rate_limit_windows (
                    scope TEXT NOT NULL,
                    connection_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    window_start INTEGER NOT NULL,
                    count INTEGER NOT NULL,
                    PRIMARY KEY (scope, connection_id, user_id, window_start)
                );

                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    connection_id TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS history_by_conversation
                    ON conversation_history (connection_id, chat_id, id DESC);
                """
            )
            self._ensure_column(
                "business_connections",
                "can_delete_received_messages",
                "INTEGER",
            )
            self._ensure_column(
                "conversation_modes",
                "mute_enabled",
                "INTEGER NOT NULL DEFAULT 0",
            )

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in self._db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _expire_old_records(self) -> None:
        now = time.time()
        with self._transaction():
            self._db.execute(
                "DELETE FROM rate_limit_windows WHERE window_start < ?",
                (int(now) - 7 * 24 * 60 * 60,),
            )
            self._db.execute(
                "DELETE FROM conversation_history WHERE created_at < ?",
                (now - 30 * 24 * 60 * 60,),
            )

    def _transaction(self):
        """Start an immediate transaction while holding the connection lock."""
        return _Transaction(self._db, self._lock)

    def save_connection(
        self,
        connection_id: str,
        owner_id: int,
        dc_id: int,
        enabled: bool,
        can_reply: bool,
        can_delete_received_messages: bool = False,
    ) -> ConnectionInfo:
        now = time.time()
        with self._transaction():
            self._db.execute(
                """
                INSERT INTO business_connections
                    (connection_id, owner_id, dc_id, enabled, can_reply,
                     can_delete_received_messages, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connection_id) DO UPDATE SET
                    owner_id=excluded.owner_id,
                    dc_id=excluded.dc_id,
                    enabled=excluded.enabled,
                    can_reply=excluded.can_reply,
                    can_delete_received_messages=excluded.can_delete_received_messages,
                    updated_at=excluded.updated_at
                """,
                (
                    connection_id,
                    owner_id,
                    dc_id,
                    int(enabled),
                    int(can_reply),
                    int(can_delete_received_messages),
                    now,
                ),
            )
        return ConnectionInfo(
            connection_id,
            owner_id,
            dc_id,
            enabled,
            can_reply,
            can_delete_received_messages,
        )

    def get_connection(self, connection_id: str) -> ConnectionInfo | None:
        with self._lock:
            row = self._db.execute(
                """
                SELECT connection_id, owner_id, dc_id, enabled, can_reply,
                       can_delete_received_messages
                FROM business_connections WHERE connection_id = ?
                """,
                (connection_id,),
            ).fetchone()
        if row is None:
            return None
        return ConnectionInfo(
            connection_id=row["connection_id"],
            owner_id=row["owner_id"],
            dc_id=row["dc_id"],
            enabled=bool(row["enabled"]),
            can_reply=bool(row["can_reply"]),
            can_delete_received_messages=(
                bool(row["can_delete_received_messages"])
                if row["can_delete_received_messages"] is not None
                else None
            ),
        )

    def get_mode(self, connection_id: str, chat_id: int) -> ConversationMode:
        with self._lock:
            row = self._db.execute(
                """
                SELECT copy_enabled, autobot_enabled, mute_enabled
                FROM conversation_modes
                WHERE connection_id = ? AND chat_id = ?
                """,
                (connection_id, chat_id),
            ).fetchone()
        if row is None:
            return ConversationMode()
        return ConversationMode(
            bool(row["copy_enabled"]),
            bool(row["autobot_enabled"]),
            bool(row["mute_enabled"]),
        )

    def change_mode(
        self,
        connection_id: str,
        chat_id: int,
        mode: str,
        enabled: bool,
    ) -> ConversationMode:
        """Persist a mode transition atomically; copy and autobot are exclusive."""
        if mode not in {"copy", "autobot"}:
            raise ValueError("mode must be 'copy' or 'autobot'")

        with self._transaction():
            row = self._db.execute(
                """
                SELECT copy_enabled, autobot_enabled, mute_enabled
                FROM conversation_modes
                WHERE connection_id = ? AND chat_id = ?
                """,
                (connection_id, chat_id),
            ).fetchone()
            copy_enabled = bool(row["copy_enabled"]) if row else False
            autobot_enabled = bool(row["autobot_enabled"]) if row else False
            mute_enabled = bool(row["mute_enabled"]) if row else False

            if mode == "copy":
                copy_enabled = enabled
                if enabled:
                    autobot_enabled = False
            else:
                autobot_enabled = enabled
                if enabled:
                    copy_enabled = False

            self._db.execute(
                """
                INSERT INTO conversation_modes
                    (connection_id, chat_id, copy_enabled, autobot_enabled, mute_enabled, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(connection_id, chat_id) DO UPDATE SET
                    copy_enabled=excluded.copy_enabled,
                    autobot_enabled=excluded.autobot_enabled,
                    updated_at=excluded.updated_at
                """,
                (
                    connection_id,
                    chat_id,
                    int(copy_enabled),
                    int(autobot_enabled),
                    int(mute_enabled),
                    time.time(),
                ),
            )

        return ConversationMode(copy_enabled, autobot_enabled, mute_enabled)

    def change_mute(self, connection_id: str, chat_id: int, enabled: bool) -> ConversationMode:
        """Persist the incoming-message mute state without changing other modes."""
        with self._transaction():
            row = self._db.execute(
                """
                SELECT copy_enabled, autobot_enabled
                FROM conversation_modes
                WHERE connection_id = ? AND chat_id = ?
                """,
                (connection_id, chat_id),
            ).fetchone()
            copy_enabled = bool(row["copy_enabled"]) if row else False
            autobot_enabled = bool(row["autobot_enabled"]) if row else False
            self._db.execute(
                """
                INSERT INTO conversation_modes
                    (connection_id, chat_id, copy_enabled, autobot_enabled, mute_enabled, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(connection_id, chat_id) DO UPDATE SET
                    mute_enabled=excluded.mute_enabled,
                    updated_at=excluded.updated_at
                """,
                (
                    connection_id,
                    chat_id,
                    int(copy_enabled),
                    int(autobot_enabled),
                    int(enabled),
                    time.time(),
                ),
            )
        return ConversationMode(copy_enabled, autobot_enabled, enabled)

    def consume_limit(
        self,
        scope: str,
        connection_id: str,
        user_id: int,
        limit: int,
        window_seconds: int,
        now: float | None = None,
    ) -> float | None:
        """Consume one fixed-window quota; return retry seconds if it is exhausted."""
        if limit < 1 or window_seconds < 1:
            raise ValueError("limit and window_seconds must be positive")
        current_time = time.time() if now is None else now
        window_start = int(current_time // window_seconds) * window_seconds
        with self._transaction():
            row = self._db.execute(
                """
                SELECT count FROM rate_limit_windows
                WHERE scope = ? AND connection_id = ? AND user_id = ? AND window_start = ?
                """,
                (scope, connection_id, user_id, window_start),
            ).fetchone()
            current_count = int(row["count"]) if row else 0
            if current_count >= limit:
                return max(0.0, window_start + window_seconds - current_time)
            self._db.execute(
                """
                INSERT INTO rate_limit_windows
                    (scope, connection_id, user_id, window_start, count)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(scope, connection_id, user_id, window_start)
                DO UPDATE SET count = count + 1
                """,
                (scope, connection_id, user_id, window_start),
            )
        return None

    def get_history(
        self,
        connection_id: str,
        chat_id: int,
        limit: int,
    ) -> list[dict[str, str]]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT role, content FROM conversation_history
                WHERE connection_id = ? AND chat_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (connection_id, chat_id, limit),
            ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    def add_exchange(
        self,
        connection_id: str,
        chat_id: int,
        user_text: str,
        assistant_text: str,
        keep_messages: int = 24,
    ) -> None:
        """Store a completed AI turn and prune old turns in one transaction."""
        if keep_messages < 2:
            raise ValueError("keep_messages must be at least 2")
        now = time.time()
        with self._transaction():
            self._db.executemany(
                """
                INSERT INTO conversation_history
                    (connection_id, chat_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (connection_id, chat_id, "user", user_text, now),
                    (connection_id, chat_id, "assistant", assistant_text, now),
                ],
            )
            self._db.execute(
                """
                DELETE FROM conversation_history
                WHERE connection_id = ? AND chat_id = ? AND id NOT IN (
                    SELECT id FROM conversation_history
                    WHERE connection_id = ? AND chat_id = ?
                    ORDER BY id DESC LIMIT ?
                )
                """,
                (connection_id, chat_id, connection_id, chat_id, keep_messages),
            )

    def close(self) -> None:
        with self._lock:
            self._db.close()


class _Transaction:
    """Context manager for serial, rollback-safe writes on the shared connection."""

    def __init__(self, db: sqlite3.Connection, lock: threading.RLock) -> None:
        self._db = db
        self._lock = lock

    def __enter__(self) -> None:
        self._lock.acquire()
        try:
            self._db.execute("BEGIN IMMEDIATE")
        except Exception:
            self._lock.release()
            raise
        return None

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            if exc_type is None:
                self._db.execute("COMMIT")
            else:
                self._db.execute("ROLLBACK")
        finally:
            self._lock.release()
        return False
