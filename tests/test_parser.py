import json
from pathlib import Path

import pytest

from transcript_listener.parser import TranscriptParseError, parse_transcript_payload


FIXTURE = Path(__file__).parent / "fixtures" / "transcript_001.json"

MARKDOWN_TRANSCRIPT = """1
[00:00:02,200 --> 00:00:13,079]
**TO**: Column's scheduling business. This is Erica speaking.

2
[00:00:14,609 --> 00:00:16,450]
**FROM**: Hello, I'd like to schedule an appointment.

3
[00:00:20,770 --> 00:00:32,470]
**TO**: OK, I can help schedule that service.
"""


def test_parse_transcript_fixture():
    transcript = parse_transcript_payload(FIXTURE.read_text())

    assert transcript.conversation_id == "conv_001"
    assert transcript.source == "test-fixture"
    assert transcript.participants["person_x"] == "Alex"
    assert len(transcript.turns) == 3
    assert transcript.turns[0].speaker_label == "Damien"


def test_parse_rejects_empty_turns():
    payload = {"conversation_id": "conv", "turns": []}

    with pytest.raises(TranscriptParseError):
        parse_transcript_payload(payload)


def test_parse_accepts_mapping_and_json():
    payload = {
        "conversation_id": "conv",
        "participants": {"a": "A"},
        "turns": [{"speaker": "a", "text": "hello"}],
    }

    assert parse_transcript_payload(payload).conversation_id == "conv"
    assert parse_transcript_payload(json.dumps(payload)).conversation_id == "conv"


def test_parse_accepts_markdown_transcript_with_metadata():
    transcript = parse_transcript_payload(
        MARKDOWN_TRANSCRIPT,
        metadata={
            "conversation_id": "call_123",
            "source": "bandwidth-call-recording",
            "user_speaker": "TO",
            "direction": "inbound",
            "from": "+18636389992",
            "to": "+18633307564",
        },
    )

    assert transcript.conversation_id == "call_123"
    assert transcript.source == "bandwidth-call-recording"
    assert transcript.user_speaker == "TO"
    assert transcript.direction == "inbound"
    assert transcript.from_number == "+18636389992"
    assert transcript.to_number == "+18633307564"
    assert transcript.participants == {}
    assert len(transcript.turns) == 3
    assert transcript.turns[0].speaker == "TO"
    assert transcript.turns[0].speaker_label == "TO"
    assert transcript.turns[0].timestamp == "00:00:02,200 --> 00:00:13,079"
    assert transcript.turns[1].speaker == "FROM"
    assert transcript.turns[1].text == "Hello, I'd like to schedule an appointment."


def test_parse_markdown_generates_stable_conversation_id_when_missing():
    first = parse_transcript_payload(MARKDOWN_TRANSCRIPT)
    second = parse_transcript_payload(MARKDOWN_TRANSCRIPT)

    assert first.conversation_id.startswith("transcript_")
    assert first.conversation_id == second.conversation_id
    assert first.source == "external-transcript"
    assert first.user_speaker == "TO"
    assert first.direction == "inbound"


def test_parse_invalid_direction_defaults_to_inbound():
    transcript = parse_transcript_payload(
        {
            "conversation_id": "call_direction",
            "direction": "sideways",
            "turns": [{"speaker": "TO", "text": "hello"}],
        }
    )

    assert transcript.direction == "inbound"


def test_parse_derives_user_speaker_from_outbound_direction():
    transcript = parse_transcript_payload(
        {
            "conversation_id": "call_outbound",
            "direction": "outbound",
            "user_speaker": "TO",
            "turns": [{"speaker": "FROM", "text": "hello"}],
        }
    )

    assert transcript.direction == "outbound"
    assert transcript.user_speaker == "FROM"
