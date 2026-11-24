# Nautilus Folder Size

[![CI](https://github.com/kodejeet/nautilus-foldersize/actions/workflows/ci.yml/badge.svg)](https://github.com/kodejeet/nautilus-foldersize/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/kodejeet/nautilus-foldersize?include_prereleases&sort=semver)](https://github.com/kodejeet/nautilus-foldersize/releases)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](LICENSE)
[![Nautilus 43+](https://img.shields.io/badge/Nautilus-43%2B-4a86cf)](https://gitlab.gnome.org/GNOME/nautilus)

See the size of selected folders without opening a terminal.

Nautilus Folder Size is a small, per-user Nautilus extension with two features:

- **Floating-bar size.** Select one or more folders and the floating selection
  bar gains the total apparent size:

  ```text
  “Photos” selected
  (containing 8 items, 4.7 GB)
  ```

- **Folder Size column.** An optional list-view column shows the same value
  for every folder in the current directory.

It uses only public Nautilus extension APIs for the column and locates the
floating bar by its GTK CSS class. It does **not** patch, rebuild, replace, or
`LD_PRELOAD` Nautilus.

## Features

- Non-blocking: scanning happens in daemon worker threads; labels and columns
  are updated on the GTK main loop with `GLib.idle_add()`.
- Multi-selection totals, but only when every selected item is a folder.
- Apparent sizes (`du -sb --apparent-size -x` semantics) formatted with
  `GLib.format_size()`.
- Symlinks are not followed. Unreadable subdirectories are skipped. Remote,
  GVFS, and pseudo filesystems are not scanned.
- In-memory + SQLite cache with a five-minute TTL and stale-while-revalidate.
  Selected folders get a `Gio.FileMonitor` for early invalidation.
- Every callback is exception-guarded. Failures are logged, never raised into
  Nautilus.
- If the floating bar is missing in a future Nautilus version, the extension
  logs one warning and disables only the pill; the official column continues
  to work.
- Kill switch for the pill, useful if a future Nautilus changes its bar.
- No network access, telemetry, or file-content reads.

## Requirements

- Linux with Nautilus 43 or newer using the 4.x Python API.
- Python 3.10+ and PyGObject (`python3-gi` on Debian/Ubuntu).
- The Nautilus Python bindings: `python3-nautilus` (Debian/Ubuntu),
  `nautilus-python` (Fedora), or `python-nautilus` (Arch).
- `du` from GNU coreutils is recommended. If it is unavailable, a built-in
  Python walker is used.

### Ubuntu compatibility

| Ubuntu | Nautilus | Nautilus Python API | Status |
| --- | --- | --- | --- |
| 24.04 LTS | 46.x | 4.0 | Supported via the 4.0 fallback |
| 26.04 LTS | 50.x | 4.1 | Primary development and live-test target |

The extension requests the `Nautilus-4.1` typelib first and falls back to
`Nautilus-4.0`, so the same file works on both releases. The test suite runs
headlessly and does not require either typelib.

## Install

```sh
git clone https://github.com/kodejeet/nautilus-foldersize.git
cd nautilus-foldersize
./install.sh
```

The installer:

1. checks Python, PyGObject, Nautilus, and the Nautilus 4.x bindings;
2. offers to install `python3-nautilus` (or the distribution equivalent);
3. copies `foldersize.py` to
   `${XDG_DATA_HOME:-~/.local/share}/nautilus-python/extensions/`;
4. restarts Nautilus with `nautilus -q`.

Nothing system-wide is modified. If the bindings are installed by the script,
log out and back in (or restart Nautilus) before using the extension.

Options:

```sh
./install.sh --dry-run      # check prerequisites, change nothing
./install.sh --no-restart   # install without restarting Nautilus
./install.sh --version
```

### Manual install

Copy `foldersize.py` to
`~/.local/share/nautilus-python/extensions/` and run `nautilus -q`.

## Use

- **Pill:** select a folder in icon or list view. The size appears after the
  scan finishes; large folders can take a while, but the window stays
  responsive. Mixed file/folder selections are left unchanged.
- **Column:** in list view, open the **Visible Columns** menu and enable
  **Folder Size**. Values are computed only while the column is visible.

### Remote and special locations

NFS, SMB/CIFS, SSHFS, GVFS, and pseudo filesystems are deliberately skipped to
avoid stalls. A skipped selection leaves the label unchanged and is recorded
in the journal.

## Configuration

Both environment variables disable only the pill:

```sh
NAUTILUS_FOLDERSIZE_NO_PILL=1 nautilus
NAUTILUS_FOLDERSIZE_DISABLE_PILL=1 nautilus
```

Or create `~/.config/nautilus-foldersize/config.json`:

```json
{"pill": false}
```

Restart Nautilus after editing the file. The **Folder Size** column keeps
working in all cases.

| Variable | Default | Meaning |
| --- | --- | --- |
| `NAUTILUS_FOLDERSIZE_NO_PILL` | unset | Disable the floating-bar feature |
| `NAUTILUS_FOLDERSIZE_DISABLE_PILL` | unset | Alias for the above |
| `NAUTILUS_FOLDERSIZE_DEBUG` | unset | Also print debug logs to stderr |
| `NAUTILUS_FOLDERSIZE_TTL` | `300` | Fresh-cache lifetime in seconds (5–86400) |
| `NAUTILUS_FOLDERSIZE_ERROR_TTL` | `60` | Error-cache lifetime in seconds (5–3600) |
| `NAUTILUS_FOLDERSIZE_DU_TIMEOUT` | `60` | Scan timeout in seconds (1–900) |
| `NAUTILUS_FOLDERSIZE_WORKERS` | `2` | Worker threads (1–4) |

Cache and state live in:

- `${XDG_CACHE_HOME:-~/.cache}/nautilus-foldersize/`
- `${XDG_CONFIG_HOME:-~/.config}/nautilus-foldersize/`

## Logs and diagnostics

```sh
journalctl --user -t nautilus-foldersize -f
```

The same tag is used for debug output:

```sh
NAUTILUS_FOLDERSIZE_DEBUG=1 nautilus
```

For a bug report, run the bundled doctor script and include its output:

```sh
./scripts/doctor.sh
```

## How it works

The extension runs inside the Nautilus process through `nautilus-python`.

- **Column:** implements `Nautilus.ColumnProvider` and
  `Nautilus.InfoProvider`, adding the private `folder_size` attribute.
- **Pill:** finds widgets with the `floating-bar` CSS class, picks the
  parenthesis-shaped details label, and watches `notify::label`. The label is
  located by class and text shape, not by a fixed widget hierarchy.
- **Paths:** read from the live `NautilusFilesView` selection model
  (`NautilusViewModel` → `Gtk.TreeListRow` → `NautilusViewItem.file`). The
  quoted name in the bar is only a fallback for single selections.
- **Work:** a bounded daemon-thread pool runs `du`, falling back to a
  stdlib walker. Results are marshalled back with `GLib.idle_add()`.
- **Coalescing:** rapid selection changes bump a token, so stale results are
  discarded; same-text selections are caught by listening to
  `selection-changed`.

More detail: [`docs/architecture.md`](docs/architecture.md).

## Troubleshooting

**No size appears in the pill**

1. Check the journal with `journalctl --user -t nautilus-foldersize -n 100`.
2. Confirm the extension is installed:
   `${XDG_DATA_HOME:-~/.local/share}/nautilus-python/extensions/foldersize.py`.
3. Restart Nautilus: `nautilus -q`.
4. Make sure a folder, not a file, is selected.
5. On a future Nautilus release, the bar may have changed. The column should
   still work; see the warning in the journal.

**The Folder Size column is blank**

- Enable it in **Visible Columns**; it is intentionally not computed while
  hidden.
- Large folders may take a few seconds to appear.
- Non-folder rows have no value.

**The extension does not load**

Install the bindings and confirm the API is visible:

```sh
python3 -c "import gi; gi.require_version('Nautilus', '4.1')"
sudo apt install python3-nautilus
```

On Ubuntu 24.04 the typelib is `Nautilus-4.0`; the extension falls back to it
automatically.

**Sizes differ from `du -sh`**

`du -sh` reports disk allocation in binary units, while this extension reports
apparent byte size in decimal units. The values are expected to differ.

More: [`docs/troubleshooting.md`](docs/troubleshooting.md).

## Development

The unit suite is headless and uses a small fake `gi` layer, so it does not need
GTK, Nautilus, or a display:

```sh
python3 -m pip install pytest ruff
python3 -m pytest -q
ruff check .
ruff format --check .
```

or:

```sh
make check
```

Useful targets:

| Target | Purpose |
| --- | --- |
| `make test` | Run the unit tests |
| `make lint` | Ruff lint + formatting check |
| `make format` | Apply Ruff formatting and safe fixes |
| `make check` | Lint + tests |
| `make install` | Per-user install from this checkout |
| `make doctor` | Print environment diagnostics |
| `make release` | Build a release tarball in `dist/` |

Live testing with a real Nautilus session:

```sh
./install.sh
journalctl --user -t nautilus-foldersize -f
```

The manual live-test checklist is in [`CONTRIBUTING.md`](CONTRIBUTING.md).
Please do not include personal paths, caches, or journal dumps with secrets in
issues.

## Uninstall

```sh
./uninstall.sh            # remove the extension
./uninstall.sh --purge    # also remove cache and configuration
./uninstall.sh --dry-run  # show what would be removed
```

## Contributing

Contributions are welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) and the
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). For security issues, follow
[`SECURITY.md`](SECURITY.md) instead of opening a public issue.

## License

GPL-3.0-or-later. See [`LICENSE`](LICENSE).
