# Contributing to Nautilus Extensions

Thanks for helping improve the extension. Bug reports, compatibility reports,
documentation fixes, and focused pull requests are all welcome.

## Before opening an issue

- Search the existing issues.
- Run `./scripts/doctor.sh` and include its output.
- Check [`docs/troubleshooting.md`](docs/troubleshooting.md).
- Remove personal paths, usernames, and file names from logs.

Security problems should follow [`SECURITY.md`](SECURITY.md), not the public
issue tracker.

## Development setup

The extension has no third-party runtime dependencies beyond what Nautilus
already ships. Development only needs Python 3.10+, `pytest`, and `ruff`.

```sh
git clone https://github.com/kodejeet/nautilus-extensions.git
cd nautilus-extensions

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install pytest ruff
```

On Debian/Ubuntu, `python3-venv` may be required for the virtualenv. You can
also use `uv`:

```sh
uv venv
uv pip install pytest ruff
```

The project metadata is for tooling and packaging; the supported installation
path is still `./install.sh`.

## Tests

The unit suite is fully headless. It replaces `gi` with
`tests/stubs/gi`, then loads the real `extensions/foldersize.py`. That means tests run
without GTK, Nautilus, a display server, or a running desktop session.

```sh
python3 -m pytest -q
python3 -m pytest -q tests/test_pill.py -vv
python3 -m pytest -q -k cache
```

Rules for new tests:

- Put pure logic tests under `tests/` and keep them deterministic.
- Use `tmp_path`; never write into the contributor's home directory.
- Do not require network access.
- If you add a filesystem edge case, cover the equivalent `du` behavior when
  possible.
- Keep the real extension importable with only the fake `gi` stubs.

## Lint and formatting

```sh
ruff check .
ruff format --check .
```

Apply fixes with:

```sh
ruff check --fix .
ruff format .
```

The configured line length is 100. The test stubs intentionally keep broad
`except Exception` guards; broad exception handling in the extension is a
deliberate requirement, not an oversight.

## Manual live testing

The headless tests cannot validate Nautilus' private widget tree. Before a
release, test on a real session:

1. `./install.sh`
2. Watch `journalctl --user -t nautilus-foldersize -f`.
3. Select one folder; confirm the pill gains `, <size>)`.
4. Select two folders; confirm the pill shows their sum.
5. Select a file, then a file + folder; confirm the pill is unchanged.
6. Switch between two folders with the same item count; confirm the value
   updates.
7. Enable **Folder Size** in list view; confirm values and scrolling.
8. Set `NAUTILUS_FOLDERSIZE_NO_PILL=1` in the environment used to start
   Nautilus, restart, and confirm only the pill is disabled.
9. `./uninstall.sh --purge`, restart, and confirm the extension is gone.

If you change the floating-bar logic, also test both icon view and list view,
and both a single window and two windows.

## Code guidelines

- Keep each extension a single self-contained file in `extensions/`.
  Nautilus loads that file directly; no package import happens at runtime.
- Keep runtime dependencies to the Python standard library plus PyGObject,
  GTK 4, and Nautilus.
- Never do filesystem work on the GTK main loop. Use `SizeService` workers.
- Marshal UI changes through `GLib.idle_add()`.
- Wrap every GTK signal callback with `@safe(...)` or an equivalent guard.
- Do not follow symlinks while scanning.
- Do not scan remote or pseudo filesystems.
- Never patch, rebuild, replace, or `LD_PRELOAD` Nautilus.
- No hardcoded home directories, usernames, hostnames, or machine paths.
- Preserve compatibility with both `Nautilus-4.1` and `Nautilus-4.0`.
- Keep the kill switch and the column-only fallback working.
- Update `README.md`, `CHANGELOG.md`, and `docs/` when behavior changes.

The invariants in [`docs/architecture.md`](docs/architecture.md) are part of the
contract. A pull request that breaks one needs a clear design discussion first.

## Commit messages

Short, imperative, and scoped:

```text
feat: cache negative scan results
fix: restore closing parenthesis after restart
docs: document Ubuntu 24.04 fallback
test: cover hard-link accounting
```

## Pull requests

A good pull request:

- explains the user-visible problem and the chosen fix;
- includes tests for new logic;
- updates docs and the changelog;
- keeps unrelated formatting changes out;
- passes `make check`;
- states which Nautilus version and Ubuntu release were used for live testing.

Small pull requests are easier to review than large mixed ones.

## Releases

Maintainers:

1. Update `VERSION`, `version` in `pyproject.toml`, and `__version__` in the
   changed extension modules.
2. Update `CHANGELOG.md`.
3. Run `make check` and the manual checklist.
4. Commit, tag `vX.Y.Z`, and push the tag.
5. The release workflow builds the tarball and publishes the GitHub release.

## License

By contributing, you agree that your contribution is licensed under
GPL-3.0-or-later, the same license as the project.
