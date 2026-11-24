import json


def test_env_truthy_understands_common_values(fs):
    for value in ("", "0", "false", "no", "off", "FALSE"):
        assert fs._env_truthy("X", {"X": value}) is False
    for value in ("1", "true", "yes", "on", "anything"):
        assert fs._env_truthy("X", {"X": value}) is True
    assert fs._env_truthy("MISSING", {}) is False


def test_pill_enabled_defaults_to_true(fs):
    assert fs.pill_enabled(config={}, environ={}) is True


def test_pill_kill_switches(fs):
    assert (
        fs.pill_enabled(config={"pill": True}, environ={"NAUTILUS_FOLDERSIZE_NO_PILL": "1"})
        is False
    )
    assert (
        fs.pill_enabled(
            config={"pill": True},
            environ={"NAUTILUS_FOLDERSIZE_DISABLE_PILL": "1"},
        )
        is False
    )
    # Explicit falsey environment values keep the pill on.
    assert (
        fs.pill_enabled(config={"pill": False}, environ={"NAUTILUS_FOLDERSIZE_NO_PILL": "0"})
        is True
    )


def test_pill_config_keys(fs):
    assert fs.pill_enabled(config={"pill": False}, environ={}) is False
    assert fs.pill_enabled(config={"enable_pill": False}, environ={}) is False
    assert fs.pill_enabled(config={"pill_enabled": False}, environ={}) is False
    assert fs.pill_enabled(config={"enable_pill": True}, environ={}) is True


def test_pill_environment_has_precedence_over_config(fs):
    assert (
        fs.pill_enabled(config={"pill": False}, environ={"NAUTILUS_FOLDERSIZE_NO_PILL": "1"})
        is False
    )
    assert (
        fs.pill_enabled(config={"pill": False}, environ={"NAUTILUS_FOLDERSIZE_NO_PILL": "0"})
        is True
    )


def test_load_config_reads_json_object(tmp_path, fs):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"pill": False}), encoding="utf-8")
    assert fs._load_config(str(path)) == {"pill": False}


def test_load_config_ignores_non_object_and_invalid_json(tmp_path, fs):
    for content in ("[]", '"text"', "{not json"):
        path = tmp_path / "config.json"
        path.write_text(content, encoding="utf-8")
        assert fs._load_config(str(path)) == {}


def test_load_config_missing_file(tmp_path, fs):
    assert fs._load_config(str(tmp_path / "missing.json")) == {}


def test_xdg_paths_are_used(fs):
    assert fs.CACHE_DIR.startswith(fs.GLib.get_user_cache_dir())
    assert fs.CONFIG_PATH.startswith(fs.GLib.get_user_config_dir())
    assert fs.CACHE_DB.endswith("sizes.sqlite3")
