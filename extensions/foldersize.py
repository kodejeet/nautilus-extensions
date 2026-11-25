# SPDX-FileCopyrightText: 2026 Nautilus Folder Size contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Nautilus Folder Size — show selected folder sizes in Nautilus.

The extension runs inside the Nautilus process (nautilus-python) and:
  * appends ", 4.7 GB" to the details label of Nautilus' floating selection
    bar ("(containing 8 items)" -> "(containing 8 items, 4.7 GB)"),
  * provides an official Nautilus.ColumnProvider "Folder Size" column.

All size work is done in background daemon threads.  Results are applied on
the GTK main loop with GLib.idle_add().  Every callback is guarded: an
exception in this file is logged and can never propagate into Nautilus.

Kill switch (pill only):
    NAUTILUS_FOLDERSIZE_NO_PILL=1
or  ~/.config/nautilus-foldersize/config.json:  {"pill": false}
The "Folder Size" column keeps working when the pill is disabled.

Logs:
    journalctl --user -t nautilus-foldersize -f
"""

import functools
import json
import os
import queue
import re
import shutil
import sqlite3
import stat as statmod
import subprocess
import sys
import syslog
import threading
import time
import traceback
from collections import OrderedDict

# ---------------------------------------------------------------------------
# Logging (initialize before anything that may fail)
# ---------------------------------------------------------------------------

APP = "nautilus-foldersize"
__version__ = "0.1.0"


def _env_truthy(name, environ=None):
    environ = os.environ if environ is None else environ
    value = environ.get(name)
    if value is None:
        return False
    return value.strip().lower() not in ("", "0", "false", "no", "off")


def _init_syslog():
    try:
        syslog.openlog(APP, syslog.LOG_PID | syslog.LOG_NDELAY, syslog.LOG_USER)
    except Exception:
        pass


_init_syslog()
_DEBUG = _env_truthy("NAUTILUS_FOLDERSIZE_DEBUG")
_last_exception_log = {}
_last_exception_lock = threading.Lock()


def log(message, level=syslog.LOG_INFO):
    try:
        if level == syslog.LOG_DEBUG and not _DEBUG:
            return
        syslog.syslog(level, str(message))
        if _DEBUG:
            print("[%s] %s" % (APP, message), file=sys.stderr, flush=True)
    except Exception:
        pass


def log_exception(context):
    """Log an exception, rate-limited so a hot callback cannot flood the journal."""
    try:
        tb = traceback.format_exc()
        key = context + "|" + (tb.splitlines()[-1] if tb else "")
        now = time.monotonic()
        with _last_exception_lock:
            if now - _last_exception_log.get(key, 0.0) < 60.0:
                return
            _last_exception_log[key] = now
        log("%s: %s" % (context, tb), syslog.LOG_WARNING)
    except Exception:
        pass


def safe(context):
    """Decorator: every callback is wrapped in try/except."""

    def decorate(function):
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except Exception:
                log_exception(context)
                return None

        return wrapper

    return decorate


# ---------------------------------------------------------------------------
# Imports and constants
# ---------------------------------------------------------------------------

try:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gio, GLib, GObject, Gtk

    NAUTILUS_API = None
    Nautilus = None
    for _candidate in ("4.1", "4.0"):
        try:
            gi.require_version("Nautilus", _candidate)
            from gi.repository import Nautilus

            NAUTILUS_API = _candidate
            break
        except (ValueError, ImportError):
            continue
    if Nautilus is None:
        raise ImportError(
            "Nautilus 4.x typelib not found (install python3-nautilus / nautilus-python)"
        )
except Exception as _import_error:
    try:
        print(
            "[%s] cannot load Nautilus 4.x API: %r" % (APP, _import_error),
            file=sys.stderr,
            flush=True,
        )
    except Exception:
        pass
    raise


def _float_env(name, default, minimum, maximum):
    try:
        value = float(os.environ.get(name, default))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


TTL = _float_env("NAUTILUS_FOLDERSIZE_TTL", 300.0, 5.0, 86400.0)
ERROR_TTL = _float_env("NAUTILUS_FOLDERSIZE_ERROR_TTL", 60.0, 5.0, 3600.0)
DU_TIMEOUT = _float_env("NAUTILUS_FOLDERSIZE_DU_TIMEOUT", 60.0, 1.0, 900.0)
MAX_WORKERS = int(_float_env("NAUTILUS_FOLDERSIZE_WORKERS", 2, 1, 4))
MAX_SELECTION = 2000
MAX_COLUMN_PENDING = 128
MAX_MONITORS = 16
DB_VERSION = 1

CACHE_DIR = os.path.join(GLib.get_user_cache_dir(), APP)
CACHE_DB = os.path.join(CACHE_DIR, "sizes.sqlite3")
CONFIG_PATH = os.path.join(GLib.get_user_config_dir(), APP, "config.json")

_QUOTE_OPEN = "\u201c"  # “
_QUOTE_CLOSE = "\u201d"  # ”
# Our own suffix: ", 4.7 GB" (GLib uses locale digits / a narrow no-break space).
_OWN_SUFFIX_RE = re.compile(
    r"^(.*),\s+[0-9][0-9.,\u00a0\u202f\u2009 ]*\s*"
    r"(?:bytes?|[kMGTPE]i?B|[kMGTPE]B)\)$",
    re.DOTALL,
)


def _strip_size_suffix(text):
    """Reverse our own ", <size>)" suffix, restoring the closing parenthesis."""
    match = _OWN_SUFFIX_RE.match(text)
    if not match:
        return text
    base = match.group(1)
    if not base.endswith(")"):
        base += ")"
    return base


_REMOTE_FS_TYPES = {
    "nfs",
    "nfs4",
    "cifs",
    "smb3",
    "smbfs",
    "afs",
    "9p",
    "ceph",
    "sshfs",
    "fuse.sshfs",
    "davfs",
    "webdav",
    "gvfs",
    "fuse.gvfsd-fuse",
    "fuse.gvfs-fuse-daemon",
}
_UNSUPPORTED_FS_TYPES = {
    "proc",
    "sysfs",
    "devtmpfs",
    "devpts",
    "debugfs",
    "tracefs",
    "securityfs",
    "cgroup",
    "cgroup2",
    "autofs",
}

# ---------------------------------------------------------------------------
# Configuration / kill switch
# ---------------------------------------------------------------------------


def _load_config(path=None):
    path = path or CONFIG_PATH
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
        log("config is not a JSON object; ignoring", syslog.LOG_WARNING)
    except FileNotFoundError:
        pass
    except Exception:
        log_exception("reading config %s" % path)
    return {}


_CONFIG = _load_config()


def pill_enabled(config=None, environ=None):
    """Pill kill switch: environment first, then config.json."""
    try:
        environ = os.environ if environ is None else environ
        config = _CONFIG if config is None else config
        for name in (
            "NAUTILUS_FOLDERSIZE_NO_PILL",
            "NAUTILUS_FOLDERSIZE_DISABLE_PILL",
        ):
            if name in environ:
                return not _env_truthy(name, environ)
        for key in ("pill", "enable_pill", "pill_enabled"):
            if key in config:
                return bool(config[key])
    except Exception:
        log_exception("pill_enabled")
    return True


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def normalize_path(path):
    try:
        if not isinstance(path, str) or not path or "\x00" in path:
            return None
        if not os.path.isabs(path):
            return None
        return os.path.normpath(path)
    except Exception:
        return None


def format_bytes(size):
    try:
        return GLib.format_size(int(size))
    except Exception:
        log_exception("GLib.format_size")
        return None


def _is_remote_or_unsupported(path):
    """Return True for remote / pseudo mounts we deliberately do not scan."""
    try:
        runtime = GLib.get_user_runtime_dir()
        if runtime and path.startswith(runtime.rstrip("/") + "/gvfs/"):
            return True
        query = Gio.File.new_for_path(path)
        info = query.query_filesystem_info("filesystem::remote,filesystem::type", None)
        if info is None:
            return False
        if info.get_attribute_boolean("filesystem::remote"):
            return True
        fs_type = (info.get_attribute_string("filesystem::type") or "").lower()
        if not fs_type:
            return False
        if fs_type in _REMOTE_FS_TYPES or fs_type in _UNSUPPORTED_FS_TYPES:
            return True
        if fs_type.startswith("fuse.sshfs") or fs_type.startswith("fuse.gvfs"):
            return True
    except Exception:
        return False
    return False


def _du_size(path, timeout):
    """Run du in a worker thread.  Returns (size, note, timed_out)."""
    executable = shutil.which("du")
    if executable is None:
        return None, "du-not-found", False
    environment = dict(os.environ)
    environment["LC_ALL"] = "C"
    environment["LANG"] = "C"
    command = [executable, "-sb", "--apparent-size", "-x", "--", path]
    started = time.monotonic()
    try:
        process = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=environment,
            close_fds=True,
        )
    except subprocess.TimeoutExpired:
        return None, "timeout", True
    except FileNotFoundError:
        return None, "du-not-found", False
    except Exception:
        log_exception("running du for %s" % path)
        return None, "du-error", False

    output = process.stdout or b""
    size = None
    if output:
        first_line = output.split(b"\n", 1)[0]
        if b"\t" in first_line:
            number = first_line.split(b"\t", 1)[0]
        else:
            parts = first_line.split(None, 1)
            number = parts[0] if parts else b""
        try:
            size = int(number)
        except Exception:
            size = None

    stderr = (process.stderr or b"").lower()
    denied = b"permission denied" in stderr
    elapsed = time.monotonic() - started
    if size is not None:
        if process.returncode != 0:
            # Partial result due to unreadable subfolders is still useful.
            log(
                "du warning for %s (rc=%d, %.2fs): partial result accepted"
                % (path, process.returncode, elapsed),
                syslog.LOG_DEBUG,
            )
        else:
            log("du %s -> %d in %.2fs" % (path, size, elapsed), syslog.LOG_DEBUG)
        return size, ("partial-permission" if denied else None), False
    return None, ("permission-denied" if denied else "du-failed"), False


def _walk_size(path, deadline):
    """Recursive apparent-size walker used if du is unavailable/failed.

    Does not follow symlinks; skips unreadable subdirectories; counts hard
    links once.  Raises TimeoutError at the deadline.
    """
    total = 0
    seen_inodes = set()
    stack = [path]
    while stack:
        if time.monotonic() > deadline:
            raise TimeoutError()
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if time.monotonic() > deadline:
                        raise TimeoutError()
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except (PermissionError, FileNotFoundError, OSError):
                        continue
                    if statmod.S_ISDIR(st.st_mode):
                        stack.append(entry.path)
                        continue
                    # Match du --apparent-size: count file and symlink lstat
                    # sizes, but not the directory inode itself. Symlinks are
                    # counted by their own length and never followed.
                    if statmod.S_ISREG(st.st_mode) and st.st_nlink > 1:
                        key = (st.st_dev, st.st_ino)
                        if key in seen_inodes:
                            continue
                        seen_inodes.add(key)
                    total += st.st_size
        except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
            continue
    return total


# ---------------------------------------------------------------------------
# Persistent + in-memory cache
# ---------------------------------------------------------------------------


class CacheEntry(object):
    __slots__ = ("computed_at", "error", "mtime_ns", "size")

    def __init__(self, size, mtime_ns, computed_at, error=None):
        self.size = size
        self.mtime_ns = mtime_ns
        self.computed_at = computed_at
        self.error = error


class Cache(object):
    def __init__(self, db_path):
        self._db_path = db_path
        self._mem = {}
        self._mem_lock = threading.RLock()
        self._db = None
        self._db_lock = threading.RLock()
        self._db_failed = False
        self._schema_ready = False
        try:
            os.makedirs(os.path.dirname(db_path), mode=0o700, exist_ok=True)
        except Exception:
            log_exception("creating cache directory")

    def _connect_locked(self):
        if self._db_failed:
            return None
        if self._db is not None:
            return self._db
        try:
            connection = sqlite3.connect(self._db_path, timeout=5.0, check_same_thread=False)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA busy_timeout=5000")
            if not self._schema_ready:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS folder_sizes (
                        path TEXT PRIMARY KEY,
                        size INTEGER,
                        mtime_ns INTEGER,
                        computed_at REAL NOT NULL,
                        error TEXT
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS folder_sizes_computed ON folder_sizes(computed_at)"
                )
                connection.commit()
                self._schema_ready = True
            self._db = connection
            return connection
        except Exception:
            self._db_failed = True
            log_exception("opening cache database %s" % self._db_path)
            return None

    def load_all(self):
        try:
            with self._db_lock:
                connection = self._connect_locked()
                if connection is None:
                    return
                rows = connection.execute(
                    "SELECT path, size, mtime_ns, computed_at, error FROM folder_sizes"
                ).fetchall()
            with self._mem_lock:
                for path, size, mtime_ns, computed_at, error in rows:
                    if path and path not in self._mem:
                        self._mem[path] = CacheEntry(size, mtime_ns, computed_at, error)
            log("cache loaded: %d entries" % len(rows), syslog.LOG_DEBUG)
        except Exception:
            log_exception("loading cache")

    def get(self, path):
        try:
            with self._mem_lock:
                return self._mem.get(path)
        except Exception:
            return None

    def get_persistent(self, path):
        entry = self.get(path)
        if entry is not None:
            return entry
        try:
            with self._db_lock:
                connection = self._connect_locked()
                if connection is None:
                    return None
                row = connection.execute(
                    "SELECT size, mtime_ns, computed_at, error FROM folder_sizes WHERE path = ?",
                    (path,),
                ).fetchone()
            if row is None:
                return None
            entry = CacheEntry(row[0], row[1], row[2], row[3])
            with self._mem_lock:
                self._mem.setdefault(path, entry)
            return entry
        except Exception:
            log_exception("reading cache row")
            return None

    def put(self, path, entry):
        try:
            with self._mem_lock:
                self._mem[path] = entry
        except Exception:
            pass
        try:
            with self._db_lock:
                connection = self._connect_locked()
                if connection is None:
                    return
                connection.execute(
                    "INSERT INTO folder_sizes "
                    "(path, size, mtime_ns, computed_at, error) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(path) DO UPDATE SET "
                    "size=excluded.size, mtime_ns=excluded.mtime_ns, "
                    "computed_at=excluded.computed_at, error=excluded.error",
                    (path, entry.size, entry.mtime_ns, entry.computed_at, entry.error),
                )
                connection.commit()
        except Exception:
            log_exception("writing cache row")

    def drop_memory(self, path):
        try:
            with self._mem_lock:
                self._mem.pop(path, None)
        except Exception:
            pass

    def delete_persistent(self, path):
        try:
            with self._db_lock:
                connection = self._connect_locked()
                if connection is None:
                    return
                connection.execute("DELETE FROM folder_sizes WHERE path = ?", (path,))
                connection.commit()
        except Exception:
            log_exception("deleting cache row")


# ---------------------------------------------------------------------------
# Background size service
# ---------------------------------------------------------------------------


class SizeResult(object):
    __slots__ = ("errors", "paths", "sizes", "total")

    def __init__(self, paths, sizes, errors, total):
        self.paths = paths
        self.sizes = sizes
        self.errors = errors
        self.total = total


class SizeService(object):
    def __init__(self, cache):
        self.cache = cache
        self._queue = queue.Queue()
        self._inflight = {}
        self._lock = threading.RLock()
        self._queue.put(("load", None))
        for index in range(MAX_WORKERS):
            thread = threading.Thread(
                target=self._worker,
                name="foldersize-%d" % index,
                daemon=True,
            )
            thread.start()

    def lookup_sum(self, paths):
        """Immediate in-memory sum; None unless every path has a known size."""
        try:
            total = 0
            for path in paths:
                entry = self.cache.get(path)
                if entry is None or entry.size is None:
                    return None
                total += entry.size
            return total if paths else None
        except Exception:
            log_exception("lookup_sum")
            return None

    def request(self, paths, callback):
        """Validate/recompute paths in a worker; callback(result) on the main loop."""
        try:
            unique = tuple(dict.fromkeys(p for p in paths if p))
            if not unique:
                return
            key = unique
            with self._lock:
                if key in self._inflight:
                    self._inflight[key].append(callback)
                    return
                self._inflight[key] = [callback]
            self._queue.put(("compute", key))
        except Exception:
            log_exception("request")

    def invalidate(self, path):
        try:
            path = normalize_path(path)
            if path is None:
                return
            self.cache.drop_memory(path)
            self._queue.put(("invalidate", path))
        except Exception:
            log_exception("invalidate")

    def _worker(self):
        while True:
            try:
                item = self._queue.get()
                if item is None:
                    continue
                kind, payload = item
                if kind == "load":
                    self.cache.load_all()
                    continue
                if kind == "invalidate":
                    self.cache.delete_persistent(payload)
                    continue
                if kind == "compute":
                    try:
                        result = self._compute(payload)
                    except Exception:
                        log_exception("compute %r" % (payload,))
                        result = SizeResult(
                            payload,
                            {path: None for path in payload},
                            {path: "internal-error" for path in payload},
                            None,
                        )
                    with self._lock:
                        callbacks = self._inflight.pop(payload, [])
                    for callback in callbacks:
                        try:
                            GLib.idle_add(self._run_callback, callback, result)
                        except Exception:
                            log_exception("scheduling size callback")
            except Exception:
                log_exception("size worker")

    @staticmethod
    def _run_callback(callback, result):
        try:
            callback(result)
        except Exception:
            log_exception("size callback")
        return False

    def _compute(self, paths):
        sizes = {}
        errors = {}
        for path in paths:
            try:
                size, error = self._compute_one(path)
            except Exception:
                log_exception("compute_one %s" % path)
                size, error = None, "internal-error"
            sizes[path] = size
            errors[path] = error
        total = None
        if sizes and all(value is not None for value in sizes.values()):
            total = sum(sizes.values())
        return SizeResult(paths, sizes, errors, total)

    def _compute_one(self, path):
        path = normalize_path(path)
        if path is None:
            return None, "invalid-path"
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            return None, "missing"
        except PermissionError:
            return None, "permission"
        except Exception:
            log_exception("lstat %s" % path)
            return None, "stat-error"

        if statmod.S_ISLNK(st.st_mode):
            return None, "symlink"
        if not statmod.S_ISDIR(st.st_mode):
            return None, "not-directory"
        if not os.access(path, os.R_OK | os.X_OK):
            return None, "permission"
        if _is_remote_or_unsupported(path):
            return None, "remote"

        now = time.time()
        mtime_ns = st.st_mtime_ns
        entry = self.cache.get_persistent(path)
        if entry is not None and entry.mtime_ns == mtime_ns:
            if entry.size is not None and now <= entry.computed_at + TTL:
                log(
                    "cache hit %s size=%s age=%.1fs" % (path, entry.size, now - entry.computed_at),
                    syslog.LOG_DEBUG,
                )
                return entry.size, None
            if entry.size is None and now <= entry.computed_at + ERROR_TTL:
                log(
                    "cache error hit %s (%s)" % (path, entry.error),
                    syslog.LOG_DEBUG,
                )
                return None, entry.error

        size, note, timed_out = _du_size(path, DU_TIMEOUT)
        if size is None and not timed_out:
            try:
                size = _walk_size(path, time.monotonic() + DU_TIMEOUT)
                note = "walker"
                log("walker %s -> %d" % (path, size), syslog.LOG_DEBUG)
            except TimeoutError:
                note = "timeout"
            except PermissionError:
                note = "permission"
            except Exception:
                log_exception("walker %s" % path)
                note = note or "walk-error"

        if size is not None:
            self.cache.put(path, CacheEntry(size, mtime_ns, time.time(), None))
            return size, None
        error = note or "unknown"
        self.cache.put(path, CacheEntry(None, mtime_ns, time.time(), error))
        log("size unavailable for %s: %s" % (path, error), syslog.LOG_DEBUG)
        return None, error


# ---------------------------------------------------------------------------
# Widget-tree helpers (pill location)
# ---------------------------------------------------------------------------


def _iter_widgets(root, max_depth=200):
    stack = [(root, 0)]
    while stack:
        widget, depth = stack.pop()
        yield widget
        if depth >= max_depth:
            continue
        try:
            child = widget.get_first_child()
        except Exception:
            continue
        while child is not None:
            stack.append((child, depth + 1))
            try:
                child = child.get_next_sibling()
            except Exception:
                break


def _is_floating_bar(widget):
    try:
        if "floating-bar" in widget.get_css_classes():
            return True
    except Exception:
        pass
    try:
        return "FloatingBar" in widget.__gtype__.name
    except Exception:
        return False


def _find_bars(root):
    return [widget for widget in _iter_widgets(root) if _is_floating_bar(widget)]


def _find_files_view(widget):
    """Find the NautilusFilesView ancestor of a widget (property based fallback)."""
    try:
        parent = widget.get_parent()
    except Exception:
        return None
    depth = 0
    while parent is not None and depth < 30:
        try:
            if parent.__gtype__.name == "NautilusFilesView":
                return parent
        except Exception:
            pass
        try:
            names = {prop.name for prop in parent.list_properties()}
            if "location" in names and "selection" in names:
                return parent
        except Exception:
            pass
        try:
            parent = parent.get_parent()
        except Exception:
            return None
        depth += 1
    return None


def _find_files_views_in_window(window):
    found = []
    try:
        for widget in _iter_widgets(window):
            try:
                if widget.__gtype__.name == "NautilusFilesView":
                    found.append(widget)
            except Exception:
                pass
        if found:
            return found
        # Property-based fallback for a future renamed type.
        for widget in _iter_widgets(window):
            try:
                names = {prop.name for prop in widget.list_properties()}
                if "location" in names and "selection" in names:
                    found.append(widget)
            except Exception:
                pass
    except Exception:
        log_exception("find files views")
    return found


def _find_files_view_in_window(window):
    views = _find_files_views_in_window(window)
    return views[0] if views else None


def _find_selection_widgets(files_view):
    found = []
    stack = [(files_view, 0)]
    while stack:
        widget, depth = stack.pop()
        if depth > 60:
            continue
        try:
            if isinstance(widget, (Gtk.GridView, Gtk.ColumnView)):
                found.append(widget)
                continue
            if isinstance(widget, Gtk.ListView):
                found.append(widget)
                continue
        except Exception:
            pass
        try:
            child = widget.get_first_child()
        except Exception:
            continue
        while child is not None:
            stack.append((child, depth + 1))
            try:
                child = child.get_next_sibling()
            except Exception:
                break
    return found


def _pick_selection_widget(files_view):
    candidates = _find_selection_widgets(files_view)
    for widget in candidates:
        try:
            if widget.get_mapped():
                return widget
        except Exception:
            pass
    for widget in candidates:
        try:
            if widget.get_visible():
                return widget
        except Exception:
            pass
    return candidates[0] if candidates else None


def _find_column_views(files_view):
    found = []
    for widget in _iter_widgets(files_view):
        try:
            if isinstance(widget, Gtk.ColumnView):
                found.append(widget)
        except Exception:
            pass
    return found


def _find_column_view(files_view):
    views = _find_column_views(files_view)
    return views[0] if views else None


def read_selection(files_view):
    """Read selected items through the view's Gtk.SelectionModel.

    Returns dict(ok, count, all_dirs, all_local, paths, names, too_many).
    This uses Nautilus' in-process model; callers fall back to label parsing.
    """
    result = {
        "ok": False,
        "count": 0,
        "all_dirs": False,
        "all_local": False,
        "paths": [],
        "names": [],
        "too_many": False,
    }
    try:
        if files_view is None:
            return result
        selection_widget = _pick_selection_widget(files_view)
        if selection_widget is None:
            return result
        model = selection_widget.get_model()
        if model is None:
            return result
        get_selection = getattr(model, "get_selection", None)
        get_item = getattr(model, "get_item", None)
        if get_selection is None or get_item is None:
            return result
        bitset = get_selection()
        if bitset is None:
            return result
        count = int(bitset.get_size())
        result["count"] = count
        result["ok"] = True
        if count <= 0:
            return result
        if count > MAX_SELECTION:
            result["too_many"] = True
            return result

        all_dirs = True
        all_local = True
        for index in range(count):
            try:
                item_index = bitset.get_nth(index)
                row = get_item(item_index)
                item = row.get_item()
                file_info = item.get_property("file")
                name = file_info.get_name()
                is_dir = bool(file_info.is_directory())
                location = file_info.get_location()
                path = normalize_path(location.get_path() if location is not None else None)
            except Exception:
                log_exception("reading selected item")
                return {
                    "ok": False,
                    "count": 0,
                    "all_dirs": False,
                    "all_local": False,
                    "paths": [],
                    "names": [],
                    "too_many": False,
                }
            if not is_dir:
                all_dirs = False
            if path is None:
                all_local = False
            else:
                result["paths"].append(path)
                result["names"].append(name or "")
        result["all_dirs"] = all_dirs
        result["all_local"] = all_local
        return result
    except Exception:
        log_exception("read_selection")
        return result


def quoted_name(texts):
    for text in texts:
        try:
            match = re.search(_QUOTE_OPEN + r"(.+?)" + _QUOTE_CLOSE, text)
            if match:
                return match.group(1)
        except Exception:
            continue
    return None


def fallback_single_path(files_view, texts):
    """Resolve "“name” selected" by joining the view location and the name."""
    try:
        name = quoted_name(texts)
        if not name or "/" in name or "\x00" in name:
            return None
        if files_view is None:
            return None
        location = files_view.get_property("location")
        if location is None:
            return None
        parent = location.get_path()
        if not parent:
            return None
        return normalize_path(os.path.join(parent, name))
    except Exception:
        log_exception("fallback_single_path")
        return None


# ---------------------------------------------------------------------------
# Pill watcher
# ---------------------------------------------------------------------------


class BarState(object):
    def __init__(self, watcher, bar, files_view):
        self.watcher = watcher
        self.engine = watcher.engine
        self.bar = bar
        self.files_view = files_view
        self.labels = []
        self.idle_id = 0
        self.settle_id = 0
        self.applying = False
        self.token = 0
        self.dead = False
        self.last_base = None
        self.last_applied = None
        self.last_paths = ()
        self.last_size = None
        self.selection_model = None
        self.selection_handler = 0
        try:
            bar.connect("destroy", self._on_bar_destroy)
        except Exception:
            pass

    # -- signal callbacks -------------------------------------------------

    def attach_selection_model(self, files_view):
        """Listen to the Gtk.SelectionModel so same-text selection changes
        (e.g. two single selections with the same item count) are noticed."""
        try:
            widget = _pick_selection_widget(files_view)
            if widget is None:
                return
            model = widget.get_model()
            if model is None or model is self.selection_model:
                return
            self.detach_selection_model()
            self.selection_model = model
            self.selection_handler = model.connect("selection-changed", self._on_selection_changed)
        except Exception:
            log_exception("attach_selection_model")

    def detach_selection_model(self):
        try:
            if self.selection_model is not None and self.selection_handler:
                self.selection_model.disconnect(self.selection_handler)
        except Exception:
            pass
        self.selection_model = None
        self.selection_handler = 0

    @safe("pill selection changed")
    def _on_selection_changed(self, _model, _position, _n_items):
        if self.dead or self.applying:
            return
        log("pill selection changed", syslog.LOG_DEBUG)
        # Let Nautilus rewrite the labels first; this also coalesces the
        # primary/details label updates into a single process pass.
        try:
            if self.settle_id:
                GLib.source_remove(self.settle_id)
            self.settle_id = GLib.timeout_add(120, self._selection_settle)
        except Exception:
            log_exception("selection settle")
            self.schedule()

    def _selection_settle(self):
        self.settle_id = 0
        try:
            self.schedule()
        except Exception:
            log_exception("selection settle fire")
        return False

    def attach_labels(self, labels):
        added = False
        try:
            for label in labels:
                if any(existing is label for existing in self.labels):
                    continue
                self.labels.append(label)
                added = True
                try:
                    label.connect("notify::label", self._on_label_notify)
                    label.connect("destroy", self._on_label_destroy)
                except Exception:
                    log_exception("connecting pill label")
        except Exception:
            log_exception("attach_labels")
        return added

    @safe("pill label notify")
    def _on_label_notify(self, label, _pspec):
        if self.dead or self.applying:
            return
        log("pill label notify %r" % label.get_text(), syslog.LOG_DEBUG)
        self.schedule()

    @safe("pill label destroy")
    def _on_label_destroy(self, label):
        self.labels = [item for item in self.labels if item is not label]
        if not self.labels:
            self.watcher.drop_state(self)

    @safe("pill bar destroy")
    def _on_bar_destroy(self, _bar):
        self.watcher.drop_state(self)

    def schedule(self):
        try:
            if self.dead or self.idle_id:
                return
            if self.settle_id:
                try:
                    GLib.source_remove(self.settle_id)
                except Exception:
                    pass
                self.settle_id = 0
            self.idle_id = GLib.idle_add(self._process_idle)
        except Exception:
            log_exception("pill schedule")

    @safe("pill idle")
    def _process_idle(self):
        self.idle_id = 0
        self.process()
        return False

    def _live_labels(self):
        result = []
        for label in list(self.labels):
            try:
                result.append((label, label.get_text()))
            except Exception:
                continue
        return result

    def _strip_own(self, text):
        try:
            if self.last_applied is not None and text == self.last_applied:
                return self.last_base
            return _strip_size_suffix(text)
        except Exception:
            pass
        return text

    def _set_detail(self, label, text):
        try:
            current = label.get_text()
            if current == text:
                return
            self.applying = True
            try:
                label.set_text(text)
            finally:
                self.applying = False
        except Exception:
            log_exception("setting pill label")

    def _restore(self, label):
        try:
            current = label.get_text()
            if self.last_applied is not None and current == self.last_applied:
                self._set_detail(label, self.last_base)
                self.last_applied = None
                self.last_paths = ()
                self.last_size = None
                return
            # Generic safety net: remove ", <size>" if it is ours.
            stripped = self._strip_own(current)
            if stripped != current:
                self._set_detail(label, stripped)
                self.last_applied = None
                self.last_paths = ()
                self.last_size = None
        except Exception:
            log_exception("restoring pill label")

    def _apply(self, label, base, paths, size, token):
        try:
            if self.dead or token != self.token:
                return
            if size is None:
                return
            current = label.get_text()
            if current != base and not (
                self.last_applied is not None
                and current == self.last_applied
                and base == self.last_base
            ):
                return
            size_text = format_bytes(size)
            if not size_text or not base.endswith(")"):
                return
            new_text = base[:-1] + ", " + size_text + ")"
            if current == new_text:
                self.last_base = base
                self.last_applied = new_text
                self.last_paths = tuple(paths)
                self.last_size = size
                return
            self._set_detail(label, new_text)
            self.last_base = base
            self.last_applied = new_text
            self.last_paths = tuple(paths)
            self.last_size = size
            log(
                "pill size %s -> %s" % (", ".join(paths), size_text),
                syslog.LOG_DEBUG,
            )
        except Exception:
            log_exception("applying pill size")

    @safe("pill size result")
    def _on_size_result(self, token, base, paths, label, result):
        if self.dead or token != self.token:
            return
        try:
            if label is None:
                return
            if result is None or result.total is None:
                self._restore(label)
                return
            for path in result.paths:
                if result.sizes.get(path) is not None:
                    self.watcher.monitor_path(path)
            self._apply(label, base, paths, result.total, token)
        except Exception:
            log_exception("pill size result body")

    # -- main logic -------------------------------------------------------

    def process(self):
        try:
            self._process()
        except Exception:
            log_exception("pill process")

    def _process(self):
        if self.dead:
            return
        labels = self._live_labels()
        if not labels:
            return

        candidates = []
        for position, (label, text) in enumerate(labels):
            base = self._strip_own(text)
            if not base:
                continue
            stripped = base.strip()
            if (
                stripped.startswith("(")
                and stripped.endswith(")")
                and _QUOTE_OPEN not in stripped
                and _QUOTE_CLOSE not in stripped
            ):
                candidates.append((position, label, base))
        if not candidates:
            return
        # Details label is the later label; position is only a tie-breaker,
        # the bar itself was located by CSS class, not hierarchy position.
        candidates.sort(key=lambda item: item[0])
        _position, detail_label, base = candidates[-1]

        current = detail_label.get_text()
        if current != base and self.last_applied is not None and current == self.last_applied:
            # Our previous suffix is still visible; its base is the same text.
            base = self.last_base or base
        elif current == self.last_applied and base == self.last_base:
            pass

        files_view = self.files_view
        try:
            if files_view is None or files_view.__gtype__.name != "NautilusFilesView":
                files_view = _find_files_view(self.bar)
                self.files_view = files_view
        except Exception:
            files_view = None

        selection = read_selection(files_view)
        paths = []
        if selection.get("ok") and selection.get("count", 0) > 0:
            if selection.get("too_many"):
                self._restore(detail_label)
                return
            if not selection.get("all_dirs") or not selection.get("all_local"):
                self._restore(detail_label)
                return
            paths = list(selection.get("paths") or [])
            if len(paths) != selection.get("count"):
                self._restore(detail_label)
                return
        else:
            # Fallback: parse the quoted name from the primary label.  Only
            # trust it when the details text says "containing" (folder
            # details); the selection model above is the primary path.
            if "containing" not in base.lower():
                self._restore(detail_label)
                return
            path = fallback_single_path(files_view, [text for _, text in labels])
            if path is None:
                self._restore(detail_label)
                return
            paths = [path]

        paths = tuple(dict.fromkeys(paths))
        if not paths:
            self._restore(detail_label)
            return

        if tuple(paths) != self.last_paths:
            # Selection changed but Nautilus may not have rewritten the
            # details label (same item count).  Remove the old size now.
            if self.last_applied is not None and detail_label.get_text() == self.last_applied:
                self._set_detail(detail_label, self.last_base or base)
                current = detail_label.get_text()
                base = current
            self.last_applied = None
            self.last_size = None

        self.token += 1
        token = self.token
        immediate = self.engine.lookup_sum(paths)
        if immediate is not None:
            self._apply(detail_label, base, paths, immediate, token)
        self.engine.request(
            paths,
            functools.partial(self._on_size_result, token, base, paths, detail_label),
        )


class PillWatcher(object):
    def __init__(self, engine):
        self.engine = engine
        self._states = {}
        self._started_at = time.monotonic()
        self._missing_since = None
        self._disabled = False
        self._warned = False
        self._reconcile_id = 0
        self._monitors = OrderedDict()
        self._monitor_started = {}
        self._monitor_timeouts = {}
        self._toplevels = Gtk.Window.get_toplevels()
        try:
            self._toplevels.connect("items-changed", self._on_toplevels_changed)
        except Exception:
            log_exception("connecting toplevels model")
        GLib.idle_add(self._scan_idle)
        self._reconcile_id = GLib.timeout_add_seconds(5, self._reconcile)

    @safe("toplevels changed")
    def _on_toplevels_changed(self, _model, _position, _removed, _added):
        if not self._disabled:
            GLib.idle_add(self._scan_idle)

    @safe("pill scan idle")
    def _scan_idle(self):
        self.scan()
        return False

    def _reconcile(self):
        # Never return None here: that would silently stop the periodic scan
        # after a transient exception.
        try:
            if self._disabled:
                return False
            self.scan()
        except Exception:
            log_exception("pill reconcile")
        return True

    def scan(self):
        if self._disabled:
            return
        found_bar = False
        try:
            toplevels = Gtk.Window.get_toplevels()
            for index in range(toplevels.get_n_items()):
                window = toplevels.get_item(index)
                if window is None:
                    continue
                for bar in _find_bars(window):
                    files_view = _find_files_view(bar)
                    if files_view is None:
                        continue
                    found_bar = True
                    state = self._states.get(id(bar))
                    new_state = state is None or state.dead
                    if new_state:
                        state = BarState(self, bar, files_view)
                        self._states[id(bar)] = state
                        log(
                            "pill attached: %s (css=%s)"
                            % (
                                bar.__gtype__.name,
                                ",".join(bar.get_css_classes()),
                            ),
                            syslog.LOG_INFO,
                        )
                    else:
                        state.files_view = files_view
                    labels = [
                        widget for widget in _iter_widgets(bar) if isinstance(widget, Gtk.Label)
                    ]
                    if labels:
                        added = state.attach_labels(labels)
                        if added or new_state:
                            # The label may already contain a selection made
                            # while we were attaching; process it now.
                            log(
                                "pill schedule (new=%s added=%s)" % (new_state, added),
                                syslog.LOG_DEBUG,
                            )
                            state.schedule()
                    state.attach_selection_model(files_view)

            # Drop states whose bar no longer exists.
            for key, state in list(self._states.items()):
                if state.dead:
                    self._states.pop(key, None)

            if found_bar:
                self._missing_since = None
                return

            # A Nautilus window exists but has no floating bar.  Wait for a
            # grace period; only then log once and disable the pill.  The
            # official column provider keeps working regardless.
            if not self._has_files_views():
                self._missing_since = None
                return
            now = time.monotonic()
            if self._missing_since is None:
                self._missing_since = now
                return
            if self._warned or now - self._missing_since < 15.0:
                return
            self._warned = True
            self._disabled = True
            if self._reconcile_id:
                try:
                    GLib.source_remove(self._reconcile_id)
                except Exception:
                    pass
                self._reconcile_id = 0
            log(
                "floating bar not found in this Nautilus version; "
                "pill feature disabled, Folder Size column remains",
                syslog.LOG_WARNING,
            )
        except Exception:
            log_exception("pill scan")

    def _has_files_views(self):
        try:
            toplevels = Gtk.Window.get_toplevels()
            for index in range(toplevels.get_n_items()):
                window = toplevels.get_item(index)
                if window is not None and _find_files_view_in_window(window) is not None:
                    return True
        except Exception:
            pass
        return False

    def drop_state(self, state):
        try:
            state.dead = True
            if state.idle_id:
                try:
                    GLib.source_remove(state.idle_id)
                except Exception:
                    pass
                state.idle_id = 0
            if state.settle_id:
                try:
                    GLib.source_remove(state.settle_id)
                except Exception:
                    pass
                state.settle_id = 0
            state.detach_selection_model()
            for key, existing in list(self._states.items()):
                if existing is state:
                    self._states.pop(key, None)
            state.labels = []
            state.bar = None
            state.files_view = None
        except Exception:
            log_exception("dropping pill state")

    # -- cache invalidation via Gio.FileMonitor ---------------------------

    def monitor_path(self, path):
        try:
            if not path or path == "/":
                return
            if path in self._monitors:
                self._monitors.move_to_end(path)
                return
            monitor = Gio.File.new_for_path(path).monitor_directory(Gio.FileMonitorFlags.NONE, None)
            if monitor is None:
                return
            monitor.connect("changed", self._on_monitor_changed, path)
            self._monitors[path] = monitor
            self._monitor_started[path] = time.monotonic()
            while len(self._monitors) > MAX_MONITORS:
                _old_path, old_monitor = self._monitors.popitem(last=False)
                self._monitor_started.pop(_old_path, None)
                try:
                    old_monitor.cancel()
                except Exception:
                    pass
            log("monitoring %s" % path, syslog.LOG_DEBUG)
        except Exception:
            log_exception("monitor_path %s" % path)

    @safe("file monitor changed")
    def _on_monitor_changed(self, _monitor, _file, _other, _event, path):
        try:
            # Give a newly created monitor a short grace period.  Initial
            # directory events can otherwise invalidate the size we have just
            # computed.  Events are delayed, not discarded.
            started = self._monitor_started.get(path, 0.0)
            remaining = 2.0 - (time.monotonic() - started)
            delay = 1500
            if remaining > 0:
                delay = int(remaining * 1000) + 1500
            existing = self._monitor_timeouts.pop(path, None)
            if existing:
                try:
                    GLib.source_remove(existing)
                except Exception:
                    pass
            self._monitor_timeouts[path] = GLib.timeout_add(
                delay, self._invalidate_after_change, path
            )
        except Exception:
            log_exception("monitor changed")

    @safe("monitor invalidate")
    def _invalidate_after_change(self, path):
        self._monitor_timeouts.pop(path, None)
        self.engine.invalidate(path)
        for state in list(self._states.values()):
            try:
                if path in state.last_paths:
                    state.schedule()
            except Exception:
                pass
        return False


# ---------------------------------------------------------------------------
# Extension core and providers
# ---------------------------------------------------------------------------

_core = None
_core_lock = threading.RLock()


class Core(object):
    def __init__(self):
        self.cache = Cache(CACHE_DB)
        self.engine = SizeService(self.cache)
        # A failure in the experimental pill path must never prevent the
        # official Folder Size column from working.
        self.watcher = None
        pill_requested = pill_enabled()
        if pill_requested:
            try:
                self.watcher = PillWatcher(self.engine)
            except Exception:
                log_exception("starting pill watcher")
                self.watcher = None
        self.column_pending = set()
        self.column_waiters = {}
        self.column_lock = threading.RLock()
        self.column_visible = False
        self.column_checked_at = 0.0
        if self.watcher is None:
            if pill_requested:
                log(
                    "pill watcher unavailable; Folder Size column remains",
                    syslog.LOG_WARNING,
                )
            else:
                log(
                    "pill disabled by kill switch; Folder Size column remains",
                    syslog.LOG_INFO,
                )

    def ensure(self):
        return self

    # -- column visibility (avoid computing the world) --------------------

    def column_is_visible(self):
        try:
            now = time.monotonic()
            if now - self.column_checked_at < 2.0:
                return self.column_visible
            self.column_checked_at = now
            visible = False
            toplevels = Gtk.Window.get_toplevels()
            for index in range(toplevels.get_n_items()):
                if visible:
                    break
                window = toplevels.get_item(index)
                if window is None:
                    continue
                for files_view in _find_files_views_in_window(window):
                    if visible:
                        break
                    for column_view in _find_column_views(files_view):
                        try:
                            if not column_view.get_mapped():
                                continue
                        except Exception:
                            pass
                        columns = column_view.get_columns()
                        if columns is None:
                            continue
                        for column_index in range(columns.get_n_items()):
                            column = columns.get_item(column_index)
                            try:
                                title = column.get_title() if column is not None else None
                            except Exception:
                                title = None
                            if title == "Folder Size":
                                visible = True
                                break
                        if visible:
                            break
            self.column_visible = visible
            return visible
        except Exception:
            log_exception("column_is_visible")
            # If detection fails in a future Nautilus, prefer a working
            # column over a silent blank one.
            self.column_visible = True
            return True

    def column_result(self, result):
        try:
            for path in result.paths:
                with self.column_lock:
                    self.column_pending.discard(path)
                    waiters = self.column_waiters.pop(path, [])
                entry = self.cache.get(path)
                if entry is None or entry.size is None:
                    continue
                for file_info in waiters:
                    try:
                        file_info.invalidate_extension_info()
                    except Exception:
                        pass
        except Exception:
            log_exception("column result")


def ensure_started():
    global _core
    with _core_lock:
        if _core is None:
            _core = Core()
            log(
                "started v%s (Nautilus API %s), cache=%s, pill=%s"
                % (
                    __version__,
                    NAUTILUS_API,
                    CACHE_DB,
                    "on" if _core.watcher else "off",
                ),
                syslog.LOG_INFO,
            )
        return _core


class FolderSizeColumnProvider(GObject.GObject, Nautilus.ColumnProvider):
    def __init__(self):
        GObject.GObject.__init__(self)
        try:
            self.core = ensure_started()
        except Exception:
            log_exception("starting extension from column provider")
            self.core = None

    def get_columns(self):
        try:
            return [
                Nautilus.Column(
                    name="NautilusPython::folder_size_column",
                    attribute="folder_size",
                    label="Folder Size",
                    description="Total apparent size of the folder contents",
                )
            ]
        except Exception:
            log_exception("get_columns")
            return []


class FolderSizeInfoProvider(GObject.GObject, Nautilus.InfoProvider):
    def __init__(self):
        GObject.GObject.__init__(self)
        try:
            self.core = ensure_started()
        except Exception:
            log_exception("starting extension from info provider")
            self.core = None

    def _add_attribute(self, file_info, size):
        try:
            text = format_bytes(size)
            if text:
                file_info.add_string_attribute("folder_size", text)
        except Exception:
            log_exception("add folder_size attribute")

    @safe("update_file_info")
    def update_file_info(self, file_info):
        if self.core is None:
            return
        try:
            if not file_info.is_directory():
                return
            if file_info.get_uri_scheme() != "file":
                return
            location = file_info.get_location()
            if location is None:
                return
            path = normalize_path(location.get_path())
            if path is None:
                return

            entry = self.core.cache.get(path)
            now = time.time()
            need_work = False
            if entry is None:
                need_work = True
            elif entry.size is not None:
                self._add_attribute(file_info, entry.size)
                need_work = now > entry.computed_at + TTL
            else:
                need_work = now > entry.computed_at + ERROR_TTL

            if not need_work:
                return
            # Only compute while the column is actually visible in a list view.
            if not self.core.column_is_visible():
                return

            with self.core.column_lock:
                if (
                    path in self.core.column_pending
                    or len(self.core.column_pending) >= MAX_COLUMN_PENDING
                ):
                    return
                self.core.column_pending.add(path)
                self.core.column_waiters.setdefault(path, []).append(file_info)

            self.core.engine.request([path], self.core.column_result)
        except Exception:
            log_exception("update_file_info body")
