"""Hermes plugin registration and ingestion orchestration."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from .config import default_storage_path, load_plugin_config
from .downloader import TranscriptDownloadError, download_transcript_url
from .extractor import extract_facts
from .lock import SingleInstanceLock
from .memory_writer import write_facts_to_memory
from .parser import TranscriptParseError, parse_transcript_payload
from .search_tool import TRANSCRIPT_SEARCH_SCHEMA, make_transcript_search_handler
from .session_import import import_to_session_db
from .storage import TranscriptArchive
from .ws_client import TranscriptWebSocketClient, start_daemon_listener

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
if not any(getattr(handler, "_transcript_listener_handler", False) for handler in logger.handlers):
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    handler._transcript_listener_handler = True  # type: ignore[attr-defined]
    logger.addHandler(handler)

_listener_lock: SingleInstanceLock | None = None
_listener_client: TranscriptWebSocketClient | None = None
_listener_thread: Any | None = None


def register(ctx: Any) -> None:
    global _listener_client, _listener_lock, _listener_thread

    plugin_key = getattr(getattr(ctx, "manifest", None), "key", None) or getattr(getattr(ctx, "manifest", None), "name", "smartnumbers")
    config = load_plugin_config(plugin_key)
    archive = TranscriptArchive(config.storage_path or default_storage_path())

    if config.register_transcript_search_tool:
        ctx.register_tool(
            name="transcript_search",
            toolset="transcript_listener",
            schema=TRANSCRIPT_SEARCH_SCHEMA,
            handler=make_transcript_search_handler(archive),
            description=TRANSCRIPT_SEARCH_SCHEMA["description"],
            emoji="🔎",
        )

    if config.run_listener and config.stream_url:
        if _listener_thread is not None and _listener_thread.is_alive():
            logger.info("transcript listener websocket already running in this process")
            return
        if _listener_lock is not None:
            _listener_lock.release()
            _listener_lock = None

        lock = SingleInstanceLock((config.storage_path or default_storage_path()).with_suffix(".lock"))
        if lock.acquire():
            client = TranscriptWebSocketClient(config.stream_url, hello_payload=_hello_payload(config))
            thread = start_daemon_listener(client, lambda payload: _handle_websocket_message(ctx, archive, config, payload))
            _listener_lock = lock
            _listener_client = client
            _listener_thread = thread
            logger.info("transcript listener websocket started for %s", config.stream_url)
        else:
            logger.info("transcript listener websocket already owned by another live process")


def _hello_payload(config: Any) -> dict[str, Any]:
    return {
        "type": "hello",
        "protocol_version": 1,
        "client": "hermes-transcript-listener",
    }


def _handle_websocket_message(ctx: Any, archive: TranscriptArchive, config: Any, payload: str) -> dict[str, Any] | None:
    decoded: Any = None
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            decoded = None

    if isinstance(decoded, Mapping):
        event_type = decoded.get("type")
        event_id = _str_or_none(decoded.get("event_id"))
        if event_type == "transcript_url":
            ack = _new_ack(config, event_id=event_id)
            ack["stages"]["download"]["attempted"] = True
            try:
                routed_payload = download_transcript_url(
                    str(decoded.get("url") or ""),
                    timeout_seconds=config.download_timeout_seconds,
                    max_bytes=config.max_download_bytes,
                    allow_insecure=config.allow_insecure_transcript_urls,
                )
                ack["stages"]["download"]["success"] = True
            except TranscriptDownloadError as exc:
                logger.warning("transcript URL event rejected: %s", exc)
                _add_ack_error(ack, "download", str(exc))
                return _finalize_ack(ack)
            return _ingest_payload(ctx, archive, config, routed_payload, ack, metadata=_metadata_from_event(decoded, config))

        if event_type and "conversation_id" not in decoded:
            logger.debug("ignored unsupported transcript listener event type: %s", event_type)
            return None

        return _ingest_payload(ctx, archive, config, payload, _new_ack(config, event_id=event_id), metadata=_metadata_from_event(decoded, config))

    return _ingest_payload(ctx, archive, config, payload, _new_ack(config, event_id=None))


def _metadata_from_event(event: Mapping[str, Any], config: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("conversation_id", "source", "participants"):
        if key in event:
            metadata[key] = event[key]
    metadata["user_speaker"] = event.get("user_speaker") or getattr(config, "user_speaker", "TO")
    return metadata


def _ingest_payload(
    ctx: Any,
    archive: TranscriptArchive,
    config: Any,
    payload: str,
    ack: dict[str, Any],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ack["stages"]["parse"]["attempted"] = True
    try:
        transcript = parse_transcript_payload(payload, metadata=metadata)
    except TranscriptParseError as exc:
        logger.warning("transcript payload rejected: %s", exc)
        _add_ack_error(ack, "parse", str(exc))
        return _finalize_ack(ack)

    ack["conversation_id"] = transcript.conversation_id
    ack["stages"]["parse"]["success"] = True

    state_session_id = None
    if config.import_to_session_db:
        ack["stages"]["session_import"]["attempted"] = True
        try:
            state_session_id = import_to_session_db(transcript, source_label=config.source_label)
            ack["stages"]["session_import"]["success"] = True
            ack["stages"]["session_import"]["state_session_id"] = state_session_id
        except Exception as exc:
            logger.warning("transcript SessionDB import failed: %s", exc)
            _add_ack_error(ack, "session_import", str(exc))

    extraction_status = "skipped"
    extraction_error = None
    if config.extract_to_memory:
        ack["stages"]["memory"]["attempted"] = True
        try:
            facts = extract_facts(ctx, transcript)
            write_results = write_facts_to_memory(facts)
            writes_succeeded = sum(1 for r in write_results if r.success)
            ack["stages"]["memory"]["facts_extracted"] = len(facts)
            ack["stages"]["memory"]["writes_attempted"] = len(write_results)
            ack["stages"]["memory"]["writes_succeeded"] = writes_succeeded
            ack["stages"]["memory"]["success"] = writes_succeeded == len(write_results)
            extraction_status = f"facts:{len(facts)} writes:{writes_succeeded}"
            if writes_succeeded != len(write_results):
                _add_ack_error(ack, "memory", "one or more memory writes failed")
        except Exception as exc:
            extraction_status = "error"
            extraction_error = str(exc)
            logger.warning("transcript fact extraction failed: %s", exc)
            _add_ack_error(ack, "memory", str(exc))

    if config.archive_raw:
        ack["stages"]["archive"]["attempted"] = True
        try:
            archive.save_transcript(
                transcript,
                state_session_id=state_session_id,
                extraction_status=extraction_status,
                extraction_error=extraction_error,
            )
            ack["stages"]["archive"]["success"] = True
        except Exception as exc:
            logger.warning("transcript archive write failed: %s", exc)
            _add_ack_error(ack, "archive", str(exc))

    if config.notify_cli:
        try:
            ctx.inject_message(
                f"Imported external transcript {transcript.conversation_id} ({len(transcript.turns)} turns).",
                role="system",
            )
        except Exception:
            pass

    return _finalize_ack(ack)


def _new_ack(config: Any, *, event_id: str | None) -> dict[str, Any]:
    return {
        "type": "transcript_ack",
        "protocol_version": 1,
        "event_id": event_id,
        "conversation_id": None,
        "success": False,
        "stages": {
            "download": {"attempted": False, "success": False},
            "parse": {"attempted": False, "success": False},
            "archive": {"attempted": False, "success": False},
            "session_import": {"attempted": False, "success": False, "state_session_id": None},
            "memory": {
                "attempted": False,
                "success": False,
                "facts_extracted": 0,
                "writes_attempted": 0,
                "writes_succeeded": 0,
            },
        },
        "errors": [],
    }


def _add_ack_error(ack: dict[str, Any], stage: str, message: str) -> None:
    ack["errors"].append({"stage": stage, "message": message})


def _finalize_ack(ack: dict[str, Any]) -> dict[str, Any]:
    stages = ack["stages"]
    attempted_stages_succeeded = all(stage["success"] for stage in stages.values() if stage["attempted"])
    ack["success"] = bool(stages["parse"]["success"] and attempted_stages_succeeded and not ack["errors"])
    logger.debug("transcript ack prepared event_id=%s success=%s payload=%s", ack.get("event_id"), ack["success"], ack)
    return ack


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
