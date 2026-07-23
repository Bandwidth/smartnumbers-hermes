from argparse import ArgumentParser

from transcript_listener import cli
from transcript_listener.config import config_from_mapping
from transcript_listener.setup_flow import SetupToken


def test_setup_forwards_container_callback_options(monkeypatch):
    parser = ArgumentParser()
    cli.setup_cli_parser(parser)
    args = parser.parse_args(
        [
            "setup",
            "--local",
            "--app-url",
            "http://mock-hermes-setup:3020",
            "--setup-url",
            "http://localhost:3020",
            "--callback-bind-host",
            "0.0.0.0",
            "--callback-host",
            "localhost",
            "--callback-port",
            "3021",
            "--no-browser",
        ]
    )
    captured = {}

    def fake_run_browser_setup(**kwargs):
        captured["kwargs"] = kwargs
        return SetupToken("bwa_key_test", "bwa_key_", "ws://connection-server:8000/ws/hermes", ())

    monkeypatch.setattr(cli, "load_plugin_config", lambda plugin_key: config_from_mapping({}))
    monkeypatch.setattr(cli, "run_browser_setup", fake_run_browser_setup)

    cli.handle_cli(args)

    assert captured["kwargs"] == {
        "app_url": "http://mock-hermes-setup:3020",
        "setup_url": "http://localhost:3020",
        "local": True,
        "timeout_seconds": 300,
        "callback_bind_host": "0.0.0.0",
        "callback_host": "localhost",
        "callback_port": 3021,
        "open_browser_enabled": False,
    }


def test_local_setup_uses_container_environment_defaults(monkeypatch):
    parser = ArgumentParser()
    cli.setup_cli_parser(parser)
    args = parser.parse_args(["setup", "--local"])
    captured = {}

    def fake_run_browser_setup(**kwargs):
        captured["kwargs"] = kwargs
        return SetupToken("bwa_key_test", "bwa_key_", "ws://connection-server:8000/ws/hermes", ())

    monkeypatch.setenv(cli.LOCAL_APP_URL_ENV, "http://mock-hermes-setup:3020")
    monkeypatch.setenv(cli.LOCAL_SETUP_URL_ENV, "http://localhost:3020")
    monkeypatch.setenv(cli.CALLBACK_BIND_HOST_ENV, "0.0.0.0")
    monkeypatch.setenv(cli.CALLBACK_HOST_ENV, "localhost")
    monkeypatch.setenv(cli.CALLBACK_PORT_ENV, "3021")
    monkeypatch.setenv(cli.NO_BROWSER_ENV, "true")
    monkeypatch.setattr(cli, "load_plugin_config", lambda plugin_key: config_from_mapping({}))
    monkeypatch.setattr(cli, "run_browser_setup", fake_run_browser_setup)

    cli.handle_cli(args)

    assert captured["kwargs"] == {
        "app_url": "http://mock-hermes-setup:3020",
        "setup_url": "http://localhost:3020",
        "local": True,
        "timeout_seconds": 300,
        "callback_bind_host": "0.0.0.0",
        "callback_host": "localhost",
        "callback_port": 3021,
        "open_browser_enabled": False,
    }
