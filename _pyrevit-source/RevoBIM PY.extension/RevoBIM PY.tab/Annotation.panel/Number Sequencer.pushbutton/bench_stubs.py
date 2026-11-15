# -*- coding: utf-8 -*-
"""Stub Revit and .NET API for running Number Sequencer modules under plain
CPython. Every name is declared in the namespace the real API puts it in, so
a name imported from the wrong namespace fails here as it would in Revit.
Bench only - never imported by the tool."""

import sys
import types

NAMESPACES = {
    "System": ["Action", "AppDomain", "TimeSpan", "Int64", "Object", "EventHandler"],
    "System.Collections.Generic": ["List"],
    "System.IO": ["File", "MemoryStream"],
    "System.Windows": ["PresentationSource", "Visibility", "Thickness", "CornerRadius",
                       "FontWeights", "Clipboard", "GridLength", "VerticalAlignment",
                       "HorizontalAlignment", "TextWrapping", "TextTrimming", "GridUnitType", "Window",
                       "DragDrop", "DragDropEffects", "DataObject",
                       "LogicalTreeHelper", "DependencyObject", "FrameworkElement", "SystemParameters",
                       "Duration", "Size", "Point", "WindowStyle", "Int32Rect"],
    "System.Windows.Markup": ["XamlReader"],
    "System.Windows.Media.Animation": ["DoubleAnimation", "CubicEase", "EasingMode"],
    "System.Windows.Media": ["SolidColorBrush", "Color", "ColorConverter", "Geometry", "Brushes", "VisualTreeHelper",
                             "PenLineCap", "PenLineJoin", "RotateTransform", "MatrixTransform", "Matrix",
                             "CompositionTarget", "PixelFormats", "Stretch"],
    "System.Windows.Data": ["Binding", "RelativeSource", "RelativeSourceMode"],
    "System.Windows.Media.Imaging": ["BitmapImage", "BitmapCacheOption", "RenderTargetBitmap", "CroppedBitmap"],
    "System.Windows.Interop": ["WindowInteropHelper"],
    "System.Windows.Input": ["Key", "Cursors", "MouseButtonState", "Keyboard", "ModifierKeys"],
    "System.Windows.Forms": ["Screen"],
    "System.Windows.Controls": ["StackPanel", "Grid", "Border", "TextBlock", "CheckBox",
                                "ColumnDefinition", "ComboBoxItem", "Button", "ComboBox",
                                "DockPanel", "Dock", "Viewbox", "Control", "ContentControl",
                                "Orientation", "TextBox", "ContextMenu", "MenuItem", "Border", "Button",
                                "ScrollViewer", "WrapPanel", "ScrollBarVisibility", "Canvas", "Image"],
    "System.Windows.Controls.Primitives": ["Popup", "PlacementMode", "Thumb"],
    "System.Windows.Shapes": ["Path", "Shape"],
    "System.Windows.Threading": ["DispatcherTimer", "DispatcherPriority"],
    "Autodesk.Revit.DB": [
        "BoundingBoxXYZ", "FilteredElementCollector", "BuiltInCategory", "BuiltInParameter", "ElementId",
        "Element", "Transaction", "SubTransaction", "TransactionGroup", "FamilySymbol",
        "IndependentTag", "Reference", "TagOrientation", "StorageType", "SpecTypeId",
        "WorksharingUtils", "IFailuresPreprocessor", "FailureProcessingResult",
        "FailureSeverity", "ConnectorType", "ConnectorProfileType", "Domain",
        "LocationCurve", "LocationPoint", "FabricationPart", "XYZ", "ViewType",
        "MEPCurve", "FamilyInstance", "OverrideGraphicSettings", "FillPatternElement",
        "TemporaryViewMode", "ElementCategoryFilter", "Color", "ViewPlan", "ElementMulticategoryFilter", "View", "View3D", "ViewFamilyType", "ViewFamily", "ViewSheet",
    ],
    "Autodesk.Revit.DB.Mechanical": ["MechanicalSystem", "Duct"],
    "Autodesk.Revit.UI": ["IExternalEventHandler", "ExternalEvent", "TaskDialog",
                          "UIThemeManager"],
    "Autodesk.Revit.UI.Selection": ["ObjectType", "ISelectionFilter"],
}


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return "{0}.{1}".format(cls.__name__, name)

    def __getitem__(cls, item):
        return cls


def _stub(name):
    def __init__(self, *args, **kwargs):
        pass
    return _Meta(name, (object,), {"__init__": __init__})


def install():
    if "clr" not in sys.modules or not getattr(sys.modules["clr"], "_bench", False):
        clr = types.ModuleType("clr")
        clr._bench = True
        clr.AddReference = lambda name: None
        sys.modules["clr"] = clr
    for ns, names in NAMESPACES.items():
        parts = ns.split(".")
        for i in range(1, len(parts) + 1):
            mod_name = ".".join(parts[:i])
            if mod_name not in sys.modules:
                sys.modules[mod_name] = types.ModuleType(mod_name)
            if i > 1:
                setattr(sys.modules[".".join(parts[:i - 1])], parts[i - 1], sys.modules[mod_name])
        mod = sys.modules[ns]
        for n in names:
            if not hasattr(mod, n):
                setattr(mod, n, _stub(n))


def uninstall():
    for name in list(sys.modules):
        if name == "clr" or name == "System" or name.startswith("System.") \
                or name == "Autodesk" or name.startswith("Autodesk."):
            del sys.modules[name]
