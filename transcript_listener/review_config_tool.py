"""Hermes tool for configuring transcript auto-review instructions."""

from __future__ import annotations

import json
from typing import Any

from .storage import TranscriptArchive


TRANSCRIPT_REVIEW_CONFIG_SCHEMA = {
    "name": "transcript_review_config",
    "description": (
        "Show, set, or clear the user's instructions for automatic phone transcript review. "
        "These instructions are used only after a new transcript arrives; if they are empty, "
        "no review task is started."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["show", "set", "clear"],
                "description": "show returns current instructions, set replaces them, clear disables auto-review tasks.",
            },
            "instructions": {
                "type": "string",
                "description": "Required when action is set. The exact user instructions for future transcript review tasks.",
            },
        },
        "required": ["action"],
    },
}


def make_transcript_review_config_handler(archive: TranscriptArchive):
    def transcript_review_config(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        try:
            action = str(args.get("action") or "show").strip().lower()
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
