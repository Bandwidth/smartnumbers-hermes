"""CLI command registration for the transcript listener plugin."""

from __future__ import annotations

import os
from argparse import ArgumentParser, Namespace

from .config import load_plugin_config
from .setup_flow import (
    API_KEY_ENV,
    DEFAULT_APP_URL,
    LOCAL_APP_URL,
    PLUGIN_KEY,
    SetupError,
    clear_setup,
    run_browser_setup,
)

LOCAL_APP_URL_ENV = "TRANSCRIPT_LISTENER_LOCAL_APP_URL"
LOCAL_SETUP_URL_ENV = "TRANSCRIPT_LISTENER_LOCAL_SETUP_URL"
CALLBACK_BIND_HOST_ENV = "TRANSCRIPT_LISTENER_CALLBACK_BIND_HOST"
CALLBACK_HOST_ENV = "TRANSCRIPT_LISTENER_CALLBACK_HOST"
CALLBACK_PORT_ENV = "TRANSCRIPT_LISTENER_CALLBACK_PORT"
NO_BROWSER_ENV = "TRANSCRIPT_LISTENER_NO_BROWSER"


def setup_cli_parser(parser: ArgumentParser) -> None:
    subcommands = parser.add_subparsers(dest="smartnumbers_command")

    setup = subcommands.add_parser("setup", help="Connect Smart Numbers to this Hermes profile")
    setup.add_argument("--local", action="store_true", help="Use the local Docker Compose mock app")
    setup.add_argument(
        "--app-url",
        default=None,
        help=f"Token exchange URL (default: {DEFAULT_APP_URL}; local: {LOCAL_APP_URL})",
    )
    setup.add_argument("--setup-url", default=None, help="Browser-facing Smart Numbers setup URL")
    setup.add_argument("--timeout-seconds", type=int, default=300, help="Seconds to wait for browser approval")
    setup.add_argument(
        "--callback-bind-host", default=None, help="Host interface for the temporary callback server"
    )
    setup.add_argument("--callback-host", default=None, help="Loopback hostname used in the browser callback URL")
    setup.add_argument(
        "--callback-port",
        type=int,
        default=None,
        help="Callback port; 0 selects an available port (manual paste defaults to 3021)",
    )
    setup.add_argument(
        "--no-browser", action="store_true", help="Print the setup URL without attempting to open a browser"
    )
    setup.add_argument(
        "--manual-paste",
        action="store_true",
        help="Complete setup by pasting the final browser redirect URL",
    )
    setup.set_defaults(func=handle_cli)

    status = subcommands.add_parser("status", help="Show Smartnumbers setup status")
    status.set_defaults(func=handle_cli)

    clear = subcommands.add_parser("clear", help="Remove saved Smartnumbers credentials")
    clear.set_defaults(func=handle_cli)

    parser.set_defaults(func=handle_cli)


def handle_cli(args: Namespace) -> None:
    command = getattr(args, "smartnumbers_command", None)
    if command == "setup":
        _setup(args)
        return
    if command == "status":
        _status()
        return
    if command == "clear":
        _clear()
        return
    print("Usage: hermes smartnumbers <setup|status|clear>")


def _setup(args: Namespace) -> None:
    try:
        existing_config = load_plugin_config(PLUGIN_KEY)
        local = bool(getattr(args, "local", False))
        app_url = getattr(args, "app_url", None) or (
            _env_value(LOCAL_APP_URL_ENV, LOCAL_APP_URL) if local else existing_config.app_url
        )
        token = run_browser_setup(
            app_url=app_url,
            setup_url=getattr(args, "setup_url", None)
            or (_env_value(LOCAL_SETUP_URL_ENV, app_url) if local else None),
            local=local,
            timeout_seconds=int(getattr(args, "timeout_seconds", 300)),
            callback_bind_host=getattr(args, "callback_bind_host", None)
            or _env_value(CALLBACK_BIND_HOST_ENV, "127.0.0.1"),
            callback_host=getattr(args, "callback_host", None) or _env_value(CALLBACK_HOST_ENV, "127.0.0.1"),
            callback_port=getattr(args, "callback_port", None)
            if getattr(args, "callback_port", None) is not None
            else _env_int(CALLBACK_PORT_ENV, 0),
            open_browser_enabled=not (
                bool(getattr(args, "no_browser", False)) or _env_flag(NO_BROWSER_ENV)
            ),
            manual_paste=bool(getattr(args, "manual_paste", False)),
        )
    except SetupError as exc:
        raise SystemExit(f"Smartnumbers setup failed: {exc}") from exc
    print("Smartnumbers connected.")
    print(f"  key_prefix: {token.key_prefix}")
    print(f"  websocket:  {token.websocket_url}")
    print(f"  saved:      {API_KEY_ENV} in Hermes .env")


def _status() -> None:
    config = load_plugin_config(PLUGIN_KEY)
    api_key = _read_api_key()
    print("Smartnumbers status")
    print(f"  run_listener: {config.run_listener}")
    print(f"  stream_url:    {config.stream_url or '(not set)'}")
    print(f"  app_url:       {config.app_url}")
    print(f"  api_key:       {'set (' + api_key[:8] + '...)' if api_key else 'not set'}")
    if config.key_prefix:
        print(f"  key_prefix:    {config.key_prefix}")


def _clear() -> None:
    try:
        clear_setup()
    except SetupError as exc:
        raise SystemExit(f"Smartnumbers clear failed: {exc}") from exc
    print("Smartnumbers credentials cleared.")


def _read_api_key() -> str:
    try:
        from hermes_cli.config import get_env_value
    except ImportError:
        return ""
    return str(get_env_value(API_KEY_ENV) or "").strip()


def _env_value(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env_value(name, str(default)))
    except ValueError:
        return default


def _env_flag(name: str) -> bool:
    return _env_value(name, "").lower() in {"1", "true", "yes", "on"}
