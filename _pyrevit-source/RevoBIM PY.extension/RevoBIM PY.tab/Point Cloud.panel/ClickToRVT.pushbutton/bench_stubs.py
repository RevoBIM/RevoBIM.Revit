# -*- coding: utf-8 -*-
"""A stub .NET / Revit API for the bench (CPython only).

Each namespace declares the names the real API puts in it, so importing a
name from the wrong namespace fails here the way it fails in Revit. The
stubs themselves do nothing: they can be called, subclassed, indexed,
OR-ed together and have any attribute read.
"""
import sys
import types

NAMESPACES = {
    'System': ['Action', 'AppDomain', 'TimeSpan', 'EventHandler', 'Double', 'Byte', 'Int64', 'DateTime',
               'Exception', 'Array', 'Object', 'String', 'Math'],
    'System.IO': ['File', 'MemoryStream', 'FileStream', 'FileMode', 'FileAccess', 'Path', 'Directory'],
    'System.Collections.Generic': ['List', 'Dictionary'],
    'System.Windows': ['Thickness', 'HorizontalAlignment', 'VerticalAlignment', 'FontWeights', 'GridLength',
                       'GridUnitType', 'WindowStartupLocation', 'Point', 'Window', 'Visibility', 'SizeToContent',
                       'PresentationSource', 'SystemParameters', 'WindowStyle', 'ResourceDictionary',
                       'CornerRadius', 'TextWrapping', 'FrameworkElement', 'UIElement'],
    'System.Windows.Controls': ['StackPanel', 'Orientation', 'Grid', 'ColumnDefinition', 'RowDefinition',
                                'TextBlock', 'CheckBox', 'ComboBox', 'Button', 'Border', 'TextBox', 'Canvas',
                                'ScrollViewer', 'WrapPanel', 'Image', 'DockPanel', 'RadioButton'],
    'System.Windows.Controls.Primitives': ['Thumb', 'Popup', 'ToggleButton'],
    'System.Windows.Input': ['Key', 'Keyboard', 'ModifierKeys', 'Cursors', 'MouseButtonState'],
    'System.Windows.Interop': ['WindowInteropHelper'],
    'System.Windows.Markup': ['XamlReader'],
    'System.Windows.Media': ['SolidColorBrush', 'ColorConverter', 'Geometry', 'PointCollection', 'Stretch',
                             'Color', 'Brushes', 'VisualTreeHelper'],
    'System.Windows.Media.Animation': ['DoubleAnimation', 'Storyboard'],
    'System.Windows.Media.Imaging': ['BitmapImage', 'BitmapCacheOption'],
    'System.Windows.Shapes': ['Path', 'Rectangle', 'Polygon', 'Shape', 'Ellipse', 'Line', 'Polyline'],
    'System.Windows.Threading': ['DispatcherTimer', 'DispatcherPriority', 'Dispatcher'],
    'System.Windows.Forms': ['Screen'],
    'Autodesk.Revit.DB': ['XYZ', 'Plane', 'PointCloudInstance', 'FilteredElementCollector', 'Level', 'Line',
                          'CurveLoop', 'Curve', 'BuiltInParameter', 'BuiltInCategory', 'FamilySymbol', 'WallType',
                          'WallKind', 'FloorType', 'CeilingType', 'Wall', 'Floor', 'Ceiling',
                          'ElementTransformUtils', 'RoutingPreferenceRuleGroupType', 'Element', 'Transaction',
                          'TransactionStatus', 'IFailuresPreprocessor', 'FailureSeverity',
                          'FailureProcessingResult', 'ElementId', 'ConnectorProfileType', 'SubTransaction',
                          'TransactionGroup', 'Transform', 'BoundingBoxXYZ', 'View3D', 'MEPSize'],
    'Autodesk.Revit.DB.PointClouds': ['PointCloudFilterFactory', 'CloudPoint', 'PointCloudFilter'],
    'Autodesk.Revit.DB.Plumbing': ['Pipe', 'PipeType', 'PipingSystemType', 'PipeSegment'],
    'Autodesk.Revit.DB.Mechanical': ['Duct', 'DuctType', 'MechanicalSystemType', 'DuctSizeSettings', 'DuctShape'],
    'Autodesk.Revit.DB.Electrical': ['CableTray', 'CableTrayType', 'Conduit', 'ConduitType', 'CableTraySizes',
                                     'ConduitSizeSettings'],
    'Autodesk.Revit.DB.Structure': ['StructuralType'],
    'Autodesk.Revit.UI': ['IExternalEventHandler', 'ExternalEvent', 'TaskDialog', 'UIThemeManager', 'UITheme'],
    'Autodesk.Revit.UI.Selection': ['ObjectType', 'ISelectionFilter'],
}


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _make(name)

    def __or__(cls, other):
        return cls

    def __and__(cls, other):
        return cls

    def __iter__(cls):
        return iter([])


class Stub(object, metaclass=_Meta):
    def __init__(self, *a, **k):
        pass

    def __call__(self, *a, **k):
        return Stub()

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return Stub()

    def __iter__(self):
        return iter([])

    def __getitem__(self, k):
        return Stub()

    def __setitem__(self, k, v):
        pass

    def __iadd__(self, other):
        return self

    def __isub__(self, other):
        return self

    def __or__(self, other):
        return self

    def __and__(self, other):
        return self


def _make(name):
    return _Meta(str(name), (Stub,), {})


class _Namespace(types.ModuleType):
    def __init__(self, name, members):
        types.ModuleType.__init__(self, name)
        self.__path__ = []
        self._members = set(members)

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        full = self.__name__ + '.' + name
        if full in sys.modules:
            return sys.modules[full]
        if name in self._members:
            v = _make(name)
            setattr(self, name, v)
            return v
        raise AttributeError('{0} has no {1}'.format(self.__name__, name))


def install():
    clr = types.ModuleType('clr')
    clr.References = []

    def add_reference(name):
        clr.References.append(name)
    clr.AddReference = add_reference
    sys.modules['clr'] = clr
    names = set(NAMESPACES)
    for ns in list(NAMESPACES):
        parts = ns.split('.')
        for k in range(1, len(parts)):
            names.add('.'.join(parts[:k]))
    for ns in sorted(names, key=lambda n: n.count('.')):
        mod = _Namespace(ns, NAMESPACES.get(ns, []))
        sys.modules[ns] = mod
        if '.' in ns:
            parent, child = ns.rsplit('.', 1)
            setattr(sys.modules[parent], child, mod)
