"""SQLite archive for external transcripts."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import default_storage_path
from .models import NormalizedTranscript
from .renderer import render_for_sessiondb


DEFAULT_CALLBACK_ID = "default-review"


@dataclass(frozen=True)
class TranscriptSearchResult:
    external_session_id: str
    timestamp: str | None
    speaker: str
    speaker_label: str
    text: str
    source: str
    state_session_id: str | None
    event_received_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "external_session_id": self.external_session_id,
            "timestamp": self.timestamp,
            "speaker": self.speaker,
            "speaker_label": self.speaker_label,
            "text": self.text,
            "source": self.source,
            "state_session_id": self.state_session_id,
            "event_received_at": self.event_received_at,
        }


@dataclass(frozen=True)
class TranscriptCallback:
    callback_id: str
    name: str
    instructions: str
    enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.callback_id,
            "name": self.name,
            "instructions": self.instructions,
            "enabled": self.enabled,
        }


class TranscriptArchive:
    """Profile-local transcript archive and direct search index."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_storage_path()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _restrict_permissions(self.path.parent, 0o700)
        self._init_schema()
        self._secure_database_files()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        self._secure_database_files()
        return conn

    def _secure_database_files(self) -> None:
        for candidate in (self.path, self.path.with_name(f"{self.path.name}-wal"), self.path.with_name(f"{self.path.name}-shm"), self.path.with_name(f"{self.path.name}-journal")):
            if candidate.exists():
                _restrict_permissions(candidate, 0o600)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS transcripts (
                    conversation_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    participants_json TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    rendered_text TEXT NOT NULL,
                    state_session_id TEXT,
                    event_received_at TEXT,
                    review_requested_at TEXT,
                    review_job_id TEXT,
                    review_status TEXT,
                    review_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    extraction_status TEXT,
                    extraction_error TEXT
                );

                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    speaker TEXT NOT NULL,
                    speaker_label TEXT NOT NULL,
                    text TEXT NOT NULL,
                    timestamp TEXT,
                    source TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(conversation_id, turn_index),
                    FOREIGN KEY(conversation_id) REFERENCES transcripts(conversation_id)
                );

                CREATE INDEX IF NOT EXISTS idx_turns_conversation ON turns(conversation_id, turn_index);
                CREATE INDEX IF NOT EXISTS idx_turns_speaker ON turns(speaker);
                CREATE INDEX IF NOT EXISTS idx_turns_timestamp ON turns(timestamp);

                CREATE TABLE IF NOT EXISTS transcript_callbacks (
                    callback_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    instructions TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS callback_executions (
                    execution_key TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    execution_kind TEXT NOT NULL,
                    callback_id TEXT,
                    status TEXT NOT NULL,
                    authorization_quote TEXT NOT NULL,
                    job_id TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS callback_mutation_tokens (
                    token TEXT PRIMARY KEY,
                    remaining_uses INTEGER NOT NULL,
                    expires_at REAL NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(transcripts)")}
            for column in (
                "event_received_at",
                "review_requested_at",
                "review_job_id",
                "review_status",
                "review_error",
            ):
                if column not in columns:
                    conn.execute(f"ALTER TABLE transcripts ADD COLUMN {column} TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_transcripts_event_received_at ON transcripts(event_received_at)")

    def save_transcript(
        self,
        transcript: NormalizedTranscript,
        *,
        state_session_id: str | None = None,
        extraction_status: str | None = None,
        extraction_error: str | None = None,
        event_received_at: str | None = None,
    ) -> None:
        now = time.time()
        event_received_at = event_received_at or _utc_now_iso()
        rendered = render_for_sessiondb(transcript)
        participants_json = json.dumps(dict(transcript.participants), ensure_ascii=False)
        raw_json = json.dumps(dict(transcript.raw), ensure_ascii=False)
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT created_at, state_session_id, review_requested_at, review_job_id,
                       review_status, review_error
                FROM transcripts
                WHERE conversation_id = ?
                """,
                (transcript.conversation_id,),
            ).fetchone()
            created_at = float(existing["created_at"]) if existing else now
            effective_state_id = state_session_id or (existing["state_session_id"] if existing else None)
            conn.execute(
                """
                INSERT OR REPLACE INTO transcripts (
                    conversation_id, source, participants_json, raw_json, rendered_text,
                    state_session_id, event_received_at, review_requested_at, review_job_id,
                    review_status, review_error, created_at, updated_at, extraction_status,
                    extraction_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transcript.conversation_id,
                    transcript.source,
                    participants_json,
                    raw_json,
                    rendered,
                    effective_state_id,
                    event_received_at,
                    existing["review_requested_at"] if existing else None,
                    existing["review_job_id"] if existing else None,
                    existing["review_status"] if existing else None,
                    existing["review_error"] if existing else None,
                    created_at,
                    now,
                    extraction_status,
                    extraction_error,
                ),
            )
            conn.execute("DELETE FROM turns WHERE conversation_id = ?", (transcript.conversation_id,))
            conn.executemany(
                """
                INSERT INTO turns (
                    conversation_id, turn_index, speaker, speaker_label, text,
                    timestamp, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        transcript.conversation_id,
                        turn.index,
                        turn.speaker,
                        turn.speaker_label,
                        turn.text,
                        turn.timestamp,
                        transcript.source,
                        now,
                    )
                    for turn in transcript.turns
                ],
            )

    def set_state_session_id(self, conversation_id: str, state_session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE transcripts SET state_session_id = ?, updated_at = ? WHERE conversation_id = ?",
                (state_session_id, time.time(), conversation_id),
            )

    def get_review_instructions(self) -> str:
        callback = self.get_callback(DEFAULT_CALLBACK_ID)
        return callback.instructions if callback and callback.enabled else ""

    def set_review_instructions(self, instructions: str) -> None:
        instructions = instructions.strip()
        if instructions:
            self.upsert_callback(
                callback_id=DEFAULT_CALLBACK_ID,
                name="Default transcript review",
                instructions=instructions,
                enabled=True,
            )
        else:
            self.remove_callback(DEFAULT_CALLBACK_ID)

    def list_callbacks(self, *, enabled_only: bool = False) -> list[TranscriptCallback]:
        where = "WHERE enabled = 1" if enabled_only else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT callback_id, name, instructions, enabled FROM transcript_callbacks {where} ORDER BY created_at, callback_id"
            ).fetchall()
        return [_callback_from_row(row) for row in rows]

    def get_callback(self, callback_id: str) -> TranscriptCallback | None:
        callback_id = _callback_id(callback_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT callback_id, name, instructions, enabled FROM transcript_callbacks WHERE callback_id = ?",
                (callback_id,),
            ).fetchone()
        return _callback_from_row(row) if row else None

    def upsert_callback(
        self,
        *,
        callback_id: str,
        name: str,
        instructions: str,
        enabled: bool = True,
    ) -> TranscriptCallback:
        callback_id = _callback_id(callback_id)
        name = _bounded_text(name, 160, "callback name")
        instructions = _bounded_text(instructions, 12000, "callback instructions")
        now = time.time()
        with self._connect() as conn:
            existing = conn.execute("SELECT created_at FROM transcript_callbacks WHERE callback_id = ?", (callback_id,)).fetchone()
            created_at = float(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT OR REPLACE INTO transcript_callbacks (
                    callback_id, name, instructions, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (callback_id, name, instructions, int(enabled), created_at, now),
            )
        return TranscriptCallback(callback_id, name, instructions, enabled)

    def set_callback_enabled(self, callback_id: str, enabled: bool) -> TranscriptCallback | None:
        callback_id = _callback_id(callback_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE transcript_callbacks SET enabled = ?, updated_at = ? WHERE callback_id = ?",
                (int(enabled), time.time(), callback_id),
            )
        return self.get_callback(callback_id)

    def remove_callback(self, callback_id: str) -> bool:
        callback_id = _callback_id(callback_id)
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM transcript_callbacks WHERE callback_id = ?", (callback_id,))
        return cursor.rowcount > 0

    def claim_execution(
        self,
        *,
        execution_key: str,
        conversation_id: str,
        execution_kind: str,
        callback_id: str | None,
        authorization_quote: str,
    ) -> bool:
        """Atomically reserve an action before creating a durable cron job."""

        now = time.time()
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO callback_executions (
                        execution_key, conversation_id, execution_kind, callback_id, status,
                        authorization_quote, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'claimed', ?, ?, ?)
                    ON CONFLICT(execution_key) DO UPDATE SET
                        status = 'claimed', error = NULL, updated_at = excluded.updated_at
                    WHERE callback_executions.status = 'error'
                       OR (callback_executions.status = 'claimed' AND callback_executions.updated_at < ?)
                    """,
                    (execution_key, conversation_id, execution_kind, callback_id, authorization_quote, now, now, now - 300),
                )
            return cursor.rowcount == 1
        except sqlite3.IntegrityError:
            return False

    def complete_execution(self, execution_key: str, *, job_id: str | None = None, error: str | None = None) -> None:
        status = "dispatched" if not error else "error"
        with self._connect() as conn:
            conn.execute(
                "UPDATE callback_executions SET status = ?, job_id = ?, error = ?, updated_at = ? WHERE execution_key = ?",
                (status, job_id, error, time.time(), execution_key),
            )

    def create_callback_mutation_token(self, *, uses: int = 10, ttl_seconds: int = 900) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._connect() as conn:
            conn.execute("DELETE FROM callback_mutation_tokens WHERE expires_at < ?", (now,))
            conn.execute(
                "INSERT INTO callback_mutation_tokens (token, remaining_uses, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (token, max(1, uses), now + max(1, ttl_seconds), now),
            )
        return token

    def consume_callback_mutation_token(self, token: str) -> bool:
        now = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE callback_mutation_tokens
                SET remaining_uses = remaining_uses - 1
                WHERE token = ? AND expires_at >= ? AND remaining_uses > 0
                """,
                (token, now),
            )
        return cursor.rowcount == 1

    def get_review_state(self, conversation_id: str) -> dict[str, str | None]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT review_requested_at, review_job_id, review_status, review_error
                FROM transcripts
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()
        if row is None:
            return {
                "review_requested_at": None,
                "review_job_id": None,
                "review_status": None,
                "review_error": None,
            }
        return {
            "review_requested_at": row["review_requested_at"],
            "review_job_id": row["review_job_id"],
            "review_status": row["review_status"],
            "review_error": row["review_error"],
        }

    def mark_review_status(
        self,
        conversation_id: str,
        *,
        review_requested_at: str | None = None,
        review_job_id: str | None = None,
        review_status: str,
        review_error: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE transcripts
                SET review_requested_at = ?, review_job_id = ?, review_status = ?,
                    review_error = ?, updated_at = ?
                WHERE conversation_id = ?
                """,
                (review_requested_at, review_job_id, review_status, review_error, time.time(), conversation_id),
            )

    def search(
        self,
        *,
        query: str = "",
        external_session_id: str = "",
        speaker: str = "",
        since: str = "",
        until: str = "",
        limit: int = 10,
        offset: int = 0,
    ) -> list[TranscriptSearchResult]:
        limit = max(1, min(int(limit or 10), 50))
        where: list[str] = []
        params: list[Any] = []
        if query.strip():
            where.append("(LOWER(t.text) LIKE LOWER(?) OR LOWER(t.speaker_label) LIKE LOWER(?))")
            needle = f"%{query.strip()}%"
            params.extend([needle, needle])
        if external_session_id.strip():
            where.append("t.conversation_id = ?")
            params.append(external_session_id.strip())
        if speaker.strip():
            where.append("(t.speaker = ? OR t.speaker_label = ?)")
            params.extend([speaker.strip(), speaker.strip()])
        if since.strip():
            where.append("tr.event_received_at IS NOT NULL AND tr.event_received_at >= ?")
            params.append(since.strip())
        if until.strip():
            where.append("tr.event_received_at IS NOT NULL AND tr.event_received_at <= ?")
            params.append(until.strip())
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        sql = f"""
            SELECT t.conversation_id, t.timestamp, t.speaker, t.speaker_label,
                   t.text, t.source, tr.state_session_id, tr.event_received_at
            FROM turns t
            JOIN transcripts tr ON tr.conversation_id = t.conversation_id
            {where_sql}
            ORDER BY COALESCE(tr.event_received_at, '') DESC, t.conversation_id, t.turn_index
            LIMIT ?
            OFFSET ?
        """
        params.extend([limit, max(0, int(offset or 0))])
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            TranscriptSearchResult(
                external_session_id=row["conversation_id"],
                timestamp=row["timestamp"],
                speaker=row["speaker"],
                speaker_label=row["speaker_label"],
                text=row["text"],
                source=row["source"],
                state_session_id=row["state_session_id"],
                event_received_at=row["event_received_at"],
            )
            for row in rows
        ]

    def search_page(self, **kwargs: Any) -> tuple[list[TranscriptSearchResult], int]:
        """Return a page and total matching turns for cursor-based retrieval."""

        results = self.search(**kwargs)
        query = str(kwargs.get("query") or "")
        external_session_id = str(kwargs.get("external_session_id") or "")
        speaker = str(kwargs.get("speaker") or "")
        since = str(kwargs.get("since") or "")
        until = str(kwargs.get("until") or "")
        where: list[str] = []
        params: list[Any] = []
        if query.strip():
            where.append("(LOWER(t.text) LIKE LOWER(?) OR LOWER(t.speaker_label) LIKE LOWER(?))")
            needle = f"%{query.strip()}%"
            params.extend([needle, needle])
        if external_session_id.strip():
            where.append("t.conversation_id = ?")
            params.append(external_session_id.strip())
        if speaker.strip():
            where.append("(t.speaker = ? OR t.speaker_label = ?)")
            params.extend([speaker.strip(), speaker.strip()])
        if since.strip():
            where.append("tr.event_received_at IS NOT NULL AND tr.event_received_at >= ?")
            params.append(since.strip())
        if until.strip():
            where.append("tr.event_received_at IS NOT NULL AND tr.event_received_at <= ?")
            params.append(until.strip())
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as conn:
            total = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM turns t JOIN transcripts tr ON tr.conversation_id = t.conversation_id {where_sql}", params
                ).fetchone()[0]
            )
        return results, total


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _callback_from_row(row: sqlite3.Row) -> TranscriptCallback:
    return TranscriptCallback(
        callback_id=str(row["callback_id"]),
        name=str(row["name"]),
        instructions=str(row["instructions"]),
        enabled=bool(row["enabled"]),
    )


def _callback_id(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "_-" else "-" for char in value.strip().lower()).strip("-")
    if not cleaned or len(cleaned) > 96:
        raise ValueError("callback id must contain 1-96 letters, numbers, underscores, or hyphens")
    return cleaned


def _bounded_text(value: str, maximum: int, label: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum:
        raise ValueError(f"{label} must contain 1-{maximum} characters")
    return cleaned


def _restrict_permissions(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass
