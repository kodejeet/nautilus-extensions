# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Renamed the repository to **Nautilus Extensions** and moved Folder Size to
  `extensions/foldersize.py` so more extensions can live in the same project.
- `install.sh` and `uninstall.sh` now discover and manage every module in
  `extensions/` instead of a single hardcoded file.
- Release archives are now named `nautilus-extensions-<version>.tar.gz`.

## [0.1.0] - 2026-11-25

### Added

- Floating-bar folder size for single and multi-folder selections.
- Official **Folder Size** list-view column via `Nautilus.ColumnProvider` and
  `Nautilus.InfoProvider`.
- Background worker pool with `GLib.idle_add()` result delivery.
- In-memory and SQLite cache with TTL, stale-while-revalidate, and
  `Gio.FileMonitor` invalidation.
- Python walker fallback with `du -sb --apparent-size -x` semantics.
- Nautilus 4.1 typelib with automatic 4.0 fallback for Ubuntu 24.04 LTS.
- Pill kill switch via environment variables or `config.json`.
- Graceful pill disable if Nautilus changes its floating bar.
- Journal logging under the `nautilus-foldersize` tag.
- Per-user `install.sh` and `uninstall.sh` with dry-run and no-restart modes.
- Headless test suite, Ruff configuration, CI, release workflow, and a
  diagnostics script.

### Fixed

- Restore the closing parenthesis when stripping a cached size suffix after a
  Nautilus restart.
- Make the Python walker match `du --apparent-size`: do not count directory
  inode sizes, count symlinks by their own length without following them, and
  count hard-linked files once.

### Compatibility

- Nautilus 43+ with the 4.x Python API.
- Ubuntu 24.04 LTS (Nautilus 46, API 4.0) and Ubuntu 26.04 LTS (Nautilus 50,
  API 4.1).
- Python 3.10+.

### Known limitations

- Remote, GVFS, and pseudo filesystems are not scanned.
- Unreadable subdirectories are skipped and only reported in the journal.
- The floating bar is located by CSS class and text shape; a future Nautilus
  redesign may disable the pill while keeping the column functional.
- Very large selections are capped at 2000 items for safety.

[Unreleased]: https://github.com/kodejeet/nautilus-extensions/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/kodejeet/nautilus-extensions/releases/tag/v0.1.0
