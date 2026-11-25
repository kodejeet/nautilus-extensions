# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |
| Other | No |

## Reporting a vulnerability

Please do **not** open a public issue for a security problem.

Use GitHub's private vulnerability reporting:

<https://github.com/kodejeet/nautilus-extensions/security/advisories/new>

Include:

- affected version (`./install.sh --version`);
- Nautilus and distribution versions;
- a description of the impact;
- reproduction steps or a proof of concept;
- any suggested mitigation.

You can expect an initial response within seven days. This is a volunteer
project, so timelines for fixes depend on severity and available time.

## Scope

The extension runs inside the Nautilus process with the privileges of the
logged-in user. Relevant security concerns include:

- reading or exposing file contents (the extension is designed only to read
  directory metadata and sizes);
- following symlinks outside the selected tree;
- command injection through paths passed to `du`;
- unsafe cache deserialization;
- privilege escalation through the installer;
- denial of service through unbounded scans or memory growth.

## Design notes

- `du` is invoked with an argument vector, never through a shell, and paths are
  separated with `--`.
- The extension makes no network requests and has no telemetry.
- Cache and configuration files live under the user's XDG directories with
  user-only permissions where the platform allows it.
- The installer is per-user and only uses root to install the distribution's
  `python3-nautilus` package when the user approves it.
- Scanning skips symlinks, remote filesystems, and pseudo filesystems.

## Out of scope

- Sizes differing from `du -sh` (different accounting semantics);
- missing values on remote or unreadable filesystems (intentional);
- issues that require an already-compromised user account;
- Nautilus itself or other third-party extensions.
