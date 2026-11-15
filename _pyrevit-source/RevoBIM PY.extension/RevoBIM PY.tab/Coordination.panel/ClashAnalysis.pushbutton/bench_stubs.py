# -*- coding: utf-8 -*-
"""A stub .NET and Revit API for running Clash Analysis modules under plain
CPython. Every name is declared in the namespace the real API puts it in, so
a mis-namespaced import fails here instead of in Revit. Nothing behaves -
it only has to import and be subclassable.
"""
import sys
import types

NAMESPACES = {
    'System': ['Action', 'AppDomain', 'Array', 'Double', 'EventHandler',
               'Int32', 'Int64', 'Object', 'String', 'TimeSpan', 'Uri'],
    'System.Collections.Generic': ['List', 'Dictionary'],
    'System.Data': ['DataTable', 'DataView', 'DataRowView'],
    'System.IO': ['File', 'FileAccess', 'FileMode', 'FileStream',
                  'MemoryStream', 'Path'],
    'System.Windows': ['Clipboard', 'FontStyles', 'FontWeights', 'FrameworkElement',
                       'GridLength', 'GridUnitType',
                       'HorizontalAlignment', 'PresentationSource',
                       'ResourceDictionary', 'SizeToContent', 'TextTrimming',
                       'Thickness', 'VerticalAlignment', 'Visibility',
                       'Window', 'WindowStartupLocation', 'WindowStyle'],
    'System.Windows.Controls': ['Button', 'CheckBox', 'ComboBox',
                                'ComboBoxItem', 'ContextMenu', 'MenuItem', 'DataGridTemplateColumn',
                                'Separator', 'DataGrid', 'DataGridLength',
                                'DataGridLengthUnitType', 'DataGridTextColumn',
                                'Dock', 'DockPanel', 'Grid', 'ListBox',
                                'ListBoxItem', 'Orientation', 'StackPanel',
                                'TextBlock', 'TextBox'],
    'System.Windows.Controls.Primitives': ['Thumb', 'Popup'],
    'System.Windows.Data': ['Binding', 'IValueConverter'],
    'System.Windows.Input': ['Cursors', 'Key', 'Keyboard', 'ModifierKeys',
                             'Mouse', 'MouseButtonState'],
    'System.Windows.Interop': ['WindowInteropHelper'],
    'System.Windows.Markup': ['XamlReader'],
    'System.Windows.Media': ['Brushes', 'Color', 'ColorConverter',
                             'RotateTransform', 'SolidColorBrush', 'VisualTreeHelper'],
    'System.Windows.Shapes': ['Ellipse', 'Shape'],
    'System.Windows.Media.Animation': ['DoubleAnimation', 'Storyboard'],
    'System.Windows.Media.Imaging': ['BitmapCacheOption', 'BitmapImage'],
    'System.Windows.Threading': ['DispatcherPriority', 'DispatcherTimer'],
    'System.Windows.Forms': ['Screen'],
    'Autodesk.Revit.DB': [
        'BooleanOperationsType', 'BooleanOperationsUtils', 'BoundingBoxXYZ',
        'BuiltInCategory', 'BuiltInParameter', 'CategoryType', 'Element',
        'ElementId', 'ElementMulticategoryFilter', 'ElementTransformUtils',
        'FailureProcessingResult', 'FailureSeverity', 'FamilyInstance',
        'FamilySymbol', 'FilteredElementCollector', 'FilteredWorksetCollector',
        'GeometryInstance', 'Group', 'GroupType', 'IFailuresPreprocessor',
        'Level', 'ModelPathUtils', 'Options', 'RevitLinkInstance', 'Solid',
        'SolidUtils', 'Transaction', 'TransactionGroup', 'TransactionStatus',
        'Transform', 'View3D', 'ViewDetailLevel', 'WorksetKind',
        'WorksharingUtils', 'XYZ', 'Category', 'ScheduleFilter',
        'ScheduleFilterType', 'ScheduleSortGroupField', 'ScheduleSortOrder',
        'ViewPlan', 'ViewSchedule', 'Workset', 'CurveElement',
        'ImportInstance', 'TemporaryViewMode', 'ViewFamily', 'ViewFamilyType'],
    'Autodesk.Revit.DB.Structure': ['StructuralType'],
    'Autodesk.Revit.UI': ['ExternalEvent', 'ExternalEventRequest',
                          'IExternalEventHandler', 'TaskDialog', 'UIApplication'],
}


class _Value(object):
    """What an enum member or a static property looks like."""

    def __init__(self, name):
        self._name = name

    def __repr__(self):
        return '<stub {0}>'.format(self._name)

    def __getattr__(self, name):
        return _Value(self._name + '.' + name)

    def __call__(self, *args, **kwargs):
        return _Value(self._name + '()')

    def __or__(self, other):
        return _Value(self._name + '|')


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith('__'):
            raise AttributeError(name)
        cache = cls.__dict__.get('_members')
        if cache is None:
            cache = {}
            type.__setattr__(cls, '_members', cache)
        if name not in cache:
            cache[name] = _Value(cls.__name__ + '.' + name)
        return cache[name]

    def __getitem__(cls, item):
        return cls


class _Stub(object, metaclass=_Meta):
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _Value(name)


def _module(name):
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    return mod


def install():
    """Put clr, System.* and Autodesk.* into sys.modules."""
    clr = _module('clr')
    clr.AddReference = lambda name: None
    for ns, names in NAMESPACES.items():
        parts = ns.split('.')
        for i in range(1, len(parts) + 1):
            mod = _module('.'.join(parts[:i]))
            if i > 1:
                setattr(sys.modules['.'.join(parts[:i - 1])], parts[i - 1], mod)
        mod = sys.modules[ns]
        for n in names:
            setattr(mod, n, _Meta(n, (_Stub,), {}))


def uninstall():
    for key in list(sys.modules.keys()):
        if key == 'clr' or key == 'System' or key.startswith('System.') or \
                key == 'Autodesk' or key.startswith('Autodesk.') or \
                key.startswith('ca_'):
            del sys.modules[key]
