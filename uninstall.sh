#!/usr/bin/env bash
# Per-user uninstaller for the Nautilus Extensions collection.

set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$HERE/extensions"
DEST_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/nautilus-python/extensions"
STATE_APPS=("nautilus-foldersize")

shopt -s nullglob
SOURCES=("$SRC_DIR"/*.py)
shopt -u nullglob

purge=0
dry_run=0

usage() {
    cat <<EOF
usage: ./uninstall.sh [options]

Options:
  --purge     also remove extension caches and configuration
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

if [ "${#SOURCES[@]}" -eq 0 ]; then
    printf 'warning: no extension modules found in %s\n' "$SRC_DIR" >&2
fi

removed=0
if [ "$dry_run" -eq 1 ]; then
    for src in "${SOURCES[@]}"; do
        dest="$DEST_DIR/$(basename "$src")"
        if [ -e "$dest" ]; then
            printf 'Would remove %s\n' "$dest"
        else
            printf 'Not installed at %s\n' "$dest"
        fi
    done
    if [ "$purge" -eq 1 ]; then
        for app in "${STATE_APPS[@]}"; do
            printf 'Would remove %s and %s\n' \
                "${XDG_CACHE_HOME:-$HOME/.cache}/$app" \
                "${XDG_CONFIG_HOME:-$HOME/.config}/$app"
        done
    fi
    exit 0
fi

for src in "${SOURCES[@]}"; do
    name="$(basename "$src")"
    dest="$DEST_DIR/$name"
    if [ -e "$dest" ]; then
        rm -f "$dest"
        rm -f "$DEST_DIR/__pycache__/${name%.py}."*.pyc 2>/dev/null || true
        printf 'Removed %s\n' "$dest"
        removed=$((removed + 1))
    else
        printf 'Not installed at %s\n' "$dest"
    fi
done

if [ "$removed" -eq 0 ]; then
    printf 'Nothing to remove.\n'
fi

if [ "$purge" -eq 1 ]; then
    for app in "${STATE_APPS[@]}"; do
        cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/$app"
        config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/$app"
        rm -rf "$cache_dir" "$config_dir"
        printf 'Removed %s and %s\n' "$cache_dir" "$config_dir"
    done
fi

if command -v nautilus >/dev/null 2>&1; then
    nautilus -q >/dev/null 2>&1 || true
    printf 'Nautilus restarted (nautilus -q).\n'
fi
