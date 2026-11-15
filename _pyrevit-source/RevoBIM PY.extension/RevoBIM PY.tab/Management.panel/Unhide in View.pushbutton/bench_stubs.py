# -*- coding: utf-8 -*-
"""Stub .NET and Revit API for the bench (plain CPython 3).

Every name is declared in the namespace the real API puts it in, and ONLY
there - so a module importing a name from the wrong namespace fails here
the same way it would fail in Revit. Members are permissive: any attribute,
call or operator works, because this checks imports and wiring, not
behaviour. Behaviour is checked in bench_logic.py with fakes.

Not shipped logic - never imported by the tool itself.
"""
import sys
import types


class _Anything(object):
    """Stands in for any .NET value: every attribute, call and operator works."""

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return _Anything()

    def __call__(self, *a, **k):
        return _Anything()

    def __iadd__(self, other):
        return self

    def __isub__(self, other):
        return self

    def __or__(self, other):
        return _Anything()

    def __and__(self, other):
        return _Anything()

    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return id(self)

    def __iter__(self):
        return iter([])

    def __len__(self):
        return 0

    def __getitem__(self, key):
        return _Anything()

    def __setitem__(self, key, value):
        pass

    def __bool__(self):
        return True

    def __str__(self):
        return 'stub'


class _NetList(list):
    def Add(self, item):
        self.append(item)

    @property
    def Count(self):
        return len(self)


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return _Anything()

    def __getitem__(cls, key):
        # List[ElementId] -> constructor of a list with .Add
        def make(items=()):
            return _NetList(items)
        return make


class _StubBase(_Anything, metaclass=_Meta):
    pass


NAMESPACES = {
    'System': ['Action', 'AppDomain', 'Boolean', 'Int32', 'Int64', 'String',
               'TimeSpan', 'Byte', 'EventHandler', 'Object', 'Exception'],
    'System.Collections.Generic': ['List', 'Dictionary'],
    'System.Data': ['DataTable', 'DataRowView', 'DataView', 'DataRow'],
    'System.IO': ['File', 'MemoryStream', 'Path'],
    'System.Windows': ['Visibility', 'GridLength', 'GridUnitType',
                       'HorizontalAlignment', 'VerticalAlignment',
                       'FrameworkElement', 'DataTemplate',
                       'FrameworkElementFactory', 'Clipboard',
                       'RoutedEventHandler', 'PresentationSource', 'UIElement',
                       'Thickness', 'Window', 'ResourceDictionary', 'WindowStyle',
                       'CornerRadius', 'Point', 'SizeToContent'],
    'System.Windows.Controls': ['DataGridTextColumn', 'DataGridTemplateColumn',
                                'DataGridLength', 'DataGridLengthUnitType',
                                'DataGridRow', 'StackPanel', 'TextBlock',
                                'TextBox', 'CheckBox', 'Button', 'Control',
                                'DataGrid', 'Orientation'],
    'System.Windows.Controls.Primitives': ['ButtonBase', 'ToggleButton', 'Thumb',
                                           'DragDeltaEventHandler'],
    'System.Windows.Data': ['Binding', 'BindingMode', 'UpdateSourceTrigger'],
    'System.Windows.Input': ['Key', 'Keyboard', 'ModifierKeys', 'Cursors',
                             'MouseButtonEventHandler', 'KeyEventHandler'],
    'System.Windows.Media': ['VisualTreeHelper', 'Visual', 'SolidColorBrush',
                             'Color', 'Brush'],
    'System.Windows.Media.Imaging': ['BitmapImage', 'BitmapCacheOption'],
    'System.Windows.Threading': ['DispatcherTimer', 'DispatcherPriority'],
    'System.Windows.Interop': ['WindowInteropHelper'],
    'System.Windows.Markup': ['XamlReader'],
    'System.Windows.Forms': ['Screen'],
    'Autodesk.Revit.DB': ['FilteredElementCollector', 'ElementId', 'View',
                          'Transaction', 'TransactionGroup',
                          'ElementMulticategoryFilter', 'ElementOwnerViewFilter',
                          'ElementClassFilter', 'WorksharingUtils',
                          'IFailuresPreprocessor', 'FailureProcessingResult',
                          'BuiltInParameter', 'BuiltInCategory', 'Element',
                          'ViewSheet', 'Category'],
    'Autodesk.Revit.UI': ['IExternalEventHandler', 'ExternalEvent', 'TaskDialog',
                          'TaskDialogCommonButtons', 'UIThemeManager',
                          'UIApplication', 'UIDocument'],
}

PACKAGES = ['Autodesk', 'Autodesk.Revit']


def install():
    """Put the stub modules into sys.modules. Returns the list of names."""
    for pkg in PACKAGES:
        if pkg not in sys.modules:
            sys.modules[pkg] = types.ModuleType(pkg)
    for ns, names in NAMESPACES.items():
        mod = types.ModuleType(ns)
        for n in names:
            setattr(mod, n, _Meta(n, (_StubBase,), {}))
        sys.modules[ns] = mod
    # parents point at children so `import Autodesk.Revit.UI as rui` resolves
    for ns in list(NAMESPACES.keys()) + PACKAGES:
        parts = ns.split('.')
        for i in range(1, len(parts)):
            parent = '.'.join(parts[:i])
            child = '.'.join(parts[:i + 1])
            if parent in sys.modules and child in sys.modules:
                setattr(sys.modules[parent], parts[i], sys.modules[child])

    clr = types.ModuleType('clr')
    clr.references = []

    def AddReference(name):
        clr.references.append(name)
    clr.AddReference = AddReference
    clr.GetClrType = lambda t: t
    sys.modules['clr'] = clr
    return NAMESPACES


def uninstall():
    for ns in list(NAMESPACES.keys()) + PACKAGES + ['clr']:
        sys.modules.pop(ns, None)
