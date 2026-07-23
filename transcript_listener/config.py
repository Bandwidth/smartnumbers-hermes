"""Configuration loading for the transcript listener plugin."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class TranscriptListenerConfig:
    stream_url: str = ""
    user_speaker: str = "TO"
    run_listener: bool = False
    archive_raw: bool = True
    import_to_session_db: bool = True
    extract_to_memory: bool = True
    register_transcript_search_tool: bool = True
    notify_cli: bool = True
    batch_max_chars: int = 12000
    batch_idle_seconds: int = 30
    source_label: str = "external-reference"
    storage_path: Path | None = None
    download_timeout_seconds: int = 15
    max_download_bytes: int = 5 * 1024 * 1024
    allow_insecure_transcript_urls: bool = False


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
        user_speaker=_str(entry.get("user_speaker"), "TO"),
        run_listener=_bool(entry.get("run_listener"), False),
        archive_raw=_bool(entry.get("archive_raw"), True),
        import_to_session_db=_bool(entry.get("import_to_session_db"), True),
        extract_to_memory=_bool(entry.get("extract_to_memory"), True),
        register_transcript_search_tool=_bool(entry.get("register_transcript_search_tool"), True),
        notify_cli=_bool(entry.get("notify_cli"), True),
        batch_max_chars=_int(entry.get("batch_max_chars"), 12000),
        batch_idle_seconds=_int(entry.get("batch_idle_seconds"), 30),
        source_label=_str(entry.get("source_label"), "external-reference"),
        storage_path=Path(storage_path).expanduser() if isinstance(storage_path, str) and storage_path.strip() else None,
        download_timeout_seconds=_int(entry.get("download_timeout_seconds"), 15),
        max_download_bytes=_int(entry.get("max_download_bytes"), 5 * 1024 * 1024),
        allow_insecure_transcript_urls=_bool(entry.get("allow_insecure_transcript_urls"), False),
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
