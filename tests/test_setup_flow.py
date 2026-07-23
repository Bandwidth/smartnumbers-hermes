import json
import os
import sys
import types
from urllib.parse import parse_qs, urlparse

from transcript_listener import setup_flow


def test_pkce_challenge_is_base64url_sha256():
    assert setup_flow.pkce_challenge("verifier") == "iMnq5o6zALKXGivsnlom_0F5_WYda32GHkxlV7mq7hQ"


def test_build_connect_url_includes_loopback_callback_params():
    url = setup_flow.build_connect_url(
        app_url="https://smart.example/",
        redirect_uri="http://127.0.0.1:1234/callback",
        state="state-1",
        code_challenge="challenge-1",
    )

    assert url.startswith("https://smart.example/hermes/connect?")
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A1234%2Fcallback" in url
    assert "state=state-1" in url
    assert "code_challenge=challenge-1" in url
    assert "code_challenge_method=S256" in url


def test_exchange_connection_token_posts_code_and_verifier(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self, max_bytes):
            assert max_bytes == 1024 * 1024
            return json.dumps(
                {
                    "api_key": "bwa_key_test",
                    "key_prefix": "bwa_key_",
                    "websocket_url": "wss://smart.example/ws/hermes",
                    "permissions": ["smart-numbers:connect"],
                }
            ).encode()

    def fake_urlopen(request, *, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(setup_flow, "urlopen", fake_urlopen)

    token = setup_flow.exchange_connection_token(
        app_url="https://smart.example",
        code="code-1",
        redirect_uri="http://127.0.0.1:1234/callback",
        code_verifier="verifier-1",
    )

    assert token.api_key == "bwa_key_test"
    assert token.key_prefix == "bwa_key_"
    assert token.websocket_url == "wss://smart.example/ws/hermes"
    assert token.permissions == ("smart-numbers:connect",)
    assert captured == {
        "url": "https://smart.example/api/hermes/connection-token",
        "method": "POST",
        "body": {
            "code": "code-1",
            "redirect_uri": "http://127.0.0.1:1234/callback",
            "code_verifier": "verifier-1",
        },
        "timeout": 15,
    }


def test_setup_token_defaults_to_public_websocket_for_production_app_url():
    token = setup_flow.SetupToken.from_mapping(
        {"api_key": "bwa_key_test"},
        app_url="https://smartnumbers.labs.bandwidth.com",
    )

    assert token.websocket_url == "wss://connections.smartnumbers.labs.bandwidth.com/ws/hermes"


def test_run_browser_setup_uses_browser_and_container_urls_separately(monkeypatch):
    captured = {}
    real_build_connect_url = setup_flow.build_connect_url

    class FakeCallbackServer:
        def __init__(self, *, bind_host, redirect_host, port):
            captured["callback"] = (bind_host, redirect_host, port)
            self.redirect_uri = "http://localhost:3021/callback"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def wait(self, timeout_seconds):
            state = parse_qs(urlparse(captured["auth_url"]).query)["state"][0]
            assert timeout_seconds == 300
            return setup_flow.CallbackResult(code="mock-code", state=state, error=None)

    token = setup_flow.SetupToken(
        api_key="bwa_key_test",
        key_prefix="bwa_key_",
        websocket_url="ws://connection-server:8000/ws/hermes",
        permissions=("smart-numbers:connect",),
    )

    def fake_exchange(**kwargs):
        captured["exchange"] = kwargs
        return token

    def fake_build_connect_url(**kwargs):
        url = real_build_connect_url(**kwargs)
        captured["auth_url"] = url
        return url

    monkeypatch.setattr(setup_flow, "CallbackServer", FakeCallbackServer)
    monkeypatch.setattr(setup_flow, "exchange_connection_token", fake_exchange)
    monkeypatch.setattr(setup_flow, "persist_setup_result", lambda setup_token, **kwargs: captured.update(persist=(setup_token, kwargs)))
    monkeypatch.setattr(setup_flow, "build_connect_url", fake_build_connect_url)

    result = setup_flow.run_browser_setup(
        app_url="http://frontend:3000",
        setup_url="http://localhost:3000",
        local=True,
        callback_bind_host="0.0.0.0",
        callback_host="localhost",
        callback_port=3021,
        open_browser_enabled=False,
    )

    assert result == token
    assert captured["callback"] == ("0.0.0.0", "localhost", 3021)
    assert captured["auth_url"].startswith("http://localhost:3000/hermes/connect?")
    assert captured["exchange"]["app_url"] == "http://frontend:3000"
    assert captured["exchange"]["code"] == "mock-code"
    assert captured["exchange"]["redirect_uri"] == "http://localhost:3021/callback"
    assert captured["exchange"]["allow_insecure"] is True
    assert captured["exchange"]["code_verifier"]
    assert captured["persist"] == (token, {"plugin_key": "smartnumbers", "api_key_env": "TRANSCRIPT_LISTENER_API_KEY", "app_url": "http://localhost:3000"})


def test_setup_token_rejects_insecure_nonlocal_websocket_url():
    try:
        setup_flow.SetupToken.from_mapping(
            {"api_key": "bwa_key_test", "websocket_url": "ws://example.com/ws/hermes"},
            app_url="https://smart.example",
        )
    except setup_flow.SetupError as exc:
        assert str(exc) == "websocket URL must use wss unless local setup is enabled"
    else:
        raise AssertionError("expected insecure websocket URL to be rejected")


def test_local_setup_allows_a_custom_http_exchange_url():
    assert (
        setup_flow._validate_app_url("http://example.com", allow_insecure=True)
        is None
    )


def test_persist_setup_result_uses_hermes_env_and_config(monkeypatch):
    saved_env = []
    saved_configs = []
    hermes_cli = types.ModuleType("hermes_cli")
    config = types.ModuleType("hermes_cli.config")
    cfg = {"plugins": {"enabled": [], "entries": {}}}

    def fake_save_env_value(name, value):
        saved_env.append((name, value))
        os.environ[name] = value

    config.save_env_value = fake_save_env_value
    config.load_config = lambda: cfg
    config.save_config = lambda value: saved_configs.append(value.copy())
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", config)
    monkeypatch.delenv("TRANSCRIPT_LISTENER_API_KEY", raising=False)

    setup_flow.persist_setup_result(
        setup_flow.SetupToken(
            api_key="bwa_key_test",
            key_prefix="bwa_key_",
            websocket_url="wss://smart.example/ws/hermes",
            permissions=("smart-numbers:connect",),
        )
    )

    assert saved_env == [("TRANSCRIPT_LISTENER_API_KEY", "bwa_key_test")]
    assert "smartnumbers" in cfg["plugins"]["enabled"]
    assert cfg["plugins"]["entries"]["smartnumbers"]["run_listener"] is True
    assert cfg["plugins"]["entries"]["smartnumbers"]["stream_url"] == "wss://smart.example/ws/hermes"
    assert cfg["plugins"]["entries"]["smartnumbers"]["key_prefix"] == "bwa_key_"
    assert saved_configs


def test_clear_setup_disables_listener_and_removes_secret(monkeypatch):
    removed = []
    saved_configs = []
    hermes_cli = types.ModuleType("hermes_cli")
    config = types.ModuleType("hermes_cli.config")
    cfg = {
        "plugins": {
            "entries": {
                "smartnumbers": {
                    "run_listener": True,
                    "stream_url": "wss://smart.example/ws/hermes",
                    "key_prefix": "bwa_key_",
                    "last_setup_at": "2026-01-01T00:00:00Z",
                }
            }
        }
    }
    config.remove_env_value = lambda name: removed.append(name)
    config.load_config = lambda: cfg
    config.save_config = lambda value: saved_configs.append(value.copy())
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", config)

    setup_flow.clear_setup()

    assert removed == ["TRANSCRIPT_LISTENER_API_KEY"]
    assert cfg["plugins"]["entries"]["smartnumbers"] == {"run_listener": False}
    assert saved_configs
