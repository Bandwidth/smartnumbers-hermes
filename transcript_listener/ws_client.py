"""WebSocket listener for transcript payloads."""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class TranscriptWebSocketClient:
    def __init__(
        self,
        stream_url: str,
        *,
        api_key_env: str = "TRANSCRIPT_LISTENER_API_KEY",
        hello_payload: Mapping[str, Any] | None = None,
        connect_factory: Callable[..., Any] | None = None,
        max_message_bytes: int | None = None,
    ) -> None:
        self.stream_url = stream_url
        self.api_key_env = api_key_env
        self.hello_payload = dict(hello_payload) if hello_payload is not None else None
        self._connect_factory = connect_factory
        self.max_message_bytes = max_message_bytes
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self, on_payload: Callable[[str], Mapping[str, Any] | None]) -> None:
        connect = self._connect_factory
        if connect is None:
            try:
                from websockets.sync.client import connect
            except Exception as exc:  # pragma: no cover - dependency/runtime environment
                logger.warning("websockets package unavailable: %s", exc)
                return

        backoff = 1.0
        while not self._stop.is_set():
            headers = []
            api_key = os.environ.get(self.api_key_env, "").strip()
            if api_key:
                headers.append(("Authorization", f"Bearer {api_key}"))
            try:
                logger.info("transcript websocket connecting url=%s", _redacted_url(self.stream_url))
                connect_args: dict[str, Any] = {"additional_headers": headers or None}
                if self._connect_factory is None and self.max_message_bytes is not None:
                    connect_args["max_size"] = self.max_message_bytes
                with connect(self.stream_url, **connect_args) as ws:
                    backoff = 1.0
                    logger.info("transcript websocket connected url=%s", _redacted_url(self.stream_url))
                    if self.hello_payload is not None:
                        ws.send(json.dumps(self.hello_payload, ensure_ascii=False))
                        logger.info("transcript websocket sent hello")
                    for message in ws:
                        if self._stop.is_set():
                            break
                        if isinstance(message, bytes):
                            message = message.decode("utf-8", errors="replace")
                        ack = on_payload(str(message))
                        if ack:
                            ws.send(json.dumps(dict(ack), ensure_ascii=False))
                            logger.debug("transcript ack sent event_id=%s success=%s", ack.get("event_id"), ack.get("success"))
                    if not self._stop.is_set():
                        logger.warning("transcript websocket closed url=%s retry_in=%.1fs", _redacted_url(self.stream_url), backoff)
            except Exception as exc:
                if self._stop.is_set():
                    break
                logger.warning(
                    "transcript websocket disconnected url=%s error_type=%s retry_in=%.1fs",
                    _redacted_url(self.stream_url),
                    type(exc).__name__,
                    backoff,
                )
            if self._stop.is_set():
                break
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 60.0)


def start_daemon_listener(client: TranscriptWebSocketClient, on_payload: Callable[[str], Mapping[str, Any] | None]) -> threading.Thread:
    thread = threading.Thread(
        target=client.run_forever,
        args=(on_payload,),
        name="transcript-listener-ws",
        daemon=True,
    )
    thread.start()
    return thread


def validate_stream_url(
    stream_url: str,
    *,
    allowed_hosts: tuple[str, ...],
    allow_insecure: bool,
) -> None:
    parsed = urlparse(stream_url)
    hostname = parsed.hostname
    if not hostname or parsed.username or parsed.password:
        raise ValueError("stream URL must include a hostname without user credentials")
    if hostname.casefold() not in {host.casefold() for host in allowed_hosts}:
        raise ValueError("stream URL host is not approved")
    if parsed.scheme == "wss":
        return
    if parsed.scheme == "ws" and allow_insecure and hostname in {"localhost", "127.0.0.1", "::1", "connection-server"}:
        return
    raise ValueError("stream URL must use wss unless explicitly configured for local development")


def _redacted_url(url: str) -> str:
    parsed = urlparse(url)
    netloc = parsed.netloc.rsplit("@", 1)[-1]
    return f"{parsed.scheme}://{netloc}{parsed.path}"
