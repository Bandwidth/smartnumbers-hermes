import json

from transcript_listener.ws_client import TranscriptWebSocketClient


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def send(self, payload: str) -> None:
        self.sent.append(payload)

    def __iter__(self):
        yield '{"type":"noop"}'


def test_client_sends_hello_payload_after_connect(monkeypatch):
    socket = FakeWebSocket()
    received: list[str] = []
    monkeypatch.delenv("TRANSCRIPT_LISTENER_API_KEY", raising=False)

    def fake_connect(url, *, additional_headers, max_size):
        assert url == "wss://example.com/transcripts"
        assert additional_headers is None
        assert max_size == 1024 * 1024
        return socket

    client = TranscriptWebSocketClient(
        "wss://example.com/transcripts",
        hello_payload={
            "type": "hello",
            "protocol_version": 1,
            "client": "hermes-transcript-listener",
        },
        connect_factory=fake_connect,
    )

    def on_payload(payload: str) -> None:
        received.append(payload)
        client.stop()

    client.run_forever(on_payload)

    assert json.loads(socket.sent[0]) == {
        "type": "hello",
        "protocol_version": 1,
        "client": "hermes-transcript-listener",
    }
    assert received == ['{"type":"noop"}']


def test_client_sends_api_key_from_env(monkeypatch):
    socket = FakeWebSocket()
    monkeypatch.setenv("TRANSCRIPT_LISTENER_API_KEY", "bwa_key_test")

    def fake_connect(url, *, additional_headers, max_size):
        assert url == "wss://example.com/transcripts"
        assert additional_headers == [("Authorization", "Bearer bwa_key_test")]
        assert max_size == 1024 * 1024
        return socket

    client = TranscriptWebSocketClient(
        "wss://example.com/transcripts",
        hello_payload={"type": "hello"},
        connect_factory=fake_connect,
    )

    def on_payload(payload: str) -> None:
        del payload
        client.stop()

    client.run_forever(on_payload)


def test_client_sends_ack_returned_by_payload_handler(monkeypatch):
    socket = FakeWebSocket()
    monkeypatch.delenv("TRANSCRIPT_LISTENER_API_KEY", raising=False)

    def fake_connect(url, *, additional_headers, max_size):
        del additional_headers
        assert url == "wss://example.com/transcripts"
        assert max_size == 2048
        return socket

    client = TranscriptWebSocketClient(
        "wss://example.com/transcripts",
        hello_payload={"type": "hello"},
        connect_factory=fake_connect,
        max_message_bytes=2048,
    )

    def on_payload(payload: str) -> dict[str, object]:
        assert payload == '{"type":"noop"}'
        client.stop()
        return {"type": "transcript_ack", "event_id": "evt_123", "success": True}

    client.run_forever(on_payload)

    assert json.loads(socket.sent[1]) == {"type": "transcript_ack", "event_id": "evt_123", "success": True}
