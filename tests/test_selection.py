class Bitset:
    def __init__(self, indexes):
        self.indexes = list(indexes)

    def get_size(self):
        return len(self.indexes)

    def get_nth(self, position):
        return self.indexes[position]


class Location:
    def __init__(self, path):
        self.path = path

    def get_path(self):
        return self.path


class FileInfo:
    def __init__(self, name, is_directory=True, path="/tmp/item"):
        self.name = name
        self.is_dir = is_directory
        self.path = path

    def get_name(self):
        return self.name

    def is_directory(self):
        return self.is_dir

    def get_location(self):
        return Location(self.path) if self.path is not None else None


class Item:
    def __init__(self, file_info):
        self.file_info = file_info

    def get_property(self, name):
        assert name == "file"
        return self.file_info


class Row:
    def __init__(self, file_info):
        self.item = Item(file_info)

    def get_item(self):
        return self.item


class Model:
    def __init__(self, bitset, rows):
        self.bitset = bitset
        self.rows = rows

    def get_selection(self):
        return self.bitset

    def get_item(self, index):
        return self.rows[index]


class SelectionWidget:
    def __init__(self, model):
        self.model = model

    def get_model(self):
        return self.model


def run_selection(fs, monkeypatch, model):
    monkeypatch.setattr(fs, "_pick_selection_widget", lambda _view: SelectionWidget(model))
    return fs.read_selection(object())


def test_read_selection_all_directories(fs, monkeypatch):
    rows = [
        Row(FileInfo("A", True, "/tmp/A")),
        Row(FileInfo("B", True, "/tmp/B")),
    ]
    result = run_selection(fs, monkeypatch, Model(Bitset([0, 1]), rows))
    assert result["ok"] is True
    assert result["count"] == 2
    assert result["all_dirs"] is True
    assert result["all_local"] is True
    assert result["paths"] == ["/tmp/A", "/tmp/B"]
    assert result["names"] == ["A", "B"]


def test_read_selection_flags_files(fs, monkeypatch):
    rows = [
        Row(FileInfo("A", True, "/tmp/A")),
        Row(FileInfo("note.txt", False, "/tmp/note.txt")),
    ]
    result = run_selection(fs, monkeypatch, Model(Bitset([0, 1]), rows))
    assert result["all_dirs"] is False
    assert result["paths"] == ["/tmp/A", "/tmp/note.txt"]


def test_read_selection_flags_non_local_items(fs, monkeypatch):
    rows = [Row(FileInfo("remote", True, None))]
    result = run_selection(fs, monkeypatch, Model(Bitset([0]), rows))
    assert result["all_local"] is False
    assert result["paths"] == []


def test_read_selection_empty(fs, monkeypatch):
    result = run_selection(fs, monkeypatch, Model(Bitset([]), []))
    assert result["ok"] is True
    assert result["count"] == 0


def test_read_selection_too_many(fs, monkeypatch):
    monkeypatch.setattr(fs, "MAX_SELECTION", 1)
    rows = [
        Row(FileInfo("A", True, "/tmp/A")),
        Row(FileInfo("B", True, "/tmp/B")),
    ]
    result = run_selection(fs, monkeypatch, Model(Bitset([0, 1]), rows))
    assert result["ok"] is True
    assert result["too_many"] is True
    assert result["paths"] == []


def test_read_selection_without_selection_model(fs, monkeypatch):
    monkeypatch.setattr(fs, "_pick_selection_widget", lambda _view: None)
    assert fs.read_selection(object())["ok"] is False
    assert fs.read_selection(None)["ok"] is False


def test_read_selection_survives_broken_rows(fs, monkeypatch):
    class BrokenBitset(Bitset):
        def get_nth(self, _position):
            raise RuntimeError("model disappeared")

    rows = [Row(FileInfo("A", True, "/tmp/A"))]
    result = run_selection(fs, monkeypatch, Model(BrokenBitset([0]), rows))
    assert result["ok"] is False
    assert result["paths"] == []


def test_fallback_path_is_normalized(fs):
    class LocationProvider:
        def get_path(self):
            return "/tmp/../tmp/Videos"

    class View:
        def get_property(self, _name):
            return LocationProvider()

    assert fs.fallback_single_path(View(), ["“clip” selected"]) == "/tmp/Videos/clip"
