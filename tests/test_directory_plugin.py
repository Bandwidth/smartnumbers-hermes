import importlib.util
import sys
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
