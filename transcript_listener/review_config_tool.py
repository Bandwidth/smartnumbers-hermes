"""Hermes tool for configuring transcript auto-review instructions."""

from __future__ import annotations

import json
import os
from typing import Any

from .storage import TranscriptArchive


TRANSCRIPT_REVIEW_CONFIG_SCHEMA = {
    "name": "transcript_review_config",
    "description": (
        "Manage generic post-call callbacks. Callbacks contain user-authorized natural-language "
        "instructions that Hermes evaluates after a transcript arrives."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["show", "set", "clear", "list", "register", "update", "enable", "disable", "remove"],
                "description": "Legacy show/set/clear manage the default callback. register/update/enable/disable/remove manage independent callbacks.",
            },
            "instructions": {
                "type": "string",
                "description": "Required when action is set. The exact user instructions for future transcript review tasks.",
            },
            "id": {"type": "string", "description": "Callback identifier for register, update, enable, disable, or remove."},
            "name": {"type": "string", "description": "Human-readable callback name for register or update."},
            "enabled": {"type": "boolean", "description": "Optional enabled state for register or update."},
            "authorization_token": {"type": "string", "description": "Required only for callback mutations from a scheduled transcript command."},
        },
        "required": ["action"],
    },
}


def make_transcript_review_config_handler(archive: TranscriptArchive):
    def transcript_review_config(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        try:
            action = str(args.get("action") or "show").strip().lower()
            if action in {"set", "clear", "register", "update", "enable", "disable", "remove"} and os.environ.get("HERMES_CRON_SESSION"):
                token = str(args.get("authorization_token") or "")
                if not archive.consume_callback_mutation_token(token):
                    return _response(False, error="callback mutation requires a valid named-command authorization")
            if action == "show":
                return _response(True, instructions=archive.get_review_instructions())
            if action == "set":
                instructions = str(args.get("instructions") or "").strip()
                if not instructions:
                    return _response(False, error="instructions is required when action is set")
                archive.set_review_instructions(instructions)
                return _response(True, instructions=instructions)
            if action == "clear":
                archive.set_review_instructions("")
                return _response(True, instructions="")
            if action == "list":
                return _callbacks_response(True, archive.list_callbacks())
            if action in {"register", "update"}:
                callback_id = str(args.get("id") or "").strip()
                name = str(args.get("name") or "").strip()
                instructions = str(args.get("instructions") or "").strip()
                if not callback_id or not name or not instructions:
                    return _callbacks_response(False, error="id, name, and instructions are required")
                existing = archive.get_callback(callback_id)
                callback = archive.upsert_callback(
                    callback_id=callback_id,
                    name=name,
                    instructions=instructions,
                    enabled=bool(args.get("enabled", existing.enabled if existing else True)),
                )
                return _callbacks_response(True, [callback])
            if action in {"enable", "disable"}:
                callback_id = str(args.get("id") or "").strip()
                if not callback_id:
                    return _callbacks_response(False, error="id is required")
                callback = archive.set_callback_enabled(callback_id, action == "enable")
                if callback is None:
                    return _callbacks_response(False, error="callback was not found")
                return _callbacks_response(True, [callback])
            if action == "remove":
                callback_id = str(args.get("id") or "").strip()
                if not callback_id:
                    return _callbacks_response(False, error="id is required")
                if not archive.remove_callback(callback_id):
                    return _callbacks_response(False, error="callback was not found")
                return _callbacks_response(True, [])
            return _response(False, error=f"unsupported action: {action}")
        except Exception as exc:
            return _response(False, error=str(exc))

    return transcript_review_config


def _response(success: bool, *, instructions: str = "", error: str = "") -> str:
    payload: dict[str, Any] = {
        "success": success,
        "instructions": instructions,
        "auto_review_enabled": bool(instructions.strip()),
    }
    if error:
        payload["error"] = error
    return json.dumps(payload, ensure_ascii=False)


def _callbacks_response(success: bool, callbacks: list[Any] | None = None, *, error: str = "") -> str:
    payload: dict[str, Any] = {
        "success": success,
        "callbacks": [callback.to_dict() for callback in callbacks or []],
    }
    if error:
        payload["error"] = error
    return json.dumps(payload, ensure_ascii=False)
