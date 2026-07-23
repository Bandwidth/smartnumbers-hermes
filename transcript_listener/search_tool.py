"""Hermes tool registration for direct transcript archive search."""

from __future__ import annotations

import json
from typing import Any

from .storage import TranscriptArchive


TRANSCRIPT_SEARCH_SCHEMA = {
    "name": "transcript_search",
    "description": (
        "Search external conversation transcripts imported by the transcript listener. "
        "Use this for direct lookup in raw external transcript history, speaker filtering, "
        "recent call lookup, or provenance-heavy retrieval. Results are newest-first by "
        "the time Hermes received the transcript event."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Text to search for in transcript turns."},
            "external_session_id": {"type": "string", "description": "Limit search to one external conversation id."},
            "speaker": {"type": "string", "description": "Filter by speaker id or speaker label."},
            "since": {"type": "string", "description": "Optional event_received_at ISO timestamp lower bound."},
            "until": {"type": "string", "description": "Optional event_received_at ISO timestamp upper bound."},
            "limit": {"type": "integer", "description": "Maximum results to return, clamped to 1-50.", "default": 10},
        },
        "required": [],
    },
}


def make_transcript_search_handler(archive: TranscriptArchive):
    def transcript_search(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        try:
            results = archive.search(
                query=str(args.get("query") or ""),
                external_session_id=str(args.get("external_session_id") or ""),
                speaker=str(args.get("speaker") or ""),
                since=str(args.get("since") or ""),
                until=str(args.get("until") or ""),
                limit=int(args.get("limit") or 10),
            )
            return json.dumps(
                {
                    "success": True,
                    "results": [result.to_dict() for result in results],
                    "count": len(results),
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)

    return transcript_search
