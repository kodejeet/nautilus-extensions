#!/usr/bin/env bash
# Read-only environment diagnostics for Nautilus Folder Size bug reports.
# This script never installs, removes, or modifies anything.

set -uo pipefail

APP="nautilus-foldersize"
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
EXTENSION="${XDG_DATA_HOME:-$HOME/.local/share}/nautilus-python/extensions/foldersize.py"

section() { printf '\n== %s ==\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

section "System"
if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    printf 'Distribution: %s\n' "${PRETTY_NAME:-unknown}"
else
    printf 'Distribution: unknown (no /etc/os-release)\n'
fi
printf 'Kernel:       %s\n' "$(uname -srm)"
printf 'Session:      %s / %s\n' \
    "${XDG_SESSION_TYPE:-unknown}" "${XDG_CURRENT_DESKTOP:-unknown}"

section "Nautilus"
if have nautilus; then
    printf 'Binary:  %s\n' "$(command -v nautilus)"
    nautilus --version 2>&1 | sed 's/^/Version: /' || true
else
    printf 'nautilus binary not found in PATH\n'
fi

section "Python"
if have python3; then
    printf 'Binary: %s\n' "$(command -v python3)"
    python3 --version 2>&1
    python3 - <<'PY' 2>&1 || true
try:
    import gi
except Exception as error:
    print("PyGObject: missing (%s)" % error)
else:
    print("PyGObject: available")
    for version in ("4.1", "4.0"):
        try:
            gi.require_version("Nautilus", version)
            from gi.repository import Nautilus  # noqa: F401
        except Exception as error:
            print("Nautilus %s typelib: unavailable (%s)" % (version, error))
        else:
            print("Nautilus %s typelib: available" % version)
            break
PY
else
    printf 'python3 not found in PATH\n'
fi

section "Utilities"
if have du; then
    printf 'du: %s\n' "$(command -v du)"
else
    printf 'du: missing (the built-in walker will be used)\n'
fi
if have journalctl; then
    printf 'journalctl: %s\n' "$(command -v journalctl)"
else
    printf 'journalctl: missing\n'
fi

section "Extension"
if [ -f "$EXTENSION" ]; then
    printf 'Installed: %s\n' "$EXTENSION"
    if have python3; then
        printf 'Compile check: '
        if python3 -c 'import sys; compile(open(sys.argv[1], encoding="utf-8").read(), sys.argv[1], "exec")' "$EXTENSION" 2>&1; then
            printf 'ok\n'
        fi
    fi
else
    printf 'Not installed at %s\n' "$EXTENSION"
    printf 'Run ./install.sh from %s\n' "$HERE"
fi

section "State"
printf 'Cache:  %s\n' "${XDG_CACHE_HOME:-$HOME/.cache}/$APP"
printf 'Config: %s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/$APP"
if [ -f "${XDG_CONFIG_HOME:-$HOME/.config}/$APP/config.json" ]; then
    printf 'config.json:\n'
    sed 's/^/  /' "${XDG_CONFIG_HOME:-$HOME/.config}/$APP/config.json"
else
    printf 'config.json: not present (defaults are active)\n'
fi

section "Kill switches"
found=0
for name in NAUTILUS_FOLDERSIZE_NO_PILL NAUTILUS_FOLDERSIZE_DISABLE_PILL; do
    if [ -n "${!name:-}" ]; then
        printf '%s=%s\n' "$name" "${!name}"
        found=1
    fi
done
if [ "$found" -eq 0 ]; then
    printf 'No pill kill-switch environment variable is set.\n'
fi

section "Recent journal"
if have journalctl; then
    journalctl --user -t "$APP" -n 30 --no-pager 2>&1 || true
else
    printf 'journalctl is unavailable on this system.\n'
fi

printf '\nDone. Review the output for personal paths before posting it.\n'
