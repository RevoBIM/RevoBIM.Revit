# -*- coding: utf-8 -*-
"""RevoBIM Match Offset - version, settings, logging and the pure maths.

Nothing in this module touches Revit or WPF, so every rule in it can be run
under plain CPython by bench_logic.py.
"""

import mo_clr  # noqa: F401  - assemblies first, always

import os
import math
import datetime

__version__ = "1.18.0"

TOOL_NAME = u"Match Offset"
RIBBON_PREFIX = u"RevoBIM "

SETTINGS_VERSION = 7
SETTINGS_FILE = u"match_offset.txt"
LOG_FILE = u"match_offset.log"
ERROR_FILE = u"match_offset_last_error.txt"

MM_PER_FT = 304.8
EPS = 1e-6
TOL_MM = 0.1
TOL_FT = TOL_MM / MM_PER_FT

ANCHOR_BOTTOM = u"bottom"
ANCHOR_MIDDLE = u"middle"
ANCHOR_TOP = u"top"
ANCHORS = (ANCHOR_BOTTOM, ANCHOR_MIDDLE, ANCHOR_TOP)

ANCHOR_LABEL = {
    ANCHOR_BOTTOM: u"Bottom",
    ANCHOR_MIDDLE: u"Middle",
    ANCHOR_TOP: u"Top",
}

try:                       # IronPython 2.7 / Python 2
    _TEXT = unicode        # noqa: F821
    _STRINGS = (str, unicode)  # noqa: F821
except NameError:          # Python 3 on the bench
    _TEXT = str
    _STRINGS = (str,)


# ======================================================================
# text and numbers
# ======================================================================

def to_text(value):
    """Anything to unicode, without ever raising."""
    if value is None:
        return u""
    if isinstance(value, _TEXT):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode('utf-8')
        except Exception:
            return value.decode('latin-1', 'replace')
    try:
        return _TEXT(value)
    except Exception:
        try:
            return _TEXT(str(value))
        except Exception:
            return u""


def ft_to_mm(value_ft):
    return float(value_ft) * MM_PER_FT


def mm_to_ft(value_mm):
    return float(value_mm) / MM_PER_FT


def format_mm(value_mm, places=1):
    """A millimetre value as it should read in a prompt or a report."""
    try:
        value = float(value_mm)
    except Exception:
        return u"?"
    if abs(value) < 0.05:
        value = 0.0
    text = u"{0:.{1}f}".format(value, places)
    if u"." in text:
        text = text.rstrip(u"0").rstrip(u".")
    if text in (u"", u"-"):
        text = u"0"
    return text


def parse_number(text, fallback=None):
    """A number out of a settings value or a text box, or the fallback."""
    raw = to_text(text).strip().replace(u",", u"")
    if not raw:
        return fallback
    for suffix in (u"mm", u"MM", u"Mm"):
        if raw.endswith(suffix):
            raw = raw[:-len(suffix)].strip()
            break
    try:
        return float(raw)
    except Exception:
        return fallback


# 0 = not worked out yet, 1 = this release has .Value, 2 = .IntegerValue.
# ISelectionFilter.AllowElement runs this on every element the cursor
# crosses, so the release is worked out once and then it is a single
# attribute read rather than two probes and a swallowed exception.
_EID_MODE = [0]


def eid_value(element_id):
    """ElementId.IntegerValue was removed in Revit 2026; .Value is the one."""
    if element_id is None:
        return 0
    mode = _EID_MODE[0]
    if mode == 1:
        try:
            return element_id.Value
        except Exception:
            _EID_MODE[0] = 0
    elif mode == 2:
        try:
            return element_id.IntegerValue
        except Exception:
            _EID_MODE[0] = 0
    try:
        value = element_id.Value
        _EID_MODE[0] = 1
        return value
    except Exception:
        pass
    try:
        value = element_id.IntegerValue
        _EID_MODE[0] = 2
        return value
    except Exception:
        return 0


# ======================================================================
# the rounding rule
# ======================================================================

ROUND_UP = u"up"
ROUND_NEAREST = u"nearest"
ROUND_DOWN = u"down"
ROUND_MODES = (ROUND_UP, ROUND_NEAREST, ROUND_DOWN)


def round_value(value_mm, step_mm, mode=ROUND_UP):
    """Round a millimetre value to a multiple of step_mm.

    A step of zero or less is no rounding at all, which is the default and
    reproduces the pre-rounding behaviour exactly. "Up" means towards plus
    infinity, so a value below a level rounds towards the level rather than
    away from it. A value already sitting on a multiple is left alone - the
    epsilon is what stops 2450.0000000001 being pushed to 2475.
    """
    try:
        value = float(value_mm)
        step = float(step_mm)
    except Exception:
        return value_mm
    if step <= 0.0:
        return value
    quotient = value / step
    if mode == ROUND_DOWN:
        count = math.floor(quotient + EPS)
    elif mode == ROUND_NEAREST:
        count = math.floor(quotient + 0.5 + EPS)
    else:
        count = math.ceil(quotient - EPS)
    return count * step


# ======================================================================
# anchors, slopes and deltas
# ======================================================================

def anchor_value(bottom_ft, middle_ft, top_ft, anchor):
    """The one of the three elevations this command works to."""
    if anchor == ANCHOR_BOTTOM:
        return bottom_ft
    if anchor == ANCHOR_TOP:
        return top_ft
    return middle_ft


def slope_degrees(rise_ft, run_ft):
    """Pitch of a run, in degrees, from its rise and its plan length."""
    rise = abs(float(rise_ft))
    run = abs(float(run_ft))
    if run < EPS:
        return 90.0 if rise > EPS else 0.0
    return math.degrees(math.atan2(rise, run))


def capture_datum(bottom_ft, middle_ft, top_ft, anchor,
                  level_elevation_ft=0.0, step_mm=0.0,
                  mode=ROUND_UP, datum=u"level"):
    """Turn the source element's own elevations into the datum to apply.

    Returns (datum_ft, raw_mm, rounded_mm, was_rounded), where the two
    millimetre values are in whichever frame the rounding was done in, so a
    prompt can honestly say what it rounded from and to.

    Rounding on the "level" datum works on the offset from the element's own
    reference level, which is the number the user sees in the properties
    palette. On the "project" datum it works on the project elevation, so a
    bank crossing two levels lands on one absolute grid.
    """
    raw_ft = anchor_value(bottom_ft, middle_ft, top_ft, anchor)
    base_ft = float(level_elevation_ft) if datum == u"level" else 0.0
    raw_mm = ft_to_mm(raw_ft - base_ft)
    rounded_mm = round_value(raw_mm, step_mm, mode)
    was_rounded = abs(rounded_mm - raw_mm) > TOL_MM
    datum_ft = base_ft + mm_to_ft(rounded_mm)
    return datum_ft, raw_mm, rounded_mm, was_rounded


def delta_for(bottom_ft, middle_ft, top_ft, anchor, datum_ft):
    """How far up (positive) this element has to move to meet the datum."""
    return float(datum_ft) - anchor_value(bottom_ft, middle_ft, top_ft, anchor)


def already_matched(delta_ft, tolerance_ft=None):
    tol = TOL_FT if tolerance_ft is None else tolerance_ft
    return abs(float(delta_ft)) <= tol


# ======================================================================
# categories
# ======================================================================
# (settings key, label, BuiltInCategory member name). The member name is
# looked up late, inside a function, never at import - one less thing that can
# die before the tool runs.

# (settings key, label, BuiltInCategory member name, group, on by default).
# The member name is looked up late, inside a function, never at import: a
# category a release does not have is skipped rather than taking the tool
# down, which is what lets one list cover Revit 2024 through 2027 where Fire
# Protection, Audio Visual Devices and Plumbing Equipment all arrived at
# different releases.
#
# The structural and architectural categories at the end are off by default.
# They are here because a services bank is often set out against them, but a
# tool that moves a beam because somebody clicked one is worse than a tool
# that needs a box ticked first.

PIPEWORK = u"Pipework"
DUCTWORK = u"Ductwork"
ELECTRICAL = u"Electrical"
FIRE = u"Fire and safety"
EQUIPMENT = u"Equipment and fixtures"
FABRICATION = u"Fabrication and supports"
OTHER = u"Structure and architecture"

CATEGORY_GROUPS = (PIPEWORK, DUCTWORK, ELECTRICAL, FIRE, EQUIPMENT,
                   FABRICATION, OTHER)

CATEGORY_DEFS = (
    (u"pipes", u"Pipes", u"OST_PipeCurves", PIPEWORK, True),
    (u"flex_pipes", u"Flex pipes", u"OST_FlexPipeCurves", PIPEWORK, True),
    (u"pipe_fittings", u"Pipe fittings", u"OST_PipeFitting", PIPEWORK, True),
    (u"pipe_accessories", u"Pipe accessories", u"OST_PipeAccessory",
     PIPEWORK, True),
    (u"pipe_insulation", u"Pipe insulation", u"OST_PipeInsulations",
     PIPEWORK, True),
    (u"plumbing_fixtures", u"Plumbing fixtures", u"OST_PlumbingFixtures",
     PIPEWORK, True),
    (u"plumbing_equipment", u"Plumbing equipment", u"OST_PlumbingEquipment",
     PIPEWORK, True),

    (u"ducts", u"Ducts", u"OST_DuctCurves", DUCTWORK, True),
    (u"flex_ducts", u"Flex ducts", u"OST_FlexDuctCurves", DUCTWORK, True),
    (u"duct_fittings", u"Duct fittings", u"OST_DuctFitting", DUCTWORK, True),
    (u"duct_accessories", u"Duct accessories", u"OST_DuctAccessory",
     DUCTWORK, True),
    (u"air_terminals", u"Air terminals", u"OST_DuctTerminal", DUCTWORK, True),
    (u"duct_insulation", u"Duct insulation", u"OST_DuctInsulations",
     DUCTWORK, True),
    (u"duct_lining", u"Duct lining", u"OST_DuctLinings", DUCTWORK, True),
    (u"mech_equipment", u"Mechanical equipment", u"OST_MechanicalEquipment",
     DUCTWORK, True),
    (u"mech_control_devices", u"Mechanical control devices",
     u"OST_MechanicalControlDevices", DUCTWORK, True),

    (u"cable_trays", u"Cable trays", u"OST_CableTray", ELECTRICAL, True),
    (u"cable_tray_fittings", u"Cable tray fittings", u"OST_CableTrayFitting",
     ELECTRICAL, True),
    (u"conduits", u"Conduits", u"OST_Conduit", ELECTRICAL, True),
    (u"conduit_fittings", u"Conduit fittings", u"OST_ConduitFitting",
     ELECTRICAL, True),
    (u"elec_equipment", u"Electrical equipment", u"OST_ElectricalEquipment",
     ELECTRICAL, True),
    (u"elec_fixtures", u"Electrical fixtures", u"OST_ElectricalFixtures",
     ELECTRICAL, True),
    (u"lighting_fixtures", u"Lighting fixtures", u"OST_LightingFixtures",
     ELECTRICAL, True),
    (u"lighting_devices", u"Lighting devices", u"OST_LightingDevices",
     ELECTRICAL, True),
    (u"data_devices", u"Data devices", u"OST_DataDevices", ELECTRICAL, True),
    (u"comm_devices", u"Communication devices", u"OST_CommunicationDevices",
     ELECTRICAL, True),
    (u"telephone_devices", u"Telephone devices", u"OST_TelephoneDevices",
     ELECTRICAL, True),
    (u"audio_visual", u"Audio visual devices", u"OST_AudioVisualDevices",
     ELECTRICAL, True),

    (u"sprinklers", u"Sprinklers", u"OST_Sprinklers", FIRE, True),
    (u"fire_protection", u"Fire protection", u"OST_FireProtection",
     FIRE, True),
    (u"fire_alarm_devices", u"Fire alarm devices", u"OST_FireAlarmDevices",
     FIRE, True),
    (u"security_devices", u"Security devices", u"OST_SecurityDevices",
     FIRE, True),
    (u"nurse_call_devices", u"Nurse call devices", u"OST_NurseCallDevices",
     FIRE, True),

    (u"specialty_equipment", u"Specialty equipment",
     u"OST_SpecialityEquipment", EQUIPMENT, True),
    (u"medical_equipment", u"Medical equipment", u"OST_MedicalEquipment",
     EQUIPMENT, True),
    (u"food_service", u"Food service equipment",
     u"OST_FoodServiceEquipment", EQUIPMENT, True),
    (u"generic_models", u"Generic models", u"OST_GenericModel",
     EQUIPMENT, True),
    (u"casework", u"Casework", u"OST_Casework", EQUIPMENT, False),
    (u"furniture", u"Furniture", u"OST_Furniture", EQUIPMENT, False),
    (u"furniture_systems", u"Furniture systems", u"OST_FurnitureSystems",
     EQUIPMENT, False),

    (u"fab_ductwork", u"Fabrication ductwork", u"OST_FabricationDuctwork",
     FABRICATION, True),
    (u"fab_pipework", u"Fabrication pipework", u"OST_FabricationPipework",
     FABRICATION, True),
    (u"fab_containment", u"Fabrication containment",
     u"OST_FabricationContainment", FABRICATION, True),
    (u"fab_hangers", u"Fabrication hangers", u"OST_FabricationHangers",
     FABRICATION, True),
    # The support steel modelled in MEP - strut, channel, trapeze bars - as
    # opposed to the building's own structural framing. Revit 2024 and up;
    # on an older Revit the category does not exist and the row is simply
    # not offered.
    (u"mep_ancillary_framing", u"MEP ancillary framing",
     u"OST_MEPAncillaryFraming", FABRICATION, True),

    (u"structural_framing", u"Structural framing", u"OST_StructuralFraming",
     OTHER, False),
    (u"structural_columns", u"Structural columns", u"OST_StructuralColumns",
     OTHER, False),
    (u"columns", u"Columns", u"OST_Columns", OTHER, False),
    (u"structural_foundations", u"Structural foundations",
     u"OST_StructuralFoundation", OTHER, False),
    (u"stairs", u"Stairs", u"OST_Stairs", OTHER, False),
    (u"railings", u"Railings", u"OST_StairsRailing", OTHER, False),
)

CATEGORY_KEYS = tuple([row[0] for row in CATEGORY_DEFS])
DEFAULT_CATEGORY_KEYS = tuple([row[0] for row in CATEGORY_DEFS if row[4]])


# Categories placed as a point rather than drawn as a run: a piece of
# equipment, a fixture, a device, a terminal. What they sit at is their own
# level offset - the number in the properties palette - and that is their
# insertion point, not the extent of whatever their family happens to draw.
# An air terminal's bounding box takes in its neck and its flange; a piece of
# mechanical equipment's takes in its base and its pipe stubs. Measuring the
# "bottom" of either gives a number that matches nothing anybody can see, and
# aligning two of them by it lines up two things that were never the point.
#
# Fittings, accessories, insulation and generic models are deliberately not
# here: a fitting travels with its run and a generic model is usually a hole,
# and for both the extent is what matters.

POINT_BASED_KEYS = (
    u"plumbing_fixtures", u"plumbing_equipment",
    u"air_terminals", u"mech_equipment", u"mech_control_devices",
    u"elec_equipment", u"elec_fixtures",
    u"lighting_fixtures", u"lighting_devices",
    u"data_devices", u"comm_devices", u"telephone_devices", u"audio_visual",
    u"sprinklers", u"fire_protection", u"fire_alarm_devices",
    u"security_devices", u"nurse_call_devices",
    u"specialty_equipment", u"medical_equipment", u"food_service",
    u"casework", u"furniture", u"furniture_systems",
)

FROM_INSERTION = u"insertion"
FROM_SOLID = u"solid"
FROM_BOX = u"box"
FROM_PARAMETERS = u"parameters"
FROM_BEARING = u"bearing"

# Fabrication parts carry their own top and bottom of part, which is what the
# shop and the installer work to, and what the properties palette shows. They
# are not measured like a Revit duct - there is no size parameter and no
# centreline offset in the same places - and they are not point based either.

FAB_KEYS = (u"fab_ductwork", u"fab_pipework", u"fab_containment",
            u"fab_hangers")
HANGER_KEYS = (u"fab_hangers",)
# Support steel: strut, channel, trapeze bars. Like a hanger, what matters
# about it is the face the service sits on, which is its top - so a duct's
# bottom matched onto it puts the strut flush under the duct.
FRAMING_KEYS = (u"mep_ancillary_framing",)
FROM_TOP = u"top"


def is_framing(key):
    return key in FRAMING_KEYS


def is_fabrication(key):
    return key in FAB_KEYS


def is_hanger(key):
    return key in HANGER_KEYS


def rod_length_after(length, delta):
    """What a hanger rod has to become when the hanger moves.

    The rod hangs from the soffit, so the top stays and the bottom goes with
    the hanger: move the hanger down and the rod gets longer by the same
    amount. Returns None where the answer is not a rod any more - a hanger
    raised further than its own rods are long has nothing left to hang from,
    and silently writing a zero or a negative length is worse than saying
    so.
    """
    try:
        new = float(length) - float(delta)
    except Exception:
        return None
    return None if new <= 0.0 else new


def host_offset_direction(asked_ft, moved_ft, tolerance=None):
    """Which way a family's offset from host runs, from one trial write.

    +1 when it went the way it was asked, -1 when it went exactly the other
    way (a family on a ceiling, whose host faces down), 0 when it went
    neither - a parameter that moves nothing is not a route.
    """
    tol = TOL_FT * 10 if tolerance is None else float(tolerance)
    try:
        asked = float(asked_ft)
        moved = float(moved_ft)
    except Exception:
        return 0
    if abs(asked) <= tol:
        return 0
    if abs(moved - asked) <= tol:
        return 1
    if abs(moved + asked) <= tol:
        return -1
    return 0


def level_offset_text(name, bottom_abs_ft, level_abs_ft, label):
    """How a match across levels reads: where the family's anchor ended up,
    measured from the family's own level."""
    try:
        above = ft_to_mm(float(bottom_abs_ft) - float(level_abs_ft))
    except Exception:
        return u""
    return u"{0}: {1} now {2} mm above its own level".format(
        to_text(name), to_text(label).lower(), format_mm(above))


UPRIGHT_RATIO = 1.5
BEARER_SHARE = 0.15
FACE_SHARE = 0.02
HEAD_FT = 150.0 / MM_PER_FT


def is_upright(low, high, span, ratio=UPRIGHT_RATIO):
    """Is this piece of a hanger a rod rather than a bearer?

    A rod, a drop, a riser clamp: taller than it is wide. A bearer, an
    angle, a channel, a strap: wider than it is tall. One number tells them
    apart and it is the only thing about a hanger that is true of every
    hanger ever made.
    """
    try:
        rise = float(high) - float(low)
        across = float(span)
    except Exception:
        return False
    if across <= 0.0:
        return rise > 0.0
    return rise > float(ratio) * across


def bearing_from_members(members, min_normal_z=0.9, ratio=UPRIGHT_RATIO,
                         share=BEARER_SHARE, face_share=FACE_SHARE,
                         head=HEAD_FT):
    """The top of a hanger's bearer, told apart from the rest of the hanger.

    "The biggest upward face" is right for a hanger drawn as a bar and two
    rods and wrong for every hanger drawn in any detail. A channel's biggest
    upward face is the inside of its back, a good two inches below the
    flanges the duct actually sits on; a hanger with a backing plate or a
    second tier has a big upward face in the middle of it that nothing ever
    touches.

    What is true of all of them: services sit on the **bearer**, the bearer
    is the widest piece that is not a rod, it is down at the **bottom of the
    rods**, and what the duct rests on is the **highest** face of it. So:
    throw away the rods, keep the broad pieces at the foot of them, and take
    the highest real face among those.

    members is a list of (low, high, plan span, plan area, faces), one per
    solid, and faces is a list of (how upward the normal is, area, height).
    All of it in feet. Returns None where the geometry does not come in
    pieces that can be told apart - a hanger modelled as one lump has no
    bearer to find, and the caller falls back.
    """
    if members is None or len(members) < 2:
        return None

    uprights = []
    bearers = []
    for member in members:
        try:
            low, high, span, area, faces = member
            upright = is_upright(low, high, span, ratio)
            low = float(low)
            high = float(high)
            area = float(area)
        except Exception:
            continue
        if upright:
            uprights.append((low, high))
        else:
            bearers.append((low, area, faces))
    if not bearers:
        return None

    biggest = 0.0
    for _low, area, _faces in bearers:
        if area > biggest:
            biggest = area
    if biggest <= 0.0:
        return None

    # Anything up at the structure is an anchor, not a bearer. The rods say
    # where the structure is: their feet are where the bearer hangs.
    ceiling = None
    if uprights:
        foot = None
        longest = 0.0
        for low, high in uprights:
            if foot is None or low < foot:
                foot = low
            if high - low > longest:
                longest = high - low
        ceiling = foot + max(float(head), 0.25 * longest)

    best = None
    for low, area, faces in bearers:
        if area < float(share) * biggest:
            continue
        if ceiling is not None and low > ceiling:
            continue
        for face in faces or []:
            try:
                normal_z, face_area, height = face
                if float(normal_z) < float(min_normal_z):
                    continue
                if float(face_area) < float(face_share) * biggest:
                    continue
                if best is None or float(height) > best:
                    best = float(height)
            except Exception:
                continue
    return best


def best_bearing(faces, min_normal_z=0.9):
    """The top of a hanger: the biggest upward-facing flat surface it has.

    A hanger's job is to hold services up, and what it holds them on is the
    top face of its bearer. The top of its geometry is the top of its rods,
    which is up at the soffit and is not where anything sits; the top of its
    bounding box is the same thing. The bearer's top face is the largest
    horizontal face pointing up - a rod end is a few hundred square
    millimetres, a bearer's top is tens of thousands.

    faces is a list of (how upward the normal is, area, elevation).
    """
    best = None
    for normal_z, area, height in faces:
        try:
            if float(normal_z) < float(min_normal_z):
                continue
            if best is None or float(area) > best[0]:
                best = (float(area), float(height))
        except Exception:
            continue
    return None if best is None else best[1]


def is_point_based(key):
    return key in POINT_BASED_KEYS


def category_group(key):
    for row in CATEGORY_DEFS:
        if row[0] == key:
            return row[3]
    return OTHER


def categories_in(group):
    return [row for row in CATEGORY_DEFS if row[3] == group]


def category_label(key):
    for row in CATEGORY_DEFS:
        if row[0] == key:
            return row[1]
    return to_text(key)


# ======================================================================
# settings
# ======================================================================

DEFAULTS = {
    u"settings_version": to_text(SETTINGS_VERSION),
    u"theme": u"auto",                    # auto | dark | light
    u"round_step_mm": u"0",
    u"round_mode": ROUND_UP,              # up | nearest | down
    u"round_datum": u"level",             # level | project
    u"move_source_on_round": u"on",
    u"measure": u"size",                  # size | box
    u"point_measure": u"solid",           # insertion | solid | box
    u"fab_measure": u"parameters",        # parameters | solid | box
    u"fab_hanger_top": u"bearing",        # bearing | solid | box
    u"fab_hanger_rods": u"on",
    u"framing_measure": u"top",           # top | solid | box
    u"include_insulation": u"off",
    u"sloped": u"skip",                   # skip | point
    u"slope_tol_deg": u"0.5",
    u"connected_fittings": u"skip",       # skip | move
    u"use_preselection": u"off",
    u"remember_datum": u"off",
    u"show_results": u"problems",         # problems | always | never
    u"debug_report": u"on",
    u"silent": u"off",
    u"categories": u"|".join(DEFAULT_CATEGORY_KEYS),
    u"key_bottom": u"AB",
    u"key_middle": u"AQ",
    u"key_top": u"AT",
    u"key_slope": u"AS",

    # Match Offset Slope
    u"slope_match_slope": u"on",
    u"slope_source": u"main",             # main | fixed
    u"slope_fixed_n": u"80",
    u"slope_direction": u"towards",       # towards | away | keep
    u"slope_trim": u"on",
    u"slope_fitting": u"auto",            # auto | none
    u"slope_hand_fitting": u"on",
    u"slope_square_branch": u"on",
    u"slope_stub_mm": u"0",
    u"slope_apparent": u"on",
    u"slope_extend_main": u"on",
    u"slope_steep_deg": u"46",
    u"slope_limit": u"400",
    u"slope_end_tol_mm": u"1",
    u"slope_inline_deg": u"2",
    u"slope_in_line": u"on",
    u"slope_repeat": u"pairs",            # pairs | main
    u"slope_inline_offset_mm": u"50",
    u"shortcuts_path": u"",
    u"last_datum_ft": u"",
    u"last_datum_anchor": u"",
}

# Keys a version reset because their meaning changed. Nothing has changed
# meaning yet, but the table ships from day one so the first change is a one
# line edit rather than a design decision under pressure.
MIGRATIONS = {
    # v2 introduced move_source_on_round. A file written by v1 has no such
    # key, so it would fall back to the default anyway; the entry is here
    # because the next key whose meaning changes has to have somewhere
    # obvious to go, and because the version stamp has to move with it.
    2: (u"move_source_on_round",),
    # v3 added Match Offset Slope. Nothing existing changed meaning, so the
    # entry is empty on purpose - the version stamp still has to move, or a
    # later migration would think a v2 file was already current.
    3: (),
    # v4 grew the category list from 25 to every standard MEP category plus
    # the structural ones. A list saved before it names only the old keys, so
    # the new categories would be silently off for anybody who had ever
    # pressed Apply - which reads as the tool not seeing air terminals rather
    # than as a setting.
    4: (u"categories",),
    # v5 added the fabrication categories, so the list grew again; and
    # point_measure changed what it defaults to, from the insertion point for
    # all three anchors to the real solid faces for top and bottom. A file
    # written before it would keep the old answer and read as the tool
    # ignoring what was asked for.
    5: (u"categories", u"point_measure"),
    # v6 added MEP ancillary framing. Nothing changed meaning, so nothing is
    # reset - the new category is added to the saved list instead, below,
    # so a list somebody has trimmed by hand stays trimmed.
    6: (),
    # v7 gave MEP ancillary framing its own setting. Nothing existing
    # changed meaning.
    7: (),
}

# Categories added since a version, ticked onto a saved list rather than
# resetting the list. Resetting it, as v4 and v5 had to, throws away every
# box somebody unticked on purpose.
ADDED_CATEGORIES = {
    6: (u"mep_ancillary_framing",),
}

# Keys that used to exist and no longer do. Ignored on load rather than
# breaking it.
REMOVED_SETTINGS = ()


def appdata_dir():
    root = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(root, 'RevoBIM')


def settings_path():
    return os.path.join(appdata_dir(), SETTINGS_FILE)


def log_path():
    return os.path.join(appdata_dir(), LOG_FILE)


def error_path():
    return os.path.join(appdata_dir(), ERROR_FILE)


def ensure_dir():
    try:
        path = appdata_dir()
        if not os.path.isdir(path):
            os.makedirs(path)
        return True
    except Exception:
        return False


def parse_settings(text):
    """Plain key=value text to a dict, splitting on the first = only.

    A value is allowed to contain = signs, which is what makes a shortcuts
    path or a future table safe to store here. A line with no = at all, or a
    key this version does not know, is dropped rather than breaking the load.
    """
    values = dict(DEFAULTS)
    for line in to_text(text).splitlines():
        line = line.strip()
        if not line or line.startswith(u"#"):
            continue
        if u"=" not in line:
            continue
        key, value = line.split(u"=", 1)
        key = key.strip()
        if not key or key in REMOVED_SETTINGS:
            continue
        if key not in DEFAULTS:
            continue
        values[key] = value.strip()
    return values


def with_categories(saved, keys):
    """A saved category list with keys added, in list order, no repeats."""
    have = [k for k in to_text(saved).split(u"|") if k]
    for key in keys:
        if key not in have:
            have.append(key)
    return u"|".join(have)


def migrate(values):
    """Reset any key whose meaning changed since the file was written."""
    try:
        was = int(parse_number(values.get(u"settings_version"), 0) or 0)
    except Exception:
        was = 0
    for version in sorted(MIGRATIONS.keys()):
        if was < version:
            for key in MIGRATIONS[version]:
                values[key] = DEFAULTS.get(key, u"")
    for version in sorted(ADDED_CATEGORIES.keys()):
        if was < version:
            values[u"categories"] = with_categories(
                values.get(u"categories", u""), ADDED_CATEGORIES[version])
    values[u"settings_version"] = to_text(SETTINGS_VERSION)
    return values


def load_settings():
    """Settings from disk, falling back to the defaults key by key."""
    try:
        path = settings_path()
        if os.path.isfile(path):
            handle = open(path, 'rb')
            try:
                raw = handle.read()
            finally:
                handle.close()
            return migrate(parse_settings(to_text(raw)))
    except Exception:
        pass
    return migrate(dict(DEFAULTS))


def serialise_settings(values):
    lines = []
    for key in sorted(values.keys()):
        if key not in DEFAULTS:
            continue
        lines.append(u"{0}={1}".format(key, to_text(values.get(key, u""))))
    return u"\n".join(lines) + u"\n"


def save_settings(values):
    try:
        ensure_dir()
        text = serialise_settings(values)
        handle = open(settings_path(), 'wb')
        try:
            handle.write(text.encode('utf-8'))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def enabled_categories(values):
    raw = to_text(values.get(u"categories", u"")).strip()
    if not raw:
        return []
    keys = []
    for part in raw.split(u"|"):
        part = part.strip()
        if part and part in CATEGORY_KEYS and part not in keys:
            keys.append(part)
    return keys


def is_on(values, key):
    return to_text(values.get(key, u"")).strip().lower() in (u"on", u"1",
                                                             u"true", u"yes")


def on_off(flag):
    return u"on" if flag else u"off"


def is_silent(values):
    """Whether the run should finish without putting anything on screen.

    Everything a run has to say - the results window and the debug report -
    is held back. A failure to start is not: a tool that dies silently is
    indistinguishable from a broken button, and there is nothing the user
    can do about it if nothing says so. The debug report is still written to
    %APPDATA%\\RevoBIM either way, so a silent run can still be looked at
    afterwards.
    """
    return is_on(values, u"silent")


# ======================================================================
# logging
# ======================================================================

# Lines are buffered and written once at the end of a run. Opening, writing
# and closing the log file per element turned a hundred matched elements into
# a hundred file handles, which is more work than the matching.
_LOG_BUFFER = []
LOG_FLUSH_AT = 400


def log(message):
    """One line for %APPDATA%\\RevoBIM\\match_offset.log. Never raises."""
    try:
        stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        _LOG_BUFFER.append(u"{0}  {1}".format(stamp, to_text(message)))
        if len(_LOG_BUFFER) >= LOG_FLUSH_AT:
            flush_log()
    except Exception:
        pass


def flush_log():
    """Write whatever is buffered. Called in a finally, so a run that dies
    still leaves its log behind."""
    if not _LOG_BUFFER:
        return
    try:
        ensure_dir()
        text = u"\n".join(_LOG_BUFFER) + u"\n"
        handle = open(log_path(), 'ab')
        try:
            handle.write(text.encode('utf-8'))
        finally:
            handle.close()
    except Exception:
        pass
    finally:
        del _LOG_BUFFER[:]


def write_breadcrumb(text):
    """The error file the thin loader writes before anything can fail."""
    try:
        ensure_dir()
        handle = open(error_path(), 'wb')
        try:
            handle.write(to_text(text).encode('utf-8'))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def clear_breadcrumb():
    try:
        path = error_path()
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


# ======================================================================
# the run report
# ======================================================================

class Report(object):
    """What a run has to say for itself.

    notes are informational and never open a window on their own; problems
    are what a clean run must not have, and are what opens the results
    window under the default "only if something needs a look" setting.
    """

    def __init__(self):
        self.notes = []
        self.problems = []
        self.matched = 0
        self.datum_text = u""
        # The debug recorder, when one is running. Kept on the report so
        # every function that already takes a report can write to it without
        # another argument being threaded through the whole tool.
        self.debug = None

    def note(self, text):
        self.notes.append(to_text(text))

    def problem(self, text):
        self.problems.append(to_text(text))

    def matched_one(self):
        self.matched += 1

    def say(self, text):
        """A line for the debug report only. Never shown to the user."""
        if self.debug is not None:
            self.debug.line(u"  {0}".format(to_text(text)))

    def note_pair(self, key, value):
        if self.debug is not None:
            self.debug.pair(key, value)

    def should_show(self, show_results):
        mode = to_text(show_results).strip().lower()
        if mode == u"never":
            return False
        if mode == u"always":
            return bool(self.problems or self.notes or self.matched)
        return bool(self.problems)


def prompt_text(anchor, datum_mm, rounded, step_mm):
    """The status prompt Revit shows during the picks.

    This is the only place the tool tells the user what it captured, which is
    why it carries the value and says when rounding moved it: the house rule
    is that a clean run finishes with no dialog at all.
    """
    label = ANCHOR_LABEL.get(anchor, to_text(anchor))
    if datum_mm is None:
        return u"Match Offset {0}: pick the element to take the {1} offset from".format(
            label, label.lower())
    text = u"{0} {1}".format(label, format_mm(datum_mm))
    if rounded:
        text += u" (rounded to {0})".format(format_mm(step_mm))
    return u"{0} - pick elements to match, Esc to finish".format(text)
