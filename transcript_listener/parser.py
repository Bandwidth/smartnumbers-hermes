"""Parser for provisional transcript payloads."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from hashlib import sha256
from typing import Any

from .models import NormalizedTranscript, TranscriptTurn


class TranscriptParseError(ValueError):
    """Raised when a transcript payload cannot be normalized."""


MARKDOWN_TURN_RE = re.compile(
    r"(?ms)^\s*(\d+)\s*\n\s*\[([^\]]+)\]\s*\n\s*\*\*([^*]+)\*\*:\s*(.*?)(?=\n\s*\n\s*\d+\s*\n\s*\[|\s*\Z)"
)


def parse_transcript_payload(payload: str | bytes | Mapping[str, Any], *, metadata: Mapping[str, Any] | None = None) -> NormalizedTranscript:
    """Parse transcript JSON or Markdown into the internal model.

    Accepted input shape::

        {
          "conversation_id": "conv_001",
          "source": "test-fixture",
          "participants": {"user": "Damien", "person_x": "Alex"},
          "turns": [{"speaker": "user", "text": "..."}]
        }
    """

    metadata = metadata or {}
    data = _coerce_mapping(payload)
    if data is None:
        return _parse_markdown(payload, metadata=metadata)

    conversation_id = _optional_str(metadata.get("conversation_id")) or _required_str(data, "conversation_id")
    source = _optional_str(data.get("source"), default="external")
    source = _optional_str(metadata.get("source"), default=source)
    participants = _parse_participants(data.get("participants"))
    turns = _parse_turns(data.get("turns"), participants)
    user_speaker = _optional_str(metadata.get("user_speaker"), default=_optional_str(data.get("user_speaker"), default="TO"))
    return NormalizedTranscript(
        conversation_id=conversation_id,
        source=source,
        participants=participants,
        turns=tuple(turns),
        user_speaker=user_speaker or None,
        raw=dict(data),
    )


def _coerce_mapping(payload: str | bytes | Mapping[str, Any]) -> Mapping[str, Any] | None:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            if _looks_like_markdown_transcript(payload):
                return None
            raise TranscriptParseError(f"Invalid transcript JSON or Markdown transcript: {exc}") from exc
        if not isinstance(decoded, Mapping):
            raise TranscriptParseError("Transcript JSON must be an object")
        return decoded
    if isinstance(payload, Mapping):
        return payload
    raise TranscriptParseError("Transcript payload must be JSON text or a mapping")


def _parse_markdown(payload: str | bytes | Mapping[str, Any], *, metadata: Mapping[str, Any]) -> NormalizedTranscript:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if not isinstance(payload, str):
        raise TranscriptParseError("Markdown transcript payload must be text")

    turns: list[TranscriptTurn] = []
    participants = _parse_participants(metadata.get("participants"))
    for match in MARKDOWN_TURN_RE.finditer(payload):
        raw_index, timestamp, speaker, text = match.groups()
        speaker = speaker.strip()
        text = _normalize_markdown_text(text)
        if not speaker or not text:
            continue
        turns.append(
            TranscriptTurn(
                index=int(raw_index) - 1,
                speaker=speaker,
                speaker_label=participants.get(speaker, speaker),
                text=text,
                timestamp=timestamp.strip() or None,
            )
        )

    if not turns:
        raise TranscriptParseError("Markdown transcript must contain at least one numbered timestamped speaker turn")

    conversation_id = _optional_str(metadata.get("conversation_id"), default=_stable_conversation_id(payload))
    source = _optional_str(metadata.get("source"), default="external-transcript")
    user_speaker = _optional_str(metadata.get("user_speaker"), default="TO")
    return NormalizedTranscript(
        conversation_id=conversation_id,
        source=source,
        participants=participants,
        turns=tuple(turns),
        user_speaker=user_speaker or None,
        raw={"format": "markdown", "text": payload},
    )


def _looks_like_markdown_transcript(payload: str) -> bool:
    return bool(MARKDOWN_TURN_RE.search(payload))


def _normalize_markdown_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _stable_conversation_id(payload: str) -> str:
    return "transcript_" + sha256(payload.encode("utf-8")).hexdigest()[:16]


def _required_str(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TranscriptParseError(f"Missing required string field: {key}")
    return value.strip()


def _optional_str(value: Any, *, default: str = "") -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _parse_participants(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TranscriptParseError("participants must be an object")
    participants: dict[str, str] = {}
    for raw_key, raw_label in value.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            continue
        key = raw_key.strip()
        label = raw_label.strip() if isinstance(raw_label, str) and raw_label.strip() else key
        participants[key] = label
    return participants


def _parse_turns(value: Any, participants: Mapping[str, str]) -> list[TranscriptTurn]:
    if not isinstance(value, list):
        raise TranscriptParseError("turns must be an array")
    turns: list[TranscriptTurn] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise TranscriptParseError(f"turns[{index}] must be an object")
        speaker = _required_str(item, "speaker")
        text = _required_str(item, "text")
        timestamp = item.get("timestamp")
        timestamp_text = str(timestamp).strip() if timestamp is not None else None
        turns.append(
            TranscriptTurn(
                index=index,
                speaker=speaker,
                speaker_label=participants.get(speaker, speaker),
                text=text,
                timestamp=timestamp_text or None,
            )
        )
    if not turns:
        raise TranscriptParseError("turns must contain at least one response")
    return turns
