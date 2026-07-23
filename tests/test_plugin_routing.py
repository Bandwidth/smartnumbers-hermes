import json
from pathlib import Path

from transcript_listener import plugin
from transcript_listener.config import config_from_mapping
from transcript_listener.downloader import TranscriptDownloadError
from transcript_listener.memory_writer import MemoryWriteResult
from transcript_listener.storage import TranscriptArchive


FIXTURE = Path(__file__).parent / "fixtures" / "transcript_001.json"

MARKDOWN_TRANSCRIPT = """1
[00:00:02,200 --> 00:00:13,079]
**TO**: Column's scheduling business. This is Erica speaking.

2
[00:00:14,609 --> 00:00:16,450]
**FROM**: Hello, I'd like to schedule an appointment.
"""


def test_transcript_url_event_downloads_then_imports(monkeypatch, tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    config = config_from_mapping(
        {
            "import_to_session_db": False,
            "extract_to_memory": False,
            "notify_cli": False,
            "download_timeout_seconds": 3,
            "max_download_bytes": 2048,
        }
    )

    def fake_download(url, *, timeout_seconds, max_bytes, allow_insecure):
        assert url == "https://example.com/transcript.json"
        assert timeout_seconds == 3
        assert max_bytes == 2048
        assert allow_insecure is False
        return FIXTURE.read_text()

    monkeypatch.setattr(plugin, "download_transcript_url", fake_download)
    event = json.dumps(
        {
            "type": "transcript_url",
            "event_id": "evt_123",
            "url": "https://example.com/transcript.json",
        }
    )

    ack = plugin._handle_websocket_message(object(), archive, config, event)

    results = archive.search(query="short version", limit=5)
    assert len(results) == 1
    assert results[0].external_session_id == "conv_001"
    assert ack is not None
    assert ack["type"] == "transcript_ack"
    assert ack["event_id"] == "evt_123"
    assert ack["conversation_id"] == "conv_001"
    assert ack["success"] is True
    assert ack["stages"]["download"] == {"attempted": True, "success": True}
    assert ack["stages"]["parse"] == {"attempted": True, "success": True}
    assert ack["stages"]["archive"] == {"attempted": True, "success": True}
    assert ack["stages"]["session_import"]["attempted"] is False
    assert ack["stages"]["memory"]["attempted"] is False
    assert ack["errors"] == []


def test_transcript_url_event_applies_markdown_metadata(monkeypatch, tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    config = config_from_mapping(
        {
            "import_to_session_db": False,
            "extract_to_memory": False,
            "notify_cli": False,
            "user_speaker": "TO",
        }
    )

    monkeypatch.setattr(plugin, "download_transcript_url", lambda *args, **kwargs: MARKDOWN_TRANSCRIPT)
    event = json.dumps(
        {
            "type": "transcript_url",
            "event_id": "evt_456",
            "url": "https://example.com/transcript.md",
            "conversation_id": "call_456",
            "source": "bandwidth-call-recording",
            "user_speaker": "FROM",
        }
    )

    ack = plugin._handle_websocket_message(object(), archive, config, event)

    results = archive.search(query="appointment", limit=5)
    assert len(results) == 1
    assert results[0].external_session_id == "call_456"
    assert ack is not None
    assert ack["success"] is True
    assert ack["conversation_id"] == "call_456"


def test_transcript_url_event_returns_ack_for_download_failure(monkeypatch, tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    config = config_from_mapping(
        {
            "import_to_session_db": False,
            "extract_to_memory": False,
            "notify_cli": False,
        }
    )

    def fake_download(url, *, timeout_seconds, max_bytes, allow_insecure):
        del url, timeout_seconds, max_bytes, allow_insecure
        raise TranscriptDownloadError("boom")

    monkeypatch.setattr(plugin, "download_transcript_url", fake_download)
    ack = plugin._handle_websocket_message(
        object(),
        archive,
        config,
        json.dumps({"type": "transcript_url", "event_id": "evt_123", "url": "https://example.com/transcript.json"}),
    )

    assert ack is not None
    assert ack["success"] is False
    assert ack["event_id"] == "evt_123"
    assert ack["stages"]["download"] == {"attempted": True, "success": False}
    assert ack["stages"]["parse"]["attempted"] is False
    assert ack["errors"] == [{"stage": "download", "message": "boom"}]


def test_direct_transcript_json_still_imports(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    config = config_from_mapping(
        {
            "import_to_session_db": False,
            "extract_to_memory": False,
            "notify_cli": False,
        }
    )

    ack = plugin._handle_websocket_message(object(), archive, config, FIXTURE.read_text())

    results = archive.search(query="short version", limit=5)
    assert len(results) == 1
    assert ack is not None
    assert ack["success"] is True
    assert ack["event_id"] is None
    assert ack["stages"]["download"]["attempted"] is False
    assert ack["stages"]["parse"] == {"attempted": True, "success": True}


def test_archive_raw_false_skips_local_archive_write(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    config = config_from_mapping(
        {
            "archive_raw": False,
            "import_to_session_db": False,
            "extract_to_memory": False,
            "notify_cli": False,
        }
    )

    ack = plugin._handle_websocket_message(object(), archive, config, FIXTURE.read_text())

    results = archive.search(query="short version", limit=5)
    assert results == []
    assert ack is not None
    assert ack["success"] is True
    assert ack["stages"]["archive"]["attempted"] is False


def test_archive_raw_false_still_imports_to_session_db(monkeypatch, tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    config = config_from_mapping(
        {
            "archive_raw": False,
            "import_to_session_db": True,
            "extract_to_memory": False,
            "notify_cli": False,
        }
    )
    imported: list[str] = []

    def fake_import_to_session_db(transcript, *, source_label):
        assert source_label == "external-reference"
        imported.append(transcript.conversation_id)
        return "external_ref_conv_001"

    monkeypatch.setattr(plugin, "import_to_session_db", fake_import_to_session_db)

    ack = plugin._handle_websocket_message(object(), archive, config, FIXTURE.read_text())

    assert imported == ["conv_001"]
    assert archive.search(query="short version", limit=5) == []
    assert ack is not None
    assert ack["success"] is True
    assert ack["stages"]["session_import"] == {"attempted": True, "success": True, "state_session_id": "external_ref_conv_001"}


def test_memory_stage_ack_counts_writes(monkeypatch, tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    config = config_from_mapping(
        {
            "import_to_session_db": False,
            "extract_to_memory": True,
            "notify_cli": False,
        }
    )

    monkeypatch.setattr(plugin, "extract_facts", lambda ctx, transcript: [{"content": "fact one"}, {"content": "fact two"}])
    monkeypatch.setattr(
        plugin,
        "write_facts_to_memory",
        lambda facts: [
            MemoryWriteResult(target="memory", content="fact one", success=True, message="ok"),
            MemoryWriteResult(target="memory", content="fact two", success=False, message="failed"),
        ],
    )

    ack = plugin._handle_websocket_message(object(), archive, config, FIXTURE.read_text())

    assert ack is not None
    assert ack["success"] is False
    assert ack["stages"]["memory"] == {
        "attempted": True,
        "success": False,
        "facts_extracted": 2,
        "writes_attempted": 2,
        "writes_succeeded": 1,
    }
    assert ack["errors"] == [{"stage": "memory", "message": "one or more memory writes failed"}]
