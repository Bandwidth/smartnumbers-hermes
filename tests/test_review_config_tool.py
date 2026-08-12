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


def test_register_requires_new_id_and_update_requires_existing_id(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive)

    registered = json.loads(
        handler(
            {
                "action": "register",
                "id": "My Calendar",
                "name": "Calendar",
                "instructions": "Add agreed events.",
                "enabled": False,
            }
        )
    )
    duplicate = json.loads(
        handler(
            {
                "action": "register",
                "id": "my-calendar",
                "name": "Replacement",
                "instructions": "Replace the existing callback.",
            }
        )
    )
    missing = json.loads(
        handler(
            {
                "action": "update",
                "id": "missing",
                "name": "Missing",
                "instructions": "This must not be created.",
            }
        )
    )
    updated = json.loads(
        handler(
            {
                "action": "update",
                "id": "My Calendar",
                "name": "Calendar follow-up",
                "instructions": "Add only confirmed events.",
            }
        )
    )

    assert registered["success"] is True
    assert registered["callbacks"][0]["id"] == "my-calendar"
    assert duplicate == {"success": False, "callbacks": [], "error": "callback already exists"}
    assert missing == {"success": False, "callbacks": [], "error": "callback was not found"}
    assert updated["success"] is True
    assert updated["callbacks"][0] == {
        "id": "my-calendar",
        "name": "Calendar follow-up",
        "instructions": "Add only confirmed events.",
        "enabled": False,
        "deliver": None,
    }
    assert archive.get_callback("missing") is None


def test_callback_mutations_normalize_ids_consistently(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive)
    handler(
        {
            "action": "register",
            "id": "My Calendar",
            "name": "Calendar",
            "instructions": "Add agreed events.",
            "enabled": False,
        }
    )

    enabled = json.loads(handler({"action": "enable", "id": "My Calendar"}))
    removed = json.loads(handler({"action": "remove", "id": "My Calendar"}))

    assert enabled["success"] is True
    assert enabled["callbacks"][0]["enabled"] is True
    assert removed == {"success": True, "callbacks": []}
    assert archive.get_callback("my-calendar") is None


def test_callback_delivery_override_can_be_preserved_and_cleared(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive)

    registered = json.loads(
        handler(
            {
                "action": "register",
                "id": "calendar",
                "name": "Calendar",
                "instructions": "Add agreed events.",
                "deliver": "telegram",
            }
        )
    )
    preserved = json.loads(
        handler(
            {
                "action": "update",
                "id": "calendar",
                "name": "Calendar",
                "instructions": "Add only confirmed events.",
            }
        )
    )
    cleared = json.loads(
        handler(
            {
                "action": "update",
                "id": "calendar",
                "name": "Calendar",
                "instructions": "Add only confirmed events.",
                "deliver": "",
            }
        )
    )

    assert registered["callbacks"][0]["deliver"] == "telegram"
    assert preserved["callbacks"][0]["deliver"] == "telegram"
    assert cleared["callbacks"][0]["deliver"] is None


def test_default_callback_set_preserves_delivery_override(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive)

    handler({"action": "set", "instructions": "Review calls.", "deliver": "telegram"})
    handler({"action": "set", "instructions": "Review calls carefully."})

    callbacks = json.loads(handler({"action": "list"}))["callbacks"]
    assert callbacks[0]["deliver"] == "telegram"
