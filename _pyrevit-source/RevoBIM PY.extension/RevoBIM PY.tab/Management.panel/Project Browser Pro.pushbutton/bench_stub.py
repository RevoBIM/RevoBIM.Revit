# -*- coding: utf-8 -*-
u"""Bench only - a permissive stand-in for clr, System.* and Autodesk.*.

Lets the whole tool import, and the browser be built and driven, under plain
CPython 3. Every name in those namespaces resolves to a stub class; every
attribute of a stub is another stub; calling one makes an instance. So a
NameError, a typo on self, a wrong argument count to our own code, or an
exception in our own logic still surfaces - only the .NET side is faked.

It cannot see a missing clr.AddReference (a stub namespace always
resolves); import_check.py's assemblies_referenced rule covers that.
Never imported by the tool itself.
"""
import importlib.abc
import importlib.machinery
import sys
import types

PREFIXES = ('clr', 'System', 'Autodesk')
CREATED = {}


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return make(name)

    def __and__(cls, other):
        return cls

    def __or__(cls, other):
        return cls

    def __iter__(cls):
        return iter([])

    def __call__(cls, *args, **kwargs):
        return type.__call__(cls, *args, **kwargs)


class Stub(object, metaclass=_Meta):
    def __init__(self, *args, **kwargs):
        object.__setattr__(self, '_args', args)

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        value = make(name)()
        object.__setattr__(self, name, value)
        return value

    def __call__(self, *args, **kwargs):
        return make('result')()

    def __iter__(self):
        return iter([])

    def __len__(self):
        return 0

    def __bool__(self):
        return True

    def __iadd__(self, other):
        return self

    def __isub__(self, other):
        return self

    def __and__(self, other):
        return self

    def __or__(self, other):
        return self

    def __getitem__(self, key):
        return make('item')()

    def __setitem__(self, key, value):
        pass

    def __contains__(self, key):
        return False

    def __lt__(self, other):
        return False

    def __le__(self, other):
        return False

    def __gt__(self, other):
        return False

    def __ge__(self, other):
        return False

    def __float__(self):
        return 1.0

    def __int__(self):
        return 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def make(name):
    key = str(name)
    cls = CREATED.get(key)
    if cls is None:
        cls = _Meta(key, (Stub,), {})
        CREATED[key] = cls
    return cls


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return make(name)


class _Finder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path, target=None):
        if fullname.split('.')[0] in PREFIXES:
            return importlib.machinery.ModuleSpec(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        module = _StubModule(spec.name)
        module.__path__ = []
        return module

    def exec_module(self, module):
        if module.__name__ == 'clr':
            module.AddReference = lambda *args: None


INSTALLED = [False]


def install():
    if not INSTALLED[0]:
        sys.meta_path.insert(0, _Finder())
        INSTALLED[0] = True


def fresh(*names):
    u"""Forget the tool's modules so the next import runs them again."""
    for name in list(sys.modules):
        if name.startswith('pbp_') or name in names:
            del sys.modules[name]
