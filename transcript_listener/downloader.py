"""Download transcript JSON from presigned URLs."""

from __future__ import annotations

import ipaddress
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class TranscriptDownloadError(RuntimeError):
    """Raised when a transcript URL cannot be downloaded safely."""


def urlopen(request: Request, *, timeout: int):
    """Open without redirects; kept as a patchable seam for tests."""

    return build_opener(_NoRedirect()).open(request, timeout=timeout)


def download_transcript_url(
    url: str,
    *,
    timeout_seconds: int = 15,
    max_bytes: int | None = None,
    allow_insecure: bool = False,
    allowed_hosts: tuple[str, ...] = (),
) -> str:
    """Fetch a presigned transcript URL and return UTF-8 JSON text."""

    normalized_url = _validate_url(url, allow_insecure=allow_insecure, allowed_hosts=allowed_hosts)
    byte_limit = max(1, int(max_bytes)) if max_bytes is not None else None
    timeout = max(1, int(timeout_seconds or 0))
    request = Request(
        normalized_url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": "hermes-transcript-listener/0.1",
        },
    )
    try:
        # Reject redirects rather than allowing an initial public URL to reach an internal host.
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200) or 200)
            if status < 200 or status >= 300:
                raise TranscriptDownloadError(f"Transcript URL returned HTTP {status}")

            content_length = response.headers.get("Content-Length") if response.headers else None
            try:
                if byte_limit is not None and content_length and int(content_length) > byte_limit:
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


def _validate_url(url: str, *, allow_insecure: bool, allowed_hosts: tuple[str, ...] = ()) -> str:
    normalized = url.strip() if isinstance(url, str) else ""
    if not normalized:
        raise TranscriptDownloadError("Transcript URL is required")
    parsed = urlparse(normalized)
    allowed_schemes = {"https"} | ({"http"} if allow_insecure else set())
    if parsed.scheme not in allowed_schemes or not parsed.netloc or parsed.username or parsed.password:
        raise TranscriptDownloadError("Transcript URL must be an HTTPS URL")
    if parsed.port not in {None, 443} and not allow_insecure:
        raise TranscriptDownloadError("Transcript URL must use the standard HTTPS port")
    hostname = parsed.hostname
    if not hostname:
        raise TranscriptDownloadError("Transcript URL must include a hostname")
    if allowed_hosts and hostname.casefold() not in {item.casefold() for item in allowed_hosts}:
        raise TranscriptDownloadError("Transcript URL host is not approved")
    _reject_private_destination(hostname)
    return normalized


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise TranscriptDownloadError("Transcript URL redirects are not allowed")


def _reject_private_destination(hostname: str) -> None:
    """Reject direct and DNS-resolved private destinations before connecting."""

    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise TranscriptDownloadError("Transcript URL hostname could not be resolved") from exc
    if not addresses:
        raise TranscriptDownloadError("Transcript URL hostname could not be resolved")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise TranscriptDownloadError("Transcript URL must not resolve to a private or reserved address")


def _read_limited(response, byte_limit: int | None) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        remaining = byte_limit + 1 - total if byte_limit is not None else 65536
        chunk = response.read(min(65536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if byte_limit is not None and total > byte_limit:
            raise TranscriptDownloadError("Transcript URL response exceeds configured size limit")
    return b"".join(chunks)
