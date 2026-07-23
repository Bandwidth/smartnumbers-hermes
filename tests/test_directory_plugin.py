import importlib.util
import sys
import tomllib
from pathlib import Path


def test_root_entry_point_exposes_register():
    root = Path(__file__).resolve().parents[1]
    module_name = "hermes_plugins.smartnumbers_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        root / "__init__.py",
        submodule_search_locations=[str(root)],
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        assert callable(module.register)
    finally:
        sys.modules.pop(module_name, None)


def test_manifest_uses_smartnumbers_identity_without_credential_gate():
    manifest = (Path(__file__).resolve().parents[1] / "plugin.yaml").read_text()

    assert "manifest_version: 1" in manifest
    assert "name: smartnumbers" in manifest
    assert "requires_env:" not in manifest


def test_package_exposes_smartnumbers_entry_point():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())

    assert project["project"]["name"] == "hermes-smartnumbers"
    assert project["project"]["entry-points"]["hermes_agent.plugins"] == {
        "smartnumbers": "transcript_listener.plugin"
    }
