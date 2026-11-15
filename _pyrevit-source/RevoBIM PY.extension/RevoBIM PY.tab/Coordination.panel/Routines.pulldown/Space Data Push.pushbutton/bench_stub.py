# -*- coding: utf-8 -*-
"""A stub Revit and .NET API for the bench checks (plain CPython 3).

Every name is declared in the namespace the REAL API puts it in. A tool module
that asks a namespace for a name it does not have fails on the bench exactly as
it would in Revit: `from System.Windows import Screen` raises ImportError here
because Screen lives in System.Windows.Forms.

When a module needs a new name, add it below IN ITS REAL NAMESPACE - that is the
whole point. Used by import_check.py and bench_logic.py; never shipped to Revit
in any way the tool imports.
"""
import sys
import types
import zlib

NAMESPACES = {
    'System': ['Action', 'AppDomain', 'TimeSpan'],
    'System.IO': ['File', 'MemoryStream'],
    'System.Collections.Generic': ['List'],
    'System.Diagnostics': ['Process'],
    'System.Windows': [
        'PresentationSource', 'WindowState', 'FontWeights', 'FrameworkElement',
        'GridLength', 'GridUnitType', 'HorizontalAlignment', 'TextTrimming',
        'TextWrapping', 'Thickness', 'VerticalAlignment', 'Window', 'CornerRadius',
    ],
    'System.Windows.Forms': ['Screen'],
    'System.Windows.Input': ['Key'],
    'System.Windows.Interop': ['WindowInteropHelper'],
    'System.Windows.Shell': ['WindowChrome'],
    'System.Windows.Markup': ['XamlReader'],
    'System.Windows.Media': ['Color', 'SolidColorBrush', 'Geometry'],
    'System.Windows.Media.Imaging': ['BitmapCacheOption', 'BitmapImage'],
    'System.Windows.Controls': ['Border', 'Button', 'ColumnDefinition', 'ComboBox', 'Grid', 'TextBlock',
                                'TextChangedEventHandler'],
    'System.Windows.Controls.Primitives': ['TextBoxBase'],
    'System.Windows.Data': ['Binding', 'RelativeSource', 'RelativeSourceMode'],
    'System.Windows.Shapes': ['Ellipse', 'Path'],
    'System.Windows.Threading': ['DispatcherTimer'],
    'Autodesk.Revit.DB': [
        'BuiltInCategory', 'BuiltInParameter', 'Element', 'ElementId',
        'FailureProcessingResult', 'FailureSeverity', 'FilteredElementCollector',
        'IFailuresPreprocessor', 'Transaction', 'WorksharingUtils',
    ],
    'Autodesk.Revit.UI': ['ExternalEvent', 'IExternalEventHandler', 'TaskDialog', 'UIThemeManager'],
    'Autodesk.Revit.UI.Selection': ['ISelectionFilter', 'ObjectType'],
    'Autodesk.Revit.Exceptions': ['OperationCanceledException'],
}

# Assemblies clr.AddReference will accept (the ones the tool asks for).
KNOWN_ASSEMBLIES = [
    'mscorlib', 'System', 'System.Core', 'System.Data', 'System.Xml', 'System.Xaml',
    'System.Drawing', 'System.Windows.Forms', 'PresentationFramework',
    'PresentationCore', 'WindowsBase', 'RevitAPI', 'RevitAPIUI',
]


class Enum(object):
    """Any enum member: equal by name, usable as int."""

    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return isinstance(other, Enum) and other.name == self.name

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.name)

    def __int__(self):
        return -(zlib.crc32(self.name.encode('ascii')) % 100000) - 1000

    def __str__(self):
        return self.name

    __repr__ = __str__


class Meta(type):
    def __getattr__(cls, item):
        if item.startswith('__'):
            raise AttributeError(item)
        return Enum(item)

    def __getitem__(cls, key):
        return cls


class Base(metaclass=Meta):
    def __init__(self, *args, **kwargs):
        pass


class StubList(list):
    def Add(self, item):
        self.append(item)

    def __class_getitem__(cls, key):
        return cls


class OperationCanceledException(Exception):
    pass


SPECIAL = {
    ('System.Collections.Generic', 'List'): StubList,
    ('Autodesk.Revit.Exceptions', 'OperationCanceledException'): OperationCanceledException,
}


class StubModule(types.ModuleType):
    def __init__(self, name, declared):
        types.ModuleType.__init__(self, name)
        self._declared = set(declared)

    def __getattr__(self, item):
        if item.startswith('__'):
            raise AttributeError(item)
        if item in self._declared:
            special = SPECIAL.get((self.__name__, item))
            obj = special if special is not None else Meta(item, (Base,), {})
            setattr(self, item, obj)
            return obj
        raise AttributeError("stub namespace %s has no name %s" % (self.__name__, item))


class StubClr(types.ModuleType):
    def __init__(self):
        types.ModuleType.__init__(self, 'clr')
        self.references = []

    def AddReference(self, name):
        if name not in KNOWN_ASSEMBLIES:
            raise IOError('Could not add reference to assembly %s' % name)
        self.references.append(name)


_INSTALLED = []


def install():
    """Put the stub namespaces and clr into sys.modules. Returns the clr stub."""
    uninstall()
    clr = StubClr()
    sys.modules['clr'] = clr
    _INSTALLED.append('clr')
    names = set()
    for ns in NAMESPACES:
        parts = ns.split('.')
        for i in range(1, len(parts) + 1):
            names.add('.'.join(parts[:i]))
    made = {}
    for ns in sorted(names):
        mod = StubModule(ns, NAMESPACES.get(ns, []))
        made[ns] = mod
        sys.modules[ns] = mod
        _INSTALLED.append(ns)
    for ns, mod in made.items():
        if '.' in ns:
            parent, child = ns.rsplit('.', 1)
            # a child module is reachable as an attribute of its parent
            mod_parent = made[parent]
            mod_parent.__dict__[child] = mod
    return clr


def uninstall():
    for name in _INSTALLED:
        sys.modules.pop(name, None)
    del _INSTALLED[:]


def purge(prefix='sdp_'):
    """Forget the tool's own modules so the next import reads the files afresh."""
    for name in list(sys.modules.keys()):
        if name.startswith(prefix):
            del sys.modules[name]
