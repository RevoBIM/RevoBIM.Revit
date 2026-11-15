# -*- coding: utf-8 -*-
"""RevoBIM PY - Service Spacing : bench check.

Loads the shipped modules against a stub Revit API that declares every name in
the namespace the real API puts it in, so a mis-namespaced import fails here
rather than in Revit as a blank white pyRevit window.  It also rejects
f-strings and bare .IntegerValue (allowed only inside the guarded eid_value
helper), both of which break on some of the Revit 2024-2027 range.

Run it with any Python 3:   python import_check.py
"""

import ast
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# the stub API - name : namespace it really lives in
# ---------------------------------------------------------------------------

NAMESPACES = {
    "Autodesk": [],
    "Autodesk.Revit": ["DB", "UI"],
    "Autodesk.Revit.DB": [
        "XYZ", "Transform", "ElementId", "BuiltInParameter", "BuiltInCategory",
        "Options", "Solid", "GeometryInstance", "ViewDetailLevel",
        "Transaction", "TransactionGroup", "SubTransaction",
        "IFailuresPreprocessor", "FailureSeverity", "FailureProcessingResult",
        "ElementTransformUtils", "InsulationLiningBase", "Line", "Curve",
        "Reference", "FilteredElementCollector", "Element",
    ],
    "Autodesk.Revit.DB.Plumbing": ["Pipe", "PipeInsulation", "PlumbingUtils"],
    "Autodesk.Revit.DB.Mechanical": ["Duct", "DuctInsulation"],
    "Autodesk.Revit.DB.Electrical": ["CableTray", "Conduit", "CableTrayFitting"],
    "Autodesk.Revit.UI": ["TaskDialog", "UIApplication", "UIDocument"],
    "Autodesk.Revit.UI.Selection": [
        "ISelectionFilter", "ObjectType", "Selection"],
    "System": ["Array", "String", "Exception"],
    "System.IO": ["StringReader", "MemoryStream", "File", "Path"],
    "System.Xml": ["XmlReader"],
    "System.Windows": ["Window", "Visibility", "Thickness"],
    "System.Windows.Markup": ["XamlReader"],
    "System.Windows.Media": ["SolidColorBrush", "Colors"],
    "System.Windows.Media.Imaging": ["BitmapImage", "BitmapCacheOption"],
    "System.Windows.Controls": ["Button", "TextBox", "ComboBox", "CheckBox"],
    "System.Diagnostics": ["Process", "ProcessStartInfo"],
    "System.Collections.Generic": ["List"],
    "pyrevit": ["forms", "script", "revit"],
}

# names that must NOT be importable from a namespace, because the real API
# puts them elsewhere and IronPython will throw at module load
FORBIDDEN = {
    "Autodesk.Revit.DB.Plumbing": ["RoutingPreferenceRuleGroupType"],
    "System": ["Uri"],
}


class _StubMeta(type):
    """Stubs are classes, so they can be subclassed the way the real API
    types are - IFailuresPreprocessor and ISelectionFilter both are."""

    def __getattr__(cls, item):
        return _Stub(cls.__name__ + "." + item)

    def __getitem__(cls, item):
        return cls

    def __iter__(cls):
        return iter([])


def _Stub(name):
    return _StubMeta(str(name), (object,), {})


def install_stubs():
    for namespace, names in NAMESPACES.items():
        module = types.ModuleType(namespace)
        for name in names:
            setattr(module, name, _Stub(namespace + "." + name))
        # a submodule must also be reachable as an attribute of its parent
        sys.modules[namespace] = module
    for namespace, names in NAMESPACES.items():
        if "." not in namespace:
            continue
        parent_name, _, leaf = namespace.rpartition(".")
        parent = sys.modules.get(parent_name)
        if parent is not None:
            setattr(parent, leaf, sys.modules[namespace])

    clr = types.ModuleType("clr")
    clr.AddReference = lambda *args, **kwargs: None
    clr.GetClrType = lambda *args, **kwargs: None
    sys.modules["clr"] = clr


# ---------------------------------------------------------------------------
# source checks
# ---------------------------------------------------------------------------

def check_source(path, problems):
    handle = open(path, "r", encoding="utf-8")
    try:
        source = handle.read()
    finally:
        handle.close()

    try:
        tree = ast.parse(source, path)
    except SyntaxError as error:
        problems.append("{0}: will not parse - {1}".format(path, error))
        return

    for node in ast.walk(tree):
        if node.__class__.__name__ == "JoinedStr":
            problems.append(
                "{0}:{1} f-string - not available on IronPython 2.7".format(
                    os.path.basename(path), node.lineno))
        if isinstance(node, ast.Attribute) and node.attr == "IntegerValue":
            # allowed only inside the guarded helper
            if "def eid_value" not in source:
                problems.append(
                    "{0}:{1} bare .IntegerValue - removed in Revit 2026"
                    .format(os.path.basename(path), node.lineno))
        if isinstance(node, ast.ImportFrom) and node.module:
            declared = NAMESPACES.get(node.module)
            banned = FORBIDDEN.get(node.module, [])
            for alias in node.names:
                if alias.name in banned:
                    problems.append(
                        "{0}:{1} {2} is not in {3}".format(
                            os.path.basename(path), node.lineno, alias.name,
                            node.module))
                elif declared is not None and alias.name not in declared:
                    problems.append(
                        "{0}:{1} {2} not declared in {3}".format(
                            os.path.basename(path), node.lineno, alias.name,
                            node.module))


def check_xaml_names(problems):
    """Every FindName in the Python must have a matching x:Name in a layout,
    and every layout must be well-formed XML."""
    import re
    import xml.etree.ElementTree as ET

    names = set()
    for entry in os.listdir(HERE):
        if not entry.lower().endswith(".xaml"):
            continue
        path = os.path.join(HERE, entry)
        handle = open(path, "r", encoding="utf-8")
        try:
            text = handle.read()
        finally:
            handle.close()
        try:
            ET.fromstring(text)
        except Exception as error:
            problems.append("{0}: not well-formed XML - {1}".format(
                entry, error))
        for match in re.finditer(r'x:Name="([^"]+)"', text):
            names.add(match.group(1))

    sources = ["results_window.py",
               os.path.join("Service Spacing.pushbutton", "script.py"),
               os.path.join("Settings.pushbutton", "script.py")]
    for relative in sources:
        path = os.path.join(HERE, relative)
        if not os.path.isfile(path):
            continue
        handle = open(path, "r", encoding="utf-8")
        try:
            text = handle.read()
        finally:
            handle.close()
        for match in re.finditer(r'FindName\("([^"]+)"\)', text):
            if match.group(1) not in names:
                problems.append("{0}: FindName('{1}') has no matching x:Name"
                                .format(os.path.basename(relative),
                                        match.group(1)))


def main():
    install_stubs()
    sys.path.insert(0, HERE)
    problems = []

    targets = ["service_spacing_core.py", "results_window.py"]
    for name in targets:
        check_source(os.path.join(HERE, name), problems)
    for folder in ("Service Spacing.pushbutton", "Settings.pushbutton"):
        path = os.path.join(HERE, folder, "script.py")
        if os.path.isfile(path):
            check_source(path, problems)

    check_xaml_names(problems)

    for name in targets:
        module_name = name[:-3]
        try:
            __import__(module_name)
        except Exception as error:
            problems.append("{0}: import failed - {1}: {2}".format(
                name, error.__class__.__name__, error))

    if problems:
        print("Service Spacing import check FAILED")
        for problem in problems:
            print("  - " + problem)
        return 1
    print("Service Spacing import check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
