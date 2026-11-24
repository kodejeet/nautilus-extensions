"""Small in-memory GTK-like objects used by the unit tests."""

from types import SimpleNamespace


class FakeWidget:
    """A minimal widget with the tree API used by foldersize.py."""

    def __init__(self, css=None, gtype="FakeWidget", children=None):
        self.__gtype__ = SimpleNamespace(name=gtype)
        self._css = list(css or [])
        self._children = []
        self._parent = None
        self._mapped = True
        self._visible = True
        for child in children or []:
            self.add(child)

    def add(self, child):
        child._parent = self
        self._children.append(child)
        return child

    def get_first_child(self):
        return self._children[0] if self._children else None

    def get_next_sibling(self):
        if self._parent is None:
            return None
        siblings = self._parent._children
        index = siblings.index(self)
        if index + 1 >= len(siblings):
            return None
        return siblings[index + 1]

    def get_parent(self):
        return self._parent

    def get_css_classes(self):
        return list(self._css)

    def get_mapped(self):
        return self._mapped

    def get_visible(self):
        return self._visible

    def connect(self, *_args, **_kwargs):
        return 0

    def list_properties(self):
        return []


class FakeLabel(FakeWidget):
    def __init__(self, text="", gtype="GtkLabel"):
        super().__init__(gtype=gtype)
        self._text = text
        self.notifications = []

    def get_text(self):
        return self._text

    def set_text(self, text):
        if text != self._text:
            self._text = text
            self.notifications.append(text)

    def connect(self, signal, callback, *args, **kwargs):
        self.notifications.append((signal, callback))
        return 0


class FakeEngine:
    def __init__(self, result=None):
        self.result = result
        self.requests = []
        self.invalidated = []
        self.cached = {}

    def lookup_sum(self, paths):
        if not paths:
            return None
        total = 0
        for path in paths:
            if path not in self.cached:
                return None
            total += self.cached[path]
        return total

    def request(self, paths, callback):
        self.requests.append((tuple(paths), callback))

    def invalidate(self, path):
        self.invalidated.append(path)


class FakeWatcher:
    def __init__(self, engine=None):
        self.engine = engine or FakeEngine()
        self.dropped = []
        self.monitored = []

    def drop_state(self, state):
        self.dropped.append(state)
        state.dead = True

    def monitor_path(self, path):
        self.monitored.append(path)
