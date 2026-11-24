import threading
import time
from types import SimpleNamespace

from gi.repository import Gtk, Nautilus
from helpers import FakeWidget


def test_column_provider_metadata(fs):
    provider = object.__new__(fs.FolderSizeColumnProvider)
    columns = provider.get_columns()
    assert len(columns) == 1
    column = columns[0]
    assert column.name == "NautilusPython::folder_size_column"
    assert column.attribute == "folder_size"
    assert column.label == "Folder Size"
    assert column.description


def test_info_provider_adds_formatted_attribute(fs):
    provider = object.__new__(fs.FolderSizeInfoProvider)
    info = Nautilus.FileInfo()
    provider._add_attribute(info, 1000)
    assert info.attributes == {"folder_size": "1.0 kB"}


def test_info_provider_survives_missing_attribute_support(fs):
    provider = object.__new__(fs.FolderSizeInfoProvider)

    class Broken:
        def add_string_attribute(self, _name, _value):
            raise RuntimeError("not supported")

    provider._add_attribute(Broken(), 1000)


def provider_with_cache(fs, entry, visible=False):
    provider = object.__new__(fs.FolderSizeInfoProvider)
    provider.core = SimpleNamespace(
        cache=SimpleNamespace(get=lambda _path: entry),
        column_is_visible=lambda: visible,
        column_lock=threading.RLock(),
        column_pending=set(),
        column_waiters={},
        column_result=lambda _result: None,
        engine=SimpleNamespace(request=lambda paths, callback: paths),
    )
    return provider


def test_update_file_info_uses_cached_value(fs):
    entry = fs.CacheEntry(1000, 0, time.time(), None)
    provider = provider_with_cache(fs, entry)
    info = Nautilus.FileInfo(is_directory=True, path="/tmp/folder")
    provider.update_file_info(info)
    assert info.attributes == {"folder_size": "1.0 kB"}


def test_update_file_info_skips_files(fs):
    provider = provider_with_cache(fs, None)
    info = Nautilus.FileInfo(is_directory=False, path="/tmp/file")
    provider.update_file_info(info)
    assert info.attributes == {}


def test_update_file_info_does_not_work_when_column_hidden(fs, monkeypatch):
    entry = fs.CacheEntry(1000, 0, time.time() - 1000, None)
    provider = provider_with_cache(fs, entry, visible=False)
    requests = []
    provider.core.engine.request = lambda paths, callback: requests.append(paths)
    info = Nautilus.FileInfo(is_directory=True, path="/tmp/folder")
    provider.update_file_info(info)
    assert requests == []
    assert provider.core.column_pending == set()


def test_update_file_info_requests_visible_column_value(fs, monkeypatch):
    entry = fs.CacheEntry(1000, 0, time.time() - 1000, None)
    provider = provider_with_cache(fs, entry, visible=True)
    requests = []
    provider.core.engine.request = lambda paths, callback: requests.append(paths)
    info = Nautilus.FileInfo(is_directory=True, path="/tmp/folder")
    provider.update_file_info(info)
    assert requests == [["/tmp/folder"]]
    assert provider.core.column_pending == {"/tmp/folder"}
    assert provider.core.column_waiters["/tmp/folder"] == [info]


def test_update_file_info_does_not_duplicate_pending_work(fs):
    entry = fs.CacheEntry(1000, 0, time.time() - 1000, None)
    provider = provider_with_cache(fs, entry, visible=True)
    requests = []
    provider.core.engine.request = lambda paths, callback: requests.append(paths)
    provider.core.column_pending.add("/tmp/folder")
    info = Nautilus.FileInfo(is_directory=True, path="/tmp/folder")
    provider.update_file_info(info)
    assert requests == []


def test_column_result_invalidates_waiters(fs):
    core = object.__new__(fs.Core)
    core.column_lock = threading.RLock()
    core.column_pending = {"/tmp/folder"}
    invalidated = []

    class Info:
        def invalidate_extension_info(self):
            invalidated.append(self)

    info = Info()
    core.column_waiters = {"/tmp/folder": [info]}
    core.cache = SimpleNamespace(get=lambda _path: fs.CacheEntry(1000, 0, time.time(), None))
    result = fs.SizeResult(("/tmp/folder",), {"/tmp/folder": 1000}, {}, 1000)
    core.column_result(result)
    assert invalidated == [info]
    assert core.column_pending == set()
    assert core.column_waiters == {}


class ColumnList:
    def __init__(self, titles):
        self.columns = [SimpleNamespace(get_title=lambda title=title: title) for title in titles]

    def get_n_items(self):
        return len(self.columns)

    def get_item(self, index):
        return self.columns[index]


class FakeColumnView(FakeWidget, Gtk.ColumnView):
    def __init__(self, titles):
        super().__init__()
        self.columns = ColumnList(titles)

    def get_columns(self):
        return self.columns


class Toplevels:
    def __init__(self, windows):
        self.windows = list(windows)

    def get_n_items(self):
        return len(self.windows)

    def get_item(self, index):
        return self.windows[index]


def test_column_visibility_detection(fs, monkeypatch):
    view = FakeWidget(gtype="NautilusFilesView")
    column_view = FakeColumnView(["Name", "Folder Size"])
    view.add(column_view)
    window = FakeWidget(children=[view])
    fake_model = Toplevels([window])
    monkeypatch.setattr(fs.Gtk.Window, "_toplevels", fake_model)

    core = object.__new__(fs.Core)
    core.column_checked_at = 0.0
    core.column_visible = False
    assert core.column_is_visible() is True

    column_view.columns = ColumnList(["Name", "Size"])
    core.column_checked_at = 0.0
    assert core.column_is_visible() is False


def test_column_visibility_falls_back_to_true_on_error(fs, monkeypatch):
    def broken():
        raise RuntimeError("future Nautilus")

    monkeypatch.setattr(fs.Gtk.Window, "get_toplevels", broken)
    core = object.__new__(fs.Core)
    core.column_checked_at = 0.0
    core.column_visible = False
    assert core.column_is_visible() is True


def test_ensure_started_is_a_singleton(fs, monkeypatch):
    monkeypatch.setattr(fs, "_core", None)
    monkeypatch.setattr(fs, "Core", lambda: SimpleNamespace(watcher=None))
    first = fs.ensure_started()
    second = fs.ensure_started()
    assert first is second
