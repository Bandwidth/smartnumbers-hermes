import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from transcript_listener.parser import parse_transcript_payload
from transcript_listener.storage import TranscriptArchive


FIXTURE = Path(__file__).parent / "fixtures" / "transcript_001.json"


def test_archive_save_and_search(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    transcript = parse_transcript_payload(
        FIXTURE.read_text(),
        metadata={"direction": "inbound", "from": "+18636389992", "to": "+18633307564"},
    )

    archive.save_transcript(
        transcript,
        state_session_id="external_ref_conv_001",
        event_received_at="2026-06-25T16:12:03.123456Z",
    )
    results = archive.search(query="approve", limit=5)

    assert len(results) == 1
    assert results[0].external_session_id == "conv_001"
    assert results[0].speaker_label == "Damien"
    assert results[0].direction == "inbound"
    assert results[0].from_number == "+18636389992"
    assert results[0].to_number == "+18633307564"
    assert results[0].state_session_id == "external_ref_conv_001"
    assert results[0].event_received_at == "2026-06-25T16:12:03.123456Z"
    parsed = datetime.fromisoformat(results[0].event_received_at.replace("Z", "+00:00"))
    assert parsed.tzinfo == UTC

    number_results = archive.search(query="+18636389992", direction="inbound")
    assert len(number_results) == len(transcript.turns)


def test_archive_filters_by_speaker(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    archive.save_transcript(parse_transcript_payload(FIXTURE.read_text()))

    results = archive.search(speaker="Alex", limit=5)

    assert len(results) == 1
    assert results[0].speaker == "person_x"


def test_archive_search_returns_most_recent_calls_first(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    payload = json.loads(FIXTURE.read_text())
    older = dict(payload, conversation_id="older_call")
    newer = dict(payload, conversation_id="newer_call")

    archive.save_transcript(parse_transcript_payload(older), event_received_at="2026-06-25T16:00:00Z")
    archive.save_transcript(parse_transcript_payload(newer), event_received_at="2026-06-25T17:00:00Z")

    results = archive.search(limit=1)

    assert len(results) == 1
    assert results[0].external_session_id == "newer_call"
    assert results[0].event_received_at == "2026-06-25T17:00:00Z"


def test_archive_migrates_existing_db_for_event_received_at(tmp_path):
    db_path = tmp_path / "transcripts.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE transcripts (
                conversation_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                participants_json TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                rendered_text TEXT NOT NULL,
                state_session_id TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                extraction_status TEXT,
                extraction_error TEXT
            )
            """
        )

    archive = TranscriptArchive(db_path)
    archive.save_transcript(
        parse_transcript_payload(FIXTURE.read_text()),
        event_received_at="2026-06-25T18:00:00Z",
    )

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(transcripts)")}
        row = conn.execute("SELECT event_received_at FROM transcripts WHERE conversation_id = ?", ("conv_001",)).fetchone()

    assert {
        "direction",
        "from_number",
        "to_number",
        "event_received_at",
        "review_requested_at",
        "review_job_id",
        "review_status",
        "review_error",
    } <= columns
    assert row["event_received_at"] == "2026-06-25T18:00:00Z"


def test_archive_migration_preserves_existing_transcript_without_call_metadata(tmp_path):
    db_path = tmp_path / "transcripts.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(
            """
            CREATE TABLE transcripts (
                conversation_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                participants_json TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                rendered_text TEXT NOT NULL,
                state_session_id TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                extraction_status TEXT,
                extraction_error TEXT
            );
            CREATE TABLE turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                turn_index INTEGER NOT NULL,
                speaker TEXT NOT NULL,
                speaker_label TEXT NOT NULL,
                text TEXT NOT NULL,
                timestamp TEXT,
                source TEXT NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE(conversation_id, turn_index)
            );
            INSERT INTO transcripts (
                conversation_id, source, participants_json, raw_json, rendered_text,
                state_session_id, created_at, updated_at, extraction_status, extraction_error
            ) VALUES ('old-call', 'legacy', '{}', '{}', 'legacy transcript', 'old-session', 1, 1, 'done', NULL);
            INSERT INTO turns (
                conversation_id, turn_index, speaker, speaker_label, text, timestamp, source, created_at
            ) VALUES ('old-call', 0, 'TO', 'TO', 'legacy text', NULL, 'legacy', 1);
            """
        )

    archive = TranscriptArchive(db_path)

    results = archive.search(external_session_id="old-call")

    assert len(results) == 1
    assert results[0].text == "legacy text"
    assert results[0].state_session_id == "old-session"
    assert results[0].direction is None
    assert results[0].from_number is None
    assert results[0].to_number is None


def test_archive_migrates_existing_callbacks_for_delivery_override(tmp_path):
    db_path = tmp_path / "transcripts.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE transcript_callbacks (
                callback_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                instructions TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO transcript_callbacks (
                callback_id, name, instructions, enabled, created_at, updated_at
            ) VALUES ('calendar', 'Calendar', 'Add agreed events.', 1, 1, 1)
            """
        )

    archive = TranscriptArchive(db_path)
    existing = archive.get_callback("calendar")
    updated = archive.upsert_callback(
        callback_id="calendar",
        name="Calendar",
        instructions="Add agreed events.",
        deliver="telegram",
    )

    with sqlite3.connect(str(db_path)) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(transcript_callbacks)")}

    assert "deliver" in columns
    assert existing is not None and existing.deliver is None
    assert updated.deliver == "telegram"
    assert TranscriptArchive(db_path).get_callback("calendar").deliver == "telegram"


def test_archive_lists_all_execution_job_ids_without_aggregate_duplicates(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    base = {
        "conversation_id": "call-1",
        "authorization_quote": "registered callback",
    }
    archive.claim_execution(
        **base,
        execution_key="aggregate",
        execution_kind="callbacks",
        callback_id=None,
    )
    archive.claim_execution(
        **base,
        execution_key="calendar",
        execution_kind="callback",
        callback_id="calendar",
    )
    archive.complete_execution("calendar", job_id="job-1")
    archive.claim_execution(
        **base,
        execution_key="summary",
        execution_kind="callback",
        callback_id="summary",
    )
    archive.complete_execution("summary", job_id="job-2")
    archive.complete_execution("aggregate", job_id="job-1")

    assert archive.list_execution_job_ids("call-1") == ["job-1", "job-2"]
