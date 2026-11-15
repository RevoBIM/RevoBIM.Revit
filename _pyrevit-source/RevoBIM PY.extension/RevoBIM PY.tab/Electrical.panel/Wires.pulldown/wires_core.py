# -*- coding: utf-8 -*-
"""RevoBIM PY - Wires core.

Shared by the Auto Wire, Re-Route Wires, Reconnect Wires and Settings
buttons.
Written for IronPython 2.7 and IronPython 3, Revit 2024 - 2027.

No f-strings, no print statements, no System.Uri, no bare .IntegerValue.
"""

__version__ = "3.7.0"

import os
import math

import clr

# --- assemblies -------------------------------------------------------------
# Requested individually inside try/except so a name that does not exist on a
# given release is skipped rather than throwing at module load.
for _asm in ('RevitAPI', 'RevitAPIUI', 'System', 'System.Core', 'mscorlib',
             'PresentationCore', 'PresentationFramework', 'WindowsBase',
             'System.Xml', 'System.Xaml'):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    XYZ, ElementId, BuiltInCategory, BuiltInParameter, Domain,
    FilteredElementCollector, ElementMulticategoryFilter,
    Transaction, SubTransaction, StorageType,
    IFailuresPreprocessor, FailureProcessingResult, FailureSeverity,
    FamilyInstance, LocationPoint, LocationCurve,
)
from Autodesk.Revit.DB.Electrical import (
    Wire, WiringType, ElectricalSystem,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType


# --- units ------------------------------------------------------------------
# Revit's internal length unit is decimal feet on every release, so the
# conversion is a constant and needs no UnitUtils / UnitTypeId call (those
# moved between 2020 and 2021 and are not worth depending on here).
MM = 1.0 / 304.8


def mm(value):
    """Millimetres to Revit internal feet."""
    return float(value) * MM


def to_mm(value):
    """Revit internal feet to millimetres."""
    return float(value) / MM


# --- Revit version helpers --------------------------------------------------
def eid_value(element_id):
    """ElementId as a number. ElementId.IntegerValue was removed in Revit 2026."""
    if element_id is None:
        return 0
    try:
        return element_id.Value
    except Exception:
        pass
    try:
        return element_id.IntegerValue  # noqa - guarded fallback, 2024/2025 only
    except Exception:
        return 0


def same_id(a, b):
    if a is None or b is None:
        return False
    return eid_value(a) == eid_value(b)


# --- what counts as a wireable electrical element ---------------------------
# key -> (label, BuiltInCategory name)
CATEGORY_DEFS = [
    ('lighting_fixtures', 'Lighting Fixtures', 'OST_LightingFixtures'),
    ('electrical_fixtures', 'Electrical Fixtures', 'OST_ElectricalFixtures'),
    ('electrical_equipment', 'Electrical Equipment', 'OST_ElectricalEquipment'),
    ('lighting_devices', 'Lighting Devices', 'OST_LightingDevices'),
    ('data_devices', 'Data Devices', 'OST_DataDevices'),
    ('fire_alarm_devices', 'Fire Alarm Devices', 'OST_FireAlarmDevices'),
    ('communication_devices', 'Communication Devices', 'OST_CommunicationDevices'),
    ('security_devices', 'Security Devices', 'OST_SecurityDevices'),
    ('nurse_call_devices', 'Nurse Call Devices', 'OST_NurseCallDevices'),
    ('telephone_devices', 'Telephone Devices', 'OST_TelephoneDevices'),
    ('mechanical_equipment', 'Mechanical Equipment', 'OST_MechanicalEquipment'),
    ('generic_models', 'Generic Models', 'OST_GenericModel'),
]

DEFAULT_CATEGORIES = ('lighting_fixtures,electrical_fixtures,electrical_equipment,'
                      'lighting_devices,data_devices,fire_alarm_devices,'
                      'communication_devices,security_devices')
DEFAULT_CATEGORIES_PLACEHOLDER = DEFAULT_CATEGORIES


def builtin_category(name):
    """BuiltInCategory by name, or None where the release does not have it."""
    try:
        return getattr(BuiltInCategory, name)
    except Exception:
        return None


# --- settings ---------------------------------------------------------------
SETTINGS_DIR = os.path.join(os.getenv('APPDATA') or '', 'RevoBIM')
SETTINGS_PATH = os.path.join(SETTINGS_DIR, 'wires.txt')
# v1.0.0 shipped as "Wire Fix" and wrote here. Read it once if the new file
# does not exist yet, so a rename does not quietly reset everything.
LEGACY_SETTINGS_PATH = os.path.join(SETTINGS_DIR, 'wire_fix.txt')

SETTINGS_VERSION = 19

# The settings schema drives both the file and the dialog: one row per setting,
# (tab, section, kind, key, label, default, extra). Adding a power rule later
# means adding a row here and nothing else.
#   kind: 'check' | 'number' | 'text' | 'choice' | 'wiretype' | 'tagfamily'
#         | 'categories' | 'note'
SCHEMA = [
    # -- Circuits ------------------------------------------------------------
    ('Circuits', 'Drawing the run', 'choice', 'arc_sag_mode',
     'Arc depth measured as', 'span',
     'span=a share of the distance being spanned|'
     'paper=a fixed size on the sheet'),
    ('Circuits', 'Drawing the run', 'number', 'arc_sag_percent',
     'Arc depth, share of the span (%)', '18',
     'The depth of the arc at its middle. A share rather than a fixed size '
     'so every wire sweeps the same amount whatever it spans - a fixed size '
     'makes a short hop bulge hard and a long one look flat.'),
    ('Circuits', 'Drawing the run', 'number', 'arc_sag_paper_mm',
     'Arc depth on paper (mm), when measured that way', '3', ''),
    ('Circuits', 'Drawing the run', 'choice', 'arc_side',
     'Arc bulges to the', 'left', 'left|right'),
    ('Circuits', 'Drawing the run', 'choice', 'trim_from',
     'Trim the wire back from', 'extent',
     "extent=the family's plan extent, plus a gap|"
     'fixed=a fixed gap from the centre'),
    ('Circuits', 'Drawing the run', 'number', 'trim_gap_paper_mm',
     'Gap left at the symbol, on paper (mm)', '2', ''),
    ('Circuits', 'Drawing the run', 'number', 'trim_fixed_paper_mm',
     'Fixed trim from centre, on paper (mm)', '4', ''),
    ('Circuits', 'Drawing the run', 'choice', 'align_target',
     'Aim a wire end at', 'edge',
     'edge=the edge of the symbol|'
     'centre=the connector node, in the middle of the symbol|'
     'trim=short of the symbol, by the trim above'),
    ('Circuits', 'Drawing the run', 'number', 'trim_max_paper_mm',
     'Never trim back further than, on paper (mm)', '6',
     "A fitting's bounding box is not its symbol: a luminaire's box can be "
     'metres across, and a trim taken from it would drag the end of the wire '
     'most of the way back to the next vertex. This is the ceiling on it.'),
    ('Circuits', 'Drawing the run', 'number', 'align_tolerance_mm',
     'Already close enough within (mm)', '1', ''),
    ('Circuits', 'Drawing the run', 'number', 'align_max_gap_mm',
     'Close enough to the node (mm)', '25',
     'Revit refuses a vertex that lands on one it already has, so the end is '
     'walked in towards the node until it is accepted. This is how close '
     'counts as arrived - 25mm is half a millimetre on a 1:50 sheet.'),
    ('Circuits', 'Drawing the run', 'choice', 'align_method',
     'Align a wire end by', 'auto',
     # align_target has no part in 'auto'. It is only read by the move and
     # nudge methods, which aim at a computed point - and a computed point is
     # what got the ends collapsed, then buried in the symbol, then left
     # 400mm short, across three releases.
     'auto=re-docking it and letting Revit place it|'
     'redock=the same thing, named|'
     'auto+rebuild=and rebuilding the wire if neither works|'
     'move=moving the vertex only|'
     'nudge=shoving the vertex and walking it in|'
     'jiggle=disconnecting and reconnecting the end|'
     'rebuild=rebuilding the wire'),
    ('Circuits', 'Drawing the run', 'choice', 'wiring_type',
     'Wires are drawn as', 'arc',
     'arc=arc wires|chamfer=chamfered wires'),
    ('Circuits', 'Drawing the run', 'number', 'chamfer_angle_deg',
     'Chamfer leaves the fitting at (deg)', '45',
     'A chamfered wire is drawn as an angle off the fitting, a straight run '
     'across, and an angle back in - not as a faceted arc. This is the angle '
     'of the two cranks; the straight between them takes the rest.'),
    ('Circuits', 'Drawing the run', 'number', 'mid_vertices',
     'Vertices between the ends of each wire', '1',
     'At least 1. 1 puts a single vertex at the middle of every wire, '
     'offset from the straight line between its ends. More are splayed '
     'evenly along the same arc - so an arc wire sweeps through them and a '
     'chamfered wire facets round the curve.'),
    ('Circuits', 'Drawing the run', 'choice', 'vertex_mode',
     'That count is', 'each',
     'each=the same on every wire|'
     'length=shared out by how long each wire is'),

    ('Circuits', 'The route', 'check', 'two_opt',
     'Pull crossings out of the route', 'yes', ''),
    ('Circuits', 'The route', 'check', 'avoid_fittings',
     'Route clear of fittings not on the circuit', 'yes',
     'Routes that run a wire across a fitting belonging to another circuit '
     'are ranked below ones that do not, and a span is flipped to arc the '
     'other way where that clears it. What cannot be cleared is reported '
     'rather than quietly drawn through.'),
    ('Circuits', 'The route', 'number', 'clash_clearance_mm',
     'Keep this far clear of them (mm)', '150', ''),
    ('Circuits', 'The route', 'check', 'group_by_space',
     'Chain each space as its own leg', 'yes',
     'Lights in one space are chained together before the run moves on, and '
     'the span that bridges two spaces takes the permanent live wire type. '
     'Off, spaces are ignored and the route runs straight through them.'),
    ('Circuits', 'The route', 'check', 'group_by_switch',
     'Chain each switch system as its own leg', 'yes',
     'Lights on one switch are chained together, then the legs are joined - '
     'which is what puts one permanent live wire between rooms rather than '
     'the run hopping back and forth.'),
    ('Circuits', 'The route', 'check', 'modeless_shuffle',
     'Leave Revit usable while the Shuffle prompt is open', 'yes',
     'On, the prompt floats and the view can be panned and zoomed while a '
     'route is being judged. Off, it is a modal dialog - Revit is locked '
     'behind it, but the tool needs no persistent engine, which is the one '
     'to fall back to if the floating window misbehaves.'),
    ('Circuits', 'The route', 'check', 'preview_shuffle',
     'Offer Shuffle after placing', 'yes',
     'Places the circuit, then holds a small prompt open so the route can be '
     'reshuffled before it is kept.'),
    ('Circuits', 'The route', 'number', 'max_members',
     'Give up on a circuit above this many members', '200', ''),

    ('Circuits', 'Tags', 'check', 'tag_circuits',
     'Tag one wire per circuit', 'yes', ''),
    ('Circuits', 'Tags', 'tagfamily', 'wire_tag_family',
     'Wire tag family', '',
     'One tag family covers lighting and power - the tag reads the circuit '
     'off the wire, so it does not need to differ between them.'),
    ('Circuits', 'Tags', 'tagtype', 'wire_tag_type',
     'Wire tag type', '', ''),
    ('Circuits', 'Tags', 'choice', 'tag_which',
     'Tag goes on', 'homerun',
     'homerun=the home run, else the longest wire|longest=the longest wire|'
     'first=the first wire in the run'),
    ('Circuits', 'Tags', 'number', 'tag_offset_mm',
     'Tag offset from the wire (mm)', '250', ''),
    ('Circuits', 'Tags', 'check', 'tag_offset_is_paper',
     'That offset is a paper measurement', 'no',
     'Off, 250mm is a real distance and holds its position against the '
     'model at every scale. On, it is multiplied by the view scale and holds '
     'its position on the sheet instead.'),
    ('Circuits', 'Tags', 'check', 'tag_leader', 'Tag has a leader', 'yes', ''),

    ('Circuits', 'What is included', 'check', 'skip_wired_circuits',
     'Leave circuits that already have wires alone', 'yes', ''),
    ('Circuits', 'What is included', 'check', 'report_offscreen',
     'Say when a circuit has members outside this view', 'yes', ''),

    # -- Lighting ------------------------------------------------------------
    ('Lighting', 'Wire types', 'wiretype', 'lighting_wire_type',
     'Lighting wire', '', ''),
    ('Lighting', 'Wire types', 'wiretype', 'lighting_emergency_wire_type',
     'Lighting wire, emergency', '', ''),
    ('Lighting', 'Wire types', 'wiretype', 'lighting_live_wire_type',
     'Lighting wire, permanent live', '',
     'Used where the run crosses from one switch system to another - same '
     'circuit, different switch.'),
    ('Lighting', 'Wire types', 'parameter', 'emergency_parameter',
     'Parameter that marks an emergency fitting', 'BGL_Elec_IsEmergency',
     'Read off the fitting, instance first then type. Yes, true or 1 all '
     'count as emergency. A span with an emergency fitting at either end '
     'takes the emergency wire type.'),
    ('Lighting', 'Wire types', 'categories', 'lighting_categories',
     'Lighting categories', 'lighting_fixtures', ''),

    ('Lighting', 'Switches and home runs', 'check', 'switch_home_run',
     'Run the home run to the switch, not the panel', 'yes', ''),
    ('Lighting', 'Switches and home runs', 'check', 'remove_panel_home_runs',
     'Remove home runs pointing back to the panel', 'yes', ''),
    ('Lighting', 'Switches and home runs', 'check', 'end_chain_at_switch',
     'End the chain at the light the switch is wired to', 'yes', ''),
    ('Lighting', 'Switches and home runs', 'categories', 'switch_categories',
     'Switch categories', 'lighting_devices', ''),
    ('Lighting', 'Switches and home runs', 'choice', 'home_run_style',
     'The home run is', 'arrow',
     'arrow=a short arc from the light, pointing at the switch|'
     'full=a wire drawn all the way to the switch'),
    ('Lighting', 'Switches and home runs', 'number', 'home_run_arrow_paper_mm',
     'Length of that arc, on paper (mm)', '10',
     'A paper measurement multiplied by the view scale, so the arrow is the '
     'same length on every sheet. It is clamped so it can never reach the '
     'switch it points at. Always drawn with one middle vertex so it arcs.'),
    ('Lighting', 'Switches and home runs', 'check', 'draw_switch_line',
     'Draw a detail line from the light to the switch', 'yes', ''),
    ('Lighting', 'Switches and home runs', 'linestyle', 'switch_line_style',
     'Line style for it', '', ''),
    ('Lighting', 'Switches and home runs', 'check', 'stub_if_no_connection',
     'Draw a stub where the switch will not take a wire', 'yes', ''),

    # -- Power ---------------------------------------------------------------
    ('Power', 'Wire types', 'wiretype', 'power_wire_type',
     'Power wire', '', ''),
    ('Power', 'Wire types', 'categories', 'power_categories',
     'Power categories', 'electrical_fixtures,electrical_equipment', ''),

    ('Power', 'Routing', 'check', 'power_enabled',
     'Include power circuits in Auto Wire', 'no',
     'Off by default. Power shares the drawing, route and tag rules on the '
     'Circuits tab; the rules that differ are not written yet, so leaving '
     'this off keeps Auto Wire to lighting.'),
    ('Power', 'Routing', 'note', 'power_note', '', '',
     'Still to come: socket rings against radials, spurs off a ring, '
     'dedicated circuits taking a direct home run, and fused connection '
     'units chaining to the appliance rather than to the next socket.'),

    # -- Reconnect -----------------------------------------------------------
    ('Reconnect', 'Finding the element', 'number', 'search_radius_mm',
     'Look this far from a loose end (mm)', '600',
     'Measured in plan only. A ceiling light sits metres above the plan the '
     'wire is drawn on.'),
    ('Reconnect', 'Finding the element', 'check', 'require_circuit',
     'Only offer elements that already carry a circuit', 'yes', ''),
    ('Reconnect', 'Finding the element', 'check', 'require_unwired',
     'Only offer elements with no wire on them yet', 'yes', ''),
    ('Reconnect', 'Finding the element', 'check', 'match_system_type',
     "Match the connector's system type", 'yes', ''),
    ('Reconnect', 'Finding the element', 'categories', 'categories',
     'Categories searched', DEFAULT_CATEGORIES_PLACEHOLDER, ''),

    ('Reconnect', 'Making the join', 'check', 'snap_on_connect',
     'Pull the wire end onto the connector as it joins', 'yes', ''),
    ('Reconnect', 'Making the join', 'check', 'recreate_if_refused',
     'Rebuild the wire where Revit refuses the join in place', 'yes', ''),
    ('Reconnect', 'Making the join', 'warn', 'cross_circuit',
     'Join a wire to an element on a DIFFERENT circuit', 'no',
     'Off by default. On, a wire can be pulled onto a circuit it was never '
     'meant to be on, and nothing warns you.'),

    ('Running', 'Reporting', 'choice', 'show_results',
     'Show results', 'needed',
     'needed=Only if something needs a look|always=Always|never=Never'),
    ('Running', 'Reporting', 'check', 'debug_geometry',
     'Put the full wire geometry in the debug report', 'no',
     'Dumps every vertex, every connector and the fitting behind it for each '
     'wire touched. Slow and long, and the only way to see what Revit thinks '
     'a wire is made of when it will not do what it is told.'),
    ('Running', 'Reporting', 'check', 'debug_report',
     'Put a Debug button on the results window', 'yes',
     'Writes everything about the run - release, settings, what the lookups '
     'resolved to, and every line including the informational ones - to '
     '%APPDATA%\\RevoBIM\\wires_debug.txt, and copies it to the clipboard '
     'so it can be pasted straight into a message.'),
    ('Running', 'Reporting', 'check', 'keep_running',
     'Keep asking for wires until Escape', 'no', ''),
]

DEFAULTS = {'settings_version': str(SETTINGS_VERSION)}
for _row in SCHEMA:
    if _row[2] != 'note':
        DEFAULTS[_row[3]] = _row[5]
DEFAULTS['categories'] = DEFAULT_CATEGORIES
# Not on any tab: the theme chip in every window header saves it straight
# away. follow / dark / light - see wires_theme.
DEFAULTS['theme'] = 'follow'

TABS = []
for _row in SCHEMA:
    if _row[0] not in TABS:
        TABS.append(_row[0])

# A settings key whose meaning changes needs a migration, not just a new
# default. MIGRATIONS[version] lists the keys reset when loading an older file.
MIGRATIONS = {
    # 3: the wire tag stopped being two settings, one per domain, and became
    # one family plus one type on the Circuits tab.
    3: ['wire_tag_family', 'wire_tag_type'],
    # 4: three_vertices (yes/no) became mid_vertices (a count), and the tag
    # offset changed from paper millimetres to model millimetres - a saved 3
    # would be read as 3mm rather than 250mm.
    4: ['mid_vertices', 'tag_offset_mm', 'tag_offset_is_paper', 'tag_leader'],
    # 5: Tidy Wires was removed, the emergency wire type and its parameter
    # arrived, and the home run arrow changed from model to paper millimetres
    # - a saved 500 would be read as 500 paper mm, which is half a metre on
    # the sheet.
    5: ['home_run_arrow_paper_mm', 'lighting_emergency_wire_type',
        'emergency_parameter'],
    # 6: mid_vertices stopped being a fixed count per span and became the
    # count on a span of average length, so a saved 4 would now bunch.
    6: ['mid_vertices', 'group_by_space', 'draw_switch_line',
        'switch_line_style'],
    # 7: the arc became a true circle and its depth is a share of the span by
    # default, so the old paper figure no longer means the same thing.
    7: ['arc_sag_mode', 'arc_sag_percent'],
    8: ['avoid_fittings', 'clash_clearance_mm'],
    # 9: the vertex count went back to being per wire rather than shared out
    # across the circuit by span length.
    9: ['mid_vertices', 'vertex_mode'],
    # 10: arc or chamfer became a setting, and the vertex count gained a
    # floor of 1 - a saved 0 would now be read as 1.
    10: ['wiring_type', 'mid_vertices'],
    11: ['chamfer_angle_deg'],
    12: ['modeless_shuffle', 'debug_report'],
    13: ['align_target', 'align_tolerance_mm'],
    14: ['align_target', 'trim_max_paper_mm'],
    15: ['align_method'],
    16: ['align_method', 'debug_geometry'],
    17: ['align_method', 'align_max_gap_mm'],
    18: ['align_target', 'align_method'],
    19: ['align_method'],
}


def _settings_bool(settings, key):
    return str(settings.get(key, DEFAULTS.get(key, 'no'))).strip().lower() in (
        'yes', 'true', '1', 'on')


def _settings_float(settings, key):
    try:
        return float(str(settings.get(key, DEFAULTS.get(key, '0'))).strip())
    except Exception:
        try:
            return float(DEFAULTS.get(key, '0'))
        except Exception:
            return 0.0


def load_settings():
    """Read the settings file, falling back to the defaults key by key."""
    settings = {}
    for key in DEFAULTS:
        settings[key] = DEFAULTS[key]
    path = SETTINGS_PATH
    if not os.path.isfile(path) and os.path.isfile(LEGACY_SETTINGS_PATH):
        path = LEGACY_SETTINGS_PATH
    try:
        if os.path.isfile(path):
            handle = open(path, 'r')
            try:
                lines = handle.read().splitlines()
            finally:
                handle.close()
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                # split on the first '=' only, so a value may contain more
                key, value = line.split('=', 1)
                key = key.strip()
                if key in DEFAULTS:
                    settings[key] = value.strip()
    except Exception:
        pass

    # migrations - keys whose meaning changed are reset to the default
    try:
        was = int(settings.get('settings_version', '0'))
    except Exception:
        was = 0
    for version in sorted(MIGRATIONS.keys()):
        if was < version:
            for key in MIGRATIONS[version]:
                settings[key] = DEFAULTS.get(key, '')
    settings['settings_version'] = str(SETTINGS_VERSION)
    return settings


def save_settings(settings):
    try:
        if not os.path.isdir(SETTINGS_DIR):
            os.makedirs(SETTINGS_DIR)
        handle = open(SETTINGS_PATH, 'w')
        try:
            handle.write('# RevoBIM PY - Wires settings\n')
            handle.write('# version {0}\n'.format(__version__))
            for key in sorted(DEFAULTS.keys()):
                handle.write('{0}={1}\n'.format(key, settings.get(key, DEFAULTS[key])))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def active_categories(settings):
    """The BuiltInCategory list the search runs over."""
    wanted = []
    raw = str(settings.get('categories', DEFAULT_CATEGORIES))
    keys = [k.strip() for k in raw.split(',') if k.strip()]
    for key, _label, bic_name in CATEGORY_DEFS:
        if key in keys:
            bic = builtin_category(bic_name)
            if bic is not None:
                wanted.append(bic)
    if not wanted:
        for key, _label, bic_name in CATEGORY_DEFS:
            if key in DEFAULT_CATEGORIES.split(','):
                bic = builtin_category(bic_name)
                if bic is not None:
                    wanted.append(bic)
    return wanted


# --- geometry ---------------------------------------------------------------
def plan_distance(a, b):
    """Distance in plan only.

    A ceiling light sits three metres above the plan the wire is drawn on, so
    a 3D distance would put every fixture out of range. Wires are view
    specific annotation over a model that is not; XY is the only comparison
    that means anything.
    """
    if a is None or b is None:
        return 1.0e9
    dx = a.X - b.X
    dy = a.Y - b.Y
    return math.sqrt(dx * dx + dy * dy)


def plan_at(point, z):
    """A point's XY carried to a given elevation."""
    return XYZ(point.X, point.Y, z)


def angle_between(v1, v2):
    """Angle in degrees between two plan vectors, or 180 where either is nil."""
    try:
        a = math.sqrt(v1[0] * v1[0] + v1[1] * v1[1])
        b = math.sqrt(v2[0] * v2[0] + v2[1] * v2[1])
        if a < 1.0e-9 or b < 1.0e-9:
            return 180.0
        dot = (v1[0] * v2[0] + v1[1] * v2[1]) / (a * b)
        dot = max(-1.0, min(1.0, dot))
        return math.degrees(math.acos(dot))
    except Exception:
        return 180.0


def element_point(element):
    """A representative plan point for the coarse distance filter."""
    try:
        loc = element.Location
    except Exception:
        return None
    if loc is None:
        return None
    try:
        if isinstance(loc, LocationPoint):
            return loc.Point
    except Exception:
        pass
    try:
        if isinstance(loc, LocationCurve):
            curve = loc.Curve
            return curve.Evaluate(0.5, True)
    except Exception:
        pass
    try:
        box = element.get_BoundingBox(None)
        if box is not None:
            return XYZ((box.Min.X + box.Max.X) / 2.0,
                       (box.Min.Y + box.Max.Y) / 2.0,
                       (box.Min.Z + box.Max.Z) / 2.0)
    except Exception:
        pass
    return None


# --- wires ------------------------------------------------------------------
def is_wire(element):
    try:
        return isinstance(element, Wire)
    except Exception:
        return False


def wire_vertices(wire):
    points = []
    try:
        count = wire.NumberOfVertices
    except Exception:
        count = 0
    for index in range(count):
        try:
            points.append(wire.GetVertex(index))
        except Exception:
            return points
    return points


def wiring_type_of(wire):
    """Chamfer or Arc, however this release exposes it."""
    try:
        value = wire.WiringType
        if value is not None:
            return value
    except Exception:
        pass
    try:
        param = wire.get_Parameter(BuiltInParameter.RBS_ELEC_WIRE_TYPE_PARAM)
        if param is not None and param.StorageType == StorageType.Integer:
            return WiringType.Arc if param.AsInteger() == 1 else WiringType.Chamfer
    except Exception:
        pass
    try:
        return WiringType.Chamfer
    except Exception:
        return None


def wire_connectors(wire):
    connectors = []
    try:
        manager = wire.ConnectorManager
        if manager is not None:
            for connector in manager.Connectors:
                connectors.append(connector)
    except Exception:
        pass
    return connectors


def wire_ends(wire):
    """[(connector, vertex_index), ...] for the wire's two ends.

    A wire has exactly two connectors whatever its vertex count; each is
    matched to whichever end vertex it sits nearest in plan.
    """
    points = wire_vertices(wire)
    connectors = wire_connectors(wire)
    if not points:
        return [(connector, -1) for connector in connectors]
    last = len(points) - 1
    ends = []
    taken = []
    for connector in connectors:
        index = 0
        try:
            near_first = plan_distance(connector.Origin, points[0])
            near_last = plan_distance(connector.Origin, points[last])
            index = 0 if near_first <= near_last else last
        except Exception:
            index = 0
        if index in taken:
            index = last if index == 0 else 0
        taken.append(index)
        ends.append((connector, index))
    return ends


def connector_is_free(connector, ignore_element_id=None):
    """True where nothing but the owner itself references the connector."""
    try:
        if not connector.IsConnected:
            return True
    except Exception:
        pass
    try:
        for reference in connector.AllRefs:
            owner = reference.Owner
            if owner is None:
                continue
            if same_id(owner.Id, connector.Owner.Id):
                continue
            if ignore_element_id is not None and same_id(owner.Id, ignore_element_id):
                continue
            return False
    except Exception:
        return False
    return True


def connected_owners(connector):
    """Elements referenced by a connector, excluding its own owner."""
    owners = []
    try:
        own_id = connector.Owner.Id
    except Exception:
        own_id = None
    try:
        for reference in connector.AllRefs:
            owner = reference.Owner
            if owner is None:
                continue
            if own_id is not None and same_id(owner.Id, own_id):
                continue
            owners.append(owner)
    except Exception:
        pass
    return owners


def opposite_connector(connector):
    """The connector this one is joined to, or None."""
    try:
        own_id = connector.Owner.Id
    except Exception:
        own_id = None
    try:
        for reference in connector.AllRefs:
            owner = reference.Owner
            if owner is None:
                continue
            if own_id is not None and same_id(owner.Id, own_id):
                continue
            return reference
    except Exception:
        pass
    return None


# --- circuits ---------------------------------------------------------------
def element_circuits(element):
    """Every ElectricalSystem the element is a member of."""
    circuits = []
    try:
        model = element.MEPModel
    except Exception:
        model = None
    if model is None:
        return circuits
    try:
        for circuit in model.GetElectricalSystems():
            circuits.append(circuit)
        return circuits
    except Exception:
        pass
    try:
        for circuit in model.ElectricalSystems:  # pre-2016 shape, kept as a fallback
            circuits.append(circuit)
    except Exception:
        pass
    return circuits


def electrical_connectors(element):
    connectors = []
    try:
        model = element.MEPModel
    except Exception:
        model = None
    if model is None:
        return connectors
    try:
        manager = model.ConnectorManager
        if manager is None:
            return connectors
        for connector in manager.Connectors:
            try:
                if connector.Domain == Domain.DomainElectrical:
                    connectors.append(connector)
            except Exception:
                connectors.append(connector)
    except Exception:
        pass
    return connectors


def element_has_wire(element):
    """True where any of the element's electrical connectors carries a wire."""
    for connector in electrical_connectors(element):
        for owner in connected_owners(connector):
            if is_wire(owner):
                return True
    return False


def connector_system_type(connector):
    try:
        return connector.ElectricalSystemType
    except Exception:
        return None


def _circuit_index(doc):
    """Circuit number + panel -> ElectricalSystem, for the parameter fallback."""
    index = {}
    try:
        collector = FilteredElementCollector(doc).OfClass(ElectricalSystem)
        for circuit in collector:
            try:
                key = '{0}|{1}'.format(circuit.PanelName or '',
                                       circuit.CircuitNumber or '')
                index[key] = circuit
            except Exception:
                pass
    except Exception:
        pass
    return index


def wire_circuit(doc, wire, cache=None):
    """The circuit a wire belongs to, by whichever route answers first."""
    try:
        system = wire.MEPSystem
        if system is not None:
            return system
    except Exception:
        pass
    for connector in wire_connectors(wire):
        try:
            system = connector.MEPSystem
            if system is not None:
                return system
        except Exception:
            pass
        for owner in connected_owners(connector):
            for circuit in element_circuits(owner):
                return circuit
    # parameter route - the wire reports its circuit number and panel even
    # where the connector walk comes back empty
    try:
        number = wire.get_Parameter(BuiltInParameter.RBS_ELEC_CIRCUIT_NUMBER)
        panel = wire.get_Parameter(BuiltInParameter.RBS_ELEC_CIRCUIT_PANEL_PARAM)
        if number is not None and panel is not None:
            key = '{0}|{1}'.format(panel.AsString() or '', number.AsString() or '')
            if key.strip('|'):
                if cache is None or 'circuits' not in cache:
                    built = _circuit_index(doc)
                    if cache is not None:
                        cache['circuits'] = built
                else:
                    built = cache['circuits']
                if key in built:
                    return built[key]
    except Exception:
        pass
    return None


def circuit_label(circuit):
    if circuit is None:
        return 'no circuit'
    try:
        panel = circuit.PanelName or '?'
        number = circuit.CircuitNumber or '?'
        return '{0} {1}'.format(panel, number)
    except Exception:
        return 'circuit'


# --- rebuilding a wire ------------------------------------------------------
COPY_PARAMS = ('ALL_MODEL_INSTANCE_COMMENTS', 'ALL_MODEL_MARK',
               'ELEM_PARTITION_PARAM')


def _copy_parameters(source, target):
    """Carry the instance parameters worth keeping onto a rebuilt wire."""
    for name in COPY_PARAMS:
        try:
            bip = getattr(BuiltInParameter, name)
        except Exception:
            continue
        try:
            src = source.get_Parameter(bip)
            dst = target.get_Parameter(bip)
            if src is None or dst is None or dst.IsReadOnly:
                continue
            if src.StorageType == StorageType.String:
                dst.Set(src.AsString() or '')
            elif src.StorageType == StorageType.Integer:
                dst.Set(src.AsInteger())
            elif src.StorageType == StorageType.Double:
                dst.Set(src.AsDouble())
            elif src.StorageType == StorageType.ElementId:
                dst.Set(src.AsElementId())
        except Exception:
            pass
    # shared and project parameters, by name
    try:
        for src in source.Parameters:
            try:
                if src.IsReadOnly or src.Definition is None:
                    continue
                name = src.Definition.Name
                dst = target.LookupParameter(name)
                if dst is None or dst.IsReadOnly:
                    continue
                if src.StorageType != dst.StorageType:
                    continue
                if src.StorageType == StorageType.String:
                    value = src.AsString()
                    if value:
                        dst.Set(value)
                elif src.StorageType == StorageType.Double:
                    dst.Set(src.AsDouble())
                elif src.StorageType == StorageType.Integer:
                    dst.Set(src.AsInteger())
            except Exception:
                pass
    except Exception:
        pass


def rebuild_wire(doc, wire, points, start_connector, end_connector):
    """Replace a wire with a new one on the same type, view and vertices.

    Wire.Create is the only sanctioned way to make a wire that is genuinely
    joined to its elements, so it is the fallback whenever ConnectTo is
    refused and the only route where the vertex count has to change.
    Returns the new wire, or None.
    """
    try:
        view_id = wire.OwnerViewId
        type_id = wire.GetTypeId()
        kind = wiring_type_of(wire)
        vertex_list = List[XYZ]()
        for point in points:
            vertex_list.Add(point)
        new_wire = Wire.Create(doc, type_id, view_id, kind, vertex_list,
                               start_connector, end_connector)
        if new_wire is None:
            return None
        _copy_parameters(wire, new_wire)
        doc.Delete(wire.Id)
        return new_wire
    except Exception:
        return None


# --- vertex cleaning --------------------------------------------------------
# --- Revit noise suppression ------------------------------------------------
class WarningSwallower(IFailuresPreprocessor):
    """Deletes warnings so a run is not stopped by Revit's own chatter."""

    def PreprocessFailures(self, accessor):
        try:
            for failure in accessor.GetFailureMessages():
                if failure.GetSeverity() == FailureSeverity.Warning:
                    accessor.DeleteWarning(failure)
        except Exception:
            pass
        return FailureProcessingResult.Continue


def apply_failure_handler(transaction):
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass


class DialogSuppressor(object):
    """Auto-dismisses anything Revit raises for the duration of a run."""

    def __init__(self, uiapp):
        self._uiapp = uiapp
        self._hooked = False

    def _handler(self, sender, args):
        try:
            args.OverrideResult(1)
        except Exception:
            pass

    def __enter__(self):
        try:
            self._uiapp.DialogBoxShowing += self._handler
            self._hooked = True
        except Exception:
            self._hooked = False
        return self

    def __exit__(self, kind, value, trace):
        if self._hooked:
            try:
                self._uiapp.DialogBoxShowing -= self._handler
            except Exception:
                pass
        return False


# --- selection --------------------------------------------------------------
class WireSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        try:
            return is_wire(element)
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return False


def selected_wires(uidoc, ask_if_empty=True):
    """Wires from the current selection, or picked. ([], [], cancelled)."""
    doc = uidoc.Document
    wires = []
    others = []
    try:
        for element_id in uidoc.Selection.GetElementIds():
            element = doc.GetElement(element_id)
            if element is None:
                continue
            if is_wire(element):
                wires.append(element)
            else:
                others.append(element)
    except Exception:
        pass

    if wires or not ask_if_empty:
        return wires, others, False

    try:
        references = uidoc.Selection.PickObjects(
            ObjectType.Element, WireSelectionFilter(),
            'Select the wires to fix, then Finish')
        for reference in references:
            element = doc.GetElement(reference.ElementId)
            if element is not None and is_wire(element):
                wires.append(element)
    except Exception:
        return [], [], True
    return wires, others, False


# --- the report -------------------------------------------------------------
class Report(object):
    """What happened, in the order it happened."""

    OK = 'ok'
    INFO = 'info'      # said for the record; never opens the window
    NOTE = 'note'      # worth a look
    SKIP = 'skip'      # something was left alone

    def __init__(self, title):
        self.title = title
        self.lines = []
        self.fixed = 0
        self.drawn = 0
        self.retyped = 0
        self.aligned = 0
        # detailed diagnostics: never shown in the window, always written to
        # the debug report, because the thing that explains a failure is
        # usually the thing nobody wants to read on a good day
        self.trace = []
        # set where a floating prompt is still open: the command returns long
        # before the run is settled, so the results window is the prompt's to
        # show, not the command's
        self.deferred = False
        self.skipped = 0

    def ok(self, text):
        self.lines.append((Report.OK, text))

    def log(self, text):
        self.trace.append(text)

    def info(self, text):
        """For the record. A run that only produces these finishes silently."""
        self.lines.append((Report.INFO, text))

    def note(self, text):
        self.lines.append((Report.NOTE, text))

    def skip(self, text):
        self.skipped += 1
        self.lines.append((Report.SKIP, text))

    def needs_a_look(self):
        """Only a note or a skip opens the window.

        Everything the run resolved along the way - which wire type, which
        switch, how many fittings were selected - is INFO, so a run that goes
        to plan finishes without a dialog. Otherwise the diagnostics added to
        make failures explicable would make every success interrupt you.
        """
        for kind, _text in self.lines:
            if kind in (Report.SKIP, Report.NOTE):
                return True
        return False

    def summary(self):
        parts = []
        if self.fixed:
            parts.append('{0} reconnected'.format(self.fixed))
        if self.drawn:
            parts.append('{0} wire(s) and tag(s) drawn'.format(self.drawn))
        # kept separate from drawn: Apply Wire Types draws nothing, and a
        # summary telling the person it drew three wires contradicts the one
        # promise that tool makes
        if self.retyped:
            parts.append('{0} wire(s) retyped'.format(self.retyped))
        if self.aligned:
            parts.append('{0} wire end(s) aligned'.format(self.aligned))
        if self.skipped:
            parts.append('{0} left alone'.format(self.skipped))
        if not parts:
            return 'Nothing to do.'
        return ', '.join(parts) + '.'


# --- candidates -------------------------------------------------------------
class Candidate(object):
    __slots__ = ('element', 'point', 'name')

    def __init__(self, element, point, name):
        self.element = element
        self.point = point
        self.name = name


def element_name(element):
    try:
        symbol = element.Symbol
        return '{0} : {1}'.format(symbol.Family.Name, symbol.Name)
    except Exception:
        pass
    try:
        return element.Name
    except Exception:
        return 'element'


def collect_candidates(doc, view, settings, restrict_to=None):
    """Every wireable element in the view, read once and reused per wire end."""
    if restrict_to:
        candidates = []
        for element in restrict_to:
            point = element_point(element)
            if point is not None:
                candidates.append(Candidate(element, point, element_name(element)))
        return candidates

    categories = active_categories(settings)
    if not categories:
        return []
    id_list = List[BuiltInCategory]()
    for category in categories:
        id_list.Add(category)
    candidates = []
    try:
        collector = FilteredElementCollector(doc, view.Id)
        collector = collector.WherePasses(ElementMulticategoryFilter(id_list))
        collector = collector.WhereElementIsNotElementType()
        for element in collector:
            try:
                if not isinstance(element, FamilyInstance):
                    continue
            except Exception:
                pass
            point = element_point(element)
            if point is None:
                continue
            candidates.append(Candidate(element, point, element_name(element)))
    except Exception:
        pass
    return candidates


def _system_types_agree(wire_type, connector_type):
    if wire_type is None or connector_type is None:
        return True
    try:
        return str(wire_type) == str(connector_type)
    except Exception:
        return True


def best_target(doc, wire, end_point, candidates, settings, wire_circ, cache):
    """The nearest element that this loose wire end ought to be joined to.

    Returns (element, connector, distance_mm, refusal). Where nothing
    qualifies the refusal says what was in range and why it was passed over,
    so a miss reads as a decision rather than a shrug.
    """
    radius = mm(_settings_float(settings, 'search_radius_mm'))
    coarse = radius + mm(1000)
    require_circuit = _settings_bool(settings, 'require_circuit')
    require_unwired = _settings_bool(settings, 'require_unwired')
    cross_circuit = _settings_bool(settings, 'cross_circuit')
    match_type = _settings_bool(settings, 'match_system_type')

    wire_type = None
    if match_type:
        for connector in wire_connectors(wire):
            wire_type = connector_system_type(connector)
            if wire_type is not None:
                break

    best = None
    passed_over = []

    for candidate in candidates:
        if plan_distance(candidate.point, end_point) > coarse:
            continue
        try:
            if same_id(candidate.element.Id, wire.Id):
                continue
        except Exception:
            continue

        connectors = electrical_connectors(candidate.element)
        if not connectors:
            continue

        circuits = element_circuits(candidate.element)
        if require_circuit and not circuits:
            passed_over.append('{0} has no circuit'.format(candidate.name))
            continue
        if require_unwired and element_has_wire(candidate.element):
            passed_over.append('{0} is already wired'.format(candidate.name))
            continue
        if wire_circ is not None and circuits and not cross_circuit:
            agree = False
            for circuit in circuits:
                if same_id(circuit.Id, wire_circ.Id):
                    agree = True
                    break
            if not agree:
                passed_over.append('{0} is on {1}, the wire is on {2}'.format(
                    candidate.name, circuit_label(circuits[0]),
                    circuit_label(wire_circ)))
                continue

        for connector in connectors:
            if not connector_is_free(connector, ignore_element_id=wire.Id):
                # an electrical connector takes several wires, so being in use
                # is not a refusal - only being in use by this same wire is
                already = False
                for owner in connected_owners(connector):
                    if same_id(owner.Id, wire.Id):
                        already = True
                        break
                if already:
                    continue
            if match_type and not _system_types_agree(
                    wire_type, connector_system_type(connector)):
                continue
            try:
                distance = plan_distance(connector.Origin, end_point)
            except Exception:
                continue
            if distance > radius:
                continue
            if best is None or distance < best[2]:
                best = (candidate.element, connector, distance, candidate.name)

    if best is None:
        refusal = None
        if passed_over:
            refusal = passed_over[0]
        return None, None, 0.0, refusal
    return best[0], best[1], best[2], None


# --- reconnect --------------------------------------------------------------
def _connect(wire, wire_connector, vertex_index, target_connector, settings):
    """Join a loose wire end to an element connector. True where it took."""
    snap = _settings_bool(settings, 'snap_on_connect')
    if snap and vertex_index >= 0:
        try:
            origin = target_connector.Origin
            current = wire.GetVertex(vertex_index)
            wire.SetVertex(vertex_index, plan_at(origin, current.Z))
        except Exception:
            pass
    try:
        wire_connector.ConnectTo(target_connector)
    except Exception:
        return False
    # verified by read-back, not assumed
    try:
        for owner in connected_owners(wire_connector):
            if same_id(owner.Id, target_connector.Owner.Id):
                return True
    except Exception:
        pass
    try:
        return wire_connector.IsConnected
    except Exception:
        return False


def _rebuild_onto(doc, wire, vertex_index, target_connector, settings):
    """Fallback: rebuild the wire with Wire.Create so the join is made at birth."""
    points = wire_vertices(wire)
    if not points:
        return None
    last = len(points) - 1
    if vertex_index < 0:
        vertex_index = 0
    try:
        origin = target_connector.Origin
        points[vertex_index] = plan_at(origin, points[vertex_index].Z)
    except Exception:
        pass

    # whatever the other end is already joined to has to be carried over
    other_index = last if vertex_index == 0 else 0
    other_connector = None
    for connector, index in wire_ends(wire):
        if index == other_index:
            other_connector = opposite_connector(connector)
            break

    if vertex_index == 0:
        start, end = target_connector, other_connector
    else:
        start, end = other_connector, target_connector
    return rebuild_wire(doc, wire, points, start, end)


def run_reconnect(uiapp, settings, wires=None):
    """Join every loose end of the selected wires to the element beside it."""
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document
    view = doc.ActiveView
    report = Report('Reconnect Wires')
    cache = {}

    restrict_to = None
    if wires is None:
        wires, others, cancelled = selected_wires(uidoc)
        if cancelled:
            return None
        if others:
            usable = [e for e in others if electrical_connectors(e)]
            if usable:
                restrict_to = usable
                report.note('Search restricted to the {0} element(s) selected '
                            'alongside the wires.'.format(len(usable)))

    if not wires:
        report.note('No wires selected. Select the wires to fix and run again.')
        return report

    candidates = collect_candidates(doc, view, settings, restrict_to)
    if not candidates:
        report.note('No wireable elements found in this view. Check the '
                    'categories in Settings.')
        return report

    transaction = Transaction(doc, 'RevoBIM Reconnect Wires')
    apply_failure_handler(transaction)
    transaction.Start()
    try:
        for wire in wires:
            sub = SubTransaction(doc)
            sub.Start()
            try:
                _reconnect_one(doc, wire, candidates, settings, report, cache)
                sub.Commit()
            except Exception as error:
                sub.RollBack()
                report.skip('Wire {0} left untouched: {1}'.format(
                    eid_value(wire.Id), error))
        transaction.Commit()
    except Exception as error:
        try:
            transaction.RollBack()
        except Exception:
            pass
        report.skip('The run was rolled back: {0}'.format(error))
    return report


def _reconnect_one(doc, wire, candidates, settings, report, cache):
    """Returns the replacement wire where one was made, else None."""
    wire_id = eid_value(wire.Id)
    circuit = wire_circuit(doc, wire, cache)
    ends = wire_ends(wire)
    if not ends:
        report.skip('Wire {0} reports no connectors.'.format(wire_id))
        return None

    replacement = None
    attempted = []

    # At most the two ends, re-read each pass: a rebuild deletes the wire the
    # connectors belong to, so anything held from before is a stale reference.
    for _pass in (0, 1):
        loose = None
        points = wire_vertices(wire)
        for connector, index in wire_ends(wire):
            if index in attempted:
                continue
            if connector_is_free(connector):
                loose = (connector, index)
                break
        if loose is None:
            break
        connector, index = loose
        attempted.append(index)

        try:
            if index >= 0 and index < len(points):
                end_point = points[index]
            else:
                end_point = connector.Origin
        except Exception:
            continue

        target, target_connector, distance, refusal = best_target(
            doc, wire, end_point, candidates, settings, circuit, cache)

        if target is None:
            if refusal:
                report.skip('Wire {0}: nothing joined - {1}.'.format(
                    wire_id, refusal))
            else:
                report.skip('Wire {0}: no wireable element within '
                            '{1:.0f}mm of that end.'.format(
                                wire_id, _settings_float(
                                    settings, 'search_radius_mm')))
            continue

        joined = _connect(wire, connector, index, target_connector, settings)

        if not joined and _settings_bool(settings, 'recreate_if_refused'):
            rebuilt = _rebuild_onto(doc, wire, index, target_connector, settings)
            if rebuilt is not None:
                replacement = rebuilt
                wire = rebuilt
                points = wire_vertices(wire)
                joined = True
                report.note('Wire {0} was refused in place and was rebuilt '
                            'as {1}.'.format(wire_id, eid_value(wire.Id)))

        if not joined:
            report.skip('Wire {0}: Revit refused the connection to {1} at '
                        '{2:.0f}mm.'.format(wire_id, element_name(target),
                                            to_mm(distance)))
            continue

        report.fixed += 1
        new_circuit = wire_circuit(doc, wire, cache)
        if new_circuit is None:
            report.note('Wire {0} joined {1} but still reports no circuit - '
                        'check the element is circuited.'.format(
                            wire_id, element_name(target)))
        else:
            report.ok('Wire {0} joined {1} on {2}, {3:.0f}mm away.'.format(
                wire_id, element_name(target), circuit_label(new_circuit),
                to_mm(distance)))
            circuit = new_circuit

    return replacement


# --- views ------------------------------------------------------------------
def is_plan_view(view):
    """Wires are only ever drawn on a floor plan or a ceiling plan."""
    try:
        from Autodesk.Revit.DB import ViewType
        if view is None or view.IsTemplate:
            return False
        return view.ViewType in (ViewType.FloorPlan, ViewType.CeilingPlan)
    except Exception:
        return False


def view_scale(view):
    try:
        scale = int(view.Scale)
        return scale if scale > 0 else 100
    except Exception:
        return 100


def paper(view, value_mm):
    """Paper millimetres to internal feet at the view's scale.

    Annotation set out from the sheet belongs in paper millimetres; annotation
    set out from the model belongs in model millimetres. A wire is a symbol,
    so its sweep and the gap at a fitting are both paper measurements.
    """
    return mm(float(value_mm) * view_scale(view))


def drawing_plane_z(doc, view):
    """The elevation wires are drawn at in this view.

    Learned from a wire already in the view rather than assumed, because the
    plane Revit puts them on is not the level elevation and not the fitting's
    height. Falls back to the view's level.
    """
    try:
        collector = FilteredElementCollector(doc, view.Id).OfClass(Wire)
        for wire in collector:
            points = wire_vertices(wire)
            if points:
                return points[0].Z
    except Exception:
        pass
    try:
        level = view.GenLevel
        if level is not None:
            return level.Elevation
    except Exception:
        pass
    return 0.0


# --- wire types and tag types ----------------------------------------------
# Both lookups try several routes and say which one answered. The first
# version wrapped the whole thing in one try/except and returned an empty
# list, so a model with wire types in it reported "none in this model" and
# every circuit then refused to draw with no way to see why. Never swallow a
# lookup - report it.

def _type_name(element):
    try:
        name = element.Name
        if name:
            return name
    except Exception:
        pass
    try:
        param = element.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if param is not None:
            return param.AsString() or ''
    except Exception:
        pass
    try:
        param = element.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
        if param is not None:
            return param.AsString() or ''
    except Exception:
        pass
    return ''


def wire_types(doc):
    """Every wire type in the model, as ([(name, element), ...], note)."""
    pairs = []
    seen = set()
    tried = []

    def take(element, route):
        try:
            key = eid_value(element.Id)
        except Exception:
            return
        if key in seen or element is None:
            return
        name = _type_name(element)
        if not name:
            return
        seen.add(key)
        pairs.append((name, element))

    # 1. by class
    try:
        from Autodesk.Revit.DB.Electrical import WireType
        before = len(pairs)
        for element in FilteredElementCollector(doc).OfClass(WireType):
            take(element, 'class')
        tried.append('OfClass(WireType) found {0}'.format(len(pairs) - before))
    except Exception as error:
        tried.append('OfClass(WireType) failed ({0})'.format(error))

    # 2. by category - works where the class filter is refused
    if not pairs:
        bic = builtin_category('OST_Wire')
        if bic is None:
            tried.append('OST_Wire is not on this release')
        else:
            try:
                collector = FilteredElementCollector(doc).OfCategory(bic)
                for element in collector.WhereElementIsElementType():
                    take(element, 'category')
                tried.append('OST_Wire element types found {0}'.format(len(pairs)))
            except Exception as error:
                tried.append('OST_Wire failed ({0})'.format(error))

    # 3. the types actually in use on wires already drawn
    if not pairs:
        try:
            for wire in FilteredElementCollector(doc).OfClass(Wire):
                element = doc.GetElement(wire.GetTypeId())
                if element is not None:
                    take(element, 'in use')
            tried.append('types in use on existing wires found {0}'.format(
                len(pairs)))
        except Exception as error:
            tried.append('walking existing wires failed ({0})'.format(error))

    # 4. the document's own default
    if not pairs:
        try:
            from Autodesk.Revit.DB import ElementTypeGroup
            type_id = doc.GetDefaultElementTypeId(ElementTypeGroup.WireType)
            element = doc.GetElement(type_id)
            if element is not None:
                take(element, 'default')
                tried.append('the document default wire type')
        except Exception as error:
            tried.append('the document default failed ({0})'.format(error))

    pairs.sort(key=lambda pair: pair[0].lower())
    return pairs, '; '.join(tried)


def find_wire_type(doc, name, cache=None):
    """The named wire type, or the first available one."""
    if cache is not None and 'wire_types' in cache:
        pairs = cache['wire_types']
    else:
        pairs, _note = wire_types(doc)
        if cache is not None:
            cache['wire_types'] = pairs
    if name:
        for label, element in pairs:
            if label == name:
                return element
        for label, element in pairs:
            if label.lower() == str(name).strip().lower():
                return element
    if pairs:
        return pairs[0][1]
    return None


# Wire tags are one setting shared by lighting and power, chosen as a family
# and then a type within it.
TAG_CATEGORY_NAMES = ('OST_WireTags', 'OST_WireTag')


def wire_tag_types(doc):
    """Wire tag types as ([(family, type, symbol), ...], note)."""
    found = []
    seen = set()
    tried = []

    def take(symbol):
        try:
            key = eid_value(symbol.Id)
        except Exception:
            return
        if key in seen:
            return
        try:
            family = symbol.Family.Name
        except Exception:
            family = 'Wire Tag'
        name = _type_name(symbol)
        if not name:
            return
        seen.add(key)
        found.append((family, name, symbol))

    # 1. the wire tag category, by whichever name this release uses
    for category_name in TAG_CATEGORY_NAMES:
        bic = builtin_category(category_name)
        if bic is None:
            continue
        try:
            collector = FilteredElementCollector(doc).OfCategory(bic)
            for symbol in collector.WhereElementIsElementType():
                take(symbol)
            tried.append('{0} found {1}'.format(category_name, len(found)))
        except Exception as error:
            tried.append('{0} failed ({1})'.format(category_name, error))
        if found:
            break

    # 2. every family symbol whose category reads as a wire tag
    if not found:
        try:
            from Autodesk.Revit.DB import FamilySymbol
            for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol):
                try:
                    label = symbol.Category.Name.lower()
                except Exception:
                    continue
                if 'wire' in label and 'tag' in label:
                    take(symbol)
            tried.append('family symbols by category name found {0}'.format(
                len(found)))
        except Exception as error:
            tried.append('family symbol walk failed ({0})'.format(error))

    if not found:
        tried.append('no wire tag family is loaded in this model')

    found.sort(key=lambda row: (row[0].lower(), row[1].lower()))
    return found, '; '.join(tried)


def tag_families(doc, cache=None):
    """Just the family names, in order."""
    rows = tag_rows(doc, cache)
    names = []
    for family, _name, _symbol in rows:
        if family not in names:
            names.append(family)
    return names


def tag_rows(doc, cache=None):
    if cache is not None and 'tag_rows' in cache:
        return cache['tag_rows']
    rows, _note = wire_tag_types(doc)
    if cache is not None:
        cache['tag_rows'] = rows
    return rows


def find_tag_type(doc, family_name, type_name, cache=None):
    """The named wire tag type. Falls back within the family, then anywhere."""
    rows = tag_rows(doc, cache)
    if not rows:
        return None
    if family_name:
        in_family = [row for row in rows if row[0] == family_name]
        if not in_family:
            in_family = [row for row in rows
                         if row[0].lower() == str(family_name).strip().lower()]
        if in_family:
            if type_name:
                for _family, name, symbol in in_family:
                    if name == type_name:
                        return symbol
                for _family, name, symbol in in_family:
                    if name.lower() == str(type_name).strip().lower():
                        return symbol
            return in_family[0][2]
    if type_name:
        for _family, name, symbol in rows:
            if name == type_name:
                return symbol
    return rows[0][2]


# --- plan extent of a symbol -----------------------------------------------
def plan_half_extent(element, view, direction):
    """Half the element's plan size along a direction, in feet.

    The support function of the bounding box, which is exact for a box and
    over-states anything inside one - so the failure direction trims the wire
    further clear of the symbol rather than into it.
    """
    box = None
    for source in (view, None):
        try:
            box = element.get_BoundingBox(source)
            if box is not None:
                break
        except Exception:
            box = None
    if box is None:
        return 0.0
    try:
        half_x = abs(box.Max.X - box.Min.X) / 2.0
        half_y = abs(box.Max.Y - box.Min.Y) / 2.0
        return abs(direction[0]) * half_x + abs(direction[1]) * half_y
    except Exception:
        return 0.0


# --- one drawn segment ------------------------------------------------------
def arc_through(ax, ay, bx, by, sag, side, count, plane_z):
    """Points along a true circular arc from A to B with a given sagitta.

    A circle rather than a Bezier, for two reasons. The sag is then exactly
    the depth of the arc at its middle, so the slider means what it says. And
    equal steps of angle are equal steps of *arc length*, so extra vertices
    land evenly spaced along the curve - a Bezier stepped in its own parameter
    bunches them toward the ends.

    Returns the whole run including both endpoints.
    """
    dx = bx - ax
    dy = by - ay
    chord = math.sqrt(dx * dx + dy * dy)
    ends = [XYZ(ax, ay, plane_z), XYZ(bx, by, plane_z)]
    if chord < 1.0e-9:
        return ends
    if count < 1:
        return ends

    # a sag past the half-chord would be more than a semicircle, which has no
    # sensible reading here and breaks the minor-arc solution
    depth = max(0.0, min(float(sag), chord * 0.49))
    if depth < 1.0e-9:
        points = [ends[0]]
        for step in range(1, count + 1):
            position = float(step) / float(count + 1)
            points.append(XYZ(ax + dx * position, ay + dy * position, plane_z))
        points.append(ends[1])
        return points

    ux = dx / chord
    uy = dy / chord
    if str(side).strip().lower() == 'right':
        px, py = uy, -ux
    else:
        px, py = -uy, ux

    half = chord / 2.0
    radius = (half * half + depth * depth) / (2.0 * depth)
    # the centre sits on the far side of the chord from the bulge
    cx = (ax + bx) / 2.0 + px * (depth - radius)
    cy = (ay + by) / 2.0 + py * (depth - radius)

    start_x = ax - cx
    start_y = ay - cy
    end_x = bx - cx
    end_y = by - cy
    start_angle = math.atan2(start_y, start_x)
    sweep = math.atan2(start_x * end_y - start_y * end_x,
                       start_x * end_x + start_y * end_y)

    points = [ends[0]]
    for step in range(1, count + 1):
        angle = start_angle + sweep * (float(step) / float(count + 1))
        points.append(XYZ(cx + radius * math.cos(angle),
                          cy + radius * math.sin(angle), plane_z))
    points.append(ends[1])
    return points


def sagitta(view, mode, value, chord_length):
    """How deep the arc should be, in feet.

    Two ways of asking for it. **span** is a percentage of the distance being
    spanned, so every wire on the drawing sweeps by the same proportion and a
    600mm hop between two downlights does not bulge as hard as a six metre one
    - which is what a fixed distance does. **paper** is a fixed measurement on
    the sheet, multiplied by the view scale.
    """
    try:
        number = float(value)
    except Exception:
        number = 0.0
    if str(mode).strip().lower() == 'paper':
        depth = paper(view, number)
    else:
        depth = chord_length * (number / 100.0)
    return max(0.0, min(depth, chord_length * 0.49))


def chamfer_through(ax, ay, bx, by, offset, side, angle_deg, extra, plane_z):
    """An angle off the fitting, a straight run across, and an angle back in.

    What a chamfered wire is meant to look like. Sampling the arc and letting
    Revit facet between the points gives a many-sided polygon instead, which
    reads as a mistake rather than a convention.

    `extra` adds further vertices along the straight middle, so raising the
    count still does something without changing the shape.
    """
    dx = bx - ax
    dy = by - ay
    chord = math.sqrt(dx * dx + dy * dy)
    ends = [XYZ(ax, ay, plane_z), XYZ(bx, by, plane_z)]
    if chord < 1.0e-9:
        return ends
    ux = dx / chord
    uy = dy / chord
    if str(side).strip().lower() == 'right':
        px, py = uy, -ux
    else:
        px, py = -uy, ux

    depth = max(0.0, abs(float(offset)))
    if depth < 1.0e-9:
        return ends

    try:
        angle = float(angle_deg)
    except Exception:
        angle = 45.0
    angle = max(5.0, min(85.0, angle))
    inset = depth / math.tan(math.radians(angle))
    # the two cranks must leave a straight between them
    inset = min(inset, chord * 0.45)

    first = XYZ(ax + ux * inset + px * depth, ay + uy * inset + py * depth,
                plane_z)
    last = XYZ(bx - ux * inset + px * depth, by - uy * inset + py * depth,
               plane_z)

    points = [ends[0], first]
    try:
        count = int(extra)
    except Exception:
        count = 0
    for step in range(1, max(0, count) + 1):
        position = float(step) / float(count + 1)
        points.append(XYZ(first.X + (last.X - first.X) * position,
                          first.Y + (last.Y - first.Y) * position, plane_z))
    points.append(last)
    points.append(ends[1])
    return points


def segment_points(point_a, point_b, plane_z, sag, side, trim_a, trim_b,
                   mid_count=1, wiring='arc', chamfer_angle=45.0):
    """The vertices of one wire between two fittings.

    `mid_count` is counted *between* the ends, so 1 gives the three-vertex
    wire - start, middle, end - with the middle at the deepest point of the
    arc. 0 gives just the two ends. More than one spaces them evenly along the
    same arc, so the sweep does not change with the count.

    `sag` is the depth of the arc at its middle, already in feet.
    """
    dx = point_b.X - point_a.X
    dy = point_b.Y - point_a.Y
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1.0e-9:
        return None
    ux = dx / length
    uy = dy / length

    ceiling = length * 0.45
    start_trim = max(0.0, min(float(trim_a), ceiling))
    end_trim = max(0.0, min(float(trim_b), ceiling))

    ax = point_a.X + ux * start_trim
    ay = point_a.Y + uy * start_trim
    bx = point_b.X - ux * end_trim
    by = point_b.Y - uy * end_trim

    count = clamp_vertices(mid_count)

    if str(wiring).strip().lower() == 'chamfer':
        # the crank takes two vertices of its own, so anything above two is
        # spread along the straight between them
        return chamfer_through(ax, ay, bx, by, sag, side, chamfer_angle,
                               max(0, count - 2), plane_z)
    return arc_through(ax, ay, bx, by, sag, side, count, plane_z)


# --- parameters on the fittings ---------------------------------------------
def fitting_parameter_names(doc, categories, limit=40):
    """Parameter names carried by the fittings in these categories.

    Read off the elements themselves, instance and type, so the dropdown only
    ever offers parameters that actually exist on something in this model.
    """
    names = set()
    if not categories:
        return []
    id_list = List[BuiltInCategory]()
    for bic in categories:
        id_list.Add(bic)
    try:
        collector = FilteredElementCollector(doc)
        collector = collector.WherePasses(ElementMulticategoryFilter(id_list))
        collector = collector.WhereElementIsNotElementType()
        seen = 0
        for element in collector:
            for source in (element, doc.GetElement(element.GetTypeId())):
                if source is None:
                    continue
                try:
                    for param in source.Parameters:
                        try:
                            if param.Definition is not None:
                                names.add(param.Definition.Name)
                        except Exception:
                            pass
                except Exception:
                    pass
            seen += 1
            if seen >= limit:
                break
    except Exception:
        pass
    return sorted(names, key=lambda text: text.lower())


def parameter_says_yes(element, doc, name):
    """Is this fitting's named parameter set? Instance first, then type.

    Yes / true / 1 all count, because a shared yes/no parameter reads back as
    an integer, a plain text parameter as a word, and which one a family uses
    is not something this tool gets to choose.
    """
    if not name or element is None:
        return False
    sources = [element]
    try:
        type_element = doc.GetElement(element.GetTypeId())
        if type_element is not None:
            sources.append(type_element)
    except Exception:
        pass

    for source in sources:
        param = None
        try:
            param = source.LookupParameter(name)
        except Exception:
            param = None
        if param is None:
            continue
        try:
            if param.StorageType == StorageType.Integer:
                return param.AsInteger() == 1
        except Exception:
            pass
        for reader in ('AsString', 'AsValueString'):
            try:
                value = getattr(param, reader)()
            except Exception:
                continue
            if value is None:
                continue
            if str(value).strip().lower() in ('yes', 'true', '1', 'y'):
                return True
    return False


def is_emergency(element, doc, settings):
    return parameter_says_yes(element, doc,
                              settings.get('emergency_parameter', ''))


# --- line styles ------------------------------------------------------------
def line_styles(doc):
    """Detail line styles as ([(name, GraphicsStyle), ...], note).

    Same rule as the wire types: several routes, and say which one answered
    rather than returning an empty list and letting the caller guess.
    """
    found = []
    tried = []
    bic = builtin_category('OST_Lines')
    if bic is None:
        return found, 'OST_Lines is not on this release'
    try:
        from Autodesk.Revit.DB import GraphicsStyleType
        categories = doc.Settings.Categories
        lines = categories.get_Item(bic)
        for sub in lines.SubCategories:
            try:
                style = sub.GetGraphicsStyle(GraphicsStyleType.Projection)
                if style is not None:
                    found.append((sub.Name, style))
            except Exception:
                pass
        tried.append('line subcategories found {0}'.format(len(found)))
    except Exception as error:
        tried.append('line subcategories failed ({0})'.format(error))

    if not found:
        try:
            from Autodesk.Revit.DB import GraphicsStyle
            for style in FilteredElementCollector(doc).OfClass(GraphicsStyle):
                try:
                    category = style.GraphicsStyleCategory
                    if category is None or category.Parent is None:
                        continue
                    if eid_value(category.Parent.Id) == eid_value(
                            ElementId(bic)):
                        found.append((category.Name, style))
                except Exception:
                    pass
            tried.append('GraphicsStyle walk found {0}'.format(len(found)))
        except Exception as error:
            tried.append('GraphicsStyle walk failed ({0})'.format(error))

    found.sort(key=lambda pair: pair[0].lower())
    return found, '; '.join(tried)


def find_line_style(doc, name, cache=None):
    if cache is not None and 'line_styles' in cache:
        pairs = cache['line_styles']
    else:
        pairs, _note = line_styles(doc)
        if cache is not None:
            cache['line_styles'] = pairs
    if name:
        for label, style in pairs:
            if label == name:
                return style
        for label, style in pairs:
            if label.lower() == str(name).strip().lower():
                return style
    return None


# --- which space a fitting is in --------------------------------------------
def space_key(element, doc):
    """A key for the space a fitting sits in, and its name.

    Spaces first because this is an MEP model, then rooms, then the point the
    fitting sits at. An empty key means no space could be found, which is a
    legitimate answer - an unspaced fitting is its own group.
    """
    for reader in ('Space', 'Room'):
        try:
            spatial = getattr(element, reader)
            if spatial is not None:
                return 'sp:{0}'.format(eid_value(spatial.Id)), _spatial_name(
                    spatial)
        except Exception:
            pass
    try:
        point = element_point(element)
        if point is not None:
            spatial = doc.GetSpaceAtPoint(point)
            if spatial is not None:
                return 'sp:{0}'.format(eid_value(spatial.Id)), _spatial_name(
                    spatial)
    except Exception:
        pass
    return '', ''


def _spatial_name(spatial):
    try:
        number = spatial.Number or ''
    except Exception:
        number = ''
    try:
        name = spatial.Name or ''
    except Exception:
        name = ''
    label = '{0} {1}'.format(number, name).strip()
    return label or 'space'


# --- spacing vertices along the whole run -----------------------------------
def vertex_spacing(span_lengths, on_average_span):
    """The distance between vertices, from the run as a whole.

    Worked out once per circuit so that a span of average length gets the
    number asked for and everything else is in proportion - which is what
    stops a long hop across a corridor carrying the same single vertex as a
    600mm hop between two downlights.
    """
    lengths = [value for value in span_lengths if value > 1.0e-9]
    if not lengths:
        return 0.0
    try:
        count = float(on_average_span)
    except Exception:
        count = 1.0
    if count < 0.5:
        return 0.0
    average = sum(lengths) / float(len(lengths))
    return average / (count + 1.0)


def vertices_for(span_length, spacing, ceiling=8):
    """How many vertices one span gets at that spacing."""
    if spacing <= 0.0 or span_length <= 0.0:
        return 0
    count = int(round(span_length / spacing)) - 1
    return max(0, min(ceiling, count))


# --- clearing other fittings ------------------------------------------------
def symbol_radius(element, view):
    """A plan radius for the fitting's symbol, in feet.

    The *smaller* half of the bounding box, not the support function used for
    trimming. A plan symbol is usually square or round about its insertion
    point, so the smaller half is the better estimate of where its edge is,
    and under-stating leaves the wire a touch short rather than running it
    through the symbol.
    """
    box = None
    for source in (view, None):
        try:
            box = element.get_BoundingBox(source)
            if box is not None:
                break
        except Exception:
            box = None
    if box is None:
        return 0.0
    try:
        half_x = abs(box.Max.X - box.Min.X) / 2.0
        half_y = abs(box.Max.Y - box.Min.Y) / 2.0
        return min(half_x, half_y)
    except Exception:
        return 0.0


def plan_radius(element, view):
    """A direction-independent plan radius for a fitting, in feet.

    Half the bounding box diagonal in plan. It over-states a round or narrow
    symbol, which is the right way to be wrong here: the wire is pushed
    further clear rather than drawn through something.
    """
    box = None
    for source in (view, None):
        try:
            box = element.get_BoundingBox(source)
            if box is not None:
                break
        except Exception:
            box = None
    if box is None:
        return 0.0
    try:
        half_x = abs(box.Max.X - box.Min.X) / 2.0
        half_y = abs(box.Max.Y - box.Min.Y) / 2.0
        return math.sqrt(half_x * half_x + half_y * half_y)
    except Exception:
        return 0.0


def point_to_segment(px, py, ax, ay, bx, by):
    """Shortest distance in plan from a point to a line segment."""
    dx = bx - ax
    dy = by - ay
    span = dx * dx + dy * dy
    if span < 1.0e-18:
        return math.sqrt((px - ax) ** 2 + (py - ay) ** 2)
    position = ((px - ax) * dx + (py - ay) * dy) / span
    position = max(0.0, min(1.0, position))
    nx = ax + dx * position
    ny = ay + dy * position
    return math.sqrt((px - nx) ** 2 + (py - ny) ** 2)


def polyline_clears(points, ox, oy, radius):
    """True where every part of the run stays `radius` clear of a point."""
    for index in range(len(points) - 1):
        gap = point_to_segment(ox, oy, points[index].X, points[index].Y,
                               points[index + 1].X, points[index + 1].Y)
        if gap < radius:
            return False
    return True



# --- arc or chamfer ---------------------------------------------------------
MIN_VERTICES = 1
MAX_VERTICES = 8


def clamp_vertices(value):
    """The vertex count, held between 1 and 8.

    The floor is 1 because a wire with no middle vertex has nothing to bend
    round: an arc wire falls back to whatever sweep Revit chooses and a
    chamfered one is a straight line.
    """
    try:
        count = int(round(float(value)))
    except Exception:
        count = MIN_VERTICES
    return max(MIN_VERTICES, min(MAX_VERTICES, count))


def wiring_kind(name):
    """WiringType.Arc or WiringType.Chamfer from a setting value."""
    try:
        if str(name).strip().lower() == 'chamfer':
            return WiringType.Chamfer
        return WiringType.Arc
    except Exception:
        return None


# --- the debug report -------------------------------------------------------
def debug_report(uiapp, settings, report, extra_lines=None):
    """Everything worth knowing about a run, as plain text.

    Written so a run that went wrong can be sent on and read by somebody who
    cannot see the model: the release, the settings in force, what the
    lookups resolved to, and every line of the report including the
    informational ones the window hides.
    """
    lines = []
    lines.append('RevoBIM PY - Wires debug report')
    lines.append('tool version: {0}'.format(__version__))
    try:
        application = uiapp.Application
        lines.append('Revit: {0}  build {1}'.format(
            application.VersionNumber, application.VersionBuild))
    except Exception:
        lines.append('Revit: could not be read')

    doc = None
    view = None
    try:
        doc = uiapp.ActiveUIDocument.Document
        view = doc.ActiveView
        lines.append('document: {0}'.format(doc.Title))
        lines.append('view: {0}  type {1}  scale 1:{2}'.format(
            view.Name, view.ViewType, view_scale(view)))
    except Exception:
        lines.append('document/view: could not be read')

    lines.append('')
    lines.append('-- what the lookups resolved --')
    if doc is not None:
        try:
            pairs, note = wire_types(doc)
            lines.append('wire types in model: {0}  ({1})'.format(
                len(pairs), note))
            for key in ('lighting_wire_type', 'lighting_emergency_wire_type',
                        'lighting_live_wire_type', 'power_wire_type'):
                found = find_wire_type(doc, settings.get(key, ''))
                lines.append('  {0} = {1!r} -> {2}'.format(
                    key, settings.get(key, ''),
                    _type_name(found) if found else 'NOTHING'))
            rows, tag_note = wire_tag_types(doc)
            lines.append('wire tag types in model: {0}  ({1})'.format(
                len(rows), tag_note))
            symbol = find_tag_type(doc, settings.get('wire_tag_family', ''),
                                   settings.get('wire_tag_type', ''))
            lines.append('  tag -> {0}'.format(
                _type_name(symbol) if symbol else 'NOTHING'))
            styles, style_note = line_styles(doc)
            lines.append('line styles in model: {0}  ({1})'.format(
                len(styles), style_note))
            wanted = settings.get('switch_line_style', '')
            lines.append('  switch line style = {0!r} -> {1}'.format(
                wanted,
                'found' if find_line_style(doc, wanted) else
                ('view default' if not wanted else 'NOTHING')))
        except Exception as error:
            lines.append('lookups failed: {0}'.format(error))

    lines.append('')
    lines.append('-- settings --')
    for key in sorted(DEFAULTS.keys()):
        value = settings.get(key, DEFAULTS[key])
        marker = '' if str(value) == str(DEFAULTS[key]) else '   <- changed'
        lines.append('  {0} = {1}{2}'.format(key, value, marker))

    lines.append('')
    lines.append('-- the run --')
    if report is not None:
        lines.append('summary: {0}'.format(report.summary()))
        for kind, text in report.lines:
            lines.append('  [{0}] {1}'.format(kind, text))
    else:
        lines.append('  no report')

    if report is not None and getattr(report, 'trace', None):
        lines.append('')
        lines.append('-- trace --')
        for line in report.trace:
            lines.append('  ' + line)

    for line in (extra_lines or []):
        lines.append(line)

    lines.append('')
    lines.append('-- end --')
    return '\n'.join(lines)


def write_debug_report(text):
    """Drop the report beside the settings file. Returns the path, or None."""
    try:
        if not os.path.isdir(SETTINGS_DIR):
            os.makedirs(SETTINGS_DIR)
        path = os.path.join(SETTINGS_DIR, 'wires_debug.txt')
        handle = open(path, 'w')
        try:
            handle.write(text)
        finally:
            handle.close()
        return path
    except Exception:
        return None



# --- how far back off a symbol a wire stops ---------------------------------
def trim_distance(view, settings, element, direction, reach):
    """How far short of a fitting a wire should stop, in feet.

    One function, used wherever a wire meets a fitting. Returns
    (trim, capped).

    The ceilings matter more than the measurement. A fitting's bounding box is
    not its symbol - a luminaire's box can be metres across - and the first
    version clamped only at 90% of the distance to the next vertex, so an
    oversized box did not look slightly wrong, it dragged the end of the wire
    nearly all the way back and collapsed it to a stub. A trim is a small
    tidying distance by definition, so it is capped at a paper measurement and
    at a third of the span, and the caller is told when the cap bit.
    """
    gap = paper(view, _settings_float(settings, 'trim_gap_paper_mm'))
    if str(settings.get('trim_from', 'extent')).strip().lower() == 'fixed':
        wanted = paper(view, _settings_float(settings, 'trim_fixed_paper_mm'))
    else:
        wanted = plan_half_extent(element, view, direction) + gap

    ceiling = paper(view, _settings_float(settings, 'trim_max_paper_mm'))
    if ceiling <= 0.0:
        ceiling = paper(view, 6)
    limit = min(ceiling, max(0.0, reach) / 3.0)
    trim = max(0.0, min(wanted, limit))
    return trim, wanted > limit + 1.0e-9


# --- where a wire should meet a fitting -------------------------------------
def arrival_point(view, settings, element, centre, from_point, plane_z=None,
                  mode=None):
    """The point a wire arriving from `from_point` should stop at.

    One rule, used both when a wire is drawn and when an existing one is
    re-aligned, so a redrawn circuit and a tidied one agree on where a wire
    meets its fitting.
    """
    if centre is None or from_point is None:
        return None
    z = centre.Z if plane_z is None else plane_z
    if mode is None:
        mode = settings.get('align_target', 'trim')
    mode = str(mode).strip().lower()
    if mode == 'centre':
        return XYZ(centre.X, centre.Y, z)

    dx = centre.X - from_point.X
    dy = centre.Y - from_point.Y
    reach = math.sqrt(dx * dx + dy * dy)
    if reach < 1.0e-9:
        return XYZ(centre.X, centre.Y, z)
    ux = dx / reach
    uy = dy / reach

    if mode == 'edge':
        # where Revit itself puts a re-docked wire: the edge of the symbol
        ceiling = paper(view, _settings_float(settings, 'trim_max_paper_mm'))
        back = min(symbol_radius(element, view), max(ceiling, 0.0),
                   reach * 0.5)
        return XYZ(centre.X - ux * back, centre.Y - uy * back, z)

    trim, _capped = trim_distance(view, settings, element, (ux, uy), reach)
    return XYZ(centre.X - ux * trim, centre.Y - uy * trim, z)
