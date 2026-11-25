"""Shared pytest setup.

The extension is written as a Nautilus process plugin, so importing it normally
requires GTK, a display, and the Nautilus typelib. The tests replace ``gi`` with
the tiny stub in ``tests/stubs`` and load the real ``extensions/foldersize.py`` directly.
That keeps the suite fast, headless, and independent of the host desktop.
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STUBS = Path(__file__).resolve().parent / "stubs"

if str(STUBS) not in sys.path:
    sys.path.insert(0, str(STUBS))

# Make sure a real PyGObject installation cannot leak into the suite.
for _name in [name for name in sys.modules if name == "gi" or name.startswith("gi.")]:
    del sys.modules[_name]

_counter = 0


def load_extension():
    """Load a fresh copy of foldersize.py as an isolated module."""
    global _counter
    _counter += 1
    name = "foldersize_test_%d" % _counter
    spec = importlib.util.spec_from_file_location(name, ROOT / "extensions" / "foldersize.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load extensions/foldersize.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    # Keep test failures and synthetic paths out of the developer's journal.
    module.log = lambda *_args, **_kwargs: None
    module.log_exception = lambda *_args, **_kwargs: None
    return module


@pytest.fixture(scope="session")
def xdg_dirs(tmp_path_factory):
    """Point every XDG directory at a temporary tree for the whole session."""
    root = tmp_path_factory.mktemp("xdg")
    home = root / "home"
    cache = root / "cache"
    config = root / "config"
    data = root / "data"
    runtime = root / "runtime"
    for path in (home, cache, config, data, runtime):
        path.mkdir()
    names = (
        "HOME",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_RUNTIME_DIR",
    )
    previous = {name: os.environ.get(name) for name in names}
    os.environ.update(
        {
            "HOME": str(home),
            "XDG_CACHE_HOME": str(cache),
            "XDG_CONFIG_HOME": str(config),
            "XDG_DATA_HOME": str(data),
            "XDG_RUNTIME_DIR": str(runtime),
        }
    )
    try:
        yield {
            "root": root,
            "home": home,
            "cache": cache,
            "config": config,
            "data": data,
            "runtime": runtime,
        }
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.fixture(scope="session")
def fs(xdg_dirs):
    """The extension module, loaded once against the temporary XDG tree."""
    return load_extension()


@pytest.fixture
def fresh_fs():
    """Factory for a throw-away module instance (for import-time config tests)."""
    return load_extension
