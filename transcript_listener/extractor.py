"""Structured durable-fact extraction via Hermes plugin LLM access."""

from __future__ import annotations

from typing import Any

from .models import NormalizedTranscript
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
            },
        }
    },
    "required": ["facts"],
}


EXTRACTION_INSTRUCTIONS = (
    "Extract high-confidence durable facts from this external conversation transcript. "
    "Use target='user' for user identity, preferences, goals, constraints, and communication style. "
    "Use target='memory' for project context, environment facts, workflows, and recurring task context. "
    "Keep each fact concise, directly supported by transcript text, and useful in future assistance."
)


def extract_facts(ctx: Any, transcript: NormalizedTranscript) -> list[dict[str, Any]]:
    rendered = render_for_llm(transcript)
    result = ctx.llm.complete_structured(
        instructions=EXTRACTION_INSTRUCTIONS,
        input=[{"type": "text", "text": rendered}],
        json_schema=FACT_EXTRACTION_SCHEMA,
        schema_name="transcript_listener.facts",
        purpose="transcript-listener.fact-extraction",
        temperature=0.0,
        max_tokens=1000,
    )
    parsed = result.parsed if isinstance(result.parsed, dict) else {}
    facts = parsed.get("facts") if isinstance(parsed, dict) else []
    return [fact for fact in facts if isinstance(fact, dict)]
