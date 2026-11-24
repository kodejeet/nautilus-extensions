#!/usr/bin/env bash
# Per-user installer for Nautilus Folder Size.
#
# Installs foldersize.py into
#   ${XDG_DATA_HOME:-~/.local/share}/nautilus-python/extensions/
# and makes sure the Nautilus Python bindings are present. It never patches
# system Nautilus files, rebuilds Nautilus, or uses LD_PRELOAD.

set -euo pipefail

APP="nautilus-foldersize"
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/foldersize.py"
DEST_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/nautilus-python/extensions"
DEST="$DEST_DIR/foldersize.py"

say() { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*" >&2; }
die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

[ -f "$SRC" ] || die "foldersize.py not found next to install.sh ($SRC)"

APP_VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$SRC" | head -n 1)"
[ -n "$APP_VERSION" ] || APP_VERSION="unknown"

restart=1
dry_run=0

usage() {
  cat <<EOF
Nautilus Folder Size installer v$APP_VERSION

Usage: ./install.sh [options]

Options:
  --no-restart   install without running "nautilus -q"
  --dry-run      check prerequisites and show what would happen
  --version      print the version and exit
  -h, --help     show this help

The extension is installed for the current user only. The target directory is
${DEST_DIR}.
EOF
}

for arg in "$@"; do
  case "$arg" in
  --no-restart) restart=0 ;;
  --dry-run) dry_run=1 ;;
  --version)
    say "$APP $APP_VERSION"
    exit 0
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    warn "error: unknown option: $arg"
    usage >&2
    exit 2
    ;;
  esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v pkexec >/dev/null 2>&1; then
    pkexec "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    die "root privileges are required (install pkexec or sudo)"
  fi
}

python_ok() {
  python3 - <<'PY' >/dev/null 2>&1
import gi
PY
}

nautilus_api() {
  python3 - <<'PY' 2>/dev/null
import sys
try:
    import gi
except Exception:
    sys.exit(2)
for version in ("4.1", "4.0"):
    try:
        gi.require_version("Nautilus", version)
        from gi.repository import Nautilus  # noqa: F401
    except Exception:
        continue
    print(version)
    sys.exit(0)
sys.exit(1)
PY
}

install_bindings() {
  local id_like
  id_like=" ${ID:-} ${ID_LIKE:-} "
  case "$id_like" in
  *debian* | *ubuntu* | *linuxmint* | *pop*)
    if ! as_root env DEBIAN_FRONTEND=noninteractive \
      apt-get install -y python3-nautilus; then
      as_root apt-get update -qq
      as_root env DEBIAN_FRONTEND=noninteractive \
        apt-get install -y python3-nautilus
    fi
    ;;
  *fedora*)
    as_root dnf install -y nautilus-python
    ;;
  *rhel* | *centos* | *rocky* | *almalinux*)
    if command -v dnf >/dev/null 2>&1; then
      as_root dnf install -y nautilus-python
    else
      as_root yum install -y nautilus-python
    fi
    ;;
  *arch* | *manjaro*)
    as_root pacman -S --needed --noconfirm python-nautilus
    ;;
  *opensuse* | *suse*)
    as_root zypper --non-interactive install python3-nautilus
    ;;
  *)
    return 1
    ;;
  esac
}

# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

command -v python3 >/dev/null 2>&1 || die "python3 was not found"

if ! python_ok; then
  die "PyGObject is missing (install python3-gi / python-gobject)"
fi

command -v nautilus >/dev/null 2>&1 || die "Nautilus is not installed"

if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
fi

api="$(nautilus_api || true)"
if [ -z "$api" ]; then
  if [ "$dry_run" -eq 1 ]; then
    die "Nautilus Python bindings are missing; install python3-nautilus"
  fi
  say "Nautilus Python bindings (Nautilus 4.x) not found; trying to install..."
  if ! install_bindings; then
    die "cannot install Nautilus Python bindings automatically.
Install the package providing python3-nautilus / nautilus-python for your
distribution, then run this script again."
  fi
  api="$(nautilus_api || true)"
fi
[ -n "$api" ] || die "Nautilus 4.x Python bindings are still unavailable.
On Debian/Ubuntu install python3-nautilus; it pulls the matching
gir1.2-nautilus-4.0 or gir1.2-nautilus-4.1 typelib for your release."

# ---------------------------------------------------------------------------
# Install the extension
# ---------------------------------------------------------------------------

say "Nautilus Folder Size $APP_VERSION"
say "Nautilus Python API: $api"
say "Source:              $SRC"
say "Destination:         $DEST"

if [ "$dry_run" -eq 1 ]; then
  say "Dry run: nothing was installed."
  exit 0
fi

mkdir -p "$DEST_DIR"
install -m 0644 "$SRC" "$DEST"

python3 - "$DEST" <<'PY' || die "installed file failed to compile"
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as handle:
    compile(handle.read(), path, "exec")
PY

say "Installed $DEST"

if [ "$restart" -eq 1 ]; then
  say "Restarting Nautilus..."
  nautilus -q >/dev/null 2>&1 || true
fi

say ""
say "Select a folder in Nautilus to see its size in the floating bar."
say "List view: enable the \"Folder Size\" column (Visible Columns menu)."
say "Logs:      journalctl --user -t $APP -f"
say "Disable the pill only:"
say "           NAUTILUS_FOLDERSIZE_NO_PILL=1 nautilus"
say "           or ~/.config/$APP/config.json  {\"pill\": false}"
