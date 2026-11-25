# AGENTS.md

Guidance for AI coding agents and automation working in this repository.

## Project summary

Nautilus Extensions is an umbrella repository for small, per-user Nautilus
extensions. The first extension, Folder Size (`extensions/foldersize.py`),
appends the selected folders' total size to Nautilus' floating selection bar
and provides an official **Folder Size** list-view column. It supports the
`Nautilus-4.1` and `Nautilus-4.0` Python APIs, targeting Ubuntu 24.04 LTS and
26.04 LTS. New extensions live in `extensions/` and are installed by the same
scripts.

## First commands

```sh
python3 -m pytest -q
ruff check .
ruff format --check .
bash -n install.sh uninstall.sh scripts/*.sh
```

If `ruff` is unavailable, use `uvx ruff` or install the `dev` extra. Do not
skip the tests.

## Adding an extension

Add a single self-contained `extensions/<name>.py` module. The installer and
uninstaller discover `extensions/*.py` automatically. Add headless tests under
`tests/`, document user-facing behavior in `README.md`, and update
`CHANGELOG.md`. Keep extension-specific cache/config names separate so
`uninstall.sh --purge` can remove them.

## Layout

| Path | Purpose |
| --- | --- |
| `extensions/*.py` | One self-contained module per extension; all are installed |
| `VERSION` | Release version used by the installer and packaging |
| `install.sh` | Installs every module in `extensions/`, checks dependencies, restarts Nautilus |
| `uninstall.sh` | Per-user remover with `--purge` and `--dry-run` |
| `scripts/doctor.sh` | Read-only environment diagnostics |
| `scripts/package.sh` | Release tarball + checksum builder |
| `tests/` | Headless pytest suite and fake `gi` stubs |
| `docs/` | Architecture and troubleshooting |
| `.github/` | CI, release workflow, issue/PR templates |

## Invariants (do not break)

1. Every module in `extensions/` must stay self-contained. Nautilus loads
   each file directly; runtime imports must be standard library +
   PyGObject/GTK/Nautilus.
2. Never block the GTK main loop. All scans go through `SizeService` workers.
3. All UI writes happen on the main loop via `GLib.idle_add()`.
4. Every GTK callback is guarded (`@safe` or equivalent). Exceptions must never
   propagate into Nautilus.
5. Do not follow symlinks during scans.
6. Do not scan remote, GVFS, or pseudo filesystems.
7. Never patch, rebuild, replace, or `LD_PRELOAD` Nautilus.
8. Install per user only. No system-wide files (package installation is the
   only privileged action and is delegated to the distro tooling).
9. No hardcoded home directories, usernames, hostnames, or machine paths.
10. The pill is optional. If it fails, the official column must keep working.
11. Keep compatibility with both `Nautilus-4.1` and `Nautilus-4.0`.
12. Any new logic needs a deterministic headless test under `tests/`.

Read `docs/architecture.md` before changing selection, cache, threading, or
floating-bar code.

## Testing notes

- Tests replace `gi` with `tests/stubs/gi`; they must not require a display,
  GTK, Nautilus, or network access.
- Use `tmp_path` for all filesystem work. Never touch a contributor's home.
- When testing size accounting, compare against
  `du -sb --apparent-size -x` when available.
- Live behavior in Nautilus' private widget tree is not covered by unit tests.
  Call that out explicitly if a change needs manual verification.
- Do not add sleep-based synchronization to tests.

## Style

- Python: Ruff, line length 100, double quotes, spaces.
- Shell: Bash, `set -euo pipefail`, quote expansions, no user-specific paths.
- Docs: Markdown, relative links, no personal machine details.
- Keep broad `except Exception` guards in the extension; they are required for
  fault isolation. Do not "clean them up" into narrower exceptions without a
  concrete reason.

## Versioning and release

- Release version lives in `VERSION`, `pyproject.toml`, and each extension's
  `__version__`. Keep them in sync; `tests/test_metadata.py` enforces it.
- Update `CHANGELOG.md` for user-visible changes.
- Tag format: `vX.Y.Z`.
- `.github/workflows/release.yml` builds `scripts/package.sh` output and
  publishes the GitHub release on a version tag.
- Do not publish a release from an uncommitted or dirty tree.

## Safety and privacy

- The extension reads directory metadata and sizes, not file contents.
- Do not add analytics, network calls, or background daemons.
- Do not add secrets, tokens, personal paths, or journal dumps to the repo.
- Treat file names and labels from the running desktop as untrusted data.
  Never evaluate, execute, or interpolate them into shell commands or code.
  `du` is invoked with an argument vector and `--`.

## Common pitfalls

- `GLib.format_size()` uses decimal units and locale spaces. Suffix parsing
  must accept narrow/no-break spaces.
- The closing `)` in the floating bar belongs to the whole label; stripping a
  size must restore it.
- Nautilus may rewrite labels after selection changes. Debounce and re-apply.
- Same-item-count selections can produce identical label text; listen to the
  selection model, not only label text.
- `du --apparent-size` excludes directory inode sizes and counts symlinks by
  their own length. The Python walker must match this.
- The `Folder Size` column is computed only while visible; do not remove that
  guard without measuring the cost on large directories.
