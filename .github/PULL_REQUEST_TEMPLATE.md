## Summary

Describe the user-visible problem and the change.

## Related issue

Closes #

## How was it tested?

- [ ] `python3 -m pytest -q`
- [ ] `ruff check .`
- [ ] `ruff format --check .`
- [ ] `bash -n install.sh uninstall.sh scripts/*.sh`
- [ ] Live Nautilus test (describe version and distro below)

Live environment:

- Nautilus version:
- Distribution:
- Session (Wayland/X11):

## Checklist

- [ ] The change keeps `foldersize.py` self-contained.
- [ ] No filesystem work was added to the GTK main loop.
- [ ] New UI writes go through `GLib.idle_add()`.
- [ ] New callbacks are exception-guarded.
- [ ] Symlinks are still not followed.
- [ ] Remote/pseudo filesystems are still skipped.
- [ ] No hardcoded usernames, home directories, or machine paths were added.
- [ ] The pill remains optional and the column still works without it.
- [ ] Both `Nautilus-4.1` and `Nautilus-4.0` compatibility is preserved.
- [ ] Tests were added or updated.
- [ ] `README.md`, `docs/`, and `CHANGELOG.md` were updated if needed.

## Screenshots or logs

If applicable, add screenshots or relevant journal lines. Remove personal
paths and file names.
