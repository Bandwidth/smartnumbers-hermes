import json

from transcript_listener.review_config_tool import make_transcript_review_config_handler
from transcript_listener.storage import TranscriptArchive


def test_review_config_tool_show_set_and_clear(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive)

    initial = json.loads(handler({"action": "show"}))
    assert initial == {"success": True, "instructions": "", "auto_review_enabled": False}

    updated = json.loads(handler({"action": "set", "instructions": "Review calls for commitments."}))
    assert updated == {
        "success": True,
        "instructions": "Review calls for commitments.",
        "auto_review_enabled": True,
    }
    assert archive.get_review_instructions() == "Review calls for commitments."

    cleared = json.loads(handler({"action": "clear"}))
    assert cleared == {"success": True, "instructions": "", "auto_review_enabled": False}
    assert archive.get_review_instructions() == ""


def test_review_config_tool_requires_instructions_for_set(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive)

    result = json.loads(handler({"action": "set", "instructions": "  "}))

    assert result["success"] is False
    assert result["auto_review_enabled"] is False
    assert "instructions is required" in result["error"]
