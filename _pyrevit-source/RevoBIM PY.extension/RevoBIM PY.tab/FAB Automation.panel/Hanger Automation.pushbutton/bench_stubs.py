# -*- coding: utf-8 -*-
"""Stub .NET / Revit API for the CPython bench.

The point of the stub is to behave like IronPython where it matters:
  - a .NET object (Window, Thumb, any control) REFUSES new Python attributes:
    assigning `win._full = False` raises AttributeError exactly as Revit did.
    Only PascalCase names (real .NET properties and events) can be set.
  - interfaces (IExternalEventHandler, ISelectionFilter...) are plain Python
    base classes, because a Python class implementing one CAN hold attributes.
  - every namespace resolves any name, so a misspelt import is caught by
    import_check's namespace rules rather than here.
Call install() before importing any fha_ module.
"""
import sys
import types


def _pascal(name):
    return bool(name) and name[0].isupper()


class NetMeta(type):
    def __getattr__(cls, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return NetObj('{0}.{1}'.format(cls.__name__, name))

    def __getitem__(cls, item):
        return cls


class NetObj(metaclass=NetMeta):
    """Any .NET object.  New lowercase attributes are refused, like IronPython."""

    def __init__(self, *args, **kwargs):
        object.__setattr__(self, '_n', type(self).__name__ if not args or not isinstance(args[0], str) else args[0])
        object.__setattr__(self, '_d', {})

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        d = object.__getattribute__(self, '_d')
        if name in d:
            return d[name]
        if _pascal(name):
            v = NetObj('{0}.{1}'.format(object.__getattribute__(self, '_n'), name))
            d[name] = v
            return v
        raise AttributeError("'{0}' object has no attribute '{1}'".format(
            type(self).__name__ if type(self) is not NetObj else 'Window', name))

    def __setattr__(self, name, value):
        if not _pascal(name):
            raise AttributeError("'{0}' object has no attribute '{1}'".format(
                type(self).__name__ if type(self) is not NetObj else 'Window', name))
        object.__getattribute__(self, '_d')[name] = value

    def __call__(self, *a, **k):
        args = ','.join(x if len(x) < 80 else '...' for x in a if isinstance(x, str))
        name = '{0}({1})'.format(object.__getattribute__(self, '_n'), args)
        if a and all(isinstance(x, str) and len(x) < 80 for x in a):
            # FindName('X') hands back the same control every time, as WPF does
            d = object.__getattribute__(self, '_d')
            calls = d.setdefault('_calls', {})
            if name not in calls:
                calls[name] = NetObj(name)
            return calls[name]
        return NetObj(name)

    def __iadd__(self, other):
        return self

    def __isub__(self, other):
        return self

    def __iter__(self):
        return iter([])

    def __getitem__(self, key):
        return NetObj('item')

    def __setitem__(self, key, value):
        pass

    def __bool__(self):
        return True

    def __int__(self):
        return 0

    def __index__(self):
        return 0

    def __float__(self):
        return 0.0

    def __str__(self):
        return object.__getattribute__(self, '_n')

    def __format__(self, spec):
        return str(self)

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return self is not other

    def _num(self, *a):
        return 0.0

    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = _num
    __truediv__ = __rtruediv__ = __neg__ = _num

    def _cmp(self, other):
        return True

    __lt__ = __le__ = __gt__ = __ge__ = _cmp


class StubModule(types.ModuleType):
    def __init__(self, name):
        types.ModuleType.__init__(self, name)
        self.__path__ = []
        self._classes = {}

    def __getattr__(self, name):
        if name.startswith('__') or name == '_classes':
            raise AttributeError(name)
        cls = self._classes.get(name)
        if cls is None:
            if len(name) > 1 and name[0] == 'I' and name[1].isupper():
                cls = type(name, (object,), {})          # interface: Python base
            else:
                cls = NetMeta(name, (NetObj,), {})       # .NET class
            self._classes[name] = cls
        return cls


NAMESPACES = [
    'clr', 'System', 'System.IO', 'System.Windows', 'System.Windows.Markup',
    'System.Windows.Media', 'System.Windows.Media.Imaging', 'System.Windows.Media.Animation', 'System.Windows.Input',
    'System.Windows.Controls', 'System.Windows.Controls.Primitives',
    'System.Windows.Interop', 'System.Windows.Threading', 'System.Windows.Forms',
    'System.Drawing', 'System.Drawing.Imaging', 'System.Collections', 'System.Collections.Generic',
    'Autodesk', 'Autodesk.Revit', 'Autodesk.Revit.DB', 'Autodesk.Revit.DB.Mechanical',
    'Autodesk.Revit.DB.Structure', 'Autodesk.Revit.DB.Plumbing', 'Autodesk.Revit.DB.Electrical',
    'Autodesk.Revit.UI',
    'Autodesk.Revit.UI.Selection',
]


class FakeList(list):
    def Add(self, x):
        self.append(x)

    @property
    def Count(self):
        return len(self)


class _ListType(object):
    def __getitem__(self, t):
        return FakeList


def install():
    mods = {}
    for name in NAMESPACES:
        m = sys.modules.get(name)
        if not isinstance(m, StubModule):
            m = StubModule(name)
            sys.modules[name] = m
        mods[name] = m
    for name in NAMESPACES:
        if '.' in name:
            parent, child = name.rsplit('.', 1)
            setattr(mods[parent], child, mods[name])
    mods['clr'].AddReference = lambda *a: None
    mods['System.Collections.Generic'].List = _ListType()
    return mods


def uninstall():
    for name in list(sys.modules):
        if name in NAMESPACES or name.startswith('fha_'):
            del sys.modules[name]
