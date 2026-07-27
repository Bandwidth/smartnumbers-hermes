from transcript_listener.config import (
    DEFAULT_APP_URL,
    DEFAULT_WEBSOCKET_URL,
    config_from_mapping,
)


def test_config_reads_download_options():
    config = config_from_mapping(
        {
            "download_timeout_seconds": "7",
            "max_download_bytes": "1234",
            "allow_insecure_transcript_urls": "true",
        }
    )

    assert config.download_timeout_seconds == 7
    assert config.max_download_bytes == 1234
    assert config.allow_insecure_transcript_urls is True


def test_config_uses_public_production_urls_by_default():
    assert DEFAULT_APP_URL == "https://smartnumbers.labs.bandwidth.com"
    assert config_from_mapping({}).app_url == DEFAULT_APP_URL
    assert DEFAULT_WEBSOCKET_URL == "wss://connections.smartnumbers.labs.bandwidth.com/ws/hermes"


def test_config_reads_user_speaker_with_default():
    assert config_from_mapping({}).user_speaker == "TO"
    assert config_from_mapping({"user_speaker": "FROM"}).user_speaker == "FROM"


def test_config_reads_auto_review_options():
    config = config_from_mapping(
        {
            "auto_review_transcripts": "false",
            "auto_review_deliver": "telegram",
            "auto_review_toolsets": ["smartnumbers", "memory", "todo"],
        }
    )

    assert config.auto_review_transcripts is False
    assert config.auto_review_deliver == "telegram"
    assert config.auto_review_toolsets == ("smartnumbers", "memory", "todo")


def test_config_auto_review_defaults_to_enabled_but_no_toolset_override():
    config = config_from_mapping({})

    assert config.auto_review_transcripts is True
    assert config.auto_review_deliver == "local"
    assert config.auto_review_toolsets is None
    assert config.max_download_bytes is None
    assert config.max_websocket_message_bytes == 1024 * 1024
    assert config.max_turns is None
