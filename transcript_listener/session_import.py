"""Adapter for importing external transcripts into Hermes SessionDB."""

from __future__ import annotations

import re

from .models import NormalizedTranscript
from .renderer import render_for_sessiondb


def state_session_id_for(conversation_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", conversation_id).strip("_") or "unknown"
    return f"external_ref_{safe}"


def import_to_session_db(transcript: NormalizedTranscript, *, source_label: str = "external-reference") -> str:
    """Create/update a Hermes reference session for a transcript."""

    from hermes_state import SessionDB

    session_id = state_session_id_for(transcript.conversation_id)
    db = SessionDB()
    db.create_session(
        session_id=session_id,
        source=source_label,
        model="external-transcript",
        system_prompt="Imported external conversation. Hermes was absent from the original dialogue.",
    )
    existing = db.get_messages(session_id)
    if not existing:
        db.append_message(session_id=session_id, role="user", content=render_for_sessiondb(transcript))
        try:
            db.end_session(session_id, "imported_external_transcript")
        except Exception:
            pass
    return session_id
