"""Hermes tool for configuring transcript auto-review instructions."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any

from .storage import DEFAULT_CALLBACK_ID, TranscriptArchive


_DELIVERY_ROUTING_TOKENS = frozenset({"all", "local"})


@dataclass(frozen=True)
class _DeliveryLocations:
    platforms: frozenset[str]
    platforms_with_home: frozenset[str]


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
                "description": "show/set/clear manage the default callback. register creates a new independent callback; update requires an existing callback.",
            },
            "instructions": {
                "type": "string",
                "description": "Required when action is set. The exact user instructions for future transcript review tasks.",
            },
            "id": {"type": "string", "description": "Callback identifier for register, update, enable, disable, or remove."},
            "name": {"type": "string", "description": "Human-readable callback name for register or update."},
            "enabled": {"type": "boolean", "description": "Optional enabled state for register or update."},
            "deliver": {
                "type": "string",
                "description": (
                    "Optional Hermes cron delivery target for set, register, or update, such as local or telegram. "
                    "Omit it when registering to inherit the plugin default, or when updating to preserve the current value. "
                    "Use an empty string during set or update to clear an override."
                ),
            },
            "authorization_token": {"type": "string", "description": "Required only for callback mutations from a scheduled transcript command."},
        },
        "required": ["action"],
    },
}


def make_transcript_review_config_handler(archive: TranscriptArchive, *, default_deliver: str = "local"):
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
                if "deliver" in args:
                    deliver = _delivery_override(args)
                    validate_callback_delivery_target(deliver or default_deliver or "local")
                    archive.set_review_instructions(instructions, deliver=deliver)
                else:
                    existing = archive.get_callback(DEFAULT_CALLBACK_ID)
                    validate_callback_delivery_target(
                        (existing.deliver if existing else None) or default_deliver or "local"
                    )
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
                if action == "register" and existing is not None:
                    return _callbacks_response(False, error="callback already exists")
                if action == "update" and existing is None:
                    return _callbacks_response(False, error="callback was not found")
                deliver = (
                    _delivery_override(args)
                    if "deliver" in args
                    else existing.deliver if existing else None
                )
                validate_callback_delivery_target(deliver or default_deliver or "local")
                callback = archive.upsert_callback(
                    callback_id=callback_id,
                    name=name,
                    instructions=instructions,
                    enabled=bool(args.get("enabled", existing.enabled if existing else True)),
                    deliver=deliver,
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


def _delivery_override(args: dict[str, Any]) -> str | None:
    value = args.get("deliver")
    if not isinstance(value, str):
        raise ValueError("callback delivery target must be a string")
    return validate_callback_delivery_target(value)


def validate_callback_delivery_target(value: str) -> str | None:
    """Normalize and validate one Hermes cron delivery route."""

    text = value.strip()
    if not text:
        return None

    configured_locations = _configured_delivery_locations()
    return ",".join(
        _validate_delivery_destination(destination, configured_locations)
        for destination in text.split(",")
    )


def _validate_delivery_destination(
    destination: str,
    configured_locations: _DeliveryLocations | None,
) -> str:
    platform, target = _parse_delivery_destination(destination)
    if platform in _DELIVERY_ROUTING_TOKENS:
        if target is not None:
            raise ValueError(f"callback delivery target {platform!r} does not accept a destination ID")
        return platform

    _validate_platform_destination(platform, target, configured_locations)
    return f"{platform}:{target}" if target is not None else platform


def _parse_delivery_destination(destination: str) -> tuple[str, str | None]:
    destination = destination.strip()
    if not destination:
        raise ValueError("callback delivery target contains an empty destination")
    if ":" not in destination:
        return destination.lower(), None

    platform, target = destination.split(":", 1)
    platform = platform.strip().lower()
    target = target.strip()
    if not platform:
        raise ValueError("explicit callback delivery targets require a platform")
    if not target:
        raise ValueError("explicit callback delivery targets require a destination ID")
    return platform, target


def _validate_platform_destination(
    platform: str,
    target: str | None,
    configured_locations: _DeliveryLocations | None,
) -> None:
    # Outside Hermes there is no gateway configuration to inspect. Syntax is
    # still normalized and checked; runtime configuration remains authoritative.
    if configured_locations is None:
        return

    if platform not in configured_locations.platforms:
        configured = ", ".join(sorted(configured_locations.platforms)) or "none"
        raise ValueError(
            f"callback delivery platform {platform!r} is not configured and enabled; "
            f"configured platforms: {configured}"
        )
    if target is None and platform not in configured_locations.platforms_with_home:
        raise ValueError(
            f"callback delivery platform {platform!r} has no configured home delivery location; "
            f"use an explicit {platform}:destination target or configure its home location"
        )


def _configured_delivery_locations() -> _DeliveryLocations | None:
    """Return connected platforms and those with cron home destinations."""

    try:
        from hermes_cli.plugins import discover_plugins
        from cron.scheduler import _get_home_target_chat_id
        from gateway.config import load_gateway_config
    except (ImportError, ModuleNotFoundError):
        # The plugin remains importable and testable outside a Hermes runtime.
        return None
    try:
        discover_plugins()
        configured = frozenset(
            platform.value
            for platform in load_gateway_config().get_connected_platforms()
            if platform.value != "local"
        )
        with_home = frozenset(platform for platform in configured if _get_home_target_chat_id(platform))
        return _DeliveryLocations(configured, with_home)
    except Exception as exc:
        raise RuntimeError(f"unable to validate callback delivery locations: {exc}") from exc
