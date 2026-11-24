import os

import pytest


def test_normalize_path_accepts_absolute_paths(fs):
    assert fs.normalize_path("/tmp/example") == "/tmp/example"
    assert fs.normalize_path("/tmp/a/../b") == "/tmp/b"
    assert fs.normalize_path("/tmp//a/") == "/tmp/a"


@pytest.mark.parametrize(
    "value",
    [None, "", "relative/path", "tmp/example", "/tmp/bad\x00name", 42],
)
def test_normalize_path_rejects_invalid_values(fs, value):
    assert fs.normalize_path(value) is None


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, "0 bytes"),
        (1, "1 byte"),
        (999, "999 bytes"),
        (1000, "1.0 kB"),
        (1023, "1.0 kB"),
        (4_703_990_926, "4.7 GB"),
        (27_400_000_000, "27.4 GB"),
    ],
)
def test_format_bytes_uses_glib_units(fs, size, expected):
    assert fs.format_bytes(size) == expected


def test_format_bytes_returns_none_for_invalid_input(fs):
    assert fs.format_bytes(None) is None
    assert fs.format_bytes("not-a-number") is None


def test_own_suffix_regex_strips_only_our_suffix(fs):
    cases = [
        ("(containing 8 items, 4.7 GB)", "(containing 8 items)"),
        ("(containing 8 items, 4.7\u202fGB)", "(containing 8 items)"),
        ("(containing 8 items, 4.7\u00a0GB)", "(containing 8 items)"),
        ("(containing 1 item, 999 bytes)", "(containing 1 item)"),
        ("(selected folder, 1.0 kB)", "(selected folder)"),
    ]
    for text, expected in cases:
        assert fs._strip_size_suffix(text) == expected


def test_own_suffix_regex_ignores_unrelated_text(fs):
    for text in [
        "(containing 8 items)",
        "(containing 8 items, calculating…)",
        "“A folder, 4.7 GB” selected",
        "(containing 8 items, 4.7 GB) extra",
    ]:
        assert fs._strip_size_suffix(text) == text


def test_quoted_name_reads_curly_quotes(fs):
    texts = ["“Photos” selected", "(containing 8 items)"]
    assert fs.quoted_name(texts) == "Photos"
    assert fs.quoted_name(["plain text"]) is None


def test_fallback_single_path_joins_view_location(fs):
    class Location:
        def get_path(self):
            return "/srv/media"

    class View:
        def get_property(self, name):
            assert name == "location"
            return Location()

    assert fs.fallback_single_path(View(), ["“Photos” selected"]) == ("/srv/media/Photos")


def test_fallback_single_path_rejects_names_with_slashes(fs):
    class View:
        def get_property(self, _name):
            raise AssertionError("view must not be queried for an invalid name")

    assert fs.fallback_single_path(View(), ["“a/b” selected"]) is None


def test_fallback_single_path_without_location(fs):
    class View:
        def get_property(self, _name):
            return None

    assert fs.fallback_single_path(View(), ["“Photos” selected"]) is None


def test_gvfs_runtime_paths_are_treated_as_remote(fs, monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setattr(fs.GLib, "get_user_runtime_dir", lambda: str(runtime))
    path = os.path.join(str(runtime), "gvfs", "smb-share", "folder")
    assert fs._is_remote_or_unsupported(path) is True


def test_local_tmp_path_is_not_remote(fs, tmp_path):
    assert fs._is_remote_or_unsupported(str(tmp_path)) is False
