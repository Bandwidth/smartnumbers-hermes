"""Configuration loading for the transcript listener plugin."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_APP_URL = "https://smartnumbers.labs.bandwidth.com"
DEFAULT_WEBSOCKET_URL = "wss://connections.smartnumbers.labs.bandwidth.com/ws/hermes"


@dataclass(frozen=True)
class TranscriptListenerConfig:
    stream_url: str = ""
    app_url: str = DEFAULT_APP_URL
    key_prefix: str = ""
    run_listener: bool = False
    archive_raw: bool = True
    extract_to_memory: bool = True
    register_transcript_search_tool: bool = True
    storage_path: Path | None = None
    download_timeout_seconds: int = 15
    max_download_bytes: int | None = None
    allow_insecure_transcript_urls: bool = False
    auto_review_transcripts: bool = True
    auto_review_deliver: str = "local"
    auto_review_toolsets: tuple[str, ...] | None = None
    activation_names: tuple[str, ...] = ()
    max_websocket_message_bytes: int = 1024 * 1024
    allowed_stream_hosts: tuple[str, ...] = ("connections.smartnumbers.labs.bandwidth.com",)
    allow_insecure_stream_url: bool = False
    allowed_transcript_hosts: tuple[str, ...] = ()


def load_plugin_config(plugin_key: str = "smartnumbers") -> TranscriptListenerConfig:
    """Load plugin config from Hermes when available, otherwise defaults."""

    entry: Mapping[str, Any] = {}
    try:
        from hermes_cli.config import cfg_get, load_config_readonly

        cfg = load_config_readonly()
        raw_entry = cfg_get(cfg, "plugins", "entries", plugin_key, default={})
        if isinstance(raw_entry, Mapping):
            entry = raw_entry
    except Exception:
        entry = {}

    return config_from_mapping(entry)


def config_from_mapping(entry: Mapping[str, Any]) -> TranscriptListenerConfig:
    storage_path = entry.get("storage_path")
    return TranscriptListenerConfig(
        stream_url=_str(entry.get("stream_url")),
        app_url=_str(entry.get("app_url"), DEFAULT_APP_URL),
        key_prefix=_str(entry.get("key_prefix")),
        run_listener=_bool(entry.get("run_listener"), False),
        archive_raw=_bool(entry.get("archive_raw"), True),
        extract_to_memory=_bool(entry.get("extract_to_memory"), True),
        register_transcript_search_tool=_bool(entry.get("register_transcript_search_tool"), True),
        storage_path=Path(storage_path).expanduser() if isinstance(storage_path, str) and storage_path.strip() else None,
        download_timeout_seconds=_int(entry.get("download_timeout_seconds"), 15),
        max_download_bytes=_optional_bounded_int(entry.get("max_download_bytes"), minimum=1, maximum=1024 * 1024 * 1024),
        allow_insecure_transcript_urls=_bool(entry.get("allow_insecure_transcript_urls"), False),
        auto_review_transcripts=_bool(entry.get("auto_review_transcripts"), True),
        auto_review_deliver=_str(entry.get("auto_review_deliver"), "local"),
        auto_review_toolsets=_str_tuple(entry.get("auto_review_toolsets")),
        activation_names=_str_tuple(entry.get("activation_names")) or (),
        max_websocket_message_bytes=_bounded_int(
            entry.get("max_websocket_message_bytes"),
            1024 * 1024,
            minimum=1024,
            maximum=1024 * 1024 * 1024,
        ),
        allowed_stream_hosts=_str_tuple(entry.get("allowed_stream_hosts")) or ("connections.smartnumbers.labs.bandwidth.com",),
        allow_insecure_stream_url=_bool(entry.get("allow_insecure_stream_url"), False),
        allowed_transcript_hosts=_str_tuple(entry.get("allowed_transcript_hosts")) or (),
    )


def default_storage_path() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return get_hermes_home() / "transcript_listener" / "transcripts.db"
    except Exception:
        return Path.home() / ".hermes" / "transcript_listener" / "transcripts.db"


def _str(value: Any, default: str = "") -> str:
    return value.strip() if isinstance(value, str) and value.strip() else default


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bounded_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    return min(maximum, max(minimum, _int(value, default)))


def _optional_bounded_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    if value is None or value == "":
        return None
    return _bounded_int(value, minimum, minimum=minimum, maximum=maximum)


def _str_tuple(value: Any) -> tuple[str, ...] | None:
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
        return tuple(item for item in items if item) or None
    if isinstance(value, list):
        items = [item.strip() for item in value if isinstance(item, str)]
        return tuple(item for item in items if item) or None
    if isinstance(value, tuple):
        items = [item.strip() for item in value if isinstance(item, str)]
        return tuple(item for item in items if item) or None
    return None
