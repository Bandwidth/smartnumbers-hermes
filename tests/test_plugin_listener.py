from pathlib import Path

from transcript_listener import plugin
from transcript_listener.config import config_from_mapping


class FakeContext:
    def __init__(self) -> None:
        self.cli_commands = []
        self.tools = []

    def register_tool(self, **kwargs):  # noqa: ANN001
        self.tools.append(kwargs)

    def register_cli_command(self, **kwargs):  # noqa: ANN001
        self.cli_commands.append(kwargs)


class FakeThread:
    def is_alive(self) -> bool:
        return True


def test_register_starts_listener_once_per_process(monkeypatch, tmp_path):
    started = []
    config = config_from_mapping(
        {
                "run_listener": True,
                "stream_url": "ws://connection-server:8000/ws/hermes",
                "storage_path": str(tmp_path / "transcripts.db"),
                "allow_insecure_stream_url": True,
                "allowed_stream_hosts": ["connection-server"],
        }
    )

    def fake_start(client, on_payload):  # noqa: ANN001
        del on_payload
        started.append(client)
        return FakeThread()

    monkeypatch.setenv("TRANSCRIPT_LISTENER_API_KEY", "bwa_key_test")
    monkeypatch.setattr(plugin, "load_plugin_config", lambda plugin_key="smartnumbers": config)
    monkeypatch.setattr(plugin, "start_daemon_listener", fake_start)
    plugin._listener_lock = None
    plugin._listener_client = None
    plugin._listener_thread = None

    try:
        plugin.register(FakeContext())
        plugin.register(FakeContext())

        assert len(started) == 1
        assert Path(str(tmp_path / "transcripts.lock")).exists()
    finally:
        if plugin._listener_lock is not None:
            plugin._listener_lock.release()
        plugin._listener_lock = None
        plugin._listener_client = None
        plugin._listener_thread = None


def test_register_skips_listener_without_api_key(monkeypatch, tmp_path):
    started = []
    config = config_from_mapping(
        {
            "run_listener": True,
            "stream_url": "ws://connection-server:8000/ws/hermes",
            "storage_path": str(tmp_path / "transcripts.db"),
        }
    )

    monkeypatch.delenv("TRANSCRIPT_LISTENER_API_KEY", raising=False)
    monkeypatch.setattr(plugin, "load_plugin_config", lambda plugin_key="smartnumbers": config)
    monkeypatch.setattr(plugin, "start_daemon_listener", lambda client, on_payload: started.append(client))
    plugin._listener_lock = None
    plugin._listener_client = None
    plugin._listener_thread = None

    plugin.register(FakeContext())

    assert started == []


def test_register_adds_cli_command(monkeypatch, tmp_path):
    config = config_from_mapping({"storage_path": str(tmp_path / "transcripts.db")})
    ctx = FakeContext()

    monkeypatch.setattr(plugin, "load_plugin_config", lambda plugin_key="smartnumbers": config)

    plugin.register(ctx)

    assert ctx.cli_commands[0]["name"] == "smartnumbers"
    assert {tool["toolset"] for tool in ctx.tools} == {"smartnumbers"}
    transcript_search = next(tool for tool in ctx.tools if tool["name"] == "transcript_search")
    assert "phone calls" in transcript_search["description"].lower()
