from gi.repository import Gtk
from helpers import FakeEngine, FakeLabel, FakeWatcher, FakeWidget


def make_state(fs, engine=None):
    watcher = FakeWatcher(engine or FakeEngine())
    bar = FakeWidget(css=["floating-bar"], gtype="NautilusFloatingBar")
    state = fs.BarState(watcher, bar, None)
    return watcher, bar, state


def make_labels(state, detail="(containing 8 items)", primary="“Photos” selected"):
    primary_label = FakeLabel(primary)
    detail_label = FakeLabel(detail)
    state.attach_labels([primary_label, detail_label])
    return primary_label, detail_label


def test_iter_widgets_visits_the_whole_tree(fs):
    leaf = FakeWidget()
    bar = FakeWidget(children=[FakeLabel(), FakeLabel()])
    root = FakeWidget(children=[bar, leaf])
    widgets = list(fs._iter_widgets(root))
    assert len(widgets) == 5
    assert set(map(id, widgets)) == {
        id(root),
        id(bar),
        id(bar._children[0]),
        id(bar._children[1]),
        id(leaf),
    }


def test_find_bars_uses_css_class_and_gtype(fs):
    bar = FakeWidget(css=["floating-bar", "horizontal"])
    typed = FakeWidget(gtype="NautilusFloatingBar")
    other = FakeWidget(css=["toolbar"])
    root = FakeWidget(children=[other, bar, typed])
    assert set(map(id, fs._find_bars(root))) == {id(bar), id(typed)}


def test_strip_own_prefers_exact_previous_result(fs):
    _watcher, _bar, state = make_state(fs)
    state.last_base = "(containing 8 items)"
    state.last_applied = "(containing 8 items, 4.7 GB)"
    assert state._strip_own(state.last_applied) == state.last_base


def test_strip_own_recognises_suffix_after_restart(fs):
    _watcher, _bar, state = make_state(fs)
    assert state._strip_own("(containing 8 items, 4.7\u202fGB)") == "(containing 8 items)"
    assert state._strip_own("(containing 8 items)") == "(containing 8 items)"
    assert state._strip_own("not ours") == "not ours"


def test_apply_appends_size(fs):
    _watcher, _bar, state = make_state(fs)
    label = FakeLabel("(containing 8 items)")
    state._apply(label, "(containing 8 items)", ("/tmp/Photos",), 4_703_990_926, state.token)
    assert label.get_text() == "(containing 8 items, 4.7 GB)"
    assert state.last_base == "(containing 8 items)"
    assert state.last_paths == ("/tmp/Photos",)


def test_apply_requires_current_base(fs):
    _watcher, _bar, state = make_state(fs)
    label = FakeLabel("(something else)")
    state._apply(label, "(containing 8 items)", ("/tmp/Photos",), 1000, state.token)
    assert label.get_text() == "(something else)"


def test_apply_rejects_stale_token(fs):
    _watcher, _bar, state = make_state(fs)
    state.token = 2
    label = FakeLabel("(containing 8 items)")
    state._apply(label, "(containing 8 items)", ("/tmp/Photos",), 1000, 1)
    assert label.get_text() == "(containing 8 items)"


def test_apply_ignores_unknown_size(fs):
    _watcher, _bar, state = make_state(fs)
    label = FakeLabel("(containing 8 items)")
    state._apply(label, "(containing 8 items)", ("/tmp/Photos",), None, state.token)
    assert label.get_text() == "(containing 8 items)"


def test_restore_removes_previous_suffix(fs):
    _watcher, _bar, state = make_state(fs)
    label = FakeLabel("(containing 8 items)")
    state._apply(label, "(containing 8 items)", ("/tmp/Photos",), 1000, state.token)
    assert label.get_text() == "(containing 8 items, 1.0 kB)"
    state._restore(label)
    assert label.get_text() == "(containing 8 items)"
    assert state.last_applied is None


def test_restore_safety_net_strips_foreign_suffix(fs):
    _watcher, _bar, state = make_state(fs)
    label = FakeLabel("(containing 8 items, 2.0 kB)")
    state._restore(label)
    assert label.get_text() == "(containing 8 items)"


def test_selection_change_reads_paths_from_model(fs, monkeypatch):
    _watcher, _bar, state = make_state(fs)
    _primary, detail = make_labels(state)
    state.files_view = FakeWidget(gtype="NautilusFilesView")
    monkeypatch.setattr(
        fs,
        "read_selection",
        lambda _view: {
            "ok": True,
            "count": 3,
            "all_dirs": True,
            "all_local": True,
            "paths": ["/tmp/A", "/tmp/B", "/tmp/A"],
            "names": ["A", "B", "A"],
            "too_many": False,
        },
    )
    state._process()
    assert _watcher.engine.requests[0][0] == ("/tmp/A", "/tmp/B")
    assert state.token == 1
    assert detail.get_text() == "(containing 8 items)"


def test_mixed_selection_restores_label(fs, monkeypatch):
    _watcher, _bar, state = make_state(fs)
    _primary, detail = make_labels(state)
    detail.set_text("(containing 8 items, 4.7 GB)")
    state.files_view = FakeWidget(gtype="NautilusFilesView")
    monkeypatch.setattr(
        fs,
        "read_selection",
        lambda _view: {
            "ok": True,
            "count": 2,
            "all_dirs": False,
            "all_local": True,
            "paths": ["/tmp/A", "/tmp/B"],
            "names": ["A", "B"],
            "too_many": False,
        },
    )
    state._process()
    assert detail.get_text() == "(containing 8 items)"
    assert _watcher.engine.requests == []


def test_too_many_selection_restores_label(fs, monkeypatch):
    _watcher, _bar, state = make_state(fs)
    _primary, detail = make_labels(state)
    detail.set_text("(containing 2001 items, 4.7 GB)")
    state.files_view = FakeWidget(gtype="NautilusFilesView")
    monkeypatch.setattr(
        fs,
        "read_selection",
        lambda _view: {
            "ok": True,
            "count": 2001,
            "all_dirs": True,
            "all_local": True,
            "paths": [],
            "names": [],
            "too_many": True,
        },
    )
    state._process()
    assert detail.get_text() == "(containing 2001 items)"


def test_fallback_single_path_used_when_model_unavailable(fs, monkeypatch):
    _watcher, _bar, state = make_state(fs)
    _primary, _detail = make_labels(state)
    state.files_view = FakeWidget(gtype="NautilusFilesView")
    monkeypatch.setattr(
        fs,
        "read_selection",
        lambda _view: {
            "ok": False,
            "count": 0,
            "all_dirs": False,
            "all_local": False,
            "paths": [],
            "names": [],
            "too_many": False,
        },
    )
    monkeypatch.setattr(fs, "fallback_single_path", lambda _view, _texts: "/tmp/Photos")
    state._process()
    assert _watcher.engine.requests[0][0] == ("/tmp/Photos",)


def test_fallback_is_gated_by_folder_details(fs, monkeypatch):
    _watcher, _bar, state = make_state(fs)
    _primary, detail = make_labels(state, detail="(3 items selected)")
    state.files_view = FakeWidget(gtype="NautilusFilesView")
    monkeypatch.setattr(
        fs,
        "read_selection",
        lambda _view: {
            "ok": False,
            "count": 0,
            "all_dirs": False,
            "all_local": False,
            "paths": [],
            "names": [],
            "too_many": False,
        },
    )
    monkeypatch.setattr(fs, "fallback_single_path", lambda _view, _texts: "/tmp/Photos")
    state._process()
    assert _watcher.engine.requests == []
    assert detail.get_text() == "(3 items selected)"


def test_immediate_cache_value_is_applied(fs, monkeypatch):
    engine = FakeEngine()
    engine.cached["/tmp/Photos"] = 4_703_990_926
    watch, _bar, state = make_state(fs, engine=engine)
    _primary, detail = make_labels(state)
    detail.set_text("(containing 8 items)")
    state.files_view = FakeWidget(gtype="NautilusFilesView")
    monkeypatch.setattr(
        fs,
        "read_selection",
        lambda _view: {
            "ok": True,
            "count": 1,
            "all_dirs": True,
            "all_local": True,
            "paths": ["/tmp/Photos"],
            "names": ["Photos"],
            "too_many": False,
        },
    )
    state._process()
    assert detail.get_text() == "(containing 8 items, 4.7 GB)"
    assert len(watch.engine.requests) == 1


def test_size_result_monitors_and_applies(fs):
    _watcher, _bar, state = make_state(fs)
    _primary, detail = make_labels(state)
    result = fs.SizeResult(
        ("/tmp/A", "/tmp/B"),
        {"/tmp/A": 1000, "/tmp/B": 2000},
        {"/tmp/A": None, "/tmp/B": None},
        3000,
    )
    state._on_size_result(state.token, "(containing 8 items)", ("/tmp/A", "/tmp/B"), detail, result)
    assert detail.get_text() == "(containing 8 items, 3.0 kB)"
    assert _watcher.monitored == ["/tmp/A", "/tmp/B"]


def test_size_result_without_total_restores(fs):
    _watcher, _bar, state = make_state(fs)
    _primary, detail = make_labels(state)
    detail.set_text("(containing 8 items, 4.7 GB)")
    result = fs.SizeResult(("/tmp/A",), {"/tmp/A": None}, {"/tmp/A": "timeout"}, None)
    state._on_size_result(state.token, "(containing 8 items)", ("/tmp/A",), detail, result)
    assert detail.get_text() == "(containing 8 items)"


def test_selection_model_attachment_listens_for_same_text_changes(fs):
    _watcher, _bar, state = make_state(fs)

    class Model:
        def __init__(self):
            self.connected = []

        def connect(self, signal, callback):
            self.connected.append(signal)
            return 7

        def disconnect(self, _handler):
            pass

    class Selection(FakeWidget, Gtk.GridView):
        def __init__(self):
            super().__init__()
            self.model = Model()

        def get_model(self):
            return self.model

    view = FakeWidget(gtype="NautilusFilesView")
    view.add(Selection())
    state.attach_selection_model(view)
    assert state.selection_model is not None
    assert state.selection_model.connected == ["selection-changed"]
    assert state.selection_handler == 7
    state.detach_selection_model()
    assert state.selection_model is None
