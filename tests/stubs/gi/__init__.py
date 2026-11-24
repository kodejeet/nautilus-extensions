"""Minimal, dependency-free stand-in for PyGObject.

The unit tests never open a window or talk to Nautilus. They only need enough
of the ``gi`` namespace to import the extension module and exercise its pure
logic. Keeping this stub in the repository makes ``pytest`` work on a headless
CI machine without GTK, Nautilus, or a display server.
"""


def require_version(namespace, version):
    """Pretend every requested typelib version is available."""


def require_versions(mapping):
    """Same as :func:`require_version` for the plural helper."""
