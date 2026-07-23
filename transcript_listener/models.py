"""Internal normalized transcript models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class TranscriptTurn:
    """One ordered speaker-labelled response in an external transcript."""

    index: int
    speaker: str
    speaker_label: str
    text: str
    timestamp: str | None = None


@dataclass(frozen=True)
class NormalizedTranscript:
    """Stable internal shape consumed by storage, rendering, and extraction."""

    conversation_id: str
    source: str
    participants: Mapping[str, str]
    turns: tuple[TranscriptTurn, ...]
    user_speaker: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def searchable_text(self) -> str:
        return "\n".join(f"{turn.speaker_label}: {turn.text}" for turn in self.turns)
