# -*- coding: utf-8 -*-
"""Bench tests for Legend Creator's pure logic.

Run outside Revit, beside the lgc_*.py modules:

    python bench_logic.py

Everything under test is imported from the modules that ship - lgc_logic,
lgc_core and lgc_drawer have no Revit or WPF imports at module level for
exactly this reason - so a test can never drift from the code it checks.
The debug report is the one part that needs Revit; it is imported against
stand-in modules that have nothing in them.

The colour tests exist because of a real crash. Revit returns a .NET Byte for
Color.Red, and '{0:02X}'.format(<Byte>) hands formatting to .NET, which reads
'02X' as a custom format string rather than "two hex digits". The result did
not parse back as hex and the window died on open. DotNetByte below imitates
that behaviour so the regression cannot come back unnoticed.
"""

import io
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import lgc_core                                           # noqa: E402
import lgc_drawer                                         # noqa: E402
from lgc_core import _TRACE, err_text, reset_trace, swallowed  # noqa: E402
from lgc_logic import (CENTRELINE_SEGMENTS, DEFAULT_LINE_WEIGHT,  # noqa: E402
                       PALETTES, PIPE_GROUP_OTHER, SYSTEM_KINDS,
                       SYSTEM_REFERENCE_SCALE, THEME_MARKER, apply_case,
                       channel, choose_template, clamp_weight, classify_pipe,
                       decode_colour_int, format_kv_list, format_mm,
                       grouped_entries, join_label, next_theme_mode,
                       parse_kv_list, phase_verdict, pick_theme,
                       read_theme_text, rgb_hex, safe_style_name, scaled_mm,
                       splice_theme, tidy_label, to_internal,
                       unique_view_name, unscaled_mm, usable_phase)

FAILURES = []


def check(label, got, want):
    if got == want:
        return
    FAILURES.append('{0}\n      got  {1!r}\n      want {2!r}'.format(
        label, got, want))


def kind(key):
    return [k for k in SYSTEM_KINDS if k['key'] == key][0]


SYS = SYSTEM_REFERENCE_SCALE

# ---------------------------------------------------------------------------
# Stand-ins for the .NET types
# ---------------------------------------------------------------------------
class DotNetByte(object):
    """Imitates System.Byte under IronPython: __format__ follows .NET rules."""

    def __init__(self, value):
        self.value = value

    def __format__(self, spec):
        if spec == '':
            return str(self.value)
        # .NET custom numeric format: '0' is a digit placeholder, anything
        # unrecognised is copied through literally. '02X' therefore yields
        # the number, then a literal '2X' - not zero-padded hex.
        if re.match(r'^0+\d*[A-Za-z]$', spec):
            return '{0}{1}'.format(self.value, spec[1:])
        return str(self.value)

    def __int__(self):
        return self.value

    def __eq__(self, other):
        return self.value == getattr(other, 'value', other)

    def __ne__(self, other):
        return not self.__eq__(other)


def parse_hex(hex_string):
    """What lgc_theme.brush() does with the string, minus the WPF call."""
    text = (hex_string or '').lstrip('#')
    if len(text) != 6:
        raise ValueError('expected six hex digits')
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_the_original_crash():
    """The exact 2.1.0 failure: .NET bytes through the old code path."""
    old = '#{0:02X}{1:02X}{2:02X}'.format(
        DotNetByte(1), DotNetByte(0), DotNetByte(0))
    check('old path still reproduces the bad string', old.startswith('#12X'),
          True)
    try:
        parse_hex(old)
        check('old path should not parse', True, False)
    except ValueError:
        pass                       # this is the crash, faithfully reproduced

    fixed = rgb_hex((DotNetByte(1), DotNetByte(0), DotNetByte(0)))
    check('fixed path on .NET bytes', fixed, '#010000')
    check('fixed path round trips', parse_hex(fixed), (1, 0, 0))


def test_colours():
    for label, rgb, want in [
            ('red', (255, 0, 0), '#FF0000'),
            ('yellow', (255, 255, 0), '#FFFF00'),
            ('salmon', (250, 128, 114), '#FA8072'),
            ('teal', (0, 128, 128), '#008080'),
            ('black', (0, 0, 0), '#000000'),
            ('.NET bytes', (DotNetByte(30), DotNetByte(144),
                            DotNetByte(255)), '#1E90FF')]:
        check('rgb_hex ' + label, rgb_hex(rgb), want)
        check('round trip ' + label, parse_hex(rgb_hex(rgb)),
              tuple(channel(c) for c in rgb))

    check('no colour falls back to grey', rgb_hex(None), '#9A9A9E')
    check('empty tuple falls back', rgb_hex(()), '#9A9A9E')
    check('out of range clamps high', rgb_hex((999, -5, 128)), '#FF0080')
    check('rubbish channel becomes 0', rgb_hex(('x', None, 10)), '#00000A')


def test_bad_hex_is_survivable():
    for bad in ['', None, '#', '#12', '#GGGGGG', 'not a colour', '#1234567']:
        try:
            parse_hex(bad)
            check('parse_hex should reject {0!r}'.format(bad), True, False)
        except (ValueError, TypeError, AttributeError):
            pass


def test_labels():
    for source, want in [
            ('EMERGENCY LIGHTING TRAY', 'EMERGENCY LIGHTING TRAY'),
            ('Containment - Emergency Lighting Tray',
             'Emergency Lighting Tray'),
            ('Containment_Fire Alarm Tray', 'Fire Alarm Tray'),
            ('Containment : Power and Lighting Trunking',
             'Power and Lighting Trunking'),
            ('CONTAINMENT - ICT TRAY', 'ICT TRAY'),
            ('Containment > LV Submain Tray', 'LV Submain Tray'),
            ('  Containment   PAVA  Tray  ', 'PAVA Tray'),
            ('BRC BTP Power Tray', 'BRC BTP Power Tray')]:
        check('tidy_label {0!r}'.format(source),
              tidy_label(source, 'containment'), want)

    check('token not present is harmless',
          tidy_label('Fire Alarm Tray', 'containment'), 'Fire Alarm Tray')
    check('label made only of the token survives as empty',
          tidy_label('Containment', 'containment'), '')


def test_scaling():
    check('swatch at the reference scale', scaled_mm(2500, 200, SYS), 2500.0)
    check('swatch at 1:100', scaled_mm(2500, 100, SYS), 1250.0)
    check('swatch at 1:50', scaled_mm(2500, 50, SYS), 625.0)

    for scale in (50, 100, 200, 500):
        paper = scaled_mm(2500, scale, SYS) / float(scale)
        check('paper width constant at 1:{0}'.format(scale),
              round(paper, 6), 12.5)

    base = {'w': 2500.0, 'h': 700.0, 'pitch': 1600.0}
    for _ in range(25):
        for scale in (50, 500, 100, 200):
            shown = dict((k, float(format_mm(scaled_mm(v, scale, SYS))))
                         for k, v in base.items())
            base = dict((k, unscaled_mm(v, scale, SYS)) for k, v in shown.items())
    check('no drift after 100 scale changes',
          dict((k, round(v, 6)) for k, v in base.items()),
          {'w': 2500.0, 'h': 700.0, 'pitch': 1600.0})


def test_theme_resolution():
    check('auto follows Revit dark', pick_theme('auto', 'dark'), 'dark')
    check('auto follows Revit light', pick_theme('auto', 'light'), 'light')
    check('auto with no Revit answer defaults dark',
          pick_theme('auto', None), 'dark')
    check('pinned dark ignores Revit', pick_theme('dark', 'light'), 'dark')
    check('pinned light ignores Revit', pick_theme('light', 'dark'),
          'light')
    check('a rubbish saved mode behaves as auto',
          pick_theme('purple', 'light'), 'light')
    check('a rubbish saved mode cycles back to dark',
          next_theme_mode('purple'), 'dark')

    # the shapes UITheme has actually printed as across releases
    for value, want in [('Dark', 'dark'), ('Light', 'light'),
                        ('UITheme.Dark', 'dark'), ('UITheme.Light', 'light'),
                        ('CanvasTheme.Dark', 'dark'), ('System.Dark', 'dark'),
                        ('Unknown', None), ('', None)]:
        check('reads {0!r}'.format(value), read_theme_text(value), want)


def test_theme_cycle():
    check('auto goes to dark', next_theme_mode('auto'), 'dark')
    check('dark goes to light', next_theme_mode('dark'), 'light')
    check('light returns to auto', next_theme_mode('light'), 'auto')

    seen, mode = [], 'auto'
    for _ in range(9):
        mode = next_theme_mode(mode)
        seen.append(mode)
    check('three clicks return to the start', seen[2], 'auto')
    check('nine clicks return to the start', seen[8], 'auto')
    check('every mode is reachable', sorted(set(seen)),
          ['auto', 'dark', 'light'])


def test_duct_labels():
    check('the worked example',
          join_label('IA', 'INTAKE AIR', 'Supply Air'), 'IA - INTAKE AIR')
    check('abbreviation only',
          join_label('EA', '', 'Exhaust Air'), 'EA')
    check('description only',
          join_label('', 'SUPPLY AIR', 'Supply Air'), 'SUPPLY AIR')
    check('neither falls back to the type name',
          join_label('', '', 'Mechanical Supply Air'),
          'Mechanical Supply Air')
    check('whitespace is trimmed, not joined blank',
          join_label('  SA  ', '  SUPPLY AIR ', 'x'), 'SA - SUPPLY AIR')
    check('a description already holding a dash survives',
          join_label('KE', 'KITCHEN - EXTRACT', 'x'),
          'KE - KITCHEN - EXTRACT')


def test_style_names():
    check('a plain name is untouched', safe_style_name('LEG_DUCT_IA - INTAKE AIR'),
          'LEG_DUCT_IA - INTAKE AIR')
    check('characters Revit refuses are replaced',
          safe_style_name('LEG_DUCT_A{B}C[D]'), 'LEG_DUCT_A-B-C-D-')
    check('a colon is replaced', safe_style_name('LEG_DUCT_A:B'),
          'LEG_DUCT_A-B')
    check('an empty name still yields something',
          safe_style_name('   '), 'Unnamed')


def test_packed_colours():
    check('red', decode_colour_int(255), (255, 0, 0))
    check('green', decode_colour_int(255 * 256), (0, 255, 0))
    check('blue', decode_colour_int(255 * 65536), (0, 0, 255))
    check('white', decode_colour_int(255 + 255 * 256 + 255 * 65536),
          (255, 255, 255))
    check('black', decode_colour_int(0), (0, 0, 0))
    check('a mixed value', decode_colour_int(30 + 144 * 256 + 255 * 65536),
          (30, 144, 255))
    check('Revit\'s "no colour" sentinel is rejected',
          decode_colour_int(-1), None)
    check('rubbish is rejected', decode_colour_int('x'), None)


    check('missing halves (None from an unset parameter)',
          join_label(None, None, 'Supply Air'), 'Supply Air')


def test_pipe_classification():
    for classification, want in [
            ('DomesticColdWater', 'Domestic'),
            ('DomesticHotWater', 'Domestic'),
            ('Domestic Cold Water', 'Domestic'),
            ('SupplyHydronic', 'Hydronic'),
            ('ReturnHydronic', 'Hydronic'),
            ('Sanitary', 'Sanitary & Vent'),
            ('Vent', 'Sanitary & Vent'),
            ('FireProtectWet', 'Fire Protection'),
            ('FireProtectDry', 'Fire Protection'),
            ('FireProtectPreaction', 'Fire Protection'),
            ('Fire Protection Other', 'Fire Protection'),
            ('OtherPipe', 'Other'),
            ('Condensate', 'Other'),
            ('', 'Other')]:
        check('{0!r} groups as'.format(classification),
              classify_pipe(classification), want)

    check('flow and return land together',
          classify_pipe('SupplyHydronic') == classify_pipe(
              'ReturnHydronic'), True)
    check('hot and cold domestic land together',
          classify_pipe('DomesticHotWater') == classify_pipe(
              'DomesticColdWater'), True)


def test_grouping():
    class Entry(object):
        def __init__(self, label, classification):
            self.label = label
            self.group = classify_pipe(classification)

    entries = [Entry('WP - WASTE PIPE', 'Sanitary'),
               Entry('FH - FIRE HYDRANT', 'FireProtectWet'),
               Entry('CWS - COLD WATER', 'DomesticColdWater'),
               Entry('LPHWF - FLOW', 'SupplyHydronic'),
               Entry('SVP - SOIL VENT PIPE', 'Vent'),
               Entry('CD - CONDENSATE', 'OtherPipe'),
               Entry('HWS - HOT WATER', 'DomesticHotWater'),
               Entry('LPHWR - RETURN', 'ReturnHydronic'),
               Entry('FS - SPRINKLER', 'FireProtectDry')]

    groups = grouped_entries(entries, kind('pipework'))
    headers = [g[0] for g in groups]
    check('headers, in classification order', headers,
          ['DOMESTIC PIPEWORK LEGEND', 'HYDRONIC PIPEWORK LEGEND',
           'SANITARY & VENT PIPEWORK LEGEND',
           'FIRE PROTECTION PIPEWORK LEGEND', 'OTHER PIPEWORK LEGEND'])
    check('every entry lands in exactly one group',
          sum(len(g[1]) for g in groups), len(entries))
    check('domestic holds both', len(groups[0][1]), 2)
    check('hydronic holds flow and return', len(groups[1][1]), 2)
    check('fire holds both', len(groups[3][1]), 2)

    class Bare(object):
        label = 'no group attribute'
    check('an entry with no group goes to Other',
          grouped_entries([Bare()], kind('pipework'))[0][0],
          '{0} PIPEWORK LEGEND'.format(PIPE_GROUP_OTHER).upper())

    single = grouped_entries(entries, kind('containment'))
    check('an ungrouped kind is one block', len(single), 1)
    check('and keeps its own heading', single[0][0], 'CONTAINMENT LEGEND')


def test_per_kind_heights():
    defaults = dict((k['key'], k['swatch_h']) for k in SYSTEM_KINDS)
    check('the shipped default string matches the kinds',
          parse_kv_list(lgc_core.DEFAULTS['sys_swatch_h'], {}), defaults)

    check('a saved list is read back',
          parse_kv_list('containment=700;ductwork=700;pipework=300', {}),
          defaults)
    check('a missing kind falls back to its default',
          parse_kv_list('pipework=250', defaults)['ductwork'], 700.0)
    check('and the one that is there wins',
          parse_kv_list('pipework=250', defaults)['pipework'], 250.0)
    check('a damaged entry is ignored',
          parse_kv_list('pipework=oops;ductwork=500', defaults)['pipework'],
          300.0)
    check('a zero is ignored',
          parse_kv_list('pipework=0', defaults)['pipework'], 300.0)
    check('rubbish leaves the defaults alone',
          parse_kv_list('!!!', defaults), defaults)
    check('empty leaves the defaults alone',
          parse_kv_list('', defaults), defaults)

    check('round trip', parse_kv_list(format_kv_list(defaults), {}), defaults)
    check('no stray separators in the written form',
          format_kv_list({'a': 1.0}), 'a=1')


def test_pipe_swatch_height():
    """75mm at 1:50 is what the house standard asks for."""
    at_reference = kind('pipework')['swatch_h']   # held at 1:200
    check('shows as 75 at 1:50',
          format_mm(scaled_mm(at_reference, 50, SYS)), '75')
    check('shows as 150 at 1:100',
          format_mm(scaled_mm(at_reference, 100, SYS)), '150')
    check('shows as 300 at 1:200',
          format_mm(scaled_mm(at_reference, 200, SYS)), '300')

    for scale in (50, 100, 200, 500):
        paper = scaled_mm(at_reference, scale, SYS) / float(scale)
        check('1.5mm on paper at 1:{0}'.format(scale), round(paper, 6), 1.5)

    check('typed at 1:50, stored at the reference',
          unscaled_mm(75.0, 50, SYS), 300.0)
    check('a pipe swatch is shorter than a tray one',
          scaled_mm(kind('pipework')['swatch_h'], 50, SYS) <
          scaled_mm(kind('containment')['swatch_h'], 50, SYS), True)


def test_centreline_pattern():
    """Line patterns are paper millimetres, so they never scale."""
    segments = CENTRELINE_SEGMENTS
    check('four segments', len(segments), 4)
    check('the order alternates',
          [s[0] for s in segments], ['dash', 'space', 'dash', 'space'])
    check('the lengths match the house pattern',
          [s[1] for s in segments], [5.0, 2.0, 2.0, 2.0])
    check('one repeat is 11mm on paper', sum(s[1] for s in segments), 11.0)


def test_line_weight():
    check('the default is 3', DEFAULT_LINE_WEIGHT, 3)
    check('a plain number', clamp_weight(5), 5)
    check('a string number', clamp_weight('3'), 3)
    check('a float rounds', clamp_weight(2.6), 3)
    check('zero clamps up', clamp_weight(0), 1)
    check('negative clamps up', clamp_weight(-4), 1)
    check('too big clamps down', clamp_weight(99), 16)
    check('the top of the range survives', clamp_weight(16), 16)
    check('rubbish falls back to the default', clamp_weight('heavy'), 3)
    check('None falls back to the default', clamp_weight(None), 3)


class Unprintable(Exception):
    def __str__(self):
        raise UnicodeEncodeError('ascii', u'', 0, 1, 'stand-in for .NET')

    def __repr__(self):
        return 'Unprintable()'


def test_units():
    check('one foot', to_internal(304.8), 1.0)
    check('a 2500mm swatch', round(to_internal(2500), 6), 8.202100)
    check('a 700mm swatch', round(to_internal(700), 6), 2.296588)
    check('takes a string number', to_internal('304.8'), 1.0)
    check('zero', to_internal(0), 0.0)


def test_err_text():
    check('first line only', err_text(Exception('first\nsecond')), u'first')
    check('non-ASCII survives', err_text(Exception(u'Pipe \u00d8110 \u2013 bad')),
          u'Pipe \u00d8110 \u2013 bad')
    check('an exception whose text cannot be read still gives something',
          err_text(Unprintable()), u'Unprintable()')


def _reads_a_missing_member(obj):
    try:
        return obj.IntegerValue
    except Exception:
        swallowed()
        return None


def test_swallowed():
    reset_trace()

    for _ in range(50):
        _reads_a_missing_member(object())
    check('fifty identical failures are one entry', len(_TRACE['order']), 1)
    key = _TRACE['order'][0]
    check('and counted fifty times', _TRACE['absorbed'][key], 50)
    check('named by the function that absorbed it',
          key[0].startswith(u'_reads_a_missing_member() line '), True)
    check('carrying the real message', 'IntegerValue' in key[1], True)
    check('written to the trace once, not fifty times',
          len([l for l in _TRACE['lines'] if 'absorbed' in l]), 1)

    swallowed()                          # outside any except block
    check('called with no exception, records nothing',
          len(_TRACE['order']), 1)


class _Missing(object):
    """A Revit that has none of what the tool expects: every member raises."""

    def __getattr__(self, name):
        raise AttributeError('stub has no {0}'.format(name))

    def __call__(self, *args, **kwargs):
        raise TypeError('stub cannot be called')


class _StubModule(types.ModuleType):
    """A module where every name exists and is a _Missing."""

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _Missing()


STUBBED = ['pyrevit', 'System', 'System.Windows', 'System.Windows.Media',
           'Autodesk', 'Autodesk.Revit', 'Autodesk.Revit.DB',
           'Autodesk.Revit.UI']
NEEDS_REVIT = ['lgc_model', 'lgc_theme', 'lgc_report']


def test_report_survives_any_revit():
    """The report is what shows when something has already gone wrong, so it
    must never fail itself. The real lgc_report, imported against a pyRevit,
    WPF and Revit that have nothing at all in them."""
    saved = dict((name, sys.modules.get(name)) for name in
                 STUBBED + NEEDS_REVIT)
    try:
        for name in STUBBED:
            sys.modules[name] = _StubModule(name)
        forms = _StubModule('pyrevit.forms')
        forms.WPFWindow = object          # a base class has to be a class
        sys.modules['pyrevit'].forms = forms
        for name in NEEDS_REVIT:
            sys.modules.pop(name, None)
        import lgc_report
        lgc_report.doc = _Missing()
        lgc_report.SETTINGS_FILE = os.path.join(HERE, 'no-such-settings.txt')
        reset_trace()
        lgc_core.log(u'start')
        _TRACE['crash'] = u'Traceback: stand-in crash\n'
        try:
            report = lgc_report.build_report(u'bench')
        except Exception as err:
            check('build_report survives a Revit with nothing in it',
                  repr(err), 'no exception')
            return
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        reset_trace()

    check('the crash comes first', report.index(u'== CRASH') <
          report.index(u'== Environment'), True)
    for section in (u'== Environment', u'== Revit API on this machine',
                    u'== Errors absorbed', u'== Settings',
                    u'== What happened'):
        check('has section ' + section, section in report, True)
    check('missing API is reported, not raised', u'MISSING' in report, True)
    check('a missing settings file is reported',
          u'no settings file' in report, True)
    check('the trace is included', u'start' in report, True)
    check('the version is stamped', lgc_core.__version__ in report, True)


def test_template_choice():
    names = ['_B_BS_01_ME_HVAC Ducting-DOC', '04_Documentation_Floorplan_'
             'Containment', 'Power Plans']
    # the model from the 2026 report: no default template, nothing saved
    model = ['_B_BS_01_ME_HVAC Ducting-DOC', 'E_Containment Plans',
             'Lighting Plans']
    index, why = choose_template(model, [0, 9, 0], '',
                                 '04_Documentation_Floorplan_Containment',
                                 True)
    check('the 2026 model: the template that has the filters',
          model[index], 'E_Containment Plans')
    check('and says why', 'most matching' in why, True)

    check('the default wins when present',
          choose_template(names, [0, 9, 4], '', names[1], True)[0], 1)
    check('last time beats the default',
          choose_template(names, [0, 9, 4], 'Power Plans', names[1],
                          True)[0], 2)
    check('a saved name no longer in the model is ignored',
          choose_template(model, [0, 9, 0], 'Gone', 'Also gone', True)[0], 1)
    index, why = choose_template(model, [0, 0, 0], '', 'Gone', True)
    check('nothing matches anywhere: first, and it says so',
          (index, 'nothing in this model matches' in why), (0, True))
    check('no templates at all', choose_template([], [], '', 'x', True)[0],
          -1)
    check('duct/pipe kinds ignore the counts',
          choose_template(model, [0, 9, 0], '', '', False)[0], 0)


def test_phase_filter():
    check('a real phase id is used', usable_phase(86961), 86961)
    check('0 is not a phase', usable_phase(0), None)
    check('-1 is not a phase', usable_phase(-1), None)
    check('nothing is not a phase', usable_phase(None), None)

    check('same phase kept', phase_verdict(86961, 86961), 'keep')
    check('other phase dropped', phase_verdict(86961, 12), 'other phase')
    check('an element with no phase is never kept by a phase filter',
          phase_verdict(86961, None), 'no phase')
    check('no filter keeps everything', phase_verdict(None, None), 'keep')
    # the 2.10 bug: an unreadable wanted phase compared as 0 against
    # phase-less elements, also 0, and kept them
    check('an unreadable phase cannot reach the comparison',
          phase_verdict(usable_phase(0), None), 'keep')


def test_case_and_names():
    check('upper', apply_case('Fire Damper fd30', 'upper'), 'FIRE DAMPER FD30')
    check('camel keeps codes', apply_case('FIRE DAMPER fd30 900x2100',
                                          'camel'),
          'Fire Damper fd30 900x2100')
    check('as written', apply_case('fIRE', 'asis'), 'fIRE')
    check('empty survives every case', apply_case('', 'camel'), '')

    taken = set(['WIP_Doors', 'WIP_Doors_2'])
    check('a free name is used as is',
          unique_view_name('WIP_Walls', taken), 'WIP_Walls')
    check('a taken name gets the next number',
          unique_view_name('WIP_Doors', taken), 'WIP_Doors_3')
    check('and that number is now taken too', 'WIP_Doors_3' in taken, True)


THEME = os.path.join(HERE, 'Theme.xaml')
LAYOUTS = ['LegendCreatorWindow.xaml', 'LegendCreatorDone.xaml',
           'LegendCreatorDebug.xaml']


def _read(name):
    handle = io.open(os.path.join(HERE, name), encoding='utf-8')
    try:
        return handle.read()
    finally:
        handle.close()


def test_theme_splice():
    """Every layout takes the shared theme and comes out as one well formed
    window, holding every key the theme defines."""
    import xml.etree.ElementTree as ET
    theme = _read('Theme.xaml')
    keys = set(re.findall(r'x:Key="([^"]+)"', theme))
    for name in LAYOUTS:
        merged = splice_theme(_read(name), theme)
        try:
            ET.fromstring(merged.encode('utf-8'))
            parsed = True
        except Exception:
            parsed = False
        check(name + ' parses once the theme is in', parsed, True)
        check(name + ' holds every theme key',
              sorted(keys - set(re.findall(r'x:Key="([^"]+)"', merged))), [])
        check(name + ' keeps no marker', THEME_MARKER in merged, False)

    for bad_layout, why in [('<Window/>', 'no marker'),
                            (THEME_MARKER * 2, 'two markers')]:
        try:
            splice_theme(bad_layout, theme)
            check('a layout with ' + why + ' is refused', False, True)
        except ValueError:
            pass
    try:
        splice_theme(THEME_MARKER, '<Grid/>')
        check('a theme that is not a dictionary is refused', False, True)
    except ValueError:
        pass


def _luminance(hex_string):
    out = []
    for i in (1, 3, 5):
        c = int(hex_string[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def _contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_palette_contrast():
    """Text stays readable on every surface it sits on, in both themes -
    4.5:1 for body text, which is what the dark palette was tuned to."""
    check('both palettes define the same keys',
          sorted(set(PALETTES['dark']) ^ set(PALETTES['light'])), [])
    for name, pal in sorted(PALETTES.items()):
        for ink in ('Ink', 'Muted'):
            for ground in ('Base', 'Card', 'Field', 'Bar', 'RowOddBrush',
                           'RowEvenBrush'):
                ratio = _contrast(pal[ink], pal[ground])
                check('{0}: {1} on {2} is {3:.2f}:1'.format(
                    name, ink, ground, ratio), ratio >= 4.5, True)

    # the theme's own brushes open dark before apply_palette runs, so they
    # must be the dark palette, or the window flashes another colour first
    theme = _read('Theme.xaml')
    for key, value in sorted(PALETTES['dark'].items()):
        declared = re.search(r'<SolidColorBrush x:Key="%s"\s+Color="#(?:FF)?'
                             r'([0-9A-Fa-f]{6})"' % key, theme)
        check('Theme.xaml declares {0}'.format(key), bool(declared), True)
        if declared:
            check('Theme.xaml default for {0} is the dark palette\'s'
                  .format(key), '#' + declared.group(1).upper(), value.upper())


# ---------------------------------------------------------------------------
# The drawer - the real class, from lgc_drawer, against stand-ins
# ---------------------------------------------------------------------------
class _Event(object):
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self, *args):
        for handler in list(self.handlers):
            handler(*args)


class _Edge(object):
    Top = 1.0
    Bottom = 1.0


class _Node(object):
    def __init__(self, visibility='Visible'):
        self.Visibility = visibility


class _Header(object):
    def __init__(self, parent):
        self.ActualHeight = 54.0
        self.CornerRadius = ('corner', '5,5,0,0')
        self.Parent = parent


class _Panel(object):
    def __init__(self):
        self.Children = []


class _Root(object):
    def __init__(self, window):
        self._window = window
        self.BorderThickness = _Edge()
        self.Height = float('nan')
        self.VerticalAlignment = 'Stretch'

    @property
    def ActualHeight(self):
        return self._window.Height


class _Button(object):
    Tag = None
    ToolTip = None
    Visibility = 'Visible'


class _Window(object):
    """Enough of a WPF Window for the drawer, refusing what WPF refuses:
    a Height below MinHeight does not take."""

    def __init__(self, left=300.0, top=100.0, height=820.0, min_height=600.0):
        self.Left = left
        self.Top = top
        self._height = height
        self.MinHeight = min_height
        self.SizeToContent = 'WidthAndHeight'
        self.PreviewKeyDown = _Event()
        self.Closed = _Event()
        self.activated = 0
        self.Content = _Root(self)
        self.grid = _Panel()
        self.header = _Header(self.grid)
        self.body = _Node()
        self.grips = _Node()
        self.overlay = _Node('Collapsed')        # already hidden before
        self.grid.Children = [self.header, self.body, self.grips,
                              self.overlay]
        self.button = _Button()

    @property
    def Height(self):
        return self._height

    @Height.setter
    def Height(self, value):
        self._height = max(value, self.MinHeight)

    @property
    def ActualHeight(self):
        return self._height

    def Activate(self):
        self.activated += 1


class _Clock(object):
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        self.now += 0.02
        return self.now


class _Timer(object):
    """Runs its ticks the moment it starts, until stopped."""
    made = []

    def __init__(self, milliseconds, callback):
        self.callback = callback
        self.running = False
        self.stops = 0
        _Timer.made.append(self)

    def Start(self):
        self.running = True
        for _ in range(500):
            if not self.running:
                return
            self.callback(None, None)

    def Stop(self):
        self.running = False
        self.stops += 1


class _UI(object):
    collapsed = 'Collapsed'
    top = 'Top'
    manual = 'Manual'
    nan = float('nan')
    key_h = 'H'
    key_enter = 'Return'
    key_escape = 'Escape'
    chord = False

    def corner(self, radius):
        return ('corner', radius)

    def ctrl_shift(self):
        return self.chord


class _Key(object):
    def __init__(self, key):
        self.Key = key
        self.Handled = False


class _Click(object):
    def __init__(self, count):
        self.ClickCount = count


AREA = (0.0, 0.0, 1920.0, 1040.0)


def _lift_drawer():
    """lgc_drawer's own namespace, with nothing parked from an earlier test.
    WPF never comes into it: the window, timer, screen and keys are all
    handed to the constructor."""
    del lgc_drawer._PARKED[:]
    return vars(lgc_drawer), []


def _drawer(space, window, ui=None, timer=None, area=AREA):
    return space['WindowDrawer'](
        window, window.header, window.button, clock=_Clock(),
        timer_factory=timer or _Timer, area=lambda w: area, ui=ui or _UI())


def test_drawer_maths():
    space, missing = _lift_drawer()
    check('the drawer module loads', missing, [])
    ease, top_of, reopen = (space['ease_out'], space['parked_top'],
                            space['reopen_rect'])

    check('ease starts at 0', ease(0.0), 0.0)
    check('ease ends at 1', ease(1.0), 1.0)
    check('ease clamps past the end', ease(3.0), 1.0)
    check('ease clamps before the start', ease(-1.0), 0.0)
    check('ease is front loaded', ease(0.5) > 0.5, True)

    check('parks 8px above the taskbar', top_of(0, 1040, 56), 976.0)
    check('a second bar stacks above the first',
          top_of(0, 1040, 56, slot=1), 976.0 - 60.0)
    check('a monitor above the primary parks on itself',
          top_of(-1080, 1040, 56), -1080 + 1040 - 8 - 56.0)

    check('not moved: straight back',
          reopen(300, 100, 820, 300, 976, 56, False, 0, 1040),
          (300, 100, 820))
    check('moved: opens upward from the bar, at its left',
          reopen(300, 100, 820, 900, 950, 56, True, 0, 1040),
          (900, 950 + 56 - 820, 820))
    check('moved to the top: kept on the screen',
          reopen(300, 100, 820, 50, 10, 56, True, 0, 1040), (50, 0, 820))
    check('taller than the screen: cut to fit',
          reopen(300, 100, 1500, 50, 500, 56, True, 0, 1040),
          (50, 0, 1040))
    check('moved on a monitor above the primary',
          reopen(300, -900, 820, 40, -200, 56, True, -1080, 1040),
          (40, -200 + 56 - 820, 820))


def test_drawer_round_trip():
    space, _missing = _lift_drawer()
    del space['_PARKED'][:]
    window = _Window()
    drawer = _drawer(space, window)
    check('starts with the shrink tooltip',
          window.button.ToolTip, space['SHRINK_TIP'])

    drawer.toggle()
    bar = 54.0 + 2.0
    check('parked', drawer.parked, True)
    check('no longer sliding', drawer.sliding, False)
    check('down to just the bar', window.Height, bar)
    check('landed 8px above the taskbar', window.Top, 1040 - 8 - bar)
    check('MinHeight relaxed while parked', window.MinHeight, 0)
    check('SizeToContent off while parked', window.SizeToContent, 'Manual')
    check('the body is put away', window.body.Visibility, 'Collapsed')
    check('the resize grips go with it', window.grips.Visibility,
          'Collapsed')
    check('the header itself stays', hasattr(window.header, 'Visibility'),
          False)
    check('the bar gets all four corners rounded',
          window.header.CornerRadius, ('corner', 5))
    check('the button turns into the green arrow', window.button.Tag,
          space['SHRUNK'])
    check('and says how to open it', window.button.ToolTip,
          space['EXPAND_TIP'])
    check('the slide timer was stopped', _Timer.made[-1].stops >= 1, True)
    check('the drawer is on the parked list', drawer in space['_PARKED'],
          True)

    drawer.toggle()
    check('open again', drawer.parked, False)
    check('back to its height', window.Height, 820.0)
    check('back to its place', (window.Left, window.Top), (300.0, 100.0))
    check('MinHeight put back', window.MinHeight, 600.0)
    check('SizeToContent put back', window.SizeToContent, 'WidthAndHeight')
    check('the body is back', window.body.Visibility, 'Visible')
    check('a panel hidden before stays hidden', window.overlay.Visibility,
          'Collapsed')
    check('the header corners put back', window.header.CornerRadius,
          ('corner', '5,5,0,0'))
    check('the body is unpinned', window.Content.Height != window.Content.Height,
          True)                                   # NaN again
    check('the body stretches again', window.Content.VerticalAlignment,
          'Stretch')
    check('the arrow is gone', window.button.Tag, None)
    check('the window is brought forward', window.activated, 1)
    check('off the parked list', drawer in space['_PARKED'], False)


def test_drawer_gestures():
    space, _missing = _lift_drawer()
    del space['_PARKED'][:]
    window = _Window()
    ui = _UI()
    drawer = _drawer(space, window, ui=ui)

    check('a click on an open window is left to drag it',
          drawer.header_down(_Click(2)), False)
    drawer.shrink()
    check('a single click on the bar is left to drag it',
          drawer.header_down(_Click(1)), False)
    check('a double click on the bar opens it',
          (drawer.header_down(_Click(2)), drawer.parked), (True, False))

    drawer.shrink()
    for key in ('Return', 'Escape'):
        if not drawer.parked:
            drawer.shrink()
        event = _Key(key)
        window.PreviewKeyDown.fire(window, event)
        check('{0} on the parked bar opens it'.format(key),
              (drawer.parked, event.Handled), (False, True))

    event = _Key('Return')
    window.PreviewKeyDown.fire(window, event)
    check('Enter on an open window is left alone', event.Handled, False)

    ui.chord = True
    window.PreviewKeyDown.fire(window, _Key('H'))
    check('Ctrl+Shift+H shrinks', drawer.parked, True)
    window.PreviewKeyDown.fire(window, _Key('H'))
    check('Ctrl+Shift+H opens', drawer.parked, False)
    ui.chord = False

    drawer.shrink()
    check('a default button pressed while parked reopens instead',
          (drawer.intercept(), drawer.parked), (True, False))
    check('and does nothing on an open window', drawer.intercept(), False)


def test_drawer_moved_bar():
    space, _missing = _lift_drawer()
    del space['_PARKED'][:]
    window = _Window()
    drawer = _drawer(space, window)
    drawer.shrink()
    window.Left, window.Top = 900.0, 950.0          # the user drags the bar
    drawer.expand()
    check('opens at the bar\'s left', window.Left, 900.0)
    check('opens upward from the bar', window.Top, 950.0 + 56.0 - 820.0)
    check('at full height', window.Height, 820.0)

    drawer.shrink()
    window.Left, window.Top = 40.0, 300.0           # dragged up high
    drawer.expand()
    check('dragged high: opens clamped to the top of the screen',
          (window.Left, window.Top), (40.0, 0.0))


def test_drawer_stacking():
    space, _missing = _lift_drawer()
    del space['_PARKED'][:]
    first, second = _Window(), _Window()
    one, two = _drawer(space, first), _drawer(space, second)
    one.shrink()
    two.shrink()
    check('the second bar parks above the first', second.Top,
          first.Top - 56.0 - 4.0)
    one.expand()
    one.shrink()
    check('the freed bottom slot is reused, not stacked onto the other',
          first.Top, 1040 - 8 - 56.0)
    check('so the two bars never overlap', first.Top != second.Top, True)

    taken = space['free_slot']
    check('free slot: none taken', taken(set()), 0)
    check('free slot: the gap below', taken(set([1])), 0)
    check('free slot: past the end', taken(set([0, 1])), 2)
    check('free slot: the gap between', taken(set([0, 2])), 1)
    second.Closed.fire(second, None)
    check('closing a parked window frees its slot',
          two in space['_PARKED'], False)


def test_drawer_failures():
    space, _missing = _lift_drawer()
    del space['_PARKED'][:]

    def no_timer(milliseconds, callback):
        raise RuntimeError('no dispatcher')

    window = _Window()
    drawer = _drawer(space, window, timer=no_timer)
    drawer.shrink()
    check('no timer: lands at once', (drawer.parked, window.Height),
          (True, 56.0))
    drawer.expand()
    check('no timer: opens at once', (drawer.parked, window.Height),
          (False, 820.0))

    class _Brittle(_Window):
        frames = 0

        @property
        def Top(self):
            return self._top

        @Top.setter
        def Top(self, value):
            _Brittle.frames += 1
            if _Brittle.frames == 3:
                raise ValueError('a frame that throws')
            self._top = value

    window = _Brittle()
    drawer = _drawer(space, window)
    drawer.shrink()
    check('a frame that throws still lands at the end',
          (drawer.parked, drawer.sliding, window.Top),
          (True, False, 1040 - 8 - 56.0))
    check('and the timer is stopped', _Timer.made[-1].running, False)
    # The bad third frame ends the slide there and then: one more write, the
    # end state. Ticking on past it would be a window juddering through
    # frames that are already failing.
    check('the slide stops at the first bad frame', _Brittle.frames, 4)

    window = _Window()
    drawer = _drawer(space, window)
    drawer.sliding = True
    drawer.toggle()
    check('a press mid-slide is ignored', drawer.parked, False)


def main():
    for test in [test_the_original_crash, test_colours,
                 test_bad_hex_is_survivable, test_labels, test_scaling,
                 test_theme_resolution, test_theme_cycle,
                 test_duct_labels, test_style_names,
                 test_packed_colours, test_pipe_classification,
                 test_grouping, test_per_kind_heights,
                 test_pipe_swatch_height, test_centreline_pattern,
                 test_line_weight, test_units, test_err_text,
                 test_swallowed, test_report_survives_any_revit,
                 test_template_choice, test_phase_filter,
                 test_case_and_names, test_theme_splice,
                 test_palette_contrast,
                 test_drawer_maths, test_drawer_round_trip,
                 test_drawer_gestures, test_drawer_moved_bar,
                 test_drawer_stacking, test_drawer_failures]:
        try:
            test()
        except Exception as err:
            # a crash inside one test is that test failing, not the bench
            FAILURES.append('{0} crashed: {1}: {2}'.format(
                test.__name__, type(err).__name__, err))

    if FAILURES:
        sys.stdout.write('{0} failure(s):\n'.format(len(FAILURES)))
        for item in FAILURES:
            sys.stdout.write('  - {0}\n'.format(item))
        return 1
    sys.stdout.write('bench logic passed\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
