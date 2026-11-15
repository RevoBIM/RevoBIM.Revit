# -*- coding: utf-8 -*-
"""Bench check for RevoBIM VlookUp. Run it before shipping:

    python import_check.py

It loads every shipped module against a stub Revit and .NET API that declares
each name in the namespace the real API puts it in, so an import written
against the wrong namespace fails here rather than showing up in Revit as a
blank white pyRevit window. It also enforces the house rules: no f-strings,
no print statements, no bare .IntegerValue outside the guarded helper, no
StaticResource in a layout file, and no FindName or DynamicResource key that
nothing defines.
"""

import ast
import io
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))

MODULES = ['xlsx_reader', 'vlookup_core', 'vlookup_ui', 'vlookup_window']
LAYOUTS = ['VlookUp.xaml', 'VlookUpResults.xaml', 'VlookUpPrompt.xaml']
THEME = 'Theme.xaml'

# Every name the shipped code asks for, in the namespace the real API puts it in.
NAMESPACES = {
    'clr': ['AddReference'],
    'System': ['DateTime', 'Array', 'Byte', 'Convert', 'String'],
    'System.IO': ['FileStream', 'FileMode', 'FileAccess', 'FileShare', 'MemoryStream',
                  'StreamReader', 'StringReader', 'File', 'Path', 'Directory'],
    'System.IO.Compression': ['ZipArchive', 'ZipArchiveMode', 'ZipFile'],
    'System.Text': ['Encoding'],
    'System.Xml': ['XmlReader', 'XmlReaderSettings', 'XmlNodeType', 'XmlDocument'],
    'System.Windows': ['Thickness', 'Visibility', 'GridLength', 'GridUnitType',
                       'TextTrimming', 'TextWrapping', 'VerticalAlignment',
                       'HorizontalAlignment', 'FontWeights', 'Clipboard', 'Window',
                       'MessageBox'],
    'System.Windows.Controls': ['Grid', 'ColumnDefinition', 'RowDefinition', 'TextBlock',
                                'Button', 'ComboBox', 'CheckBox', 'ToolTip', 'StackPanel',
                                'Orientation', 'Border', 'ScrollBarVisibility', 'ListBox'],
    'System.Windows.Input': ['Key', 'Cursors', 'Keyboard'],
    'System.Windows.Markup': ['XamlReader'],
    'System.Windows.Media': ['Brushes', 'SolidColorBrush', 'Colors'],
    'System.Windows.Media.Imaging': ['BitmapImage', 'BitmapCacheOption'],
    'System.Windows.Interop': ['WindowInteropHelper'],
    'Microsoft.Win32': ['OpenFileDialog', 'SaveFileDialog'],
    'Autodesk': [],
    'Autodesk.Revit': ['DB', 'UI'],
    'Autodesk.Revit.DB': ['StorageType', 'SpecTypeId', 'FilteredElementCollector',
                          'Material', 'Level', 'ElementId', 'UnitUtils', 'Transaction',
                          'IFailuresPreprocessor', 'FailureProcessingResult',
                          'BuiltInParameter', 'Element', 'Parameter'],
    'Autodesk.Revit.UI': ['TaskDialog', 'UIApplication', 'UIDocument'],
    'Autodesk.Windows': ['ComponentManager'],
}

# A .NET namespace only carries the names of assemblies the module itself has
# already referenced. Importing another module that references them does not
# help, because this module's own imports run first. Each namespace prefix
# below therefore has to be preceded, in the same file, by a clr.AddReference
# naming one of the assemblies listed against it.
ASSEMBLY_FOR = [
    ('System.Windows.Markup', ['System.Xaml', 'PresentationFramework']),
    ('System.Windows.Media.Imaging', ['PresentationCore']),
    ('System.Windows.Media', ['PresentationCore']),
    ('System.Windows.Controls', ['PresentationFramework']),
    ('System.Windows.Input', ['PresentationCore']),
    ('System.Windows.Interop', ['PresentationCore']),
    ('System.Windows', ['PresentationFramework']),
    ('System.Windows.Forms', ['System.Windows.Forms']),
    ('Microsoft.Win32', ['PresentationFramework']),
    ('System.Xml', ['System.Xml']),
    ('System.IO.Compression', ['System.IO.Compression', 'System.IO.Compression.FileSystem']),
    ('Autodesk.Revit', ['RevitAPI', 'RevitAPIUI']),
    ('Autodesk.Windows', ['AdWindows']),
]

failures = []
notes = []


def fail(message):
    failures.append(message)


def note(message):
    notes.append(message)


# ------------------------------------------------------------------ stub api

class StubModule(types.ModuleType):
    def __init__(self, name, declared):
        types.ModuleType.__init__(self, name)
        self._declared = set(declared)
        self._cache = {}

    def __getattr__(self, item):
        if item.startswith('_'):
            raise AttributeError(item)
        if item in self._cache:
            return self._cache[item]
        if item not in self._declared:
            raise AttributeError(
                '{0} does not live in {1} - check the namespace'.format(item, self.__name__))
        made = type(str(item), (object,), {'__stub__': True})
        self._cache[item] = made
        return made


def install_stubs():
    for name, declared in NAMESPACES.items():
        module = StubModule(name, declared)
        sys.modules[name] = module
    for name in NAMESPACES:
        if '.' in name:
            parent, leaf = name.rsplit('.', 1)
            if parent in sys.modules:
                setattr(sys.modules[parent], leaf, sys.modules[name])
                sys.modules[parent]._declared.add(leaf)

    def add_reference(_name):
        return None
    sys.modules['clr'].AddReference = add_reference
    sys.modules['clr'].AddReferenceByName = add_reference

    # IFailuresPreprocessor is subclassed at module load, so it must be a class
    revit_db = sys.modules['Autodesk.Revit.DB']
    revit_db._cache['IFailuresPreprocessor'] = type('IFailuresPreprocessor', (object,), {})


# ------------------------------------------------------------------ source rules

F_STRING = re.compile(r'(^|[^A-Za-z0-9_\'"])[fF]["\']')
PRINT_STATEMENT = re.compile(r'^\s*print\s+[^(=]')


def read(path):
    handle = io.open(path, 'r', encoding='utf-8')
    try:
        return handle.read()
    finally:
        handle.close()


def check_sources():
    for name in MODULES + ['script']:
        path = os.path.join(HERE, name + '.py')
        if not os.path.isfile(path):
            fail('{0}.py is missing'.format(name))
            continue
        text = read(path)
        try:
            tree = ast.parse(text)
        except SyntaxError as err:
            fail('{0}.py will not parse: {1}'.format(name, err))
            continue

        for number, line in enumerate(text.split('\n'), 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            if F_STRING.search(line):
                fail('{0}.py line {1}: f-string - IronPython 2.7 cannot parse it'
                     .format(name, number))
            if PRINT_STATEMENT.match(line):
                fail('{0}.py line {1}: print statement'.format(name, number))

        guarded = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'eid_value':
                for inner in ast.walk(node):
                    if hasattr(inner, 'lineno'):
                        guarded.add(inner.lineno)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == 'IntegerValue':
                if node.lineno not in guarded:
                    fail('{0}.py line {1}: bare .IntegerValue - gone in Revit 2026'
                         .format(name, node.lineno))

        check_assembly_references(name, text, tree)


def _reference_lines(text, assembly):
    """Line numbers carrying a clr.AddReference for this assembly, loop or not."""
    found = []
    quoted = ("'" + assembly + "'", '"' + assembly + '"')
    for number, line in enumerate(text.split('\n'), 1):
        if line.strip().startswith('#'):
            continue
        for token in quoted:
            if token in line:
                found.append(number)
                break
    return found


def check_assembly_references(name, text, tree):
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        for prefix, assemblies in ASSEMBLY_FOR:
            if node.module != prefix and not node.module.startswith(prefix + '.'):
                continue
            ok = False
            for assembly in assemblies:
                for line in _reference_lines(text, assembly):
                    if line < node.lineno:
                        ok = True
                        break
                if ok:
                    break
            if not ok:
                fail('{0}.py line {1}: imports from {2} with no clr.AddReference for '
                     '{3} above it - the name will not resolve in Revit'
                     .format(name, node.lineno, node.module, ' or '.join(assemblies)))
            break


# ------------------------------------------------------------------ xaml rules

def check_xaml():
    theme_path = os.path.join(HERE, THEME)
    if not os.path.isfile(theme_path):
        fail('{0} is missing'.format(THEME))
        return
    theme_text = read(theme_path)
    theme_keys = set(re.findall(r'x:Key="([^"]+)"', theme_text))
    names = set()

    for layout in LAYOUTS:
        path = os.path.join(HERE, layout)
        if not os.path.isfile(path):
            fail('{0} is missing'.format(layout))
            continue
        text = read(path)
        names.update(re.findall(r'x:Name="([^"]+)"', text))
        if 'StaticResource' in text:
            fail('{0} uses StaticResource - the theme is merged after parsing, '
                 'so only DynamicResource works'.format(layout))
        for key in re.findall(r'DynamicResource ([^}]+)\}', text):
            if key.strip() not in theme_keys:
                fail('{0} asks for "{1}", which {2} does not define'
                     .format(layout, key.strip(), THEME))

    # template parts inside the theme are legitimate FindName targets too
    names.update(re.findall(r'x:Name="([^"]+)"', theme_text))

    for name in MODULES + ['script']:
        path = os.path.join(HERE, name + '.py')
        if not os.path.isfile(path):
            continue
        text = read(path)
        for wanted in re.findall(r'FindName\([\'"]([^\'"]+)[\'"]\)', text):
            if wanted not in names:
                fail('{0}.py calls FindName("{1}") but no layout declares it'
                     .format(name, wanted))
        for wanted in re.findall(r'FindResource\([\'"]([^\'"]+)[\'"]\)', text):
            if wanted not in theme_keys:
                fail('{0}.py asks for the resource "{1}", which {2} does not define'
                     .format(name, wanted, THEME))

    try:
        import xml.etree.ElementTree as elementtree
        for layout in LAYOUTS + [THEME]:
            path = os.path.join(HERE, layout)
            if os.path.isfile(path):
                elementtree.parse(path)
    except Exception as err:
        fail('XAML will not parse as XML: {0}'.format(err))


# ------------------------------------------------------------------ imports

def check_imports():
    install_stubs()
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    for name in MODULES:
        try:
            __import__(name)
            note('imported {0}'.format(name))
        except Exception as err:
            fail('{0} will not import: {1}: {2}'.format(name, type(err).__name__, err))


def main():
    check_sources()
    check_xaml()
    check_imports()
    output = []
    for line in notes:
        output.append('  ok   ' + line)
    for line in failures:
        output.append('  FAIL ' + line)
    output.append('')
    if failures:
        output.append('{0} problem(s) found.'.format(len(failures)))
    else:
        output.append('All checks passed.')
    sys.stdout.write('\n'.join(output) + '\n')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
