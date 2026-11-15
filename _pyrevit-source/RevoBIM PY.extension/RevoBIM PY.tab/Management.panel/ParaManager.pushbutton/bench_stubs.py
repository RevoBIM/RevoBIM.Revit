# -*- coding: utf-8 -*-
"""A stand-in Revit and .NET, so every module loads under plain CPython."""
import sys
import types


class StubType(type):
    def __getattr__(cls, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return Stub()

    def __or__(cls, other):
        return cls


class Stub(metaclass=StubType):
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return Stub()

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return Stub()

    def __iadd__(self, other):
        return self

    def __or__(self, other):
        return self

    def __getitem__(self, key):
        return Stub


class Module(types.ModuleType):
    __path__ = []

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return type(name, (Stub,), {})


def install():
    names = ('clr', 'System', 'System.Collections', 'System.Collections.Generic', 'System.Data',
             'System.IO', 'System.IO.Compression', 'System.Text', 'System.Windows',
             'System.Windows.Controls', 'System.Windows.Controls.Primitives', 'System.Windows.Data',
             'System.Windows.Forms', 'System.Windows.Input', 'System.Windows.Interop',
             'System.Windows.Markup', 'System.Windows.Media', 'System.Windows.Media.Imaging',
             'System.Windows.Shapes', 'System.Windows.Threading', 'Microsoft', 'Microsoft.Win32',
             'Autodesk', 'Autodesk.Revit', 'Autodesk.Revit.DB', 'Autodesk.Revit.UI')
    for name in names:
        sys.modules[name] = Module(name)
