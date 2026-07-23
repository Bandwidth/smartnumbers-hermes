"""Hermes directory-plugin entry point."""

try:
    from .transcript_listener.plugin import register
except ImportError:  # pragma: no cover - pip entrypoint import shape
    from transcript_listener.plugin import register

__all__ = ["register"]
