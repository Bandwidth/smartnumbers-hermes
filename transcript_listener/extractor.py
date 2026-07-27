"""Structured durable-fact extraction via Hermes plugin LLM access."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .models import NormalizedTranscript, TranscriptTurn
from .renderer import render_for_llm


FACT_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "enum": ["user", "memory"]},
                    "content": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "source": {"type": "string"},
                },
                "required": ["target", "content", "confidence", "source"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["facts"],
    "additionalProperties": False,
}


EXTRACTION_INSTRUCTIONS = (
    "Extract high-confidence durable facts from this external conversation transcript. "
    "Use target='user' for user identity, preferences, goals, constraints, and communication style. "
    "Use target='memory' for project context, environment facts, workflows, and recurring task context. "
    "Keep each fact concise, directly supported by transcript text, and useful in future assistance."
)


def extract_facts(ctx: Any, transcript: NormalizedTranscript, *, batch_max_chars: int = 12000) -> list[dict[str, Any]]:
    """Extract facts from every transcript chunk without discarding long calls."""

    facts: list[dict[str, Any]] = []
    for chunk in _transcript_chunks(transcript, batch_max_chars=max(1, batch_max_chars)):
        result = ctx.llm.complete_structured(
            instructions=EXTRACTION_INSTRUCTIONS,
            input=[{"type": "text", "text": render_for_llm(chunk)}],
            json_schema=FACT_EXTRACTION_SCHEMA,
            schema_name="transcript_listener.facts",
            purpose="transcript-listener.fact-extraction",
            temperature=0.0,
            max_tokens=1000,
        )
        parsed = result.parsed if isinstance(result.parsed, dict) else {}
        chunk_facts = parsed.get("facts") if isinstance(parsed, dict) else []
        facts.extend(validate_facts(chunk_facts, transcript))
    return facts


def _transcript_chunks(transcript: NormalizedTranscript, *, batch_max_chars: int) -> list[NormalizedTranscript]:
    """Split only LLM input; archival and search always retain complete turns."""

    chunks: list[NormalizedTranscript] = []
    current: list[TranscriptTurn] = []
    current_chars = 0
    for turn in transcript.turns:
        fragments = _turn_fragments(turn, batch_max_chars=batch_max_chars)
        for fragment in fragments:
            size = len(fragment.speaker_label) + len(fragment.text) + 2
            if current and current_chars + size > batch_max_chars:
                chunks.append(replace(transcript, turns=tuple(current)))
                current = []
                current_chars = 0
            current.append(fragment)
            current_chars += size
    if current:
        chunks.append(replace(transcript, turns=tuple(current)))
    return chunks


def _turn_fragments(turn: TranscriptTurn, *, batch_max_chars: int) -> list[TranscriptTurn]:
    available = max(1, batch_max_chars - len(turn.speaker_label) - 2)
    if len(turn.text) <= available:
        return [turn]
    return [
        replace(turn, text=turn.text[start : start + available])
        for start in range(0, len(turn.text), available)
    ]


def validate_facts(facts: Any, transcript: NormalizedTranscript) -> list[dict[str, Any]]:
    """Allow only bounded, high-confidence, evidence-backed descriptive facts."""

    if not isinstance(facts, list):
        return []
    transcript_text = transcript.searchable_text()
    user_turns = "\n".join(turn.text for turn in transcript.turns if turn.speaker == transcript.user_speaker)
    accepted: list[dict[str, Any]] = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        target = fact.get("target")
        content = fact.get("content")
        source = fact.get("source")
        if target not in {"memory", "user"} or fact.get("confidence") != "high":
            continue
        if not isinstance(content, str) or not isinstance(source, str):
            continue
        content = content.strip()
        source = source.strip()
        if not content or len(content) > 500 or not source or len(source) > 1000:
            continue
        if source not in transcript_text or _looks_imperative(content):
            continue
        if target == "user" and source not in user_turns:
            continue
        accepted.append({"target": target, "content": content, "confidence": "high", "source": source})
    return accepted


def _looks_imperative(content: str) -> bool:
    return content.lower().startswith(("ignore ", "always ", "never ", "must ", "do not ", "send ", "run ", "delete "))
