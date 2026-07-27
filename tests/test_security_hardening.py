import json
import os
import sqlite3

import pytest

from transcript_listener import downloader
from transcript_listener.config import config_from_mapping
from transcript_listener.downloader import TranscriptDownloadError
from transcript_listener.extractor import extract_facts
from transcript_listener.parser import TranscriptParseError, parse_transcript_payload
from transcript_listener.review_config_tool import make_transcript_review_config_handler
from transcript_listener.storage import TranscriptArchive
from transcript_listener.ws_client import validate_stream_url


def test_downloader_rejects_private_destination_before_opening(monkeypatch):
    monkeypatch.setattr(downloader.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 0))])

    with pytest.raises(TranscriptDownloadError, match="private or reserved"):
        downloader.download_transcript_url("https://example.com/transcript.json")


def test_downloader_enforces_host_allowlist(monkeypatch):
    monkeypatch.setattr(downloader.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("8.8.8.8", 0))])

    with pytest.raises(TranscriptDownloadError, match="not approved"):
        downloader.download_transcript_url("https://example.com/transcript.json", allowed_hosts=("storage.example",))


def test_stream_url_requires_approved_wss_destination():
    validate_stream_url(
        "wss://connections.smartnumbers.labs.bandwidth.com/ws/hermes",
        allowed_hosts=("connections.smartnumbers.labs.bandwidth.com",),
        allow_insecure=False,
    )
    with pytest.raises(ValueError, match="not approved"):
        validate_stream_url("wss://attacker.example/ws", allowed_hosts=("connections.smartnumbers.labs.bandwidth.com",), allow_insecure=False)


def test_parser_enforces_turn_and_character_limits():
    with pytest.raises(TranscriptParseError, match="turn limit"):
        parse_transcript_payload({"conversation_id": "x", "turns": [{"speaker": "TO", "text": "a"}, {"speaker": "TO", "text": "b"}]}, max_turns=1)
    with pytest.raises(TranscriptParseError, match="character limit"):
        parse_transcript_payload({"conversation_id": "x", "turns": [{"speaker": "TO", "text": "abcdef"}]}, max_turn_chars=5)


def test_parser_accepts_large_transcripts_without_an_application_default_cap():
    transcript = parse_transcript_payload(
        {"conversation_id": "large", "turns": [{"speaker": "TO", "text": "x" * 200_000}]}
    )

    assert len(transcript.turns[0].text) == 200_000


def test_fact_extraction_processes_every_long_turn_in_chunks():
    transcript = parse_transcript_payload(
        {"conversation_id": "large", "turns": [{"speaker": "TO", "text": "x" * 100}]},
        metadata={"user_speaker": "TO"},
    )
    calls = []

    class LLM:
        def complete_structured(self, **kwargs):  # noqa: ANN003
            calls.append(kwargs["input"][0]["text"])
            return type("Result", (), {"parsed": {"facts": []}})()

    extract_facts(type("Context", (), {"llm": LLM()})(), transcript, batch_max_chars=30)

    assert len(calls) > 1


def test_callback_registry_migrates_legacy_instruction_and_paginates_search(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    archive.set_setting("review_instructions", "Create follow-up tasks.")
    archive._init_schema()

    callbacks = archive.list_callbacks()

    assert callbacks[0].callback_id == "default-review"
    assert callbacks[0].instructions == "Create follow-up tasks."


def test_callback_registry_has_no_revision_concept(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    callback = archive.upsert_callback(
        callback_id="calendar",
        name="Calendar",
        instructions="Add agreed events.",
    )

    assert callback.to_dict() == {
        "id": "calendar",
        "name": "Calendar",
        "instructions": "Add agreed events.",
        "enabled": True,
    }
    with archive._connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(transcript_callbacks)")}
    assert "revision" not in columns


def test_callback_registry_remains_compatible_with_legacy_revision_column(tmp_path):
    path = tmp_path / "transcripts.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE transcript_callbacks (
                callback_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                instructions TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )

    archive = TranscriptArchive(path)
    callback = archive.upsert_callback(
        callback_id="calendar",
        name="Calendar",
        instructions="Add agreed events.",
    )

    assert callback.to_dict()["id"] == "calendar"
    assert "revision" not in callback.to_dict()


def test_cron_callback_mutation_requires_named_command_token(monkeypatch, tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive)
    monkeypatch.setenv("HERMES_CRON_SESSION", "1")

    denied = json.loads(handler({"action": "register", "id": "calendar", "name": "Calendar", "instructions": "Add events."}))
    token = archive.create_callback_mutation_token(uses=1)
    allowed = json.loads(
        handler(
            {
                "action": "register",
                "id": "calendar",
                "name": "Calendar",
                "instructions": "Add events.",
                "authorization_token": token,
            }
        )
    )

    assert denied["success"] is False
    assert allowed["success"] is True
    assert archive.get_callback("calendar") is not None


def test_callback_execution_claims_are_idempotent(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    kwargs = {
        "execution_key": "execution-1",
        "conversation_id": "call-1",
        "execution_kind": "callbacks",
        "callback_id": None,
        "authorization_quote": "registered callback",
    }

    assert archive.claim_execution(**kwargs) is True
    assert archive.claim_execution(**kwargs) is False
    archive.complete_execution("execution-1", error="dispatch failed")
    assert archive.claim_execution(**kwargs) is True


def test_archive_files_are_private(tmp_path):
    archive = TranscriptArchive(tmp_path / "nested" / "transcripts.db")

    assert os.stat(archive.path.parent).st_mode & 0o777 == 0o700
    assert os.stat(archive.path).st_mode & 0o777 == 0o600
