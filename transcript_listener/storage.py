"""SQLite archive for external transcripts."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import default_storage_path
from .models import NormalizedTranscript
from .renderer import render_for_sessiondb


REVIEW_INSTRUCTIONS_SETTING = "review_instructions"


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


class TranscriptArchive:
    """Profile-local transcript archive and direct search index."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_storage_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

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

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
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

    def get_setting(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return str(row["value"])

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, value, time.time()),
            )

    def delete_setting(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    def get_review_instructions(self) -> str:
        return self.get_setting(REVIEW_INSTRUCTIONS_SETTING).strip()

    def set_review_instructions(self, instructions: str) -> None:
        instructions = instructions.strip()
        if instructions:
            self.set_setting(REVIEW_INSTRUCTIONS_SETTING, instructions)
        else:
            self.delete_setting(REVIEW_INSTRUCTIONS_SETTING)

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
        """
        params.append(limit)
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


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
