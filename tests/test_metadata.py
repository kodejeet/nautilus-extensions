from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_version_matches_extension(fs):
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "%s"' % fs.__version__ in pyproject


def test_version_file_matches_extension(fs):
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert version == fs.__version__


def test_changelog_has_release_entry(fs):
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [%s]" % fs.__version__ in changelog


def test_source_has_spdx_header():
    source = (ROOT / "extensions" / "foldersize.py").read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: GPL-3.0-or-later" in source
