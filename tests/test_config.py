from transcript_listener.config import config_from_mapping


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


def test_config_reads_user_speaker_with_default():
    assert config_from_mapping({}).user_speaker == "TO"
    assert config_from_mapping({"user_speaker": "FROM"}).user_speaker == "FROM"
