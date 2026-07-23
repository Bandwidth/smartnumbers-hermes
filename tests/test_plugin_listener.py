from pathlib import Path

from transcript_listener import plugin
from transcript_listener.config import config_from_mapping


class FakeContext:
    def register_tool(self, **kwargs):  # noqa: ANN001
        del kwargs


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
        }
    )

    def fake_start(client, on_payload):  # noqa: ANN001
        del on_payload
        started.append(client)
        return FakeThread()

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
