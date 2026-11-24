#!/usr/bin/env bash
# Per-user uninstaller for Nautilus Folder Size.

set -euo pipefail

APP="nautilus-foldersize"
DEST_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/nautilus-python/extensions"
DEST="$DEST_DIR/foldersize.py"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/$APP"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/$APP"

purge=0
dry_run=0

usage() {
    cat <<EOF
usage: ./uninstall.sh [options]

Options:
  --purge     also remove the size cache and configuration
  --dry-run   show what would be removed, without changing anything
  -h, --help  show this help
EOF
}

for arg in "$@"; do
    case "$arg" in
        --purge) purge=1 ;;
        --dry-run) dry_run=1 ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'error: unknown option: %s\n' "$arg" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ "$dry_run" -eq 1 ]; then
    if [ -e "$DEST" ]; then
        printf 'Would remove %s\n' "$DEST"
    else
        printf 'Not installed at %s\n' "$DEST"
    fi
    if [ "$purge" -eq 1 ]; then
        printf 'Would remove %s and %s\n' "$CACHE_DIR" "$CONFIG_DIR"
    fi
    exit 0
fi

if [ -e "$DEST" ]; then
    rm -f "$DEST"
    printf 'Removed %s\n' "$DEST"
else
    printf 'Not installed at %s\n' "$DEST"
fi
rm -f "$DEST_DIR/__pycache__/foldersize."*.pyc 2>/dev/null || true

if [ "$purge" -eq 1 ]; then
    rm -rf "$CACHE_DIR" "$CONFIG_DIR"
    printf 'Removed %s and %s\n' "$CACHE_DIR" "$CONFIG_DIR"
fi

if command -v nautilus >/dev/null 2>&1; then
    nautilus -q >/dev/null 2>&1 || true
    printf 'Nautilus restarted (nautilus -q).\n'
fi
