import os
import shutil
import stat
import time
from types import SimpleNamespace

import pytest


def expected_apparent_size(root):
    """Independent reference for du --apparent-size semantics."""
    total = 0
    seen = set()
    stack = [str(root)]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                st = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(st.st_mode):
                    stack.append(entry.path)
                    continue
                if stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
                    key = (st.st_dev, st.st_ino)
                    if key in seen:
                        continue
                    seen.add(key)
                total += st.st_size
    return total


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "tree"
    (root / "sub").mkdir(parents=True)
    (root / "empty").mkdir()
    (root / "a.txt").write_bytes(b"hello")
    (root / "sub" / "b.bin").write_bytes(b"x" * 100)
    return root


def test_walker_matches_du_apparent_size(fs, tree):
    assert fs._walk_size(str(tree), time.monotonic() + 30) == expected_apparent_size(tree)
    if shutil.which("du"):
        size, note, timed_out = fs._du_size(str(tree), 30)
        assert (note, timed_out) == (None, False)
        assert size == expected_apparent_size(tree)


def test_walker_counts_hard_links_once(fs, tmp_path):
    root = tmp_path / "links"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"abcdef")
    os.link(target, root / "hard")
    size = fs._walk_size(str(root), time.monotonic() + 30)
    assert size == len(b"abcdef")


def test_walker_does_not_follow_symlinks(fs, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    big = outside / "big"
    big.write_bytes(b"z" * 10_000)
    root = tmp_path / "tree"
    root.mkdir()
    (root / "real").write_bytes(b"abc")
    os.symlink(big, root / "link")

    size = fs._walk_size(str(root), time.monotonic() + 30)
    link_size = os.lstat(root / "link").st_size
    assert size == 3 + link_size
    assert size < 10_000


def test_walker_skips_unreadable_directories(fs, tree, monkeypatch):
    blocked = tree / "sub"
    real_scandir = os.scandir

    def guarded(path):
        if os.fspath(path) == str(blocked):
            raise PermissionError("denied")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", guarded)
    assert fs._walk_size(str(tree), time.monotonic() + 30) == 5


def test_walker_honours_deadline(fs, tree):
    with pytest.raises(TimeoutError):
        fs._walk_size(str(tree), time.monotonic() - 1)


def test_du_timeout_is_reported(fs, tree, monkeypatch):
    def timeout(*_args, **_kwargs):
        raise fs.subprocess.TimeoutExpired(["du"], 1)

    monkeypatch.setattr(fs.shutil, "which", lambda _name: "/usr/bin/du")
    monkeypatch.setattr(fs.subprocess, "run", timeout)
    assert fs._du_size(str(tree), 1) == (None, "timeout", True)


@pytest.mark.parametrize(
    ("stdout", "stderr", "returncode", "expected"),
    [
        (b"42\t/tmp/x\n", b"", 0, (42, None, False)),
        (b"42 /tmp/x\n", b"", 0, (42, None, False)),
        (
            b"42\t/tmp/x\n",
            b"du: cannot read: Permission denied\n",
            1,
            (42, "partial-permission", False),
        ),
        (b"", b"du: cannot read: Permission denied\n", 1, (None, "permission-denied", False)),
        (b"not-a-number\t/tmp/x\n", b"", 0, (None, "du-failed", False)),
    ],
)
def test_du_parses_output(fs, monkeypatch, stdout, stderr, returncode, expected):
    monkeypatch.setattr(fs.shutil, "which", lambda _name: "/usr/bin/du")
    monkeypatch.setattr(
        fs.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=stdout, stderr=stderr, returncode=returncode
        ),
    )
    assert fs._du_size("/tmp/x", 1) == expected


def test_du_missing_executable(fs, monkeypatch):
    monkeypatch.setattr(fs.shutil, "which", lambda _name: None)
    assert fs._du_size("/tmp/x", 1) == (None, "du-not-found", False)


def make_service(fs, tmp_path):
    service = object.__new__(fs.SizeService)
    service.cache = fs.Cache(str(tmp_path / "sizes.sqlite3"))
    return service


def test_compute_one_uses_cache_within_ttl(fs, tmp_path, monkeypatch):
    folder = tmp_path / "folder"
    folder.mkdir()
    service = make_service(fs, tmp_path)
    monkeypatch.setattr(fs, "_is_remote_or_unsupported", lambda _path: False)
    calls = []

    def du(path, timeout):
        calls.append(path)
        return 10, None, False

    monkeypatch.setattr(fs, "_du_size", du)
    assert service._compute_one(str(folder)) == (10, None)
    assert service._compute_one(str(folder)) == (10, None)
    assert calls == [str(folder)]


def test_compute_one_recomputes_after_ttl(fs, tmp_path, monkeypatch):
    folder = tmp_path / "folder"
    folder.mkdir()
    service = make_service(fs, tmp_path)
    monkeypatch.setattr(fs, "_is_remote_or_unsupported", lambda _path: False)
    monkeypatch.setattr(fs, "_du_size", lambda _p, _t: (10, None, False))
    assert service._compute_one(str(folder)) == (10, None)

    monkeypatch.setattr(fs, "TTL", 0.0)
    monkeypatch.setattr(fs, "_du_size", lambda _p, _t: (11, None, False))
    assert service._compute_one(str(folder)) == (11, None)


@pytest.mark.parametrize(
    ("setup", "expected_error"),
    [
        ("missing", "missing"),
        ("file", "not-directory"),
        ("symlink", "symlink"),
        ("remote", "remote"),
        ("timeout", "timeout"),
    ],
)
def test_compute_one_rejects_unsupported_targets(fs, tmp_path, monkeypatch, setup, expected_error):
    target = tmp_path / setup
    if setup == "file":
        target.write_text("x", encoding="utf-8")
    elif setup == "symlink":
        (tmp_path / "real").mkdir()
        target.symlink_to(tmp_path / "real", target_is_directory=True)
    elif setup == "remote" or setup == "timeout":
        target.mkdir()

    service = make_service(fs, tmp_path)
    monkeypatch.setattr(fs, "_is_remote_or_unsupported", lambda _path: setup == "remote")
    monkeypatch.setattr(
        fs,
        "_du_size",
        lambda _p, _t: (
            (None, "timeout", True) if setup == "timeout" else (None, "du-failed", False)
        ),
    )
    assert service._compute_one(str(target)) == (None, expected_error)


def test_compute_one_falls_back_to_walker(fs, tmp_path, monkeypatch):
    folder = tmp_path / "folder"
    folder.mkdir()
    service = make_service(fs, tmp_path)
    monkeypatch.setattr(fs, "_is_remote_or_unsupported", lambda _path: False)
    monkeypatch.setattr(fs, "_du_size", lambda _p, _t: (None, "du-failed", False))
    monkeypatch.setattr(fs, "_walk_size", lambda _p, _deadline: 777)
    assert service._compute_one(str(folder)) == (777, None)
    assert service.cache.get(str(folder)).size == 777


def test_compute_one_reports_walker_timeout(fs, tmp_path, monkeypatch):
    folder = tmp_path / "folder"
    folder.mkdir()
    service = make_service(fs, tmp_path)
    monkeypatch.setattr(fs, "_is_remote_or_unsupported", lambda _path: False)
    monkeypatch.setattr(fs, "_du_size", lambda _p, _t: (None, "du-failed", False))

    def timeout(_path, _deadline):
        raise TimeoutError

    monkeypatch.setattr(fs, "_walk_size", timeout)
    assert service._compute_one(str(folder)) == (None, "timeout")


def test_compute_reports_each_missing_path(fs, tmp_path):
    service = make_service(fs, tmp_path)
    first = str(tmp_path / "missing-a")
    second = str(tmp_path / "missing-b")
    result = service._compute((first, second))
    assert result.paths == (first, second)
    assert result.sizes == {first: None, second: None}
    assert result.errors == {first: "missing", second: "missing"}
    assert result.total is None


def test_size_result_total(fs):
    result = fs.SizeResult(("/a", "/b"), {"/a": 1, "/b": 2}, {"/a": None, "/b": None}, 3)
    assert result.total == 3


def test_lookup_sum_requires_every_path(fs, tmp_path):
    service = make_service(fs, tmp_path)
    assert service.lookup_sum([]) is None
    assert service.lookup_sum(("/a",)) is None
    service.cache.put("/a", fs.CacheEntry(2, 0, time.time(), None))
    service.cache.put("/b", fs.CacheEntry(3, 0, time.time(), None))
    assert service.lookup_sum(("/a", "/b")) == 5
    service.cache.put("/c", fs.CacheEntry(None, 0, time.time(), "error"))
    assert service.lookup_sum(("/a", "/c")) is None
