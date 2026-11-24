"""Small fake ``gi.repository`` used by the test suite."""

import os
from typing import ClassVar


class _FileSystemInfo:
    def __init__(self, remote=False, fs_type="ext4"):
        self._remote = remote
        self._fs_type = fs_type

    def get_attribute_boolean(self, _name):
        return self._remote

    def get_attribute_string(self, _name):
        return self._fs_type


class File:
    def __init__(self, path):
        self._path = path

    @classmethod
    def new_for_path(cls, path):
        return cls(path)

    def query_filesystem_info(self, _attributes, _cancellable=None):
        return _FileSystemInfo()

    def monitor_directory(self, _flags, _cancellable=None):
        return None


class FileMonitorFlags:
    NONE = 0


class FileMonitor:
    def cancel(self):
        pass

    def connect(self, *_args, **_kwargs):
        return 0


class Gio:
    File = File
    FileMonitor = FileMonitor
    FileMonitorFlags = FileMonitorFlags


class _ToplevelList:
    def __init__(self, items=None):
        self._items = list(items or [])

    def get_n_items(self):
        return len(self._items)

    def get_item(self, index):
        try:
            return self._items[index]
        except IndexError:
            return None

    def connect(self, *_args, **_kwargs):
        return 0


class Window:
    _toplevels = _ToplevelList()

    @classmethod
    def get_toplevels(cls):
        return cls._toplevels


class Label:
    def __init__(self, text=""):
        self._text = text

    def get_text(self):
        return self._text

    def set_text(self, text):
        self._text = text

    def connect(self, *_args, **_kwargs):
        return 0


class Widget:
    def get_mapped(self):
        return True

    def get_visible(self):
        return True

    def get_css_classes(self):
        return []


class GridView(Widget):
    pass


class ColumnView(Widget):
    def get_columns(self):
        return None


class ListView(Widget):
    pass


class Gtk:
    Window = Window
    Label = Label
    Widget = Widget
    GridView = GridView
    ColumnView = ColumnView
    ListView = ListView


class _Source:
    def __init__(self, callback=None, args=()):
        self.callback = callback
        self.args = args


class GLib:
    """Enough of GLib for deterministic tests; no main loop is involved."""

    SOURCE_REMOVE = True
    _sources: ClassVar[dict] = {}
    _next_id = 1
    _idle_callbacks: ClassVar[list] = []

    @staticmethod
    def get_user_cache_dir():
        return os.environ.get("XDG_CACHE_HOME", os.path.join(os.path.expanduser("~"), ".cache"))

    @staticmethod
    def get_user_config_dir():
        return os.environ.get("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config"))

    @staticmethod
    def get_user_runtime_dir():
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if runtime:
            return runtime
        return "/run/user/%d" % os.getuid()

    @staticmethod
    def format_size(size):
        size = int(size)
        if size < 1000:
            return "1 byte" if size == 1 else "%d bytes" % size
        value = float(size)
        units = ("kB", "MB", "GB", "TB", "PB", "EB")
        unit = 0
        value /= 1000.0
        while value >= 1000.0 and unit < len(units) - 1:
            value /= 1000.0
            unit += 1
        return "%.1f %s" % (value, units[unit])

    @classmethod
    def idle_add(cls, callback, *args):
        cls._idle_callbacks.append((callback, args))
        return len(cls._idle_callbacks)

    @classmethod
    def run_idle(cls):
        callbacks = list(cls._idle_callbacks)
        cls._idle_callbacks.clear()
        for callback, args in callbacks:
            callback(*args)

    @classmethod
    def timeout_add(cls, _interval, _callback, *_args):
        return 0

    @classmethod
    def timeout_add_seconds(cls, _interval, _callback, *_args):
        return 0

    @classmethod
    def source_remove(cls, _source_id):
        return True


class GObject:
    class GObject:
        def __init__(self, *args, **kwargs):
            pass


def _install():
    """Expose the fakes as attributes of the package's default namespace."""
    import sys

    package = sys.modules[__name__]
    for name, value in {
        "Gio": Gio,
        "GLib": GLib,
        "GObject": GObject,
        "Gtk": Gtk,
    }.items():
        setattr(package, name, value)


_install()
