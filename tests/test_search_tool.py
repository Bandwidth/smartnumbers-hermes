import json
from pathlib import Path

from transcript_listener.parser import parse_transcript_payload
from transcript_listener.search_tool import make_transcript_search_handler
from transcript_listener.storage import TranscriptArchive


FIXTURE = Path(__file__).parent / "fixtures" / "transcript_001.json"


def test_transcript_search_tool_returns_json(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    archive.save_transcript(
        parse_transcript_payload(
            FIXTURE.read_text(),
            metadata={"direction": "inbound", "from": "+18636389992", "to": "+18633307564"},
        )
    )
    handler = make_transcript_search_handler(archive)

    payload = json.loads(handler({"query": "short version", "from": "+18636389992", "limit": 10}))

    assert payload["success"] is True
    assert payload["count"] == 1
    assert payload["results"][0]["external_session_id"] == "conv_001"
    assert payload["results"][0]["direction"] == "inbound"
    assert payload["results"][0]["from"] == "+18636389992"
    assert payload["results"][0]["to"] == "+18633307564"
    assert payload["results"][0]["event_received_at"]
