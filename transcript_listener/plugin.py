"""Hermes plugin registration and ingestion orchestration."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .cli import handle_cli, setup_cli_parser
from .config import TranscriptListenerConfig, default_storage_path, load_plugin_config
from .downloader import TranscriptDownloadError, download_transcript_url
from .extractor import extract_facts
from .lock import SingleInstanceLock
from .memory_writer import write_facts_to_memory
from .parser import TranscriptParseError, parse_transcript_payload
from .review_config_tool import TRANSCRIPT_REVIEW_CONFIG_SCHEMA, make_transcript_review_config_handler
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

    plugin_key = getattr(getattr(ctx, "manifest", None), "key", None) or getattr(
        getattr(ctx, "manifest", None), "name", "smartnumbers"
    )
    config = load_plugin_config(plugin_key)
    archive = TranscriptArchive(config.storage_path or default_storage_path())

    if hasattr(ctx, "register_cli_command"):
        ctx.register_cli_command(
            name="smartnumbers",
            help="Manage Smart Numbers transcript listener setup",
            setup_fn=setup_cli_parser,
            handler_fn=handle_cli,
        )

    if config.register_transcript_search_tool:
        ctx.register_tool(
            name="transcript_search",
            toolset="smartnumbers",
            schema=TRANSCRIPT_SEARCH_SCHEMA,
            handler=make_transcript_search_handler(archive),
            description=TRANSCRIPT_SEARCH_SCHEMA["description"],
            emoji="🔎",
        )
    ctx.register_tool(
        name="transcript_review_config",
        toolset="smartnumbers",
        schema=TRANSCRIPT_REVIEW_CONFIG_SCHEMA,
        handler=make_transcript_review_config_handler(archive),
        description=TRANSCRIPT_REVIEW_CONFIG_SCHEMA["description"],
        emoji="📝",
    )

    if config.run_listener and config.stream_url:
        if not os.environ.get("TRANSCRIPT_LISTENER_API_KEY", "").strip():
            logger.warning(
                "transcript listener is enabled but TRANSCRIPT_LISTENER_API_KEY is missing; "
                "run `hermes smartnumbers setup`"
            )
            return
        if _listener_thread is not None and _listener_thread.is_alive():
            logger.info("transcript listener websocket already running in this process")
            return
        if _listener_lock is not None:
            _listener_lock.release()
            _listener_lock = None

        lock = SingleInstanceLock((config.storage_path or default_storage_path()).with_suffix(".lock"))
        if lock.acquire():
            client = TranscriptWebSocketClient(config.stream_url, hello_payload=_hello_payload())
            thread = start_daemon_listener(client, lambda payload: _handle_websocket_message(ctx, archive, config, payload))
            _listener_lock = lock
            _listener_client = client
            _listener_thread = thread
            logger.info("transcript listener websocket started for %s", config.stream_url)
        else:
            logger.info("transcript listener websocket already owned by another live process")


def _hello_payload() -> dict[str, Any]:
    return {
        "type": "hello",
        "protocol_version": 1,
        "client": "hermes-transcript-listener",
    }


def _handle_websocket_message(
    ctx: Any,
    archive: TranscriptArchive,
    config: TranscriptListenerConfig,
    payload: str,
) -> dict[str, Any] | None:
    event_received_at = _utc_now_iso()
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
            ack = _new_ack(event_id=event_id)
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
            return _ingest_payload(
                ctx,
                archive,
                config,
                routed_payload,
                ack,
                metadata=_metadata_from_event(decoded, config),
                event_received_at=event_received_at,
            )

        if event_type and "conversation_id" not in decoded:
            logger.debug("ignored unsupported transcript listener event type: %s", event_type)
            return None

        return _ingest_payload(
            ctx,
            archive,
            config,
            payload,
            _new_ack(event_id=event_id),
            metadata=_metadata_from_event(decoded, config),
            event_received_at=event_received_at,
        )

    return _ingest_payload(ctx, archive, config, payload, _new_ack(event_id=None), event_received_at=event_received_at)


def _metadata_from_event(event: Mapping[str, Any], config: TranscriptListenerConfig) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("conversation_id", "source", "participants"):
        if key in event:
            metadata[key] = event[key]
    metadata["user_speaker"] = event.get("user_speaker") or config.user_speaker
    return metadata


def _ingest_payload(
    ctx: Any,
    archive: TranscriptArchive,
    config: TranscriptListenerConfig,
    payload: str,
    ack: dict[str, Any],
    *,
    metadata: Mapping[str, Any] | None = None,
    event_received_at: str | None = None,
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
                event_received_at=event_received_at,
            )
            ack["stages"]["archive"]["success"] = True
            review_result = _maybe_dispatch_auto_review(ctx, archive, config, transcript, event_received_at=event_received_at)
            ack["stages"]["review"].update(review_result)
            if review_result["attempted"] and not review_result["success"]:
                _add_ack_error(ack, "review", str(review_result.get("error") or "transcript review dispatch failed"))
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


def _new_ack(*, event_id: str | None) -> dict[str, Any]:
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
            "review": {"attempted": False, "success": False, "status": "not_started", "job_id": None},
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


def _maybe_dispatch_auto_review(
    ctx: Any,
    archive: TranscriptArchive,
    config: Any,
    transcript: Any,
    *,
    event_received_at: str | None,
) -> dict[str, Any]:
    if not getattr(config, "auto_review_transcripts", True):
        archive.mark_review_status(transcript.conversation_id, review_status="skipped:disabled")
        return {"attempted": False, "success": False, "status": "skipped:disabled", "job_id": None}

    review_state = archive.get_review_state(transcript.conversation_id)
    if review_state.get("review_job_id") or review_state.get("review_status") == "dispatched":
        return {
            "attempted": False,
            "success": True,
            "status": "skipped:duplicate",
            "job_id": review_state.get("review_job_id"),
        }

    instructions = archive.get_review_instructions()
    if not instructions:
        archive.mark_review_status(transcript.conversation_id, review_status="skipped:no_instructions")
        return {"attempted": False, "success": False, "status": "skipped:no_instructions", "job_id": None}

    requested_at = _utc_now_iso()
    args: dict[str, Any] = {
        "action": "create",
        "schedule": requested_at,
        "prompt": _build_auto_review_prompt(transcript, instructions, event_received_at=event_received_at),
        "name": f"Review transcript {transcript.conversation_id}",
        "deliver": getattr(config, "auto_review_deliver", "local") or "local",
    }
    toolsets = getattr(config, "auto_review_toolsets", None)
    if toolsets:
        args["enabled_toolsets"] = list(toolsets)

    try:
        dispatch_tool = getattr(ctx, "dispatch_tool")
        raw_result = dispatch_tool("cronjob", args)
        job_id = _extract_review_job_id(raw_result)
        archive.mark_review_status(
            transcript.conversation_id,
            review_requested_at=requested_at,
            review_job_id=job_id,
            review_status="dispatched",
        )
        return {"attempted": True, "success": True, "status": "dispatched", "job_id": job_id}
    except Exception as exc:
        error = str(exc)
        logger.warning("transcript auto-review dispatch failed: %s", error)
        archive.mark_review_status(
            transcript.conversation_id,
            review_requested_at=requested_at,
            review_status="error",
            review_error=error,
        )
        return {"attempted": True, "success": False, "status": "error", "job_id": None, "error": error}


def _build_auto_review_prompt(transcript: Any, instructions: str, *, event_received_at: str | None) -> str:
    return "\n".join(
        [
            "A new phone transcript is available.",
            "",
            f"Conversation ID: {transcript.conversation_id}",
            f"Received at: {event_received_at or 'unknown'}",
            f"Source: {transcript.source}",
            f"Turn count: {len(transcript.turns)}",
            "",
            "Transcript access:",
            f"Use transcript_search with external_session_id={transcript.conversation_id!r} to inspect this transcript.",
            "",
            "User-configured transcript review instructions:",
            instructions.strip(),
        ]
    )


def _extract_review_job_id(raw_result: Any) -> str | None:
    parsed: Any = raw_result
    if isinstance(raw_result, str):
        try:
            parsed = json.loads(raw_result)
        except json.JSONDecodeError:
            return None
    if isinstance(parsed, Mapping):
        for key in ("job_id", "id"):
            value = parsed.get(key)
            if value:
                return str(value)
        job = parsed.get("job")
        if isinstance(job, Mapping) and job.get("id"):
            return str(job["id"])
    return None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
