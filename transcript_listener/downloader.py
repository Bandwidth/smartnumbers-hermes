"""Download transcript JSON from presigned URLs."""

from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class TranscriptDownloadError(RuntimeError):
    """Raised when a transcript URL cannot be downloaded safely."""


def download_transcript_url(
    url: str,
    *,
    timeout_seconds: int = 15,
    max_bytes: int = 5 * 1024 * 1024,
    allow_insecure: bool = False,
) -> str:
    """Fetch a presigned transcript URL and return UTF-8 JSON text."""

    normalized_url = _validate_url(url, allow_insecure=allow_insecure)
    byte_limit = max(1, int(max_bytes or 0))
    timeout = max(1, int(timeout_seconds or 0))
    request = Request(
        normalized_url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": "hermes-transcript-listener/0.1",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200) or 200)
            if status < 200 or status >= 300:
                raise TranscriptDownloadError(f"Transcript URL returned HTTP {status}")

            content_length = response.headers.get("Content-Length") if response.headers else None
            try:
                if content_length and int(content_length) > byte_limit:
                    raise TranscriptDownloadError("Transcript URL response exceeds configured size limit")
            except ValueError:
                pass

            body = _read_limited(response, byte_limit)
    except TranscriptDownloadError:
        raise
    except HTTPError as exc:
        raise TranscriptDownloadError(f"Transcript URL returned HTTP {exc.code}") from exc
    except (OSError, TimeoutError, URLError) as exc:
        raise TranscriptDownloadError(f"Transcript URL download failed: {exc}") from exc

    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TranscriptDownloadError("Transcript URL response is not valid UTF-8") from exc


def _validate_url(url: str, *, allow_insecure: bool) -> str:
    normalized = url.strip() if isinstance(url, str) else ""
    if not normalized:
        raise TranscriptDownloadError("Transcript URL is required")
    parsed = urlparse(normalized)
    allowed_schemes = {"https"} | ({"http"} if allow_insecure else set())
    if parsed.scheme not in allowed_schemes or not parsed.netloc:
        raise TranscriptDownloadError("Transcript URL must be an HTTPS URL")
    return normalized


def _read_limited(response, byte_limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        remaining = byte_limit + 1 - total
        chunk = response.read(min(65536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > byte_limit:
            raise TranscriptDownloadError("Transcript URL response exceeds configured size limit")
    return b"".join(chunks)
