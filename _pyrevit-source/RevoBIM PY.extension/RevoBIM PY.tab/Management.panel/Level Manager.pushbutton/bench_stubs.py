# -*- coding: utf-8 -*-
"""Stub .NET and Revit API for the bench, run under plain CPython.

Every name is declared in the namespace the real API puts it in, so an import
from the wrong namespace fails here the way it would fail in Revit. Not
shipped as part of the tool's runtime - only import_check / bench_logic use it.
"""
import sys
import types

NAMESPACES = {
    "System": ["Action", "AppDomain", "TimeSpan", "DateTime", "Object", "String",
               "Double", "DBNull", "Int64", "Exception"],
    "System.IO": ["File", "MemoryStream", "Path", "Directory"],
    "System.Collections.Generic": ["List", "Dictionary", "HashSet"],
    "System.Data": ["DataTable", "DataColumn", "DataView", "DataRowView"],
    "System.Windows": [
        "Window", "Thickness", "Visibility", "GridLength", "GridUnitType",
        "HorizontalAlignment", "VerticalAlignment", "Clipboard", "FontWeights",
        "TextWrapping", "TextTrimming", "CornerRadius", "WindowStartupLocation",
        "PresentationSource", "ResourceDictionary", "WindowState", "FrameworkElement",
        "SystemParameters", "RoutedEventHandler", "DependencyObject",
        "SizeToContent", "Point",
    ],
    "System.Windows.Controls": [
        "DataGrid", "DataGridTemplateColumn", "DataGridTextColumn", "DataGridLength",
        "DataGridLengthUnitType", "StackPanel", "DockPanel", "TextBlock", "TextBox",
        "Button", "CheckBox", "Orientation", "Dock", "ListBoxItem", "ListBox",
        "Border", "Grid", "ColumnDefinition", "RowDefinition", "Canvas", "Viewbox",
        "Image", "ComboBox", "ScrollViewer", "Control",
    ],
    "System.Windows.Controls.Primitives": ["Popup", "PlacementMode", "Thumb", "ButtonBase"],
    "System.Windows.Data": ["Binding", "RelativeSource", "RelativeSourceMode", "IValueConverter"],
    "System.Windows.Input": ["Keyboard", "ModifierKeys", "Key", "Cursors", "Mouse"],
    "System.Windows.Markup": ["XamlReader"],
    "System.Windows.Media": ["VisualTreeHelper", "SolidColorBrush", "Color", "Geometry",
                             "Stretch", "Brushes"],
    "System.Windows.Media.Imaging": ["BitmapImage", "BitmapCacheOption"],
    "System.Windows.Shapes": ["Path", "Shape", "Rectangle", "Ellipse"],
    "System.Windows.Interop": ["WindowInteropHelper"],
    "System.Windows.Threading": ["DispatcherTimer", "DispatcherPriority", "Dispatcher"],
    "System.Windows.Forms": ["Screen", "Clipboard"],
    "Autodesk.Revit.DB": [
        "FilteredElementCollector", "Level", "ElementId", "BuiltInParameter",
        "BuiltInCategory", "CategoryType", "StorageType", "LocationPoint",
        "LocationCurve", "XYZ", "ElementTransformUtils", "WorksharingUtils",
        "MEPCurve", "FamilyInstance", "FabricationPart", "Transaction",
        "TransactionGroup", "SubTransaction", "IFailuresPreprocessor",
        "FailureProcessingResult", "FailureSeverity", "Element", "Wall", "Group",
        "View", "View3D", "ViewSheet", "Viewport", "ViewFamilyType", "ViewFamily",
        "ElementCategoryFilter", "BoundingBoxXYZ", "TemporaryViewMode", "Category",
    ],
    "Autodesk.Revit.UI": [
        "IExternalEventHandler", "ExternalEvent", "ExternalEventRequest",
        "TaskDialog", "TaskDialogCommonButtons", "TaskDialogResult",
        "UIThemeManager", "UIApplication",
    ],
}


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any(cls.__name__ + "." + name)


class _Any(object):
    """Stands in for anything: attribute, call, operator, iteration."""

    def __init__(self, name="any", *args, **kwargs):
        object.__setattr__(self, "_name", name if isinstance(name, str) else "any")

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any(self._name + "." + name)

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def __call__(self, *args, **kwargs):
        return _Any(self._name + "()")

    def __iadd__(self, other):
        return self

    def __isub__(self, other):
        return self

    def __or__(self, other):
        return self

    def __and__(self, other):
        return self

    def __iter__(self):
        return iter([])

    def __getitem__(self, key):
        return _Any(self._name + "[]")

    def __setitem__(self, key, value):
        pass

    def __bool__(self):
        return False

    __nonzero__ = __bool__

    def __str__(self):
        return self._name


def _make_class(name):
    return _Meta(name, (_Any,), {})


def install():
    """Put the stub namespaces into sys.modules. Idempotent."""
    if "clr" in sys.modules and getattr(sys.modules["clr"], "_bench_stub", False):
        return
    clr = types.ModuleType("clr")
    clr._bench_stub = True
    clr.references = []
    clr.AddReference = lambda name: clr.references.append(name)
    clr.GetClrType = lambda t: t
    sys.modules["clr"] = clr
    for ns, names in NAMESPACES.items():
        parts = ns.split(".")
        for i in range(1, len(parts) + 1):
            sub = ".".join(parts[:i])
            if sub not in sys.modules:
                mod = types.ModuleType(sub)
                sys.modules[sub] = mod
                if i > 1:
                    setattr(sys.modules[".".join(parts[:i - 1])], parts[i - 1], mod)
        mod = sys.modules[ns]
        for name in names:
            setattr(mod, name, _make_class(name))


def uninstall():
    for key in list(sys.modules.keys()):
        if key == "clr" or key.split(".")[0] in ("System", "Autodesk"):
            del sys.modules[key]
