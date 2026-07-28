"""Structured durable-fact extraction via Hermes plugin LLM access."""

from __future__ import annotations

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
                    "assertion_turn_index": {"type": "integer"},
                    "confirmation_turn_index": {"type": "integer"},
                },
                "required": [
                    "target",
                    "content",
                    "confidence",
                    "source",
                    "assertion_turn_index",
                    "confirmation_turn_index",
                ],
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
    "Keep each fact concise, directly supported by transcript text, and useful in future assistance. "
    "Set assertion_turn_index to the numbered turn containing the fact and copy source verbatim from that turn. "
    "If the configured user speaker states the fact, set confirmation_turn_index to the same turn. "
    "If another speaker states it, emit the fact only when a later numbered turn from the configured user speaker "
    "clearly agrees with or verifies the same proposition, and set confirmation_turn_index to that later turn. "
    "Do not treat silence, mere acknowledgement, uncertainty, or unrelated agreement as confirmation."
)


def extract_facts(ctx: Any, transcript: NormalizedTranscript) -> list[dict[str, Any]]:
    """Extract durable facts from one complete, finished transcript."""

    result = ctx.llm.complete_structured(
        instructions=EXTRACTION_INSTRUCTIONS,
        input=[{"type": "text", "text": render_for_llm(transcript)}],
        json_schema=FACT_EXTRACTION_SCHEMA,
        schema_name="transcript_listener.facts",
        purpose="transcript-listener.fact-extraction",
        temperature=0.0,
        max_tokens=1000,
    )
    parsed = result.parsed if isinstance(result.parsed, dict) else {}
    facts = parsed.get("facts") if isinstance(parsed, dict) else []
    return validate_facts(facts, transcript)


def validate_facts(facts: Any, transcript: NormalizedTranscript) -> list[dict[str, Any]]:
    """Allow only bounded, high-confidence, evidence-backed descriptive facts."""

    if not isinstance(facts, list):
        return []
    indexed_turns: dict[int, tuple[int, TranscriptTurn] | None] = {}
    for position, turn in enumerate(transcript.turns):
        indexed_turns[turn.index] = None if turn.index in indexed_turns else (position, turn)
    accepted: list[dict[str, Any]] = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        target = fact.get("target")
        content = fact.get("content")
        source = fact.get("source")
        assertion_index = fact.get("assertion_turn_index")
        confirmation_index = fact.get("confirmation_turn_index")
        if target not in {"memory", "user"} or fact.get("confidence") != "high":
            continue
        if not isinstance(content, str) or not isinstance(source, str):
            continue
        if not _is_turn_index(assertion_index) or not _is_turn_index(confirmation_index):
            continue
        assertion_entry = indexed_turns.get(assertion_index)
        confirmation_entry = indexed_turns.get(confirmation_index)
        if assertion_entry is None or confirmation_entry is None:
            continue
        assertion_position, assertion_turn = assertion_entry
        confirmation_position, confirmation_turn = confirmation_entry
        content = content.strip()
        source = source.strip()
        if not content or len(content) > 500 or len(source) < 8 or len(source) > 1000:
            continue
        if source not in assertion_turn.text or _looks_imperative(content):
            continue
        if assertion_turn.speaker == transcript.user_speaker:
            if confirmation_index != assertion_index:
                continue
        elif (
            confirmation_turn.speaker != transcript.user_speaker
            or confirmation_position <= assertion_position
        ):
            continue
        accepted.append(
            {
                "target": target,
                "content": content,
                "confidence": "high",
                "source": source,
                "assertion_turn_index": assertion_index,
                "confirmation_turn_index": confirmation_index,
            }
        )
    return accepted


def _is_turn_index(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _looks_imperative(content: str) -> bool:
    return content.lower().startswith(("ignore ", "always ", "never ", "must ", "do not ", "send ", "run ", "delete "))
