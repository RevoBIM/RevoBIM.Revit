# -*- coding: utf-8 -*-
"""A stub Revit and .NET API for the bench, run under plain CPython.

Each name is declared in the namespace the real API puts it in, and ONLY
there - so a mis-namespaced import fails here instead of showing up in
Revit as a blank white pyRevit window. Add a name to KNOWN only after
checking where the real API keeps it.
"""

import sys
import types

KNOWN = {
    "System": ["Action", "AppDomain", "TimeSpan", "Exception", "Int64",
               "String", "Environment", "Uri", "Double"],
    "System.IO": ["MemoryStream", "File", "StringReader", "Path"],
    "System.Collections.Generic": ["List", "Dictionary"],
    "System.Windows": ["Window", "Thickness", "GridLength", "GridUnitType",
                       "HorizontalAlignment", "VerticalAlignment",
                       "Visibility", "TextTrimming", "TextWrapping",
                       "Clipboard", "SystemParameters", "PresentationSource",
                       "FontWeights", "CornerRadius", "WindowStyle",
                       "WindowState", "ResourceDictionary", "SizeToContent"],
    "System.Windows.Controls": ["Grid", "ColumnDefinition", "RowDefinition",
                                "Border", "TextBlock", "StackPanel",
                                "ComboBox", "TextBox", "Button", "CheckBox",
                                "RadioButton", "ScrollViewer", "Image"],
    "System.Windows.Controls.Primitives": ["Thumb", "Popup", "ToggleButton"],
    "System.Windows.Markup": ["XamlReader"],
    "System.Windows.Media": ["SolidColorBrush", "ColorConverter", "Color",
                             "Brushes"],
    "System.Windows.Media.Imaging": ["BitmapImage", "BitmapCacheOption"],
    "System.Windows.Input": ["Cursors", "Key", "Keyboard", "ModifierKeys",
                             "Mouse"],
    "System.Windows.Interop": ["WindowInteropHelper"],
    "System.Windows.Threading": ["DispatcherTimer", "DispatcherPriority"],
    "System.Windows.Forms": ["Screen"],
    "Autodesk.Revit.DB": ["FilteredElementCollector", "BuiltInCategory",
                          "BuiltInParameter", "StorageType", "Transaction",
                          "TransactionGroup", "TransactionStatus",
                          "IFailuresPreprocessor", "FailureProcessingResult",
                          "FailureSeverity", "WorksharingUtils", "ElementId",
                          "Reference", "CheckoutStatus", "SpecTypeId",
                          "Element", "ElementType", "FamilySymbol",
                          "SubTransaction", "UnitUtils", "UnitTypeId"],
    "Autodesk.Revit.DB.Mechanical": ["Duct", "DuctType", "MechanicalUtils"],
    "Autodesk.Revit.DB.Plumbing": ["Pipe", "PlumbingUtils"],
    "Autodesk.Revit.UI": ["IExternalEventHandler", "ExternalEvent",
                          "TaskDialog", "UIApplication", "UIDocument"],
    "Autodesk.Revit.UI.Selection": ["ISelectionFilter", "ObjectType",
                                    "Selection"],
    "Autodesk.Revit.Exceptions": ["OperationCanceledException",
                                  "InvalidOperationException"],
}


class _Anything(object):
    """An attribute that exists and does nothing - enough for module-level
    code to load. Real behaviour is supplied by bench_logic where needed."""

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return _Anything()

    def __call__(self, *args, **kwargs):
        return _Anything()

    def __iadd__(self, other):
        return self


def _make_class(name):
    return type(name, (object,), {"__init__": lambda self, *a, **k: None})


def install(overrides=None):
    """Replace System, Autodesk and clr in sys.modules with stubs. overrides
    is {"Namespace.Name": object} for bench tests needing behaviour."""
    overrides = overrides or {}
    for key in list(sys.modules.keys()):
        if key == "clr" or key.split(".")[0] in ("System", "Autodesk"):
            del sys.modules[key]
    clr = types.ModuleType("clr")
    clr.AddReference = lambda name: None
    sys.modules["clr"] = clr
    for namespace, names in KNOWN.items():
        parts = namespace.split(".")
        for i in range(1, len(parts) + 1):
            prefix = ".".join(parts[:i])
            if prefix not in sys.modules:
                sys.modules[prefix] = types.ModuleType(prefix)
            if i > 1:
                setattr(sys.modules[".".join(parts[:i - 1])], parts[i - 1],
                        sys.modules[prefix])
        module = sys.modules[namespace]
        for name in names:
            full = namespace + "." + name
            if full in overrides:
                setattr(module, name, overrides[full])
            else:
                setattr(module, name, _make_class(name))
    return sys.modules


def forget(prefix="dar_"):
    for key in list(sys.modules.keys()):
        if key.startswith(prefix):
            del sys.modules[key]
