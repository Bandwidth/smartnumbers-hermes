"""Browser-based setup flow for Smart Numbers transcript delivery."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from .config import DEFAULT_APP_URL, DEFAULT_WEBSOCKET_URL

LOCAL_APP_URL = "http://localhost:3020"
CONNECT_PATH = "/hermes/connect"
TOKEN_PATH = "/api/hermes/connection-token"
API_KEY_ENV = "TRANSCRIPT_LISTENER_API_KEY"
PLUGIN_KEY = "smartnumbers"


class SetupError(Exception):
    """Raised when transcript listener setup fails."""


@dataclass(frozen=True)
class SetupToken:
    api_key: str
    key_prefix: str
    websocket_url: str
    permissions: tuple[str, ...]

    @classmethod
    def from_mapping(
        cls,
        payload: dict[str, Any],
        *,
        app_url: str,
        allow_insecure_websocket: bool = False,
    ) -> "SetupToken":
        api_key = _required_str(payload, "api_key")
        websocket_url = _optional_str(payload, "websocket_url") or default_websocket_url(app_url)
        _validate_websocket_url(websocket_url, allow_insecure=allow_insecure_websocket)
        permissions = payload.get("permissions")
        return cls(
            api_key=api_key,
            key_prefix=_optional_str(payload, "key_prefix") or api_key[:16],
            websocket_url=websocket_url,
            permissions=tuple(item for item in permissions if isinstance(item, str)) if isinstance(permissions, list) else (),
        )


@dataclass(frozen=True)
class PkcePair:
    verifier: str
    challenge: str


@dataclass(frozen=True)
class CallbackResult:
    code: str | None
    state: str | None
    error: str | None


def run_browser_setup(
    *,
    app_url: str,
    setup_url: str | None = None,
    local: bool = False,
    plugin_key: str = PLUGIN_KEY,
    api_key_env: str = API_KEY_ENV,
    timeout_seconds: int = 300,
    callback_bind_host: str = "127.0.0.1",
    callback_host: str = "127.0.0.1",
    callback_port: int = 0,
    open_browser_enabled: bool = True,
    open_browser: Callable[[str], bool] = webbrowser.open,
) -> SetupToken:
    app_url = normalize_app_url(app_url)
    setup_url = normalize_app_url(setup_url or app_url)
    # `--local` is an explicit opt-in for a custom HTTP endpoint. In Docker
    # Compose that endpoint is a service hostname (for example, `frontend`),
    # not necessarily a loopback name.
    allow_insecure = local
    _validate_app_url(app_url, allow_insecure=allow_insecure)
    _validate_app_url(setup_url, allow_insecure=local and _is_loopback_http(setup_url))
    pkce = create_pkce_pair()
    state = secrets.token_urlsafe(32)

    with CallbackServer(bind_host=callback_bind_host, redirect_host=callback_host, port=callback_port) as callback_server:
        redirect_uri = callback_server.redirect_uri
        auth_url = build_connect_url(
            app_url=setup_url,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=pkce.challenge,
        )
        print(f"Open Smart Numbers setup in your browser:\n{auth_url}")
        if open_browser_enabled and not open_browser(auth_url):
            print("Could not open a browser automatically. Open the URL above manually.")
        result = callback_server.wait(timeout_seconds)

    if result.error:
        raise SetupError(f"setup was rejected: {result.error}")
    if not result.code:
        raise SetupError("setup callback did not include a code")
    if result.state != state:
        raise SetupError("setup callback state did not match")

    token = exchange_connection_token(
        app_url=app_url,
        code=result.code,
        redirect_uri=redirect_uri,
        code_verifier=pkce.verifier,
        allow_insecure=allow_insecure,
    )
    persist_setup_result(token, plugin_key=plugin_key, api_key_env=api_key_env, app_url=setup_url)
    return token


def create_pkce_pair() -> PkcePair:
    verifier = secrets.token_urlsafe(64)
    return PkcePair(verifier=verifier, challenge=pkce_challenge(verifier))


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def build_connect_url(*, app_url: str, redirect_uri: str, state: str, code_challenge: str) -> str:
    query = urlencode(
        {
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{url_for_path(app_url, CONNECT_PATH)}?{query}"


def exchange_connection_token(
    *,
    app_url: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    allow_insecure: bool = False,
    timeout_seconds: int = 15,
) -> SetupToken:
    app_url = normalize_app_url(app_url)
    _validate_app_url(app_url, allow_insecure=allow_insecure)
    body = json.dumps(
        {
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
    ).encode("utf-8")
    request = Request(
        url_for_path(app_url, TOKEN_PATH),
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - URL is user-supplied and validated above.
            raw = response.read(1024 * 1024)
    except HTTPError as exc:
        raise SetupError(f"setup token endpoint returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise SetupError(f"setup token endpoint unavailable: {exc.reason}") from exc
    except OSError as exc:
        raise SetupError(f"setup token endpoint unavailable: {exc}") from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SetupError("setup token endpoint returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise SetupError("setup token endpoint returned invalid payload")
    return SetupToken.from_mapping(payload, app_url=app_url, allow_insecure_websocket=allow_insecure)


def persist_setup_result(
    token: SetupToken,
    *,
    plugin_key: str = PLUGIN_KEY,
    api_key_env: str = API_KEY_ENV,
    app_url: str | None = None,
) -> None:
    try:
        from hermes_cli.config import load_config, save_config, save_env_value
    except ImportError as exc:
        raise SetupError("Hermes config API is unavailable") from exc

    save_env_value(api_key_env, token.api_key)
    if os.environ.get(api_key_env) != token.api_key:
        raise SetupError(f"Hermes did not persist {api_key_env}")
    cfg = load_config()
    plugins = _dict_child(cfg, "plugins")
    enabled = plugins.setdefault("enabled", [])
    if isinstance(enabled, list) and plugin_key not in enabled:
        enabled.append(plugin_key)
    entries = _dict_child(plugins, "entries")
    entry = _dict_child(entries, plugin_key)
    entry.update(
        {
            "run_listener": True,
            "stream_url": token.websocket_url,
            "key_prefix": token.key_prefix,
            "last_setup_at": _utc_now_iso(),
        }
    )
    if app_url:
        entry["app_url"] = normalize_app_url(app_url)
    save_config(cfg)


def clear_setup(*, plugin_key: str = PLUGIN_KEY, api_key_env: str = API_KEY_ENV) -> None:
    try:
        from hermes_cli.config import load_config, remove_env_value, save_config
    except ImportError as exc:
        raise SetupError("Hermes config API is unavailable") from exc

    remove_env_value(api_key_env)
    cfg = load_config()
    entry = cfg.get("plugins", {}).get("entries", {}).get(plugin_key)
    if isinstance(entry, dict):
        for key in ("stream_url", "key_prefix", "last_setup_at"):
            entry.pop(key, None)
        entry["run_listener"] = False
        save_config(cfg)


def normalize_app_url(app_url: str) -> str:
    value = app_url.strip().rstrip("/")
    if not value:
        raise SetupError("app URL is required")
    return value


def url_for_path(app_url: str, path: str) -> str:
    return f"{normalize_app_url(app_url)}/{path.lstrip('/')}"


def websocket_url_for_app_url(app_url: str) -> str:
    parsed = urlparse(normalize_app_url(app_url))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}/ws/hermes"


def default_websocket_url(app_url: str) -> str:
    if normalize_app_url(app_url) == DEFAULT_APP_URL:
        return DEFAULT_WEBSOCKET_URL
    return websocket_url_for_app_url(app_url)


class CallbackServer:
    def __init__(
        self,
        *,
        bind_host: str = "127.0.0.1",
        redirect_host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        if not _is_loopback_host(redirect_host):
            raise SetupError("callback host must be a loopback hostname or address")
        if not 0 <= port <= 65535:
            raise SetupError("callback port must be between 0 and 65535")
        self._redirect_host = redirect_host
        self._server = _CallbackHTTPServer((bind_host, port), _CallbackHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="transcript-listener-setup-callback", daemon=True)

    @property
    def redirect_uri(self) -> str:
        return f"http://{self._redirect_host}:{self._server.server_port}/callback"

    def __enter__(self) -> "CallbackServer":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def wait(self, timeout_seconds: int) -> CallbackResult:
        if not self._server.event.wait(timeout_seconds):
            raise SetupError("timed out waiting for browser setup callback")
        return self._server.result or CallbackResult(code=None, state=None, error="missing_callback")


class _CallbackHTTPServer(ThreadingHTTPServer):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.event = threading.Event()
        self.result: CallbackResult | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        query = parse_qs(parsed.query)
        self.server.result = CallbackResult(
            code=_first(query.get("code")),
            state=_first(query.get("state")),
            error=_first(query.get("error")),
        )
        self.server.event.set()
        body = b"<html><body><h1>Smart Numbers connected</h1><p>You can close this window.</p></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def _validate_app_url(app_url: str, *, allow_insecure: bool) -> None:
    parsed = urlparse(app_url)
    if parsed.scheme == "https" and parsed.hostname:
        return
    if parsed.scheme == "http" and parsed.hostname and allow_insecure:
        return
    raise SetupError("app URL must use https unless supported local setup is enabled")


def _is_loopback_http(app_url: str) -> bool:
    parsed = urlparse(app_url)
    return parsed.scheme == "http" and _is_loopback_host(parsed.hostname)


def _is_loopback_host(host: str | None) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"}


def _validate_websocket_url(websocket_url: str, *, allow_insecure: bool) -> None:
    parsed = urlparse(websocket_url)
    if parsed.scheme == "wss" and parsed.hostname:
        return
    if (
        parsed.scheme == "ws"
        and parsed.hostname
        and allow_insecure
        and parsed.hostname in {"localhost", "127.0.0.1", "::1", "connection-server"}
    ):
        return
    raise SetupError("websocket URL must use wss unless local setup is enabled")


def _dict_child(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        value = {}
        parent[key] = value
    return value


def _required_str(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise SetupError(f"setup token response missing {key}")
    return item.strip()


def _optional_str(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    return item.strip() if isinstance(item, str) and item.strip() else ""


def _first(values: list[str] | None) -> str | None:
    return values[0] if values else None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
