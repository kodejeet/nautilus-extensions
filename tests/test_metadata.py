from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_version_matches_extension(fs):
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "%s"' % fs.__version__ in pyproject


def test_changelog_has_release_entry(fs):
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [%s]" % fs.__version__ in changelog


def test_source_has_spdx_header():
    source = (ROOT / "foldersize.py").read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: GPL-3.0-or-later" in source
