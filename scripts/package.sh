#!/usr/bin/env bash
# Build a source release tarball and checksum in dist/.
#
# Usage: ./scripts/package.sh [output-directory]
# The version is read from the first extension module so there is one source
# of truth.

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

NAME="nautilus-extensions"
VERSION="$(tr -d '[:space:]' < VERSION 2>/dev/null || true)"
[ -n "$VERSION" ] || {
    printf 'error: cannot read the VERSION file\n' >&2
    exit 1
}

DIST="${1:-$ROOT/dist}"
ARCHIVE="$DIST/$NAME-$VERSION.tar.gz"

mkdir -p "$DIST"

printf 'Checking sources...\n'
python3 - <<'PY'
from pathlib import Path

for path in sorted(Path("extensions").glob("*.py")):
    with path.open("r", encoding="utf-8") as handle:
        compile(handle.read(), str(path), "exec")
PY
bash -n install.sh uninstall.sh scripts/*.sh

printf 'Creating %s\n' "$ARCHIVE"
tar \
    --exclude-vcs \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='.ruff_cache' \
    --exclude='*.pyc' \
    --exclude='.venv' \
    --exclude='dist' \
    --transform "s,^,$NAME-$VERSION/," \
    -czf "$ARCHIVE" \
    extensions \
    install.sh \
    uninstall.sh \
    README.md \
    CHANGELOG.md \
    LICENSE \
    CONTRIBUTING.md \
    CODE_OF_CONDUCT.md \
    SECURITY.md \
    AGENTS.md \
    Makefile \
    pyproject.toml \
    VERSION \
    .editorconfig \
    .gitattributes \
    .gitignore \
    .pre-commit-config.yaml \
    docs \
    scripts \
    tests \
    .github

(
    cd "$DIST"
    sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256"
)

printf '\nBuilt:\n'
printf '  %s\n' "$ARCHIVE"
printf '  %s.sha256\n' "$ARCHIVE"
printf '\nVerify with:\n  sha256sum -c %s.sha256\n' "$(basename "$ARCHIVE")"
