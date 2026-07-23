import pytest

from transcript_listener import downloader
from transcript_listener.downloader import TranscriptDownloadError, download_transcript_url


class FakeResponse:
    def __init__(self, body: bytes, *, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self._offset = 0
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._body) - self._offset
        start = self._offset
        end = min(len(self._body), start + size)
        self._offset = end
        return self._body[start:end]


def test_download_transcript_url_returns_text(monkeypatch):
    def fake_urlopen(request, *, timeout):
        assert request.full_url == "https://example.com/transcript.json"
        assert timeout == 5
        return FakeResponse(b'{"conversation_id":"conv"}')

    monkeypatch.setattr(downloader, "urlopen", fake_urlopen)

    text = download_transcript_url("https://example.com/transcript.json", timeout_seconds=5)

    assert text == '{"conversation_id":"conv"}'


def test_download_transcript_url_rejects_http_by_default():
    with pytest.raises(TranscriptDownloadError, match="HTTPS"):
        download_transcript_url("http://example.com/transcript.json")


def test_download_transcript_url_enforces_size_limit(monkeypatch):
    def fake_urlopen(request, *, timeout):
        return FakeResponse(b"abcdef")

    monkeypatch.setattr(downloader, "urlopen", fake_urlopen)

    with pytest.raises(TranscriptDownloadError, match="size limit"):
        download_transcript_url("https://example.com/transcript.json", max_bytes=5)
