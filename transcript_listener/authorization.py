"""Determine which transcript turns may authorize Hermes actions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .config import TranscriptListenerConfig
from .models import NormalizedTranscript


@dataclass(frozen=True)
class AuthorizedCommand:
    """A named command spoken by the locally configured user speaker."""

    turn_index: int
    command: str
    quote: str


def authoritative_speaker(config: TranscriptListenerConfig, event: Mapping[str, Any] | None = None) -> str:
    """Resolve authority from local configuration, never a payload speaker field."""

    direction = config.default_call_direction
    if config.trust_event_direction and isinstance(event, Mapping):
        candidate = event.get("direction")
        if isinstance(candidate, str) and candidate.lower() in {"inbound", "outbound"}:
            direction = candidate.lower()
    return dict(config.user_speaker_by_direction).get(direction, config.user_speaker)


def activation_names(config: TranscriptListenerConfig) -> tuple[str, ...]:
    """Return configured names plus the active Hermes branding name when available."""

    names: list[str] = []
    for configured_name in config.activation_names:
        names.extend((configured_name, configured_name.split()[0]))
    try:
        from hermes_cli.skin_engine import get_active_skin

        name = str(get_active_skin().get_branding("agent_name", "Hermes Agent")).strip()
        if name:
            names.extend((name, name.split()[0]))
    except Exception:
        names.extend(("Hermes Agent", "Hermes"))
    unique: list[str] = []
    for name in names:
        cleaned = name.strip()
        if cleaned and cleaned.casefold() not in {item.casefold() for item in unique}:
            unique.append(cleaned)
    return tuple(unique)


def detect_named_commands(
    transcript: NormalizedTranscript,
    *,
    authoritative_speaker_id: str,
    names: Iterable[str],
) -> list[AuthorizedCommand]:
    """Find exact wake-name commands at the beginning of authoritative turns."""

    alternatives = [re.escape(name.strip()) for name in names if name.strip()]
    if not alternatives:
        return []
    # Do not accept a bare mention in the middle of a sentence as authority.
    pattern = re.compile(
        rf"^\s*(?:(?:hey|ok|okay)\s+)?(?:{'|'.join(alternatives)})\b[\s,:;\-]+(.+?)\s*$",
        re.IGNORECASE,
    )
    commands: list[AuthorizedCommand] = []
    for turn in transcript.turns:
        if turn.speaker != authoritative_speaker_id:
            continue
        match = pattern.match(turn.text)
        if match:
            commands.append(AuthorizedCommand(turn.index, match.group(1), f"{turn.speaker_label}: {turn.text}"))
    return commands
