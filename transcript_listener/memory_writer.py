"""Adapter for writing extracted facts to Hermes built-in memory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class MemoryWriteResult:
    target: str
    content: str
    success: bool
    message: str


def write_facts_to_memory(facts: Iterable[Mapping[str, Any]]) -> list[MemoryWriteResult]:
    """Write extracted facts to MEMORY.md / USER.md through Hermes MemoryStore."""

    from tools.memory_tool import MemoryStore

    store = MemoryStore()
    store.load_from_disk()
    results: list[MemoryWriteResult] = []
    for fact in facts:
        target = str(fact.get("target") or "memory")
        if target not in {"memory", "user"}:
            target = "memory"
        content = str(fact.get("content") or "").strip()
        if not content:
            continue
        response = store.add(target, content)
        results.append(
            MemoryWriteResult(
                target=target,
                content=content,
                success=bool(response.get("success")),
                message=str(response.get("message") or response.get("error") or ""),
            )
        )
    return results
