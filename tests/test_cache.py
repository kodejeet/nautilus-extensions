import time


def make_entry(fs, size, mtime_ns=None, age=0.0, error=None):
    return fs.CacheEntry(
        size,
        mtime_ns if mtime_ns is not None else time.time_ns(),
        time.time() - age,
        error,
    )


def test_cache_put_get_and_delete(tmp_path, fs):
    cache = fs.Cache(str(tmp_path / "cache" / "sizes.sqlite3"))
    path = "/tmp/folder"
    assert cache.get(path) is None

    cache.put(path, make_entry(fs, 1234))
    entry = cache.get(path)
    assert entry is not None
    assert entry.size == 1234
    assert cache.get_persistent(path) is entry

    cache.delete_persistent(path)
    cache.drop_memory(path)
    assert cache.get_persistent(path) is None


def test_cache_persists_across_instances(tmp_path, fs):
    db = str(tmp_path / "sizes.sqlite3")
    first = fs.Cache(db)
    first.put("/tmp/a", make_entry(fs, 10))
    first.put("/tmp/b", make_entry(fs, None, error="permission"))

    second = fs.Cache(db)
    assert second.get("/tmp/a") is None
    second.load_all()
    assert second.get("/tmp/a").size == 10
    error_entry = second.get("/tmp/b")
    assert error_entry.size is None
    assert error_entry.error == "permission"


def test_cache_reader_sees_committed_rows_without_load_all(tmp_path, fs):
    db = str(tmp_path / "sizes.sqlite3")
    first = fs.Cache(db)
    first.put("/tmp/a", make_entry(fs, 42))

    second = fs.Cache(db)
    entry = second.get_persistent("/tmp/a")
    assert entry is not None
    assert entry.size == 42
    # get_persistent warms the in-memory layer.
    assert second.get("/tmp/a") is entry


def test_cache_put_replaces_existing_row(tmp_path, fs):
    cache = fs.Cache(str(tmp_path / "sizes.sqlite3"))
    path = "/tmp/folder"
    cache.put(path, make_entry(fs, 1))
    cache.put(path, make_entry(fs, 2))
    assert cache.get(path).size == 2
    cache.drop_memory(path)
    assert cache.get_persistent(path).size == 2


def test_cache_handles_unusable_database_path(tmp_path, fs):
    # The parent exists as a regular file, so sqlite cannot create the DB.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    cache = fs.Cache(str(blocker / "sizes.sqlite3"))
    cache.put("/tmp/a", make_entry(fs, 1))
    assert cache.get("/tmp/a").size == 1  # memory cache still works
    assert cache.get_persistent("/tmp/other") is None
