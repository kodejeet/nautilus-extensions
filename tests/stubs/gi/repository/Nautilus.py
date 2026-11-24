"""Fake Nautilus typelib surface needed to import the extension."""


class ColumnProvider:
    pass


class InfoProvider:
    pass


class Column:
    def __init__(self, name=None, attribute=None, label=None, description=None):
        self.name = name
        self.attribute = attribute
        self.label = label
        self.description = description


class FileInfo:
    """Only used by tests that call provider methods directly."""

    def __init__(self, name="", is_directory=True, path="/tmp/example"):
        self._name = name
        self._is_directory = is_directory
        self._path = path
        self.attributes = {}

    def get_name(self):
        return self._name

    def is_directory(self):
        return self._is_directory

    def get_uri_scheme(self):
        return "file"

    def get_location(self):
        return _Location(self._path)

    def add_string_attribute(self, name, value):
        self.attributes[name] = value

    def invalidate_extension_info(self):
        pass


class _Location:
    def __init__(self, path):
        self._path = path

    def get_path(self):
        return self._path
