# Architecture

This document explains how the extension fits into Nautilus and where the
important invariants live. It is aimed at contributors changing
`foldersize.py`.

## Process model

`nautilus-python` imports `foldersize.py` inside every Nautilus process that
loads user extensions. The module is imported once; `ensure_started()` creates
a process-wide `Core` object lazily when either provider is instantiated.

```text
Nautilus process
├── Gtk main loop
│   ├── FolderSizeColumnProvider (official extension API)
│   ├── FolderSizeInfoProvider   (official extension API)
│   └── PillWatcher              (experimental, optional)
│       └── BarState per floating bar
│           ├── label watcher (notify::label)
│           └── selection watcher (selection-changed)
└── SizeService
    ├── daemon worker threads
    ├── in-memory cache
    └── SQLite cache
```

The GTK main loop is never allowed to block. All scanning runs on daemon
threads. Results are delivered with `GLib.idle_add()`.

## Nautilus API compatibility

The module requests the `Nautilus-4.1` typelib first and falls back to
`Nautilus-4.0`:

```python
for candidate in ("4.1", "4.0"):
    gi.require_version("Nautilus", candidate)
```

Ubuntu 26.04 ships Nautilus 50 with the 4.1 typelib; Ubuntu 24.04 ships
Nautilus 46 with 4.0. The Python surface used here is the same on both:
`ColumnProvider`, `InfoProvider`, and `Column`.

`Nautilus.LocationWidgetProvider` no longer exists in the 4.x Python API.
The extension deliberately does not use it. The floating bar is found in the
GTK widget tree instead, and the files view is reached from the bar's ancestors
and from the `location` property.

## Folder Size column

`FolderSizeColumnProvider.get_columns()` declares:

```text
name      NautilusPython::folder_size_column
attribute folder_size
label     Folder Size
```

`FolderSizeInfoProvider.update_file_info()` fills that attribute:

1. Reject non-directories and non-`file://` URIs.
2. Serve a fresh cache value immediately.
3. If work is needed, check that a `Gtk.ColumnView` in a mapped files view
   currently shows the `Folder Size` column. This avoids scanning every folder
   in every directory when the column is hidden.
4. Queue one request per path, keep the `Nautilus.FileInfo` as a waiter, and
   call `invalidate_extension_info()` when the value is ready.

Visibility detection is intentionally forgiving: if a future Nautilus makes
the widget introspection fail, `column_is_visible()` returns `True` rather
than showing a permanently blank column.

## Selection paths

The primary source of truth is the in-process selection model:

```text
NautilusFilesView
└── Gtk.GridView / Gtk.ColumnView / Gtk.ListView
    └── Gtk.SelectionModel
        └── Gtk.TreeListRow
            └── NautilusViewItem.file  (NautilusVFSFile / Nautilus.FileInfo)
```

`read_selection()` returns a dictionary with `ok`, `count`, `all_dirs`,
`all_local`, `paths`, `names`, and `too_many`. The pill is updated only when:

- the selection model was readable;
- at least one item is selected;
- every item is a directory;
- every item has a local absolute path;
- the selection is under the safety limit (2000 items).

Otherwise the previous suffix is removed and the label is left as Nautilus
wrote it.

If the model cannot be read, the code falls back to parsing the quoted name
from the primary label and joining it to the view's `location`. That fallback
is trusted only when the details text contains `containing` (folder details),
and it never runs for names containing `/`.

## Floating-bar detection

Nautilus' floating bar is a `NautilusFloatingBar` with the GTK CSS class
`floating-bar`. The extension:

1. iterates `Gtk.Window.get_toplevels()` and all descendant widgets;
2. matches the CSS class `floating-bar` (or a `FloatingBar` GType as a
   fallback);
3. finds the ancestor `NautilusFilesView`;
4. collects descendant `Gtk.Label`s and selects the parenthesis-shaped details
   label.

Label order is only a tie-breaker. The code does not depend on a fixed
container hierarchy, which makes it resilient to GTK layout changes.

If no bar is found while a Nautilus files view exists, a 15-second grace period
starts. After that, the pill subsystem logs one warning and disables itself.
The official column is unaffected. A Nautilus process restart re-arms it.

## Feedback-loop avoidance

Writing the details label triggers `notify::label`, which could schedule another
pass forever. Three mechanisms prevent that:

- `_set_detail()` sets `self.applying = True` around `set_text()`; the notify
  handler returns early while that flag is set.
- `last_base` / `last_applied` remember exactly what was written.
- `_strip_size_suffix()` recognizes our own `", <size>)"` suffix after a
  restart or if the in-memory state was lost.

`_OWN_SUFFIX_RE` accepts locale spaces (narrow no-break space, no-break space,
thin space) because `GLib.format_size()` is locale-aware.

## Background service and cache

`SizeService` owns a bounded `queue.Queue` and 1–4 daemon threads. Requests with
the same ordered path tuple are coalesced. A token per `BarState` discards stale
results when the selection changes quickly.

`_compute_one()` validates the path with `lstat`:

- symlink → rejected;
- not a directory → rejected;
- unreadable → rejected;
- remote / pseudo filesystem → rejected.

It then checks the SQLite-backed cache. Entries are keyed by absolute path and
store the folder `mtime_ns`, the computed size, the computation time, and an
error string. Fresh values are served for `TTL` seconds (300 by default).
Expired values are revalidated in the background, so the UI keeps showing the
old size while a new scan runs.

`du -sb --apparent-size -x -- <path>` is the primary scanner. If `du` is
missing, fails, or exits with a partial result, the built-in walker is used.
The walker intentionally matches `du --apparent-size` semantics:

- directory inode sizes are not added;
- symlink lengths are added, but symlink targets are never followed;
- hard-linked regular files are counted once;
- unreadable directories are skipped;
- the deadline is enforced between entries.

The cache lives under `${XDG_CACHE_HOME:-~/.cache}/nautilus-foldersize/`. Its
SQLite connection uses WAL mode and a 5-second busy timeout. Database failures
degrade to the in-memory cache; they never break the extension.

`Gio.FileMonitor` watches selected folders. Directory events are debounced
(1.5–3.5 seconds, with a short post-creation grace period) and then invalidate
the cache entry and reschedule the pill. Only the 16 most recently used
monitors are kept.

## Failure isolation

Every GTK callback is wrapped by `@safe(context)`. `log_exception()` is
rate-limited per context and message so a broken callback cannot flood the
journal. The pill and the column start independently: a failure in
`PillWatcher` leaves `Core.column_provider` usable.

The kill switch is evaluated once at startup:

1. `NAUTILUS_FOLDERSIZE_NO_PILL`
2. `NAUTILUS_FOLDERSIZE_DISABLE_PILL`
3. `{"pill": false}` (or `enable_pill` / `pill_enabled`) in `config.json`

Any of them disables only the watcher. The column providers still start.

## Privacy

The extension:

- reads directory entries and metadata to compute sizes;
- does not open or upload file contents;
- makes no network requests;
- has no telemetry;
- stores only absolute paths, sizes, mtimes, timestamps, and error tags in the
  local cache.

## Invariants

Changes must preserve these:

1. Never block the GTK main loop. Scan only in workers.
2. Apply all UI changes on the main loop (`GLib.idle_add`).
3. Every callback is exception-guarded; never raise into Nautilus.
4. Do not follow symlinks during scans.
5. Do not scan remote/pseudo filesystems.
6. Do not patch or rebuild Nautilus; install per user only.
7. No hardcoded home directories, usernames, or machine-specific paths.
8. The pill is optional; the official column must keep working if it fails.
9. Keep the extension importable on both `Nautilus-4.0` and `Nautilus-4.1`.
10. New logic needs a headless test in `tests/`.
