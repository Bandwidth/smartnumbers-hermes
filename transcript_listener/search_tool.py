"""Hermes tool registration for direct transcript archive search."""

from __future__ import annotations

import json
from typing import Any

from .storage import TranscriptArchive


TRANSCRIPT_SEARCH_SCHEMA = {
    "name": "transcript_search",
    "description": (
        "Search transcripts of inbound and outbound phone calls imported by the "
        "Smartnumbers transcript listener. Use this tool when the user asks what was "
        "said, discussed, promised, or agreed during a phone call; wants to find calls "
        "by participant, date, speaker, or spoken content; or needs the exact wording "
        "and provenance of a call. This searches archived phone-call transcripts, not "
        "Hermes chat history, email, or other conversations. Results are newest-first "
        "by the time Hermes received the transcript event."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Words or phrases to find in the spoken turns of archived phone calls.",
            },
            "external_session_id": {
                "type": "string",
                "description": "Limit the search to one phone call's external conversation ID.",
            },
            "speaker": {
                "type": "string",
                "description": "Filter phone-call turns by participant speaker ID or label.",
            },
            "since": {"type": "string", "description": "Optional event_received_at ISO timestamp lower bound."},
            "until": {"type": "string", "description": "Optional event_received_at ISO timestamp upper bound."},
            "limit": {"type": "integer", "description": "Maximum results to return, clamped to 1-50.", "default": 10},
            "offset": {"type": "integer", "description": "Pagination offset. Use next_offset returned by a prior call.", "default": 0},
        },
        "required": [],
    },
}


def make_transcript_search_handler(archive: TranscriptArchive):
    def transcript_search(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        try:
            limit = int(args.get("limit") or 10)
            offset = max(0, int(args.get("offset") or 0))
            results, total = archive.search_page(
                query=str(args.get("query") or ""),
                external_session_id=str(args.get("external_session_id") or ""),
                speaker=str(args.get("speaker") or ""),
                since=str(args.get("since") or ""),
                until=str(args.get("until") or ""),
                limit=limit,
                offset=offset,
            )
            next_offset = offset + len(results)
            return json.dumps(
                {
                    "success": True,
                    "results": [result.to_dict() for result in results],
                    "count": len(results),
                    "total": total,
                    "next_offset": next_offset if next_offset < total else None,
                    "source_trust": "external-untrusted",
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)

    return transcript_search
