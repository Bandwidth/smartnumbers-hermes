"""WebSocket listener for transcript payloads."""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable, Mapping
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
if not any(getattr(handler, "_transcript_listener_handler", False) for handler in logger.handlers):
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    handler._transcript_listener_handler = True  # type: ignore[attr-defined]
    logger.addHandler(handler)


class TranscriptWebSocketClient:
    def __init__(
        self,
        stream_url: str,
        *,
        api_key_env: str = "TRANSCRIPT_LISTENER_API_KEY",
        hello_payload: Mapping[str, Any] | None = None,
        connect_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.stream_url = stream_url
        self.api_key_env = api_key_env
        self.hello_payload = dict(hello_payload) if hello_payload is not None else None
        self._connect_factory = connect_factory
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
                logger.info("transcript websocket connecting url=%s", self.stream_url)
                with connect(self.stream_url, additional_headers=headers or None) as ws:
                    backoff = 1.0
                    logger.info("transcript websocket connected url=%s", self.stream_url)
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
                            logger.debug("transcript ack sent event_id=%s success=%s payload=%s", ack.get("event_id"), ack.get("success"), ack)
                    if not self._stop.is_set():
                        logger.warning("transcript websocket closed url=%s retry_in=%.1fs", self.stream_url, backoff)
            except Exception as exc:
                if self._stop.is_set():
                    break
                logger.warning(
                    "transcript websocket disconnected url=%s error=%s: %s retry_in=%.1fs",
                    self.stream_url,
                    type(exc).__name__,
                    exc,
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
