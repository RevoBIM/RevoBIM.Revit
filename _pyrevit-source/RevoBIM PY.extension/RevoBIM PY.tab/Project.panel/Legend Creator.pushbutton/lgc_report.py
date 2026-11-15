# -*- coding: utf-8 -*-

"""Legend Creator - the debug report and its window.

Shown when Debug is ticked and on any crash, copied to the clipboard first.
Every part of it is guarded: it runs when something has already gone wrong.
"""

import io
import os
import re
import sys
import time

from pyrevit import DB, forms

from lgc_core import (REPORT_FILE, SETTINGS_DIR, SETTINGS_FILE, _DEBUG, _TRACE,
                      __version__, crash_text, err_text, log, swallowed)
from lgc_drawer import make_drawer
from lgc_model import element_name
from lgc_theme import apply_palette, load_window

# The active document, bound by lgc_app.bind_document() at the start of every
# run - never captured at import, which pyRevit may cache across runs and
# models.
doc = None


# ---------------------------------------------------------- the report
def _row(label, value):
    return u'  {0:<26}{1}'.format(label, value)


def environment_lines():
    out = []

    def add(label, getter):
        try:
            value = getter()
        except Exception as err:
            value = u'unavailable - {0}'.format(err_text(err))
        out.append(_row(label, value))

    def revit_app():
        from pyrevit import HOST_APP
        return HOST_APP.app

    def framework():
        from System.Runtime.InteropServices import RuntimeInformation
        return RuntimeInformation.FrameworkDescription

    def pyrevit_version():
        from pyrevit.versionmgr import get_pyrevit_version
        return get_pyrevit_version().get_formatted()

    def engine():
        impl = getattr(sys, 'implementation', None)
        name = getattr(impl, 'name', 'ironpython')
        return u'{0} {1}'.format(name, sys.version.replace('\n', ' '))

    def os_version():
        from System import Environment
        return Environment.OSVersion.VersionString

    add('Tool', lambda: u'Legend Creator {0}'.format(__version__))
    add('Revit', lambda: u'{0}'.format(revit_app().VersionName))
    add('Revit number / build', lambda: u'{0} / {1}'.format(
        revit_app().VersionNumber, revit_app().VersionBuild))
    add('Revit update', lambda: revit_app().SubVersionNumber)
    add('Revit language', lambda: revit_app().Language)
    add('pyRevit', pyrevit_version)
    add('Python engine', engine)
    add('.NET', framework)
    add('Windows', os_version)
    add('Tool folder', lambda: os.path.dirname(os.path.abspath(__file__)))
    add('Document', lambda: doc.Title)
    add('Workshared / cloud', lambda: u'{0} / {1}'.format(
        doc.IsWorkshared, getattr(doc, 'IsModelInCloud', '?')))
    add('Active view', lambda: u'{0} ({1})'.format(
        element_name(doc.ActiveView), doc.ActiveView.ViewType))
    add('Legend views', lambda: len([
        v for v in DB.FilteredElementCollector(doc).OfClass(DB.View)
        if v.ViewType == DB.ViewType.Legend and not v.IsTemplate]))
    add('Legend components', lambda: DB.FilteredElementCollector(doc)
        .OfCategory(DB.BuiltInCategory.OST_LegendComponents)
        .WhereElementIsNotElementType().GetElementCount())
    add('Debug tick', lambda: u'on' if _DEBUG['on'] else u'off')
    return out


def _uitheme_values():
    import Autodesk.Revit.UI as revit_ui
    manager = getattr(revit_ui, 'UIThemeManager')
    return u'canvas {0}, ui {1}'.format(
        getattr(manager, 'CurrentCanvasTheme', '-'),
        getattr(manager, 'CurrentTheme', '-'))


def _member(owner_path, name):
    """Look a .NET member up by name, raising if it is not there."""
    owner = DB
    for part in owner_path.split('.'):
        owner = getattr(owner, part)
    getattr(owner, name)


def _ui_member(owner, name):
    import Autodesk.Revit.UI as revit_ui
    getattr(getattr(revit_ui, owner), name)


def _source_names():
    """Every BuiltInParameter and BuiltInCategory the tool names.

    Read from the lgc_*.py modules themselves, so the probe list can never
    fall behind the code that depends on it.
    """
    folder = os.path.dirname(os.path.abspath(__file__))
    text = u''
    try:
        for name in sorted(os.listdir(folder)):
            if name.startswith('lgc_') and name.endswith('.py'):
                text += io.open(os.path.join(folder, name),
                                encoding='utf-8').read()
    except Exception:
        swallowed()
        return [], []
    bips = set(re.findall(r'BuiltInParameter\.([A-Z][A-Z0-9_]+)', text))
    bips |= set(re.findall(r"'([A-Z][A-Z0-9_]*_PARAM|ALL_MODEL_DESCRIPTION)'",
                           text))
    bics = set(re.findall(r'\b(OST_[A-Za-z0-9_]+)\b', text))
    return sorted(bips), sorted(bics)


API_PROBES = [
    # Both probed by name: which of the two this Revit has is exactly the
    # question (IntegerValue was removed in 2026).
    ('ElementId.Value', lambda: getattr(DB.ElementId.InvalidElementId,
                                        'Value')),
    ('ElementId.IntegerValue', lambda: getattr(DB.ElementId.InvalidElementId,
                                               'IntegerValue')),
    ('UIThemeManager', _uitheme_values),
    ('Mechanical.MechanicalSystem',
     lambda: _member('Mechanical', 'MechanicalSystem')),
    ('Plumbing.PipingSystem', lambda: _member('Plumbing', 'PipingSystem')),
    ('MEPSystemType.LineColor', lambda: _member('MEPSystemType', 'LineColor')),
    ('MEPSystemType.SystemClassification',
     lambda: _member('MEPSystemType', 'SystemClassification')),
    ('FilledRegionType.LineWeight',
     lambda: _member('FilledRegionType', 'LineWeight')),
    ('FilledRegionType.ForegroundPatternColor',
     lambda: _member('FilledRegionType', 'ForegroundPatternColor')),
    ('FilledRegionType.IsMasking',
     lambda: _member('FilledRegionType', 'IsMasking')),
    ('FilledRegion.Create', lambda: _member('FilledRegion', 'Create')),
    ('Category.SetLineWeight', lambda: _member('Category', 'SetLineWeight')),
    ('Category.SetLinePatternId',
     lambda: _member('Category', 'SetLinePatternId')),
    ('LinePatternSegmentType.Dash',
     lambda: _member('LinePatternSegmentType', 'Dash')),
    ('LinePatternElement.Create',
     lambda: _member('LinePatternElement', 'Create')),
    ('TextNote.GetFormattedText',
     lambda: _member('TextNote', 'GetFormattedText')),
    ('TextNoteOptions.VerticalAlignment',
     lambda: _member('TextNoteOptions', 'VerticalAlignment')),
    ('ParameterFilterElement.GetElementFilter',
     lambda: _member('ParameterFilterElement', 'GetElementFilter')),
    ('ParameterFilterElement.GetRules (old)',
     lambda: _member('ParameterFilterElement', 'GetRules')),
    ('ElementParameterFilter.GetRules',
     lambda: _member('ElementParameterFilter', 'GetRules')),
    ('FilterStringRule.RuleString',
     lambda: _member('FilterStringRule', 'RuleString')),
    ('OverrideGraphicSettings.SurfaceForegroundPatternColor',
     lambda: _member('OverrideGraphicSettings',
                     'SurfaceForegroundPatternColor')),
    ('ElementTransformUtils.CopyElements',
     lambda: _member('ElementTransformUtils', 'CopyElements')),
    ('View.Duplicate', lambda: _member('View', 'Duplicate')),
    ('UIDocument.RequestViewChange',
     lambda: _ui_member('UIDocument', 'RequestViewChange')),
    ('DockablePanes.BuiltInDockablePanes',
     lambda: _ui_member('DockablePanes', 'BuiltInDockablePanes')),
    ('UI Automation', lambda: __import__('System.Windows.Automation')),
]


def api_probe_lines():
    out = []

    def probe(label, fn):
        try:
            value = fn()
            shown = u'' if value is None or isinstance(value, type(sys)) \
                else u'  = {0}'.format(value)
            out.append(u'  ok       {0}{1}'.format(label, shown))
        except Exception as err:
            out.append(u'  MISSING  {0}  - {1}'.format(label, err_text(err)))

    for label, fn in API_PROBES:
        probe(label, fn)

    bips, bics = _source_names()
    for label, enum_name, names in (('BuiltInParameters used',
                                     'BuiltInParameter', bips),
                                    ('BuiltInCategories used',
                                     'BuiltInCategory', bics)):
        # The enum itself is looked up under a guard too: this runs when
        # something has already failed, so it must not fail in turn.
        try:
            enum = getattr(DB, enum_name)
            missing = [n for n in names if getattr(enum, n, None) is None]
            out.append(_row(label, u'{0}, missing: {1}'.format(
                len(names), u', '.join(missing) or u'none')))
        except Exception as err:
            out.append(_row(label, u'could not read {0} - {1}'.format(
                enum_name, err_text(err))))
    return out


def settings_lines():
    try:
        text = io.open(SETTINGS_FILE, encoding='utf-8').read()
    except Exception as err:
        return [u'  (no settings file - {0})'.format(err_text(err))]
    return [u'  ' + line for line in text.splitlines() if line.strip()]


def build_report(reason):
    """The whole report as one block of text, most important part first."""
    out = [u'RevoBIM Legend Creator - debug report',
           u'Why shown: {0}'.format(reason),
           u'Copy everything in this box and paste it into the chat.',
           u'']

    if _TRACE['crash']:
        out += [u'== CRASH', _TRACE['crash'].rstrip(), u'']

    out += [u'== Environment'] + environment_lines() + [u'']
    out += [u'== Revit API on this machine'] + api_probe_lines() + [u'']

    order = _TRACE['order']
    out.append(u'== Errors absorbed ({0} distinct)'.format(len(order)))
    if not order:
        out.append(u'  none')
    for key in order[:250]:
        out.append(u'  x{0:<4} {1}: {2}'.format(
            _TRACE['absorbed'][key], key[0], key[1]))
    if len(order) > 250:
        out.append(u'  ... {0} more'.format(len(order) - 250))
    out.append(u'')

    out += [u'== Settings'] + settings_lines() + [u'']
    out += [u'== What happened'] + _TRACE['lines'] + [u'']
    return u'\n'.join(out)


def copy_to_clipboard(text):
    """Clipboard first, because it is the step most likely to get the report
    to Claude even if the window that shows it cannot open."""
    for _attempt in range(3):
        try:
            from System.Windows import Clipboard
            Clipboard.SetText(text)
            return True
        except Exception:
            time.sleep(0.15)
    return False


def report_crash(stage='run'):
    """Called from inside an except block: record the crash, then show it.
    A crash is always reported, Debug or not - it may come before the window
    and its Debug tick ever appear."""
    _TRACE['crash'] = crash_text()
    log(u'CRASH while trying to {0}'.format(stage))
    log(_TRACE['crash'])
    show_debug_report(u'the tool crashed while trying to {0}'.format(stage),
                      _TRACE.get('theme', 'dark'))


def show_debug_report(reason, theme_name='dark'):
    """Show the report, copied to the clipboard, saved when Debug is on.

    Falls back to a plain alert if the themed window itself will not load,
    since that may be the very failure being reported.
    """
    report = build_report(reason)
    copied = copy_to_clipboard(report)

    saved_to = u''
    if _DEBUG['on']:
        try:
            if not os.path.isdir(SETTINGS_DIR):
                os.makedirs(SETTINGS_DIR)
            handle = io.open(REPORT_FILE, 'w', encoding='utf-8')
            try:
                handle.write(report)
            finally:
                handle.close()
            saved_to = REPORT_FILE
        except Exception:
            saved_to = u''

    try:
        folder = os.path.dirname(__file__)
        window = DebugWindow(os.path.join(folder, 'LegendCreatorDebug.xaml'),
                             report, theme_name, copied, saved_to,
                             bool(_TRACE['crash']))
        window.show_dialog()
        return
    except Exception:
        fallback = crash_text()

    head = report[:1800]
    note = (u'\n\n... (cut short here)\n\nThe full report is on your '
            u'clipboard - paste it into the chat.' if copied else
            u'\n\n... (cut short here)')
    forms.alert(head + note + u'\n\nThe report window failed too:\n' +
                fallback[-600:], title='RevoBIM - Legend Creator - debug')


# ---------------------------------------------------------------------------
# Completion window
# ---------------------------------------------------------------------------
class DebugWindow(forms.WPFWindow):
    """The debug report, in one selectable block with a Copy button."""

    def __init__(self, xaml_path, report, theme_name, copied, saved_to,
                 crashed):
        load_window(self, xaml_path)
        self.version_tb.Text = 'v' + __version__
        apply_palette(self, theme_name)
        self.drawer = make_drawer(self)
        self.report = report

        self.header_bar.MouseLeftButtonDown += self.drag_window
        self.shrink_btn.Click += self.on_shrink
        self.close_btn.Click += self.dismiss
        self.done_btn.Click += self.dismiss
        self.copy_btn.Click += self.copy_clicked

        self.title_tb.Text = ('Legend Creator stopped with an error' if crashed
                              else 'Debug report')
        self.hint_tb.Text = (
            'Already copied to your clipboard - paste it straight into the '
            'chat.' if copied else
            'Click Copy report, then paste it into the chat.')
        self.where_tb.Text = (u'Also saved to {0}'.format(saved_to)
                              if saved_to else u'')
        self.report_tb.Text = report

    def copy_clicked(self, sender, args):
        if self.drawer.intercept():
            return
        if copy_to_clipboard(self.report):
            self.copy_btn.Content = 'Copied'
        else:
            # select it all so Ctrl+C works when the clipboard is busy
            self.report_tb.Focus()
            self.report_tb.SelectAll()
            self.copy_btn.Content = 'Press Ctrl+C'

    def drag_window(self, sender, args):
        if self.drawer.header_down(args):
            return
        try:
            self.DragMove()
        except Exception:
            pass

    def on_shrink(self, sender, args):
        self.drawer.toggle()

    def dismiss(self, sender, args):
        if sender is not self.close_btn and self.drawer.intercept():
            return
        self.Close()
