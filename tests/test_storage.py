from pathlib import Path

from transcript_listener.parser import parse_transcript_payload
from transcript_listener.storage import TranscriptArchive


FIXTURE = Path(__file__).parent / "fixtures" / "transcript_001.json"


def test_archive_save_and_search(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    transcript = parse_transcript_payload(FIXTURE.read_text())

    archive.save_transcript(transcript, state_session_id="external_ref_conv_001")
    results = archive.search(query="approve", limit=5)

    assert len(results) == 1
    assert results[0].external_session_id == "conv_001"
    assert results[0].speaker_label == "Damien"
    assert results[0].state_session_id == "external_ref_conv_001"


def test_archive_filters_by_speaker(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    archive.save_transcript(parse_transcript_payload(FIXTURE.read_text()))

    results = archive.search(speaker="Alex", limit=5)

    assert len(results) == 1
    assert results[0].speaker == "person_x"
