import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.sh"
UNINSTALL = ROOT / "uninstall.sh"


def run(script, *args, env=None, cwd=None, check=False):
    return subprocess.run(
        ["bash", str(script), *args],
        env=env,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def fake_nautilus(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "nautilus.log"
    script = bin_dir / "nautilus"
    script.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$NAUTILUS_TEST_LOG"\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    return bin_dir, log


def temp_env(tmp_path):
    home = tmp_path / "home"
    cache = tmp_path / "cache"
    config = tmp_path / "config"
    data = tmp_path / "data"
    for path in (home, cache, config, data):
        path.mkdir()
    bin_dir, log = fake_nautilus(tmp_path)
    env = dict(os.environ)
    env.update(
        {
            "HOME": str(home),
            "XDG_CACHE_HOME": str(cache),
            "XDG_CONFIG_HOME": str(config),
            "XDG_DATA_HOME": str(data),
            "PATH": str(bin_dir) + os.pathsep + env.get("PATH", ""),
            "NAUTILUS_TEST_LOG": str(log),
        }
    )
    return env, data, cache, config


@pytest.mark.parametrize("script", [INSTALL, UNINSTALL])
def test_scripts_parse(script):
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("script", [INSTALL, UNINSTALL])
def test_help_exits_zero(script):
    result = run(script, "--help")
    assert result.returncode == 0
    assert "usage:" in result.stdout.lower()


def test_install_version_matches_source():
    result = run(INSTALL, "--version")
    assert result.returncode == 0
    assert "0.1.0" in result.stdout


@pytest.mark.parametrize("script", [INSTALL, UNINSTALL])
def test_unknown_option_is_rejected(script):
    result = run(script, "--definitely-not-an-option")
    assert result.returncode == 2
    assert "unknown option" in result.stderr


def test_uninstall_dry_run_changes_nothing(tmp_path):
    env, data, cache, _config = temp_env(tmp_path)
    extension = data / "nautilus-python" / "extensions" / "foldersize.py"
    extension.parent.mkdir(parents=True)
    extension.write_text("# installed\n", encoding="utf-8")
    cache_file = cache / "nautilus-foldersize" / "sizes.sqlite3"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("cache", encoding="utf-8")

    result = run(UNINSTALL, "--purge", "--dry-run", env=env)
    assert result.returncode == 0
    assert "Would remove" in result.stdout
    assert extension.exists()
    assert cache_file.exists()


def test_uninstall_removes_extension(tmp_path):
    env, data, cache, _config = temp_env(tmp_path)
    extension = data / "nautilus-python" / "extensions" / "foldersize.py"
    extension.parent.mkdir(parents=True)
    extension.write_text("# installed\n", encoding="utf-8")
    cache_file = cache / "nautilus-foldersize" / "sizes.sqlite3"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("cache", encoding="utf-8")

    result = run(UNINSTALL, env=env)
    assert result.returncode == 0
    assert "Removed" in result.stdout
    assert not extension.exists()
    assert cache_file.exists()


def test_uninstall_purge_removes_state(tmp_path):
    env, data, cache, config = temp_env(tmp_path)
    extension = data / "nautilus-python" / "extensions" / "foldersize.py"
    extension.parent.mkdir(parents=True)
    extension.write_text("# installed\n", encoding="utf-8")
    cache_file = cache / "nautilus-foldersize" / "sizes.sqlite3"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("cache", encoding="utf-8")
    config_file = config / "nautilus-foldersize" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}", encoding="utf-8")

    result = run(UNINSTALL, "--purge", env=env)
    assert result.returncode == 0
    assert not extension.exists()
    assert not cache_file.exists()
    assert not config_file.exists()


def test_uninstall_is_idempotent(tmp_path):
    env, _data, _cache, _config = temp_env(tmp_path)
    result = run(UNINSTALL, env=env)
    assert result.returncode == 0
    assert "Not installed" in result.stdout


def _nautilus_api_available():
    code = (
        "import gi\n"
        "for version in ('4.1', '4.0'):\n"
        "    try:\n"
        "        gi.require_version('Nautilus', version)\n"
        "        from gi.repository import Nautilus\n"
        "        print(version)\n"
        "        raise SystemExit(0)\n"
        "    except Exception:\n"
        "        pass\n"
        "raise SystemExit(1)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    return result.returncode == 0


@pytest.mark.skipif(
    not _nautilus_api_available(),
    reason="Nautilus 4.x Python bindings are not installed on this machine",
)
def test_install_dry_run(tmp_path):
    env, data, _cache, _config = temp_env(tmp_path)
    result = run(INSTALL, "--dry-run", env=env)
    assert result.returncode == 0, result.stderr
    assert "Nautilus Folder Size 0.1.0" in result.stdout
    assert "Dry run" in result.stdout
    assert not (data / "nautilus-python" / "extensions" / "foldersize.py").exists()
