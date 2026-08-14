import json

from transcript_listener import review_config_tool
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


def test_callback_delivery_override_rejects_unknown_destination(monkeypatch, tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive)
    monkeypatch.setattr(
        review_config_tool,
        "_configured_delivery_locations",
        lambda: review_config_tool._DeliveryLocations(frozenset({"telegram"}), frozenset({"telegram"})),
    )

    result = json.loads(
        handler(
            {
                "action": "register",
                "id": "summary",
                "name": "Summary",
                "instructions": "Summarize the call.",
                "deliver": "telgram",
            }
        )
    )

    assert result["success"] is False
    assert "callback delivery platform 'telgram' is not configured and enabled" in result["error"]
    assert archive.get_callback("summary") is None


def test_callback_delivery_override_normalizes_supported_destinations(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive)

    result = json.loads(
        handler(
            {
                "action": "register",
                "id": "summary",
                "name": "Summary",
                "instructions": "Summarize the call.",
                "deliver": " Telegram:-1001234567890:17585, LOCAL ",
            }
        )
    )

    assert result["success"] is True
    assert result["callbacks"][0]["deliver"] == "telegram:-1001234567890:17585,local"


def test_callback_delivery_override_rejects_malformed_explicit_target(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive)

    result = json.loads(
        handler(
            {
                "action": "set",
                "instructions": "Summarize the call.",
                "deliver": "telegram:",
            }
        )
    )

    assert result["success"] is False
    assert result["error"] == "explicit callback delivery targets require a destination ID"
    assert archive.get_review_instructions() == ""


def test_callback_delivery_override_rejects_non_string_value(tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive)

    result = json.loads(
        handler(
            {
                "action": "set",
                "instructions": "Summarize the call.",
                "deliver": ["telegram"],
            }
        )
    )

    assert result["success"] is False
    assert result["error"] == "callback delivery target must be a string"
    assert archive.get_review_instructions() == ""


def test_callback_delivery_validation_accepts_configured_plugin_platform(monkeypatch, tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive)
    monkeypatch.setattr(
        review_config_tool,
        "_configured_delivery_locations",
        lambda: review_config_tool._DeliveryLocations(frozenset({"custom_chat"}), frozenset({"custom_chat"})),
    )

    result = json.loads(
        handler(
            {
                "action": "register",
                "id": "summary",
                "name": "Summary",
                "instructions": "Summarize the call.",
                "deliver": "custom_chat",
            }
        )
    )

    assert result["success"] is True
    assert result["callbacks"][0]["deliver"] == "custom_chat"


def test_callback_delivery_validation_rejects_unconfigured_builtin(monkeypatch, tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive)
    monkeypatch.setattr(
        review_config_tool,
        "_configured_delivery_locations",
        lambda: review_config_tool._DeliveryLocations(frozenset({"discord"}), frozenset({"discord"})),
    )

    result = json.loads(
        handler(
            {
                "action": "register",
                "id": "summary",
                "name": "Summary",
                "instructions": "Summarize the call.",
                "deliver": "telegram",
            }
        )
    )

    assert result["success"] is False
    assert result["error"] == (
        "callback delivery platform 'telegram' is not configured and enabled; "
        "configured platforms: discord"
    )
    assert archive.get_callback("summary") is None


def test_inherited_default_delivery_is_validated_on_callback_creation(monkeypatch, tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive, default_deliver="telegram")
    monkeypatch.setattr(
        review_config_tool,
        "_configured_delivery_locations",
        lambda: review_config_tool._DeliveryLocations(frozenset({"discord"}), frozenset({"discord"})),
    )

    result = json.loads(
        handler(
            {
                "action": "register",
                "id": "summary",
                "name": "Summary",
                "instructions": "Summarize the call.",
            }
        )
    )

    assert result["success"] is False
    assert "platform 'telegram' is not configured and enabled" in result["error"]
    assert archive.get_callback("summary") is None


def test_explicit_target_only_requires_configured_platform(monkeypatch, tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive)
    monkeypatch.setattr(
        review_config_tool,
        "_configured_delivery_locations",
        lambda: review_config_tool._DeliveryLocations(frozenset({"custom_chat"}), frozenset()),
    )

    explicit = json.loads(
        handler(
            {
                "action": "register",
                "id": "explicit",
                "name": "Explicit",
                "instructions": "Summarize the call.",
                "deliver": "custom_chat:room-1",
            }
        )
    )
    missing_home = json.loads(
        handler(
            {
                "action": "register",
                "id": "home",
                "name": "Home",
                "instructions": "Summarize the call.",
                "deliver": "custom_chat",
            }
        )
    )

    assert explicit["success"] is True
    assert missing_home["success"] is False
    assert "has no configured home delivery location" in missing_home["error"]


def test_fanout_route_does_not_require_a_configured_home_location(monkeypatch, tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive)
    monkeypatch.setattr(
        review_config_tool,
        "_configured_delivery_locations",
        lambda: review_config_tool._DeliveryLocations(frozenset({"custom_chat"}), frozenset()),
    )

    result = json.loads(
        handler(
            {
                "action": "set",
                "instructions": "Summarize the call.",
                "deliver": "all",
            }
        )
    )

    assert result["success"] is True
    assert archive.get_callback("default-review").deliver == "all"


def test_origin_is_rejected_as_an_unconfigured_platform(monkeypatch, tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive)
    monkeypatch.setattr(
        review_config_tool,
        "_configured_delivery_locations",
        lambda: review_config_tool._DeliveryLocations(frozenset({"telegram"}), frozenset({"telegram"})),
    )

    result = json.loads(
        handler(
            {
                "action": "set",
                "instructions": "Summarize the call.",
                "deliver": "origin",
            }
        )
    )

    assert result["success"] is False
    assert "platform 'origin' is not configured and enabled" in result["error"]


def test_callback_delivery_validation_fails_closed_when_configuration_cannot_be_loaded(monkeypatch, tmp_path):
    archive = TranscriptArchive(tmp_path / "transcripts.db")
    handler = make_transcript_review_config_handler(archive)

    def fail_validation():
        raise RuntimeError("unable to validate callback delivery locations: broken config")

    monkeypatch.setattr(review_config_tool, "_configured_delivery_locations", fail_validation)

    result = json.loads(
        handler(
            {
                "action": "register",
                "id": "summary",
                "name": "Summary",
                "instructions": "Summarize the call.",
                "deliver": "telegram",
            }
        )
    )

    assert result["success"] is False
    assert result["error"] == "unable to validate callback delivery locations: broken config"
    assert archive.get_callback("summary") is None
