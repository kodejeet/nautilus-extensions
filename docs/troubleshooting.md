# Troubleshooting

Start with the doctor script:

```sh
./scripts/doctor.sh
```

It prints your Nautilus version, Python/PyGObject status, the available
Nautilus typelib, the installed extension path, and recent journal lines. It
changes nothing.

## Collecting logs

```sh
journalctl --user -t nautilus-foldersize -n 200 --no-pager
```

For verbose output:

```sh
NAUTILUS_FOLDERSIZE_DEBUG=1 nautilus
```

Debug messages go to stderr and to the journal. Remember that `nautilus -q`
shuts down the current process and starts a fresh one on the next window.

## The extension is not loaded

Check the install location:

```sh
ls -l "${XDG_DATA_HOME:-$HOME/.local/share}/nautilus-python/extensions/foldersize.py"
```

If it is missing, run `./install.sh`.

Check the bindings:

```sh
python3 - <<'PY'
import gi
for version in ("4.1", "4.0"):
    try:
        gi.require_version("Nautilus", version)
        from gi.repository import Nautilus
        print("Nautilus Python API:", version)
        break
    except Exception as error:
        print(version, "unavailable:", error)
else:
    raise SystemExit("install python3-nautilus")
PY
```

On Ubuntu 24.04 the available typelib is normally `Nautilus-4.0`. The
extension handles that fallback automatically.

## The pill has no size

- Select a directory, not a file. Mixed file/folder selections are ignored by
  design.
- Wait for the scan. The first scan of a very large folder can take up to the
  `NAUTILUS_FOLDERSIZE_DU_TIMEOUT` (60 seconds by default).
- Look for `floating bar not found` in the journal. If present, Nautilus has
  changed its bar; the Folder Size column should still work. Please open an
  issue with your Nautilus version.
- Look for `remote` or `permission` messages. Remote mounts and unreadable
  folders are skipped intentionally.
- Confirm the pill feature is not disabled by a kill switch:

  ```sh
  env | grep NAUTILUS_FOLDERSIZE
  cat "${XDG_CONFIG_HOME:-$HOME/.config}/nautilus-foldersize/config.json" 2>/dev/null
  ```

## The Folder Size column is blank

- Enable **Folder Size** under **Visible Columns**. The extension does not
  compute values while the column is hidden.
- Wait a moment; values are painted asynchronously.
- Try a small local folder first.
- If every row stays blank, check the journal for `column` errors.

## Sizes look different from `du -sh`

The extension reports **apparent size** in decimal units, matching:

```sh
du -sb --apparent-size -x -- /path/to/folder
```

`du -sh` reports **disk allocation** in binary units. Sparse files, filesystem
block sizes, compression, and hard links all make the two numbers differ.

To verify a value:

```sh
du -sb --apparent-size -x -- "/path/to/folder"
```

## The size is stale

The cache TTL is five minutes. A selected folder is also monitored for direct
changes, but changes in deeply nested folders may not be noticed immediately.
Workarounds:

```sh
rm -rf "${XDG_CACHE_HOME:-$HOME/.cache}/nautilus-foldersize"
nautilus -q
```

Or lower the TTL:

```sh
NAUTILUS_FOLDERSIZE_TTL=30 nautilus
```

## Scans are too slow

- Increase `NAUTILUS_FOLDERSIZE_DU_TIMEOUT` for very large or cold folders.
- Lower `NAUTILUS_FOLDERSIZE_WORKERS` to 1 if several scans compete for I/O.
- Avoid selecting a directory that contains a huge number of small files.
- Remote filesystems are skipped on purpose. Copying the data local is the
  only supported workaround.

## Nautilus freezes or crashes

The extension runs in-process, so a Nautilus crash should still be reported,
but first rule out the extension:

```sh
./uninstall.sh
nautilus -q
```

If the problem disappears, reinstall and collect the journal with
`NAUTILUS_FOLDERSIZE_DEBUG=1`. Please include your Nautilus version:

```sh
nautilus --version
```

## Cache or configuration reset

```sh
rm -rf "${XDG_CACHE_HOME:-$HOME/.cache}/nautilus-foldersize"
rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/nautilus-foldersize"
nautilus -q
```

## Uninstall

```sh
./uninstall.sh --purge
```

This removes the extension, its cache, and its configuration. It never removes
system packages.

## Reporting a bug

Open <https://github.com/kodejeet/nautilus-extensions/issues> and include:

- the output of `./scripts/doctor.sh`;
- the Nautilus version and distribution release;
- exact reproduction steps;
- whether the pill, the column, or both are affected;
- relevant journal lines.

Please remove personal paths and file names from logs before posting.
