# -*- coding: utf-8 -*-
"""Callout to 3D - bench tests of the rules themselves.

Run under plain CPython from this folder:

    python bench_logic.py

The Revit API is stubbed by import_check, and only the API is stubbed - every
rule under test is the real shipped code.
"""

from __future__ import print_function

import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import import_check                                    # noqa: E402
import_check.install_stubs()

import c3d_core as core                                # noqa: E402
import c3d_geom as geom                                # noqa: E402

PASSED = []
FAILED = []


def check(label, got, want):
    if got == want:
        PASSED.append(label)
    else:
        FAILED.append((label, got, want))


def check_true(label, value):
    check(label, bool(value), True)


def close(label, got, want, tolerance=0.001):
    try:
        ok = abs(float(got) - float(want)) <= tolerance
    except Exception:
        ok = False
    if ok:
        PASSED.append(label)
    else:
        FAILED.append((label, got, want))


# ---------------------------------------------------------------------------
# view template abbreviation
# ---------------------------------------------------------------------------

S = dict(core.DEFAULTS)

check("abbrev: the worked example",
      core.abbreviate_template("04_Documentation_Floorplan_Drainage", S), "Drainage")
check("abbrev: two useful words survive as camel case",
      core.abbreviate_template("04_Documentation_Floorplan_Above Ceiling", S), "AboveCeiling")
check("abbrev: a leading number is dropped",
      core.abbreviate_template("12_Drainage", S), "Drainage")
check("abbrev: a two word stop phrase goes",
      core.abbreviate_template("01_Floor Plan_Ventilation", S), "Ventilation")
check("abbrev: an acronym keeps its case",
      core.abbreviate_template("03_Documentation_Plan_LV", S), "LV")
check("abbrev: nothing left falls back to the last word",
      core.abbreviate_template("Documentation_Plan", S), "Plan")
check("abbrev: an empty name gives nothing",
      core.abbreviate_template("", S), "")
check("abbrev: hyphens split too",
      core.abbreviate_template("04-Documentation-Drainage", S), "Drainage")
check("abbrev: only the last few words are kept",
      core.abbreviate_template("A_B_C_D_E", dict(S, abbrev_max_tokens="2")), "DE")
check("abbrev: as written keeps the source spelling",
      core.abbreviate_template("04_Documentation_drainage", dict(S, abbrev_case="as_is")),
      "drainage")
check("abbrev: upper case mode",
      core.abbreviate_template("04_Documentation_Drainage", dict(S, abbrev_case="upper")),
      "DRAINAGE")
check("abbrev: a word added to the stop list is dropped",
      core.abbreviate_template("04_Documentation_Riser_Drainage",
                               dict(S, abbrev_stopwords="documentation,drainage")), "Riser")
check("abbrev: stopping every word still gives the last one rather than nothing",
      core.abbreviate_template("04_Documentation_Drainage",
                               dict(S, abbrev_stopwords="documentation,drainage")), "Drainage")

check("camel: lower case word", core.camel("drainage"), "Drainage")
check("camel: mixed case survives", core.camel("AboveCeiling"), "AboveCeiling")
check("camel: short acronym survives", core.camel("RCP"), "RCP")


# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------

taken = set()
tokens = {"kind": "3D", "level": "Level 04", "abbrev": "Drainage", "callout": "Callout 1"}
first = core.unique_name(S["view_name_pattern"], tokens, taken)
check("view name: the pattern reads as asked", first, "CO_3D_Level 04_Drainage_1")
second = core.unique_name(S["view_name_pattern"], tokens, taken)
check("view name: a second view counts on", second, "CO_3D_Level 04_Drainage_2")
third = core.unique_name(S["view_name_pattern"], tokens, taken)
check("view name: and a third", third, "CO_3D_Level 04_Drainage_3")

taken2 = set(["co_3d_level 04_drainage_1"])
check("view name: a name already in the model is stepped over",
      core.unique_name(S["view_name_pattern"], tokens, taken2), "CO_3D_Level 04_Drainage_2")

section_tokens = dict(tokens, kind="Section")
taken3 = set()
names = [core.unique_name(S["view_name_pattern"], section_tokens, taken3) for _ in range(4)]
check("view name: four sections come out numbered",
      names, ["CO_Section_Level 04_Drainage_1", "CO_Section_Level 04_Drainage_2",
              "CO_Section_Level 04_Drainage_3", "CO_Section_Level 04_Drainage_4"])

check("clean name: the characters Revit refuses are taken out",
      core.clean_name("Bad:name{here}"), "Bad name here")

taken4 = set()
new_name, changed = core.callout_new_name("Callout of Level 04", "Level 04", S, taken4)
check("callout rename: the prefix goes on", new_name, "CO_Callout of Level 04_Level 04_1")
check("callout rename: it counts as a change", changed, True)

taken5 = set()
again, changed_again = core.callout_new_name("CO_Callout 1_Level 04_1", "Level 04", S, taken5)
check("callout rename: a name already in the form is left alone", again,
      "CO_Callout 1_Level 04_1")
check("callout rename: and reports no change", changed_again, False)

taken6 = set()
stacked, _ = core.callout_new_name("CO_Callout 1", "Level 04", S, taken6)
check("callout rename: the prefix is not stacked twice", stacked, "CO_Callout 1_Level 04_1")

numbers = set()
check("sheet number: the default pattern",
      core.sheet_number_for(S["sheet_number_pattern"], {"level": "L04"}, numbers), "CO_L04_01")
check("sheet number: the next one counts on",
      core.sheet_number_for(S["sheet_number_pattern"], {"level": "L04"}, numbers), "CO_L04_02")
existing = set(["co_l04_01", "co_l04_02"])
check("sheet number: numbers already used are stepped over",
      core.sheet_number_for(S["sheet_number_pattern"], {"level": "L04"}, existing), "CO_L04_03")
check("sheet number: a custom sequence is followed",
      core.sheet_number_for("MEP-{level}-{nnn}", {"level": "04"}, set()), "MEP-04-001")

details = {}
check("sheet name: the first detail",
      core.sheet_name_for(S["sheet_name_pattern"],
                          {"abbrev": "Drainage", "level": "L04"}, details),
      "Callout_Drainage_L04 Detail 1")
check("sheet name: the second detail on the same level counts on",
      core.sheet_name_for(S["sheet_name_pattern"],
                          {"abbrev": "Drainage", "level": "L04"}, details),
      "Callout_Drainage_L04 Detail 2")
check("sheet name: a different discipline starts again",
      core.sheet_name_for(S["sheet_name_pattern"],
                          {"abbrev": "Ventilation", "level": "L04"}, details),
      "Callout_Ventilation_L04 Detail 1")

check("expand: an unknown token is left visible rather than blanked",
      core.expand("A_{nope}", {"level": "x"}), "A_{nope}")

check("level token: full name by default", core.level_token("Level 04 Roof", S), "Level 04 Roof")
check("level token: short takes the numbered part",
      core.level_token("Level 04 Roof", dict(S, level_token="short")), "04")


# ---------------------------------------------------------------------------
# the sheet name push
# ---------------------------------------------------------------------------

pairs, spare = core.split_for_push("Callout_Drainage_L04 Detail 1", "_",
                                   ["Discipline", "Series", "Stage"])
check("name push: the pieces pair up in order",
      pairs, [("Discipline", "Callout"), ("Series", "Drainage"), ("Stage", "L04 Detail 1")])
check("name push: nothing spare here", spare, [])

pairs2, spare2 = core.split_for_push("A_B_C_D", "_", ["One", "Two"])
check("name push: only as many pieces as parameters are written",
      pairs2, [("One", "A"), ("Two", "B")])
check("name push: the spare pieces are reported", spare2, ["C", "D"])

pairs3, _ = core.split_for_push("OnlyOne", "_", ["One", "Two"])
check("name push: a spare parameter is left alone rather than cleared",
      pairs3, [("One", "OnlyOne")])


# ---------------------------------------------------------------------------
# the section array
# ---------------------------------------------------------------------------

check("stations: one section sits on the middle",
      geom.section_stations(1, 0.0, 1000.0), [500.0])
check("stations: two sit at a third and two thirds",
      [round(value, 3) for value in geom.section_stations(2, 0.0, 900.0)], [300.0, 600.0])
check("stations: three are evenly spaced",
      [round(value, 3) for value in geom.section_stations(3, 0.0, 800.0)], [200.0, 400.0, 600.0])
check("stations: none asked for, none given", geom.section_stations(0, 0.0, 1000.0), [])
check("stations: a negative count gives none", geom.section_stations(-2, 0.0, 1000.0), [])
check("stations: never on an edge",
      all([0.0 < value < 1000.0 for value in geom.section_stations(5, 0.0, 1000.0)]), True)
check("stations: an offset span is handled",
      geom.section_stations(1, 2000.0, 3000.0), [2500.0])

frames = geom.section_frames((0.0, 0.0, 4000.0, 3000.0), 2, 1, 0.0, 3500.0, 250.0)
check("frames: two X and one Y", len(frames), 3)
check("frames: the X sections come first", [f["axis"] for f in frames], ["X", "X", "Y"])
check("frames: every X section faces the same way",
      len(set([f["look"] for f in frames if f["axis"] == "X"])), 1)
check("frames: an X section looks along Y",
      frames[0]["look"], (0.0, 1.0, 0.0))
check("frames: a Y section looks along X",
      frames[2]["look"], (-1.0, 0.0, 0.0))
close("frames: an X section spans the callout plus both margins",
      frames[0]["width"], 4500.0)
close("frames: a Y section spans the other way",
      frames[2]["width"], 3500.0)
close("frames: the height is base to top", frames[0]["height"], 3500.0)
close("frames: the origin sits at mid height", frames[0]["origin"][2], 1750.0)
close("frames: the first X station is a third up", frames[0]["origin"][1], 1000.0)

flipped = geom.section_frames((0.0, 0.0, 100.0, 100.0), 1, 1, 0.0, 100.0, 0.0,
                              flip_x=True, flip_y=True)
check("frames: flipping turns the X sections round", flipped[0]["look"], (0.0, -1.0, 0.0))
check("frames: flipping turns the Y sections round", flipped[1]["look"], (1.0, 0.0, 0.0))

labelled = geom.section_frames((0.0, 0.0, 100.0, 100.0), 2, 2, 0.0, 100.0, 0.0)
check("frames: every section is labelled by axis and order",
      [spec["label"] for spec in labelled], ["X1", "X2", "Y1", "Y2"])
check("frames: and says whether it is turned round",
      [spec["flipped"] for spec in labelled], [False, False, False, False])

one = geom.section_frames((0.0, 0.0, 100.0, 100.0), 2, 2, 0.0, 100.0, 0.0,
                          per={"X2": True})
check("frames: one section can be turned round on its own",
      [spec["flipped"] for spec in one], [False, True, False, False])
check("frames: and it really does look the other way",
      one[1]["look"], (0.0, -1.0, 0.0))
check("frames: its neighbour on the same axis is untouched",
      one[0]["look"], (0.0, 1.0, 0.0))

both = geom.section_frames((0.0, 0.0, 100.0, 100.0), 2, 0, 0.0, 100.0, 0.0,
                           flip_x=True, per={"X1": True})
check("frames: an override on a flipped axis turns that one back, rather than "
      "flipping it twice", [spec["flipped"] for spec in both], [False, True])
check("frames: so the flipped-back one looks the original way",
      both[0]["look"], (0.0, 1.0, 0.0))

check("frames: an override for a section that does not exist is ignored",
      len(geom.section_frames((0.0, 0.0, 10.0, 10.0), 1, 0, 0.0, 10.0, 0.0,
                              per={"X9": True})), 1)
check("frames: a Y override only touches Y",
      [spec["flipped"] for spec in
       geom.section_frames((0.0, 0.0, 10.0, 10.0), 1, 1, 0.0, 10.0, 0.0,
                           per={"Y1": True})], [False, True])

check("frames: none asked for, none made",
      geom.section_frames((0.0, 0.0, 10.0, 10.0), 0, 0, 0.0, 10.0), [])


# ---------------------------------------------------------------------------
# where the top of the box goes
# ---------------------------------------------------------------------------

close("top: the level above wins", geom.top_z_mm("next_level", 0.0, 3600.0, 4000.0), 3600.0)
close("top: with no level above it falls back to the fixed height",
      geom.top_z_mm("next_level", 0.0, None, 4000.0), 4000.0)
close("top: a level above at the same elevation is not used",
      geom.top_z_mm("next_level", 3600.0, 3600.0, 4000.0), 7600.0)
close("top: fixed is measured from the level",
      geom.top_z_mm("fixed", 12000.0, 15600.0, 4000.0), 16000.0)
close("top: the offset moves the top off the level above",
      geom.top_z_mm("next_level", 0.0, 3600.0, 4000.0, 250.0), 3850.0)
close("top: a negative offset stops the box short of the slab over it",
      geom.top_z_mm("next_level", 0.0, 3600.0, 4000.0, -300.0), 3300.0)
close("top: the offset is not applied to the fixed height as well",
      geom.top_z_mm("fixed", 0.0, 3600.0, 4000.0, -300.0), 4000.0)
close("top: nor to the fallback when there is no level above",
      geom.top_z_mm("next_level", 0.0, None, 4000.0, -300.0), 4000.0)
close("top: an offset that would put the top under the level falls back",
      geom.top_z_mm("next_level", 0.0, 200.0, 4000.0, -300.0), 4000.0)
check("top: the default offset is 200 below the top",
      core.DEFAULTS["3d_top_offset_mm"], "-200")
check("top: and a value saved before 2.5.0 is reset to it",
      "3d_top_offset_mm" in core.MIGRATIONS.get(5, []), True)
check("top: and a saved value from before it existed is reset",
      "3d_top_offset_mm" in core.MIGRATIONS.get(2, []), True)


# ---------------------------------------------------------------------------
# the cell a viewport is moved into
# ---------------------------------------------------------------------------

check("cell centre", geom.cell_centre((10.0, 20.0, 100.0, 50.0)), (60.0, 45.0))


# ---------------------------------------------------------------------------
# units and settings
# ---------------------------------------------------------------------------

close("units: 304.8mm is a foot", core.mm_to_ft(304.8), 1.0)
close("units: and back again", core.ft_to_mm(1.0), 304.8)
close("units: rubbish gives zero rather than throwing", core.mm_to_ft("nonsense"), 0.0)

check("settings: an integer reads back", core.get_int({"a": "12"}, "a"), 12)
check("settings: a number written as a float still reads",
      core.get_int({"a": "12.0"}, "a"), 12)
check("settings: rubbish falls back", core.get_int({"a": "twelve"}, "a", 5), 5)
check("settings: a missing key falls back", core.get_float({}, "a", 1.5), 1.5)
check("settings: on means true", core.get_bool({"a": "on"}, "a"), True)
check("settings: 0 means false", core.get_bool({"a": "0"}, "a"), False)
check("settings: a pipe separated list splits",
      core.get_list({"a": "one|two| three "}, "a"), ["one", "two", "three"])

values = dict(core.DEFAULTS)
core.set_map(values, "sheet_titleblocks", {"A1": "BGL: A1", "A0": "BGL: A0"})
check("settings: a map writes in a stable order",
      values["sheet_titleblocks"], "A0=BGL: A0|A1=BGL: A1")
check("settings: and reads back",
      core.get_map(values, "sheet_titleblocks"), {"A0": "BGL: A0", "A1": "BGL: A1"})

handle, path = tempfile.mkstemp(suffix=".txt")
os.close(handle)
try:
    core.save_settings(values, path)
    back = core.load_settings(path)
    check("settings: a value with '=' in it survives the round trip",
          back["sheet_titleblocks"], values["sheet_titleblocks"])
    check("settings: the version is stamped",
          back["settings_version"], str(core.SETTINGS_VERSION))
    handle = open(path, "a")
    handle.write("\nnot_a_real_key=1\nrubbish line with no equals\n")
    handle.close()
    damaged = core.load_settings(path)
    check("settings: an unknown key is ignored rather than breaking the load",
          "not_a_real_key" in damaged, False)
    check("settings: and the real keys still come back",
          damaged["sheet_number_pattern"], core.DEFAULTS["sheet_number_pattern"])
finally:
    try:
        os.remove(path)
    except Exception:
        pass

missing = core.load_settings(os.path.join(tempfile.gettempdir(), "c3d_not_here.txt"))
check("settings: a missing file falls back to the defaults key by key",
      missing["sheet_size_default"], core.DEFAULTS["sheet_size_default"])

check("ids: a None id is zero", core.eid_value(None), 0)


# ---------------------------------------------------------------------------
# the band writes through to the rows
# ---------------------------------------------------------------------------

band_rows = [{"x_count": 2, "y_count": 2, "depth_mm": 500.0, "size": "A1"},
             {"x_count": 2, "y_count": 2, "depth_mm": 500.0, "size": "A1"}]
check("band: asking for three X puts three X on every row it applies to",
      core.apply_counts(band_rows, 3, 2, 500.0, "A1"), 2)
check("band: and the rows really carry it",
      [row["x_count"] for row in band_rows], [3, 3])
check("band: five sections asked for is five sections on the row",
      band_rows[0]["x_count"] + band_rows[0]["y_count"], 5)
check("band: setting the same values again moves nothing",
      core.apply_counts(band_rows, 3, 2, 500.0, "A1"), 0)
check("band: the depth and the sheet size go through too",
      core.apply_counts(band_rows, 3, 2, 750.0, "A0"), 2)
check("band: and land", (band_rows[0]["depth_mm"], band_rows[0]["size"]), (750.0, "A0"))
check("band: no rows, nothing to do", core.apply_counts([], 3, 2, 500.0, "A1"), 0)
check("band: nothing at all is handled", core.apply_counts(None, 3, 2, 500.0, "A1"), 0)


# ---------------------------------------------------------------------------
# opening the sheets afterwards
# ---------------------------------------------------------------------------

import c3d_ops as ops                                   # noqa: E402


class _FakeView(object):
    def __init__(self, name):
        self.Name = name


class _FakeDoc(object):
    def __init__(self, views):
        self._views = views

    def GetElement(self, view_id):
        return self._views.get(view_id)


class _FakeUiDoc(object):
    def __init__(self, views):
        self.Document = _FakeDoc(views)
        self.requested = []
        self.activated = []
        self._active = None

    def RequestViewChange(self, view):
        self.requested.append(view.Name)

    def _get_active(self):
        return self._active

    def _set_active(self, view):
        self._active = view
        self.activated.append(view.Name)

    ActiveView = property(_get_active, _set_active)


class _FakeUiApp(object):
    def __init__(self, uidoc):
        self.ActiveUIDocument = uidoc


def _open(view_ids, views, single=None):
    uidoc = _FakeUiDoc(views)
    handler = ops.OpenViewHandler()
    handler.view_ids = list(view_ids)
    handler.view_id = single
    handler.Execute(_FakeUiApp(uidoc))
    return uidoc, handler


VIEWS = {1: _FakeView("CO_L04_01"), 2: _FakeView("CO_L04_02"),
         3: _FakeView("CO_L04_03")}

uidoc, handler = _open([1], VIEWS)
check("open: one sheet goes through RequestViewChange", uidoc.requested, ["CO_L04_01"])
check("open: and does not touch ActiveView", uidoc.activated, [])

uidoc, handler = _open([1, 2, 3], VIEWS)
check("open: several are opened one at a time through ActiveView",
      uidoc.activated, ["CO_L04_01", "CO_L04_02", "CO_L04_03"])
check("open: RequestViewChange is not used for several, since only the last "
      "would survive the API context", uidoc.requested, [])
check("open: the last sheet is left in front", uidoc.ActiveView.Name, "CO_L04_03")
check("open: the list is cleared so a second raise cannot repeat it",
      handler.view_ids, [])

uidoc, _handler = _open([], VIEWS, single=2)
check("open: the single id still works on its own", uidoc.requested, ["CO_L04_02"])

uidoc, _handler = _open([9, 1, 8], VIEWS)
check("open: an id that is no longer in the model is stepped over",
      uidoc.activated, ["CO_L04_01"])

uidoc, _handler = _open([], VIEWS)
check("open: nothing asked for, nothing opened",
      (uidoc.requested, uidoc.activated), ([], []))


# ---------------------------------------------------------------------------
# the results carry what the run made
# ---------------------------------------------------------------------------

results = ops.Results()
check("results: no sheets to start with", results.sheet_ids, [])
results.sheets.append(("CO_L04_01", "Callout_Drainage_L04 Detail 1", 4))
results.sheet_ids.append(1)
check("results: a sheet id is kept beside its name", results.sheet_ids, [1])
check("results: a clean run needs no look", results.needs_a_look, False)
results.warn("something")
check("results: a warning does", results.needs_a_look, True)


# ---------------------------------------------------------------------------
# the title block for a paper size
# ---------------------------------------------------------------------------

import c3d_model as model                               # noqa: E402


class _TitleDoc(object):
    def __init__(self, blocks):
        self.blocks = blocks


def _blocks(pairs):
    return [{"type": None, "id": None, "family": family, "type_name": type_name,
             "name": u"{0}: {1}".format(family, type_name)}
            for family, type_name in pairs]


HOUSE = _blocks([("BGL_TitleBlocks_A0-A1-A2", "BGL_A0"),
                 ("BGL_TitleBlocks_A0-A1-A2", "BGL_A0_L"),
                 ("BGL_TitleBlocks_A0-A1-A2", "BGL_A1"),
                 ("BGL_TitleBlocks_A0-A1-A2", "BGL_A1_L"),
                 ("BGL_TitleBlocks_A0-A1-A2", "BGL_A2")])


def _for_size(size, mapping=None, blocks=None):
    original = model.title_blocks
    model.title_blocks = lambda doc: (blocks if blocks is not None else HOUSE)
    try:
        return model.title_block_for_size(None, size, mapping)
    finally:
        model.title_blocks = original


check("title block: A1 picks the A1 type, not the first type in a family whose "
      "name happens to list every size",
      _for_size("A1")["type_name"], "BGL_A1")
check("title block: A0 picks A0", _for_size("A0")["type_name"], "BGL_A0")
check("title block: A2 picks A2", _for_size("A2")["type_name"], "BGL_A2")
check("title block: the settings map wins outright",
      _for_size("A1", {"A1": "BGL_TitleBlocks_A0-A1-A2: BGL_A1_L"})["type_name"],
      "BGL_A1_L")
check("title block: a family on its own in the map still narrows it",
      _for_size("A2", {"A2": "BGL_TitleBlocks_A0-A1-A2:"})["family"],
      "BGL_TitleBlocks_A0-A1-A2")
check("title block: a size nothing is named for falls back rather than failing",
      _for_size("A3") is not None, True)
check("title block: no title blocks at all gives nothing",
      _for_size("A1", blocks=[]), None)
check("title block: a family name is used when no type name carries the size",
      _for_size("A1", blocks=_blocks([("House_A1_Sheet", "Standard")]))["type_name"],
      "Standard")


# ---------------------------------------------------------------------------
# the scale is proved, not assumed
# ---------------------------------------------------------------------------


class _ScaleView(object):
    """A view whose template refuses the scale, the way Revit does it: the
    write does not raise, it just does not take."""

    def __init__(self, locked_at=None):
        self.Scale = 50
        self._locked_at = locked_at
        self.ViewTemplateId = None
        self.Document = None

    def __setattr__(self, name, value):
        if name == "Scale" and getattr(self, "_locked_at", None):
            object.__setattr__(self, "Scale", self._locked_at)
            return
        object.__setattr__(self, name, value)


free = _ScaleView()
report = ops.Results()
ops._set_scale(free, 100, report, "the 3D")
check("scale: a view that takes it is set", free.Scale, 100)
check("scale: and nothing is reported", report.warnings, [])

locked = _ScaleView(locked_at=200)
report = ops.Results()
ops._set_scale(locked, 100, report, "the 3D")
check("scale: a scale that will not take is not reported as success",
      locked.Scale, 200)
check("scale: it says what it asked for and what it got",
      len(report.warnings), 1)
check("scale: and needs a look", report.needs_a_look, True)

report = ops.Results()
ops._set_scale(_ScaleView(), 0, report, "the 3D")
check("scale: no scale asked for, nothing done and nothing said",
      report.warnings, [])


# ---------------------------------------------------------------------------
# the not-on-a-sheet filter
# ---------------------------------------------------------------------------

import c3d_grid as grid_module                          # noqa: E402


class _FakeGrid(object):
    def __init__(self):
        self.ItemsSource = None


def _table(rows):
    table = grid_module.CalloutGrid.__new__(grid_module.CalloutGrid)
    table.window = None
    table.grid = _FakeGrid()
    table.rows = rows
    table.visible = list(rows)
    table.on_change = None
    table.on_select = None
    table.searches = {}
    table.filters = {}
    table.keyword = ""
    table.prefilter = None
    table.sort_key = None
    table.sort_down = False
    return table


def _row(name, sheet=None, checked=False):
    return {"name": name, "sheet": sheet, "sheet_text": (sheet or ""),
            "checked": checked, "level_mm": 0.0, "x_count": 1, "y_count": 1,
            "level_name": "L04", "parent_name": "", "scale": 50,
            "size_mm": (1000.0, 1000.0), "status": "", "note": "",
            "depth_mm": 500.0, "size": "A1", "sheet_number": ""}


rows = [_row("CO 1"), _row("CO 2", sheet="A-100"), _row("CO 3"),
        _row("CO 4", sheet="A-101")]
table = _table(rows)

table.prefilter = lambda row: not row.get("sheet")
table.refresh()
check("sheet filter: only the callouts not on a sheet are shown",
      [row["name"] for row in table.visible], ["CO 1", "CO 3"])
check("sheet filter: the hidden ones are still in the row list", len(table.rows), 4)

table.prefilter = None
table.refresh()
check("sheet filter: unticking it brings them all back",
      [row["name"] for row in table.visible], ["CO 1", "CO 2", "CO 3", "CO 4"])

rows[1]["checked"] = True
rows[2]["checked"] = True
check("ticking: everything ticked runs while everything is on show",
      [row["name"] for row in table.ticked()], ["CO 2", "CO 3"])
check("ticking: and nothing is out of sight", table.ticked_out_of_sight(), [])

table.prefilter = lambda row: not row.get("sheet")
table.refresh()
check("ticking: a ticked row filtered out of sight does not join the run",
      [row["name"] for row in table.ticked()], ["CO 3"])
check("ticking: it is reported rather than dropped quietly",
      [row["name"] for row in table.ticked_out_of_sight()], ["CO 2"])

check("sheet filter: the default is to hide what is already on a sheet",
      core.DEFAULTS["hide_on_sheet"], "1")


# ---------------------------------------------------------------------------
# what the Flip column says
# ---------------------------------------------------------------------------

check("flip column: nothing flipped, nothing said",
      grid_module._flip_text({}), "")
check("flip column: a whole axis reads as its letter",
      grid_module._flip_text({"flip_x": True}), "X")
check("flip column: both axes",
      grid_module._flip_text({"flip_x": True, "flip_y": True}), "X Y")
check("flip column: a single section reads as its own label",
      grid_module._flip_text({"flips": {"Y2": True}}), "Y2")
check("flip column: an axis and a section together",
      grid_module._flip_text({"flip_x": True, "flips": {"X3": True, "Y1": True}}),
      "X X3 Y1")


# ---------------------------------------------------------------------------
# finding the callouts
# ---------------------------------------------------------------------------

import c3d_model as model                               # noqa: E402


class _Id(object):
    def __init__(self, value):
        self.Value = value

    def __eq__(self, other):
        return getattr(other, "Value", None) == self.Value

    def __hash__(self):
        return hash(self.Value)


class _Type(object):
    def __init__(self, name):
        self.Name = name


class _View(model.ViewPlan, model.View):
    """A plan view, which is what a callout of a plan actually is - and what
    the scan collects by class rather than by asking every view in turn."""

    def __init__(self, name, type_id, template=False, refs=None):
        self.Name = name
        self.Id = _Id(id(self) % 100000)
        self._type_id = type_id
        self.IsTemplate = template
        self._refs = refs or []

    def GetTypeId(self):
        return self._type_id

    def GetReferenceCallouts(self):
        return self._refs


class _Collector(object):
    def __init__(self, doc):
        self.doc = doc
        self.want = None

    def OfClass(self, cls):
        self.want = cls
        return self

    def OfCategory(self, bic):
        self.want = "category"
        return self

    def WhereElementIsNotElementType(self):
        return self

    def WhereElementIsElementType(self):
        return self

    def __iter__(self):
        if self.want == "category":
            return iter(self.doc.markers)
        return iter([view for view in self.doc.views if isinstance(view, self.want)])


class _Doc(object):
    def __init__(self, views, types, markers=None):
        self.views = views
        self.markers = markers or []
        self._types = types

    def GetElement(self, element_id):
        key = getattr(element_id, "Value", element_id)
        if key in self._types:
            return self._types[key]
        for view in self.views:
            if getattr(view.Id, "Value", None) == key:
                return view
        return None


PLAN_TYPE, CALLOUT_TYPE, DETAIL_TYPE = _Id(1), _Id(2), _Id(3)
TYPES = {1: _Type("Floor Plan"), 2: _Type("BGL_Callout"), 3: _Type("Detail View")}


def _find(views, settings, markers=None):
    doc = _Doc(views, TYPES, markers)
    original = model.FilteredElementCollector
    model.FilteredElementCollector = lambda document: _Collector(document)
    try:
        return model.find_callout_views(doc, settings, False)
    finally:
        model.FilteredElementCollector = original


VIEWS = [_View("Level 04", PLAN_TYPE),
         _View("Riser 1", CALLOUT_TYPE),
         _View("Riser 2", CALLOUT_TYPE),
         _View("Detail 1", DETAIL_TYPE),
         _View("A template", CALLOUT_TYPE, template=True)]

base = dict(core.DEFAULTS)
rows, routes = _find(VIEWS, base)
check("finding: the type name route picks up the callout types",
      sorted([item["view"].Name for item in rows]), ["Riser 1", "Riser 2"])
check("finding: and says so", routes["type"], 2)
check("finding: a view template is never a callout",
      [item for item in rows if item["view"].IsTemplate], [])

rows, _routes = _find(VIEWS, dict(base, type_contains="Detail"))
check("finding: the token is what decides it",
      [item["view"].Name for item in rows], ["Detail 1"])

rows, _routes = _find(VIEWS, dict(base, type_contains="callout, detail"))
check("finding: a comma separated token list takes any one of them",
      sorted([item["view"].Name for item in rows]),
      ["Detail 1", "Riser 1", "Riser 2"])

rows, _routes = _find(VIEWS, dict(base, type_contains="CALLOUT"))
check("finding: the match ignores case", len(rows), 2)

rows, _routes = _find(VIEWS, dict(base, type_contains="Nothing like this"))
check("finding: a token that matches nothing finds nothing", rows, [])

rows, _routes = _find(VIEWS, dict(base, route_type="0"))
check("finding: the route can be turned off", rows, [])

rows, _routes = _find(VIEWS, dict(base, type_contains=""))
check("finding: an empty token turns it off rather than matching everything",
      rows, [])

check("finding: the default token is Callout", core.DEFAULTS["type_contains"], "Callout")
check("finding: all three routes are on by default",
      [core.get_bool(core.DEFAULTS, key) for key in
       ("route_reference", "route_marker", "route_type")], [True, True, True])
check("finding: the views shown are callouts only, by default",
      core.view_filter(core.DEFAULTS), "callouts")

# ---------------------------------------------------------------------------
# 2.7.0 - a plan with a marker drawn somewhere is a callout
class _Section(model.ViewSection, model.View):
    def __init__(self, name):
        self.Name = name
        self.Id = _Id(id(self) % 100000)
        self.IsTemplate = False
        self.ViewType = "Section"

    def GetTypeId(self):
        return PLAN_TYPE


class _Viewer(object):
    def __init__(self, name, owner):
        self.Name = name
        self.Id = _Id(900000 + len(name))
        self.OwnerViewId = owner.Id
        self.Parameters = []

    def get_Parameter(self, which):
        return None


_level = _View("Level 00", PLAN_TYPE)
_plant = _View("Plant Room", PLAN_TYPE)              # a callout on a plain plan type
_cut = _Section("Section 1")
_viewer_views = [_level, _plant, _cut]
_viewer_rows, _viewer_routes = _find(
    _viewer_views, dict(base, type_contains=""),
    [_Viewer("Plant Room", _level), _Viewer("Section 1", _level)])
check("viewer: a plan with a marker in another view is a callout, whatever its type",
      [item["view"].Name for item in _viewer_rows], ["Plant Room"])
check("viewer: found by its marker, and said so", _viewer_routes["viewer"], 1)
check("viewer: drawn in the parent view the marker sits in",
      _viewer_rows[0]["parent"] is _level, True)
check("viewer: a section's own marker does not make it a callout",
      model.is_callout_kind(_cut), False)
check("viewer: nor does a plan with no marker anywhere",
      "Level 00" in [item["view"].Name for item in _viewer_rows], False)
check("viewer: the route can be turned off",
      _find(_viewer_views, dict(base, type_contains="", route_viewer="0", route_marker="0"),
            [_Viewer("Plant Room", _level)])[0], [])

check("views box: callouts only hides a plan that is not one",
      [core.keeps_view({"is_callout": flag}, "callouts") for flag in (True, False)], [True, False])
check("views box: floor plans only is the other way round",
      [core.keeps_view({"is_callout": flag}, "plans") for flag in (True, False)], [False, True])
check("views box: both shows both",
      [core.keeps_view({"is_callout": flag}, "both") for flag in (True, False)], [True, True])
check("views box: an unknown setting is callouts only",
      core.view_filter({"view_filter": "nonsense"}), "callouts")

doc = _Doc(VIEWS, TYPES)
cache = {}
check("type name: read from the view's own type",
      model.view_type_name(doc, VIEWS[1], cache), "BGL_Callout")
check("type name: and cached by type id, not by view",
      model.view_type_name(doc, VIEWS[2], cache), "BGL_Callout")
check("type name: one entry per type", len(cache), 1)

original = model.FilteredElementCollector
model.FilteredElementCollector = lambda document: _Collector(document)
try:
    tally = model.view_type_tally(doc)
finally:
    model.FilteredElementCollector = original
check("type tally: the commonest type comes first, templates left out",
      tally, [("BGL_Callout", 2), ("Detail View", 1), ("Floor Plan", 1)])


# ---------------------------------------------------------------------------
# route order is a speed decision
# ---------------------------------------------------------------------------

child = _View("Riser detail", PLAN_TYPE)
parent = _View("Level 04 plan", PLAN_TYPE, refs=[child.Id])
PAIR = [parent, child, _View("Riser 1", CALLOUT_TYPE)]

rows, routes = _find(PAIR, base)
check("order: the cheap type route answers, so the slow one is not run",
      routes["reference"], 0)
check("order: and it says it was skipped rather than that it found nothing",
      routes["ms"].get("reference"), -1.0)
check("order: the type route did the work", routes["type"], 1)

rows, routes = _find(PAIR, dict(base, route_type="0"))
check("order: with nothing else to go on the slow route runs",
      [item["view"].Name for item in rows], ["Riser detail"])
check("order: and is counted", routes["reference"], 1)
check("order: it is the route that fills in the parent",
      rows[0]["parent"].Name, "Level 04 plan")
check("order: and it was timed rather than marked skipped",
      routes["ms"].get("reference") >= 0, True)

rows, routes = _find(PAIR, dict(base, route_reference_always="1"))
check("order: ticking 'run it anyway' runs it alongside the others",
      routes["reference"], 1)
check("order: both routes' finds are merged",
      sorted([item["view"].Name for item in rows]), ["Riser 1", "Riser detail"])

rows, routes = _find(PAIR, dict(base, route_reference="0", route_type="0",
                                route_marker="0"))
check("order: every route off finds nothing rather than throwing", rows, [])

check("order: the slow route is on by default, but not forced",
      [core.get_bool(core.DEFAULTS, "route_reference"),
       core.get_bool(core.DEFAULTS, "route_reference_always")], [True, False])
check("order: the scan looks at plan views by default",
      core.DEFAULTS["scan_scope"], "plans")

original = model.FilteredElementCollector
model.FilteredElementCollector = lambda document: _Collector(document)
try:
    scanned = model.scan_views(doc, dict(base))
    scanned_all = model.scan_views(doc, dict(base, scan_scope="every"))
    scanned_bad = model.scan_views(doc, dict(base, scan_scope="nonsense"))
finally:
    model.FilteredElementCollector = original

check("scan: plans only is the default, and it is a class filter not a "
      "property read", len(scanned), 4)
check("scan: view templates never come back",
      [view for view in scanned if view.IsTemplate], [])
check("scan: every view is an option", len(scanned_all), 4)
check("scan: an unknown scope falls back to plans rather than to nothing",
      len(scanned_bad), 4)
check("scan: the default scope", core.DEFAULTS["scan_scope"], "plans")


# ---------------------------------------------------------------------------
# the callout frame, in model space
# ---------------------------------------------------------------------------

FT = 304.8


class _XYZ(object):
    def __init__(self, x, y, z=0.0):
        self.X, self.Y, self.Z = float(x), float(y), float(z)

    def Normalize(self):
        length = (self.X ** 2 + self.Y ** 2 + self.Z ** 2) ** 0.5 or 1.0
        return _XYZ(self.X / length, self.Y / length, self.Z / length)

    def CrossProduct(self, other):
        return _XYZ(self.Y * other.Z - self.Z * other.Y,
                    self.Z * other.X - self.X * other.Z,
                    self.X * other.Y - self.Y * other.X)

    def __repr__(self):
        return "({0:.3f}, {1:.3f}, {2:.3f})".format(self.X, self.Y, self.Z)


class _Transform(object):
    """A rotation about Z plus a translation, which is every crop transform a
    plan callout can have."""

    def __init__(self, origin=None, angle=0.0):
        import math as _math
        self.Origin = origin or _XYZ(0, 0, 0)
        self._cos = _math.cos(angle)
        self._sin = _math.sin(angle)
        self.BasisX = _XYZ(self._cos, self._sin, 0)
        self.BasisY = _XYZ(-self._sin, self._cos, 0)
        self.BasisZ = _XYZ(0, 0, 1)

    def OfVector(self, vector):
        return _XYZ(vector.X * self._cos - vector.Y * self._sin,
                    vector.X * self._sin + vector.Y * self._cos, vector.Z)

    def OfPoint(self, point):
        turned = self.OfVector(point)
        return _XYZ(turned.X + self.Origin.X, turned.Y + self.Origin.Y,
                    turned.Z + self.Origin.Z)


class _Identity(object):
    @property
    def Identity(self):
        return _Transform()


class _Box(object):
    def __init__(self, transform=None, low=None, high=None):
        self.Transform = transform
        self.Min = low
        self.Max = high


class _CropView(object):
    def __init__(self, box):
        self.CropBox = box


geom.XYZ = _XYZ
geom.Transform = _Identity()
geom.BoundingBoxXYZ = _Box


def _crop(centre_mm, size_mm, angle=0.0):
    """A crop box the way Revit hands one over: local coordinates plus a
    transform, with the local minimum nowhere near the model minimum."""
    origin = _XYZ(centre_mm[0] / FT, centre_mm[1] / FT, 3.0)
    half_x, half_y = size_mm[0] / 2.0 / FT, size_mm[1] / 2.0 / FT
    box = _Box(_Transform(origin, angle),
               _XYZ(-half_x, -half_y, -1.0), _XYZ(half_x, half_y, 1.0))
    return geom.crop_frame(_CropView(box))


class _Curve(object):
    def __init__(self, start, end):
        self._points = (start, end)

    def GetEndPoint(self, index):
        return self._points[index]


class _ShapeManager(object):
    def __init__(self, loops):
        self._loops = loops

    def GetCropShape(self):
        return self._loops


class _ShapeView(object):
    """A view that answers both ways, so which one wins can be proved."""

    def __init__(self, loops, box=None):
        self._manager = _ShapeManager(loops)
        self.CropBox = box

    def GetCropRegionShapeManager(self):
        return self._manager


def _loop(centre_mm, size_mm):
    half_x, half_y = size_mm[0] / 2.0, size_mm[1] / 2.0
    corners = [(centre_mm[0] - half_x, centre_mm[1] - half_y),
               (centre_mm[0] + half_x, centre_mm[1] - half_y),
               (centre_mm[0] + half_x, centre_mm[1] + half_y),
               (centre_mm[0] - half_x, centre_mm[1] + half_y)]
    curves = []
    for index in range(4):
        start = corners[index]
        end = corners[(index + 1) % 4]
        curves.append(_Curve(_XYZ(start[0] / FT, start[1] / FT, 12000.0 / FT),
                             _XYZ(end[0] / FT, end[1] / FT, 12000.0 / FT)))
    return [curves]


shape_frame = geom.crop_frame(_ShapeView(_loop((120000.0, 45000.0), (8000.0, 5000.0))))
close("crop region: the centre comes straight out of the model coordinates",
      shape_frame["centre"][0], 120000.0, 0.5)
close("crop region: on both axes", shape_frame["centre"][1], 45000.0, 0.5)
close("crop region: half the width", shape_frame["half_x"], 4000.0, 0.5)
close("crop region: half the height", shape_frame["half_y"], 2500.0, 0.5)
check("crop region: and it says where it came from",
      shape_frame["source"], "crop region")
check("crop region: a square crop is not called rotated",
      shape_frame["rotated"], False)
close("crop region: the elevation is the curves' own",
      shape_frame["z"], 12000.0, 1.0)

# a crop box that disagrees must not win
wrong_box = _Box(_Transform(_XYZ(240000.0 / FT, 90000.0 / FT, 3.0), 0.0),
                 _XYZ(-4000.0 / FT, -2500.0 / FT, -1.0),
                 _XYZ(4000.0 / FT, 2500.0 / FT, 1.0))
both = geom.crop_frame(_ShapeView(_loop((120000.0, 45000.0), (8000.0, 5000.0)), wrong_box))
close("crop region: the curves win over a crop box that disagrees",
      both["centre"][0], 120000.0, 0.5)
check("crop region: and the frame says which was used", both["source"], "crop region")

check("crop region: a view with no crop shape falls back to the box",
      _crop((10000.0, 0.0), (1000.0, 1000.0))["source"], "crop box")
check("crop region: an empty crop shape falls back too",
      geom.crop_frame(_ShapeView([], wrong_box))["source"], "crop box")


# ---------------------------------------------------------------------------
# one crop read per callout per refresh, and one log line per view
# ---------------------------------------------------------------------------


class _CountingView(_ShapeView):
    """Counts how often its crop is asked for."""

    def __init__(self, loops, box, view_id):
        _ShapeView.__init__(self, loops, box)
        self.Id = _Id(view_id)
        self.asked = 0

    def GetCropRegionShapeManager(self):
        self.asked += 1
        return _ShapeView.GetCropRegionShapeManager(self)


counted = _CountingView(_loop((120000.0, 45000.0), (8000.0, 5000.0)), wrong_box, 4242)
frames = {}
first_read = geom.crop_frame(counted, frames)
second_read = geom.crop_frame(counted, frames)
check("cache: the second read of a callout in the same refresh is the first one",
      first_read is second_read, True)
check("cache: and the crop was only asked for once", counted.asked, 1)
check("cache: with no cache it is read fresh, as the debug report wants",
      geom.crop_frame(counted) is not first_read, True)

logged = []
real_log = core.log
core.log = lambda text: logged.append(text)
try:
    geom._DISAGREEMENT_SAID.discard(4343)
    noisy = _CountingView(_loop((120000.0, 45000.0), (8000.0, 5000.0)), wrong_box, 4343)
    for _round in range(6):
        geom.crop_frame(noisy, {})
finally:
    core.log = real_log
check("log: a crop disagreement is said once, not once per read - it was six "
      "identical lines per refresh", len([line for line in logged if "disagree" in line]), 1)


# ---------------------------------------------------------------------------
# the section direction is remembered
# ---------------------------------------------------------------------------

check("direction: a fresh install starts from the documented convention",
      core.DEFAULTS["sec_sign"], "-1")
check("direction: it is a setting, so what the first section taught is kept",
      "sec_sign" in core.DEFAULTS, True)

frame = _crop((120000.0, 45000.0), (8000.0, 5000.0))
close("frame: the centre comes out in model millimetres, not local ones",
      frame["centre"][0], 120000.0, 0.5)
close("frame: on both axes", frame["centre"][1], 45000.0, 0.5)
close("frame: half the width", frame["half_x"], 4000.0, 0.5)
close("frame: half the height", frame["half_y"], 2500.0, 0.5)
check("frame: a callout square to the project is not rotated", frame["rotated"], False)

turned = _crop((10000.0, 0.0), (4000.0, 2000.0), angle=math.pi / 2.0)
check("frame: a rotated callout is spotted", turned["rotated"], True)
close("frame: and its X axis has turned with it", turned["axis_x"][1], 1.0, 0.001)
close("frame: its centre is still the model centre", turned["centre"][0], 10000.0, 0.5)

ext = geom.extents_mm(frame, 0.0)
check("extents: measured from the centre, so they are symmetric",
      [round(value, 1) for value in ext], [-4000.0, -2500.0, 4000.0, 2500.0])
ext_margin = geom.extents_mm(frame, 250.0)
check("extents: a margin grows them both ways",
      [round(value, 1) for value in ext_margin], [-4250.0, -2750.0, 4250.0, 2750.0])

box = geom.section_box(frame, ext, -50.0, 3300.0)
close("3D box: the left hand edge sits on the callout, not on the origin",
      box.Min.X * FT, 116000.0, 1.0)
close("3D box: the right hand edge too", box.Max.X * FT, 124000.0, 1.0)
close("3D box: the near edge", box.Min.Y * FT, 42500.0, 1.0)
close("3D box: the far edge", box.Max.Y * FT, 47500.0, 1.0)
close("3D box: the bottom is the level less its offset", box.Min.Z * FT, -50.0, 0.5)
close("3D box: the top is the level above less its offset", box.Max.Z * FT, 3300.0, 0.5)
close("3D box: an unrotated callout gets an identity transform",
      box.Transform.Origin.X, 0.0, 0.0001)

# a callout turned a quarter turn is the same rectangle with its half sizes
# swapped, and is built axis aligned so a transform Revit might ignore is not
# the thing standing between the box and the callout
turned_box = geom.section_box(turned, geom.extents_mm(turned, 0.0), 0.0, 3000.0)
close("3D box: a quarter turn is taken out rather than left in a transform",
      turned_box.Transform.Origin.X, 0.0, 0.0001)
close("3D box: the short side of the callout is along model X", 
      turned_box.Min.X * FT, 9000.0, 1.0)
close("3D box: and the other edge with it", turned_box.Max.X * FT, 11000.0, 1.0)
close("3D box: the long side is along model Y", turned_box.Min.Y * FT, -2000.0, 1.0)
close("3D box: and its other edge", turned_box.Max.Y * FT, 2000.0, 1.0)
close("3D box: the elevations go straight in", turned_box.Max.Z * FT, 3000.0, 0.5)

check("quarter turn: square to the project", geom._quarter_turn((1.0, 0.0)), 0)
check("quarter turn: a right angle", geom._quarter_turn((0.0, 1.0)), 90)
check("quarter turn: upside down", geom._quarter_turn((-1.0, 0.0)), 180)
check("quarter turn: three quarters", geom._quarter_turn((0.0, -1.0)), 270)
check("quarter turn: a real angle is not one",
      geom._quarter_turn((0.866, 0.5)), None)

# a callout at a genuine angle keeps its transform, because there is no way to
# describe it without one
angled = _crop((50000.0, 20000.0), (6000.0, 3000.0), angle=math.pi / 6.0)
angled_box = geom.section_box(angled, geom.extents_mm(angled, 0.0), 0.0, 3000.0)
close("3D box: a real angle keeps its centre in the transform",
      angled_box.Transform.Origin.X * FT, 50000.0, 1.0)
close("3D box: on both axes", angled_box.Transform.Origin.Y * FT, 20000.0, 1.0)
close("3D box: with the transform on the ground so Z stays absolute",
      angled_box.Transform.Origin.Z, 0.0, 0.0001)
close("3D box: and the extents as offsets from it",
      angled_box.Min.X * FT, -3000.0, 1.0)
close("3D box: its elevations go straight in too",
      angled_box.Max.Z * FT, 3000.0, 0.5)

point = geom._to_model(frame, (0.0, 0.0, 1500.0))
close("to model: the middle of the callout is the middle of the callout",
      point.X * FT, 120000.0, 1.0)
close("to model: on both axes", point.Y * FT, 45000.0, 1.0)
close("to model: and Z goes through as an absolute elevation",
      point.Z * FT, 1500.0, 0.5)

edge = geom._to_model(frame, (4000.0, 0.0, 0.0))
close("to model: an offset lands on the callout's edge", edge.X * FT, 124000.0, 1.0)

turned_point = geom._to_model(turned, (2000.0, 0.0, 0.0))
close("to model: a rotated callout turns its offsets with it",
      turned_point.Y * FT, 2000.0, 1.0)
close("to model: leaving the other axis on the centre",
      turned_point.X * FT, 10000.0, 1.0)

specs = geom.section_frames(ext, 2, 1, -50.0, 3300.0, 250.0)
mid = [geom._to_model(frame, spec["origin"]) for spec in specs]
check("sections: three of them", len(specs), 3)
close("sections: the first X cut runs through the callout, a third up",
      mid[0].Y * FT, 45000.0 - 2500.0 + (5000.0 / 3.0), 2.0)
close("sections: and sits on the callout in X", mid[0].X * FT, 120000.0, 1.0)
close("sections: the Y cut sits on the callout in Y", mid[2].Y * FT, 45000.0, 1.0)
close("sections: each is cut over the same band as the 3D box",
      specs[0]["height"], 3350.0, 0.5)
close("sections: centred half way up it", mid[0].Z * FT, (3300.0 - 50.0) / 2.0, 1.0)


# ---------------------------------------------------------------------------
# one band for the 3D and the sections
# ---------------------------------------------------------------------------

band_settings = dict(core.DEFAULTS)
row = {"level_mm": 12000.0, "next_level_mm": 15600.0}
check("band: the bottom is the level less its offset, the top the level above "
      "less its own", ops.band_for(row, band_settings), (11950.0, 15400.0))
check("band: with no level above it falls back to the fixed height",
      ops.band_for({"level_mm": 0.0, "next_level_mm": None},
                   dict(band_settings, **{"3d_top_rule": "next_level"})),
      (-50.0, 4000.0))

check("band: the callout's own view range is what is used by default, with the "
      "box's offsets on it", ops.band_for({"level_mm": 12000.0, "next_level_mm": 15600.0,
                                           "range_mm": (11800.0, 15100.0)}, band_settings),
      (11750.0, 14900.0))
check("band: with no offsets the view range is used exactly",
      ops.band_for({"level_mm": 12000.0, "next_level_mm": 15600.0,
                    "range_mm": (11800.0, 15100.0)},
                   dict(band_settings, **{"3d_top_offset_mm": "0", "3d_bottom_offset_mm": "0"})),
      (11800.0, 15100.0))
check("band: offsets that would turn the box inside out are dropped",
      ops.band_for({"level_mm": 0.0, "range_mm": (0.0, 3000.0)},
                   dict(band_settings, **{"3d_top_offset_mm": "-4000"})), (0.0, 3000.0))
check("band: a view range that cannot be read falls back to the levels",
      ops.band_for({"level_mm": 12000.0, "next_level_mm": 15600.0,
                    "range_mm": None}, band_settings),
      (11950.0, 15400.0))
check("band: the view range is the default rule",
      core.DEFAULTS["3d_top_rule"], "view_range")
check("band: an inside out view range is not trusted",
      ops.sane_band((15000.0, 12000.0)), False)
check("band: nor one a kilometre tall", ops.sane_band((0.0, 1000000.0)), False)
check("band: nor one with no height at all", ops.sane_band((3000.0, 3000.0)), False)
check("band: a normal storey is fine", ops.sane_band((11800.0, 15100.0)), True)
check("band: rubbish is not trusted either", ops.sane_band(None), False)
check("band: an absurd view range falls back to the levels",
      ops.band_for({"level_mm": 12000.0, "next_level_mm": 15600.0,
                    "range_mm": (15000.0, 12000.0)}, band_settings),
      (11950.0, 15400.0))
check("band: and the section box is shown",
      core.get_bool(core.DEFAULTS, "3d_section_box_visible"), True)


# ---------------------------------------------------------------------------
# where the camera stands
# ---------------------------------------------------------------------------

# every corner stands the camera ABOVE the box, never under it
for corner in ("se_iso", "sw_iso", "ne_iso", "nw_iso"):
    vector = geom.orientation_vector(corner)
    check("camera: {0} stands above the callout, not under it".format(corner),
          vector[2] > 0, True)
    stand = geom.eye_point_mm((0.0, 0.0, 90000.0), vector, 30000.0)
    check("camera: so the eye for {0} is higher than the box".format(corner),
          stand[2] > 90000.0, True)

check("camera: south east stands east and south",
      [geom.orientation_vector("se_iso")[0] > 0,
       geom.orientation_vector("se_iso")[1] < 0], [True, True])
check("camera: north west stands west and north",
      [geom.orientation_vector("nw_iso")[0] < 0,
       geom.orientation_vector("nw_iso")[1] > 0], [True, True])

close("camera: the default pitch is the true isometric, so all three faces "
      "come out equal", geom.orientation_vector("se_iso")[2], 1.0, 0.001)
check("camera: a steeper pitch looks more from overhead",
      geom.orientation_vector("se_iso", 60.0)[2] >
      geom.orientation_vector("se_iso", 35.264)[2], True)
check("camera: a shallower one more from the side",
      geom.orientation_vector("se_iso", 15.0)[2] <
      geom.orientation_vector("se_iso", 35.264)[2], True)
check("camera: an absurd pitch is clamped rather than turned upside down",
      geom.orientation_vector("se_iso", -90.0)[2] > 0, True)
check("camera: and so is one past vertical",
      geom.orientation_vector("se_iso", 400.0)[2] > 0, True)
check("camera: rubbish falls back to the isometric",
      round(geom.orientation_vector("se_iso", "nonsense")[2], 3), 1.0)
check("camera: an unknown corner gives nothing rather than a guess",
      geom.orientation_vector("up_iso"), None)

eye = geom.eye_point_mm((120000.0, 45000.0, 1500.0), (1.0, -1.0, 1.0), 30000.0)
check("camera: it stands off along +forward, so it looks back at the callout",
      [round(value, 1) for value in eye], [150000.0, 15000.0, 31500.0])
check("camera: a callout far from the origin does not leave the camera at the "
      "origin", eye[0] > 100000.0, True)
close("camera: the stand off distance is what was asked for",
      ((eye[0] - 120000.0) ** 2 + (eye[1] - 45000.0) ** 2 +
       (eye[2] - 1500.0) ** 2) ** 0.5, 30000.0 * (3 ** 0.5), 1.0)
check("camera: at the origin with no target it still points somewhere sane",
      geom.eye_point_mm((0.0, 0.0, 0.0), (1.0, -1.0, 1.0), 1000.0),
      (1000.0, -1000.0, 1000.0))

middle = geom.box_centre(geom.section_box(frame, ext, -50.0, 3300.0))
close("camera: the target is the middle of the box, in X",
      middle.X * FT, 120000.0, 1.0)
close("camera: in Y", middle.Y * FT, 45000.0, 1.0)
close("camera: and half way up it", middle.Z * FT, 1625.0, 1.0)


# ---------------------------------------------------------------------------
# X down the left, Y down the right
# ---------------------------------------------------------------------------

A1 = (15.0, 15.0, 706.0, 564.0)


def _column_overlap(cells):
    real = [cell for cell in cells if cell]
    for index, first in enumerate(real):
        for second in real[index + 1:]:
            if (first[0] < second[0] + second[2] - 0.01 and
                    second[0] < first[0] + first[2] - 0.01 and
                    first[1] < second[1] + second[3] - 0.01 and
                    second[1] < first[1] + first[3] - 0.01):
                return True
    return False


plan = geom.two_column_layout(A1, (340.0, 200.0), (300.0, 190.0),
                              [(330.0, 120.0)] * 2, [(280.0, 120.0)] * 2,
                              12.0, 6.0)
check("columns: the plan sits at the top left",
      [round(value, 1) for value in plan["callout"][:2]], [15.0, 379.0])
check("columns: the 3D sits at the head of the right hand column",
      round(plan["3d"][0], 1), 367.0)
check("columns: an X section lines up under the plan",
      round(plan["x"][0][0], 1), 15.0)
check("columns: and a Y section under the 3D",
      round(plan["y"][0][0], 1), round(plan["3d"][0], 1))
check("columns: the X sections are stacked below one another",
      plan["x"][1][1] < plan["x"][0][1], True)
check("columns: nothing overlaps",
      _column_overlap([plan["callout"], plan["3d"]] + plan["x"] + plan["y"]), False)
check("columns: two each fits without running off the bottom", plan["overflow"], False)
check("columns: and the columns fit across the sheet", plan["too_wide"], False)

# the column is as wide as whatever has to go in it, so a section wider than
# the plan pushes the right hand column across rather than being sat on
wide = geom.two_column_layout(A1, (200.0, 200.0), (300.0, 190.0),
                              [(400.0, 100.0)], [(280.0, 100.0)], 12.0, 6.0)
check("columns: a section wider than the plan sets the column width",
      round(wide["3d"][0], 1), 427.0)
check("columns: and still nothing overlaps",
      _column_overlap([wide["callout"], wide["3d"]] + wide["x"] + wide["y"]), False)

# the gap is squeezed before anything is allowed off the sheet
tight = geom.two_column_layout(A1, (340.0, 200.0), (300.0, 190.0),
                               [(330.0, 110.0)] * 3, [], 12.0, 30.0, 2.0)
gaps = [round(tight["x"][index][1] - (tight["x"][index + 1][1] +
                                      tight["x"][index + 1][3]), 1)
        for index in range(2)]
check("columns: the gap is squeezed to fit them in rather than overflowing",
      gaps[0] < 30.0, True)
check("columns: evenly, not just the last one", gaps[0], gaps[1])
check("columns: and they stay on the sheet", tight["overflow"], False)

# too many to fit even squeezed: they go below, and it is reported
lots = geom.two_column_layout(A1, (340.0, 200.0), (300.0, 190.0),
                              [(330.0, 120.0)] * 6, [], 12.0, 6.0, 2.0)
check("columns: too many to fit is reported rather than hidden",
      lots["overflow"], True)
check("columns: all of them are still placed", len(lots["x"]), 6)
check("columns: they carry on below the sheet rather than being shrunk",
      lots["x"][-1][1] < 15.0, True)
check("columns: and none of them overlap even so",
      _column_overlap(lots["x"]), False)

# one column empty
one_sided = geom.two_column_layout(A1, (340.0, 200.0), (300.0, 190.0),
                                   [(330.0, 120.0)], [], 12.0, 6.0)
check("columns: with no Y sections the right hand column is simply empty",
      one_sided["y"], [])
check("columns: and the 3D still sits at the head of it",
      one_sided["3d"] is not None, True)

check("columns: nothing at all is handled",
      geom.two_column_layout(A1, None, None, [], [], 12.0, 6.0)["x"], [])

places, used, over = geom.column_stack([], 500.0, 15.0, 6.0)
check("columns: an empty stack gives nothing back", (places, over), ([], False))


# ---------------------------------------------------------------------------
# a viewport is measured title and all, and moved by its footprint
# ---------------------------------------------------------------------------


# a 300 x 150 view box, centred on (150, 75), with a title strip below it that
# is WIDER than the view - 340mm, starting 30mm to the left
BOX = ((0.0, 0.0), (300.0, 150.0))
LABEL = ((-30.0, -20.0), (310.0, 0.0))
foot = geom.footprint_mm(BOX, LABEL, (150.0, 75.0), 0.0)
close("footprint: the title is wider than the view, and it is the width that counts",
      foot["width"], 340.0)
close("footprint: the title adds its depth to the height", foot["height"], 170.0)
close("footprint: the middle of it is left of the box centre", foot["offset_x"], -10.0)
close("footprint: and below it", foot["offset_y"], -10.0)

bare = geom.footprint_mm(BOX, None, (150.0, 75.0), 0.0)
check("footprint: with no title it is just the box",
      (round(bare["width"], 1), round(bare["height"], 1)), (300.0, 150.0))
check("footprint: and is centred on the point that moves it",
      (round(bare["offset_x"], 3), round(bare["offset_y"], 3)), (0.0, 0.0))

padded = geom.footprint_mm(BOX, LABEL, (150.0, 75.0), 4.0)
close("footprint: clear air is added all round", padded["width"], 348.0)
close("footprint: without moving its middle", padded["offset_x"], -10.0)


class _Viewport(object):
    def __init__(self):
        self.moved_to = None

    def SetBoxCenter(self, point):
        self.moved_to = (round(point.X * FT, 3), round(point.Y * FT, 3))


ops.XYZ = _XYZ
report = ops.Results()
viewport = _Viewport()
ops.move_viewport(viewport, (100.0, 200.0, 340.0, 170.0), report, "a section",
                  (foot["offset_x"], foot["offset_y"]))
check("move: the box centre goes the offset away from the cell's middle, so the "
      "whole footprint lands in the cell", viewport.moved_to, (280.0, 295.0))

plain = _Viewport()
ops.move_viewport(plain, (100.0, 200.0, 340.0, 170.0), report, "a section", (0.0, 0.0))
check("move: centring the box instead lands out by the size of the title - the "
      "overlap bug", plain.moved_to != viewport.moved_to, True)

# two stacked in a column, measured and moved, must not overlap
places, _gap, _over = geom.column_stack([(340.0, 170.0), (340.0, 170.0)], 500.0, 15.0, 6.0)
first, second = _Viewport(), _Viewport()
ops.move_viewport(first, (15.0,) + places[0][1:], report, "X1", (-10.0, -10.0))
ops.move_viewport(second, (15.0,) + places[1][1:], report, "X2", (-10.0, -10.0))
check("move: two stacked sections keep the stacking distance once moved",
      round(first.moved_to[1] - second.moved_to[1], 1), 176.0)
check("move: and line up on one side", first.moved_to[0], second.moved_to[0])

check("move: the squeeze has a floor, so a gap cannot go negative",
      core.get_float(core.DEFAULTS, "section_min_gap_mm") > 0, True)


# ---------------------------------------------------------------------------
# finding and starting the easter egg
# ---------------------------------------------------------------------------

import io                                               # noqa: E402
import shutil                                           # noqa: E402
import c3d_ui as ui                                     # noqa: E402


def _egg_tree(files):
    """An extension laid out the way the real one is, with an egg in it."""
    root = tempfile.mkdtemp(prefix="c3d_egg_")
    egg = os.path.join(root, "lib", "revobim", "egg")
    os.makedirs(egg)
    for name, body in files.items():
        handle = io.open(os.path.join(egg, name), "w", encoding="utf-8")
        try:
            handle.write(body)
        finally:
            handle.close()
    for package in (os.path.join(root, "lib", "revobim"), egg):
        path = os.path.join(package, "__init__.py")
        if not os.path.isfile(path):
            io.open(path, "w", encoding="utf-8").close()
    # the tool sits three folders below the extension root
    tool = os.path.join(root, "RevoBIM PY.tab", "Sheet Tools.panel", "x.pulldown")
    os.makedirs(tool)
    return root, os.path.join(tool, "c3d_ui.py"), egg


def _with_egg(files, game="pacman", owner="a window"):
    root, pretend_file, egg = _egg_tree(files)
    real_file = ui.__file__
    kept = list(sys.path)
    for name in list(sys.modules.keys()):
        if name.startswith("revobim"):
            del sys.modules[name]
    ui.__file__ = pretend_file
    try:
        found = ui.egg_folder()
        report = ui.egg_report()
        started = ui.launch_egg(owner, game)
        opened = []
        module = sys.modules.get("revobim.egg.pacman")
        if module is not None:
            opened = list(getattr(module, "OPENED", []))
        return found, report, started, opened
    finally:
        ui.__file__ = real_file
        sys.path[:] = kept
        for name in list(sys.modules.keys()):
            if name.startswith("revobim"):
                del sys.modules[name]
        shutil.rmtree(root, ignore_errors=True)


PACMAN = u"OPENED = []\ndef show(owner=None):\n    OPENED.append(owner)\n"

WINDOW_CLASS = (u"SHOWN = []\n"
                u"class PacmanWindow(object):\n"
                u"    def __init__(self, owner=None):\n"
                u"        self.owner = owner\n"
                u"    def Show(self):\n"
                u"        SHOWN.append(self.owner)\n")

found, report, started, opened = _with_egg({"pacman.py": PACMAN})
check("egg: the folder is found by walking up from the tool",
      found[0].endswith(os.path.join("lib", "revobim", "egg")), True)
check("egg: and PacMan starts", started, True)
check("egg: the game is handed the owner window, not the game's own name",
      opened, ["a window"])
check("egg: the report says what is in the folder",
      bool([line for line in report if "pacman.py" in line]), True)
check("egg: and what each module offers",
      bool([line for line in report if "show" in line]), True)

# the public surface the egg actually documents is egg_hook.attach, which
# wires a logo rather than opening anything - so it must not count as started
found, report, started, opened = _with_egg(
    {"egg_hook.py": u"def attach(element, window=None):\n    return True\n"})
check("egg: a folder with nothing that opens a game says so", started, False)

# an egg that is a window class rather than a function: the class is found by
# its name, built, and shown - a call that hands a window back and is never
# shown looks exactly like nothing having happened
def _with_class_egg():
    root, pretend_file, egg = _egg_tree({"games.py": WINDOW_CLASS})
    real_file = ui.__file__
    kept = list(sys.path)
    for name in list(sys.modules.keys()):
        if name.startswith("revobim"):
            del sys.modules[name]
    ui.__file__ = pretend_file
    try:
        del ui.LAST_EGG_ROUTE[:]
        started = ui.launch_egg("a window", "pacman")
        module = sys.modules.get("revobim.egg.games")
        return started, list(getattr(module, "SHOWN", [])), list(ui.LAST_EGG_ROUTE)
    finally:
        ui.__file__ = real_file
        sys.path[:] = kept
        for name in list(sys.modules.keys()):
            if name.startswith("revobim"):
                del sys.modules[name]
        shutil.rmtree(root, ignore_errors=True)


started, shown, route = _with_class_egg()
check("egg: a window class named for the game is found and built", started, True)
check("egg: and its window is actually shown, not just made",
      shown, ["a window"])
check("egg: the route it took is reported, so it can be said which call fired",
      bool(route) and route[-1].endswith("PacmanWindow"), True)


# a module that raises is reported rather than being taken for success
found, report, started, opened = _with_egg(
    {"pacman.py": u"def show(owner=None):\n    raise ValueError('no board')\n"})
check("egg: a game that throws is not reported as started", started, False)

# no egg at all
root = tempfile.mkdtemp(prefix="c3d_noegg_")
tool = os.path.join(root, "a", "b", "c")
os.makedirs(tool)
real_file = ui.__file__
ui.__file__ = os.path.join(tool, "c3d_ui.py")
try:
    check("egg: with no egg folder anywhere it says so rather than throwing",
          ui.egg_folder(), (None, None))
    check("egg: and the report says where it looked",
          bool([line for line in ui.egg_report() if "NOT FOUND" in line]), True)
finally:
    ui.__file__ = real_file
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# which level elevation is the internal one
# ---------------------------------------------------------------------------


class _Level(object):
    def __init__(self, elevation_mm, project_mm):
        self.Elevation = elevation_mm / FT
        self.ProjectElevation = project_mm / FT
        self.Name = "L00"


class _RangeView(object):
    """A plan whose crop plane sits at its cut plane, which is what says where
    the level really is."""

    def __init__(self, level, crop_z_mm, cut_offset_mm, centre=(0.0, 0.0)):
        self.GenLevel = level
        self._crop_z = crop_z_mm
        self._cut = cut_offset_mm
        self.Name = "a callout"
        self._centre = centre

    def GetCropRegionShapeManager(self):
        loops = _loop(self._centre, (4000.0, 3000.0))
        for curve in loops[0]:
            for point in curve._points:
                point.Z = self._crop_z / FT
        return _ShapeManager(loops)


def _source_for(views):
    original = geom.cut_plane_offset_mm
    geom.cut_plane_offset_mm = lambda view: view._cut
    try:
        return model.elevation_source(None, [{"view": view} for view in views])
    finally:
        geom.cut_plane_offset_mm = original


# the real model: Elevation is the shared one, 87994mm out
survey = _Level(88230.0, 236.0)
chosen, votes, evidence = _source_for([_RangeView(survey, 1736.0, 1500.0)])
check("elevation: the crop plane says ProjectElevation is the internal one",
      chosen, "ProjectElevation")
check("elevation: and only that one gets a vote",
      (votes["Elevation"], votes["ProjectElevation"]), (0, 1))

# a project set up the usual way
normal = _Level(3600.0, 3600.0 - 0.0)
chosen, _votes, _evidence = _source_for([_RangeView(normal, 5100.0, 1500.0)])
check("elevation: where the two agree, Elevation is used", chosen, "Elevation")

# one odd view cannot decide it
mixed = [_RangeView(survey, 1736.0, 1500.0), _RangeView(survey, 1736.0, 1500.0),
         _RangeView(survey, 88230.0 + 1500.0, 1500.0)]
chosen, votes, _evidence = _source_for(mixed)
check("elevation: the answer they mostly agree on wins", chosen, "ProjectElevation")
check("elevation: and the odd one out is still counted",
      (votes["Elevation"], votes["ProjectElevation"]), (1, 2))

# nothing to go on
chosen, votes, evidence = _source_for([])
check("elevation: with no evidence it falls back to Elevation", chosen, "Elevation")
check("elevation: and says it had none", evidence, [])

check("elevation: level_model_z follows what it is told",
      round(geom.level_model_z(survey, "ProjectElevation") * FT, 1), 236.0)
check("elevation: and the other way", 
      round(geom.level_model_z(survey, "Elevation") * FT, 1), 88230.0)


# ---------------------------------------------------------------------------
# picking a view family type offers its own template
# ---------------------------------------------------------------------------


class _TemplateType(object):
    def __init__(self, template_id):
        self.DefaultTemplateId = template_id


class _TemplateDoc(object):
    def __init__(self, templates):
        self._templates = templates

    def GetElement(self, element_id):
        return self._templates.get(getattr(element_id, "Value", element_id))


TEMPLATE_DOC = _TemplateDoc({71: _Type("04_Documentation_Section_Drainage")})
FAMILY_TYPES = [{"name": "04 Documentation Section - Sketch", "type": _TemplateType(_Id(71))},
                {"name": "Building Section", "type": _TemplateType(_Id(-1))}]

real_types = model.view_family_types
model.view_family_types = lambda doc, family: FAMILY_TYPES
try:
    check("template: a type with a default template offers it",
          model.default_template_name(TEMPLATE_DOC, "04 Documentation Section - Sketch",
                                      "section"),
          "04_Documentation_Section_Drainage")
    check("template: the match ignores case",
          model.default_template_name(TEMPLATE_DOC, "04 DOCUMENTATION SECTION - SKETCH",
                                      "section"),
          "04_Documentation_Section_Drainage")
    check("template: a type with no default template offers nothing, so the "
          "box is left as it was", model.default_template_name(
              TEMPLATE_DOC, "Building Section", "section"), "")
    check("template: an unknown type offers nothing",
          model.default_template_name(TEMPLATE_DOC, "Not a type", "section"), "")
    check("template: a blank type offers nothing",
          model.default_template_name(TEMPLATE_DOC, "", "section"), "")
finally:
    model.view_family_types = real_types

check("template: following the type is on by default",
      core.get_bool(core.DEFAULTS, "template_follows_type"), True)
check("template: the list stays to the matching kind by default",
      core.get_bool(core.DEFAULTS, "template_list_all"), False)


# ---------------------------------------------------------------------------
# the drawer - arithmetic
# ---------------------------------------------------------------------------

AREA = (0.0, 0.0, 1920.0, 1040.0)
check("drawer: easing starts at nothing", core.ease_out(0.0), 0.0)
check("drawer: and finishes at everything", core.ease_out(1.0), 1.0)
close("drawer: half way in time is most of the way there", core.ease_out(0.5), 0.875)
check("drawer: a late tick cannot overshoot", core.ease_out(1.7), 1.0)
check("drawer: nor an early one undershoot", core.ease_out(-0.2), 0.0)
check("drawer: rubbish lands rather than throwing", core.ease_out("x"), 1.0)
check("drawer: the bar is the header plus the edge above and below",
      core.bar_height(48.0, 1.0), 50.0)
check("drawer: the bar parks on the bottom, clear of the taskbar",
      core.parked_top(AREA, 50.0), 986.0)
check("drawer: a second bar stacks above the first, not on it",
      core.parked_top(AREA, 50.0, 1), 928.0)
check("drawer: on a monitor ABOVE the primary the bar parks on that monitor - "
      "the negative top is the whole point",
      core.parked_top((0.0, -1080.0, 1920.0, 1040.0), 50.0), -94.0)
check("drawer: left where it parked, it reopens where it came from",
      core.reopen_top(100.0, 840.0, 986.0, 986.0, 50.0, AREA), 100.0)
check("drawer: carried up the screen, it opens upward from where the bar sits",
      core.reopen_top(100.0, 840.0, 986.0, 900.0, 50.0, AREA), 110.0)
check("drawer: and is held inside the working area",
      core.reopen_top(100.0, 840.0, 986.0, 300.0, 50.0, AREA), 0.0)
check("drawer: a window taller than the screen opens at its top",
      core.reopen_top(100.0, 1400.0, 986.0, 500.0, 50.0, AREA), 0.0)


# ---------------------------------------------------------------------------
# the drawer - behaviour, through a fake timer
# ---------------------------------------------------------------------------

import datetime as _real_datetime                       # noqa: E402


class _Event(object):
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self, sender=None, args=None):
        for handler in list(self.handlers):
            handler(sender, args)


class _Clock(object):
    now_value = _real_datetime.datetime(2026, 1, 1)


class _FakeDateTimeModule(object):
    class datetime(object):
        @staticmethod
        def now():
            return _Clock.now_value


ESCAPED = []          # what a tick let escape - the dispatcher would swallow it


class _FakeTimer(object):
    """Never ticks inside Start(), which is what a real DispatcherTimer does -
    a fake that ran the ticks at once would hide a missing fallback."""

    live = []

    def __init__(self):
        self.Tick = _Event()
        self.Interval = None
        self.running = False

    def Start(self):
        self.running = True
        _FakeTimer.live.append(self)

    def Stop(self):
        self.running = False


def _pump(limit=200):
    for _round in range(limit):
        timers = [timer for timer in _FakeTimer.live if timer.running]
        if not timers:
            return
        _Clock.now_value += _real_datetime.timedelta(milliseconds=15)
        for timer in timers:
            for handler in list(timer.Tick.handlers):
                try:
                    handler(timer, None)
                except Exception as err:
                    ESCAPED.append(u"{0}".format(err))


class _Ns(object):
    def __init__(self, **values):
        self.__dict__.update(values)


class _Window(object):
    def __init__(self):
        self.Left, self.Top, self.Width, self.Height = 200.0, 100.0, 1380.0, 840.0
        self.MinHeight = 620.0
        self.SizeToContent = "Height"
        self.Owner = None
        self.Closed = _Event()
        self.activated = 0
        self.refuse_top = 0

    def __setattr__(self, name, value):
        if name == "Top" and getattr(self, "refuse_top", 0) > 0:
            object.__setattr__(self, "refuse_top", self.refuse_top - 1)
            raise ValueError("Top refused mid-slide")
        object.__setattr__(self, name, value)

    def Activate(self):
        self.activated += 1


class _Part(object):
    def __init__(self):
        self.Visibility = "V"


class _Body(object):
    def __init__(self, header):
        self.Children = [header, _Part(), _Part()]
        self.ActualHeight = 838.0
        self.Height = float("nan")
        self.VerticalAlignment = "Stretch"


class _Header(object):
    def __init__(self):
        self.ActualHeight = 48.0
        self.CornerRadius = (6, 6, 0, 0)
        self.Parent = None


class _Button(object):
    def __init__(self):
        self.Click = _Event()
        self.Content = None
        self.Tag = None
        self.ToolTip = None


ui.DispatcherTimer = _FakeTimer
ui.TimeSpan = _Ns(FromMilliseconds=lambda ms: ms)
ui.Visibility = _Ns(Visible="V", Collapsed="C")
ui.VerticalAlignment = _Ns(Top="Top", Stretch="Stretch")
ui.CornerRadius = lambda *values: values if len(values) > 1 else (values[0],) * 4
ui.Double = _Ns(NaN=float("nan"))
ui.SizeToContent = _Ns(Manual="Manual")
ui.datetime = _FakeDateTimeModule


def _new_drawer():
    window, header, button, grips = _Window(), _Header(), _Button(), _Part()
    body = _Body(header)
    header.Parent = body
    drawer = ui.Drawer(window, header, button, grips, lambda: AREA)
    return drawer, window, body, button, grips


def _is_nan(value):
    return value != value


del ui._DRAWERS[:]
drawer, window, body, button, grips = _new_drawer()
drawer.shrink()
check("drawer: nothing moves inside Start() - the slide is the timer's job",
      (window.Top, drawer.sliding), (100.0, True))
check("drawer: the body is pinned for the slide so the table does not "
      "re-measure every frame", (body.Height, body.VerticalAlignment), (838.0, "Top"))
check("drawer: MinHeight is relaxed, or it vetoes the slide half way",
      window.MinHeight, 0)
check("drawer: and SizeToContent, which vetoes it too", window.SizeToContent, "Manual")
_pump()
check("drawer: it parks on the bottom of the screen", window.Top, 986.0)
check("drawer: as just its header bar", window.Height, 50.0)
check("drawer: the button turns into the green up arrow", button.Tag, "shrunk")
check("drawer: everything but the header is put away",
      [part.Visibility for part in body.Children[1:]], ["C", "C"])
check("drawer: the header's corners round off all four sides",
      ui.Drawer.__module__ and drawer.header.CornerRadius, (6, 6, 6, 6))
check("drawer: the grips are parked, or they swallow the click on the arrow",
      grips.Visibility, "C")
check("drawer: the body is unpinned once parked", _is_nan(body.Height), True)
check("drawer: and it is no longer sliding", drawer.sliding, False)

drawer.expand()
_pump()
check("drawer: the arrow brings it back where it was",
      (window.Top, window.Height), (100.0, 840.0))
check("drawer: MinHeight is put back, or it can be dragged shut for the session",
      window.MinHeight, 620.0)
check("drawer: SizeToContent is put back too", window.SizeToContent, "Height")
check("drawer: the parts come back", [part.Visibility for part in body.Children[1:]],
      ["V", "V"])
check("drawer: and the grips", grips.Visibility, "V")
check("drawer: the body is unpinned", (_is_nan(body.Height), body.VerticalAlignment),
      (True, "Stretch"))
check("drawer: the button is the shrink button again", button.Tag, None)
check("drawer: the window is brought to the front", window.activated, 1)

# a part that was already hidden stays hidden
body.Children[2].Visibility = "C"
drawer.shrink(); _pump(); drawer.expand(); _pump()
check("drawer: a part that was hidden before parking stays hidden after",
      [part.Visibility for part in body.Children[1:]], ["V", "C"])
body.Children[2].Visibility = "V"

# a tick that throws lands rather than jamming
window.refuse_top = 1
drawer.shrink()
_pump()
check("drawer: a tick that throws still lands", window.Top, 986.0)
check("drawer: and leaves the drawer free to move again", drawer.sliding, False)
check("drawer: the throw was caught by the tick itself, not left for the "
      "dispatcher", ESCAPED, [])
check("drawer: and noted", len(drawer.errors) >= 1, True)

# closing while parked settles, so a remembered size is the real one
drawer.settle()
check("drawer: settling puts the real size back at once",
      (window.Top, window.Height, drawer.shrunk), (100.0, 840.0, False))

# two parked bars stack
del ui._DRAWERS[:]
first = _new_drawer()
second = _new_drawer()
first[0].shrink(); _pump()
second[0].shrink(); _pump()
check("drawer: a second bar parks above the first",
      (first[1].Top, second[1].Top), (986.0, 928.0))

# ---------------------------------------------------------------------------
# 2.1.0 - the layout presets, the preview and the rules under the sheet group
SIZES = ((340.0, 200.0), (300.0, 190.0), [(330.0, 90.0)] * 2, [(280.0, 90.0)] * 2)
for key in geom.preset_keys():
    laid = geom.layout_for(key, A1, SIZES[0], SIZES[1], SIZES[2], SIZES[3], 12.0, 6.0)
    check(u"layout {0}: nothing overlaps".format(key), geom.overlaps(laid), [])
    check(u"layout {0}: every view gets a place".format(key),
          [role for role, _cell in geom.layout_roles(laid)],
          ["callout", "3d", "X1", "X2", "Y1", "Y2"])
    check(u"layout {0}: two each fits on an A1".format(key), laid["overflow"], False)
    check(u"layout {0}: the cells keep the sizes they were given".format(key),
          (tuple(laid["callout"][2:]), tuple(laid["x"][0][2:])), (SIZES[0], SIZES[2][0]))
    thumb = geom.thumbnail_layout(key)
    check(u"layout {0}: its thumbnail draws without overlaps".format(key),
          geom.overlaps(thumb), [])

columns = geom.layout_for("columns", A1, *(SIZES + (12.0, 6.0)))
check("layout: columns is exactly what 2.0 placed",
      columns, geom.two_column_layout(A1, *(SIZES + (12.0, 6.0))))
check("layout: an unknown preset falls back to the columns",
      geom.layout_for("nonsense", A1, *(SIZES + (12.0, 6.0))), columns)
mirror = geom.layout_for("mirror", A1, *(SIZES + (12.0, 6.0)))
check("layout mirror: the 3D is on the left and the plan on the right",
      mirror["3d"][0] < mirror["callout"][0], True)
check("layout mirror: the Y sections go down the left",
      mirror["y"][0][0] < mirror["x"][0][0], True)
rows = geom.layout_for("rows", A1, *(SIZES + (12.0, 6.0)))
check("layout rows: every section sits below the plan and the 3D",
      max([cell[1] + cell[3] for cell in rows["x"] + rows["y"]]) <=
      min(rows["callout"][1], rows["3d"][1]) + 0.001, True)
check("layout rows: the first two sit side by side",
      round(rows["x"][0][1], 3) == round(rows["x"][1][1], 3), True)
check("layout rows: and a row too wide for the sheet wraps underneath",
      rows["y"][1][1] < rows["x"][0][1], True)
left = geom.layout_for("plan_left", A1, *(SIZES + (12.0, 6.0)))
check("layout plan_left: the 3D sits under the plan",
      (left["3d"][0], left["3d"][1] < left["callout"][1]), (15.0, True))
check("layout plan_left: every section is in one column to the right",
      len(set([round(cell[0], 3) for cell in left["x"] + left["y"]])), 1)
packed = geom.layout_for("rows", A1, SIZES[0], SIZES[1], [(330.0, 90.0)] * 8, [], 12.0, 6.0)
check("layout rows: more than the sheet holds is flagged, not hidden",
      (packed["overflow"], len(packed["x"])), (True, 8))

check("cycler: next goes round", [geom.next_preset(key) for key in geom.preset_keys()],
      geom.preset_keys()[1:] + geom.preset_keys()[:1])
check("cycler: back from the first is the last",
      geom.next_preset(geom.preset_keys()[0], -1), geom.preset_keys()[-1])
check("cycler: an unknown preset starts from the first",
      geom.next_preset("nonsense"), geom.preset_keys()[1])
check("cycler: every preset has a title and a line under it",
      all([all(geom.preset_label(key)) for key in geom.preset_keys()]), True)

moved = geom.apply_moves(columns, {"X2": (500.0, 100.0), "3d": (600.0, 450.0)})
check("drag: a moved box is centred where it was let go",
      [round(value, 3) for value in geom.cell_centre(moved["x"][1])], [500.0, 100.0])
check("drag: at its own size, not the preview's guess",
      moved["x"][1][2:], columns["x"][1][2:])
check("drag: the 3D moves too", geom.cell_centre(moved["3d"]), (600.0, 450.0))
check("drag: what was not moved stays put",
      (moved["callout"], moved["x"][0], moved["y"]), (columns["callout"], columns["x"][0], columns["y"]))
check("drag: the layout it came from is left alone", columns["x"][1] != moved["x"][1], True)
check("drag: no moves is the layout unchanged", geom.apply_moves(columns, {}), columns)
check("drag: a move for a section that is no longer made is ignored",
      geom.apply_moves(columns, {"X9": (1.0, 1.0)})["x"], columns["x"])

fit = geom.sheet_fit(841.0, 594.0, 500.0, 400.0, 10.0)
corner = geom.to_canvas(fit, 594.0, 0.0, 0.0)
check("preview: the paper is fitted whole and centred",
      [round(value, 3) for value in (corner[0], 400.0 - corner[1])],
      [10.0, round((400.0 - 594.0 * fit[0]) / 2.0, 3)])
back = geom.from_canvas(fit, 594.0, *geom.to_canvas(fit, 594.0, 321.0, 123.0))
check("preview: canvas and sheet convert both ways",
      [round(value, 6) for value in back], [321.0, 123.0])
check("preview: the sheet origin is the bottom left, as Revit has it",
      geom.to_canvas(fit, 594.0, 0.0, 594.0)[1] < corner[1], True)
check("preview: a box dragged off the paper is held on it",
      geom.clamp_centre((0, 0, 100.0, 60.0), (-50.0, 900.0), 841.0, 594.0), (50.0, 564.0))
check("preview: and lands on a whole millimetre",
      geom.clamp_centre((0, 0, 100.0, 60.0), (300.4, 200.6), 841.0, 594.0), (300.0, 201.0))
check("preview: overlaps are found by role",
      geom.overlaps({"callout": (0, 0, 10, 10), "3d": (5, 5, 10, 10), "x": [(30, 30, 5, 5)], "y": []}),
      [("callout", "3d")])
check("preview: touching edges are not an overlap",
      geom.overlaps({"callout": (0, 0, 10, 10), "3d": (10, 0, 10, 10), "x": [], "y": []}), [])

guess = geom.estimate_sizes(2500.0, 1500.0, 3000.0, 50, 250.0, 3, 1)
check("estimate: one cell per section asked for", (len(guess["x"]), len(guess["y"])), (3, 1))
close("estimate: the plan is the crop at scale", guess["callout"][0], 100.0)
close("estimate: an X section is as wide as the callout plus its margins",
      guess["x"][0][0], (5000.0 + 500.0) / 50.0)
close("estimate: and as tall as the band plus a title", guess["x"][0][1], 3000.0 / 50.0 + 14.0)
check("estimate: the 3D is wider than the plan, being an isometric",
      guess["3d"][0] > guess["callout"][0], True)
close("estimate: a nonsense scale is taken as 1:50",
      geom.estimate_sizes(1000.0, 1000.0, 3000.0, "x", 0.0, 0, 0)["callout"][0], 40.0)

check("groups: only the callout selection is open to start with",
      core.open_groups(core.DEFAULTS), ["selection"])
check("groups: and the 2.1.0 all-open state is not carried forward",
      core.MIGRATIONS[4], ["groups_open"])
check("groups: the order is the window's, not the file's",
      core.open_groups({"groups_open": "sheet|selection"}), ["selection", "sheet"])
check("groups: an unknown name is ignored", core.open_groups({"groups_open": "nope|array"}), ["array"])
check("groups: all shut is remembered as all shut", core.open_groups({"groups_open": ""}), [])
check("groups: written back in order", core.groups_text(["sheet", "array"]), "array|sheet")
close("groups: a fold starts where it is", core.fold_height(0.0, 300.0, 0.0), 0.0)
close("groups: and lands exactly", core.fold_height(0.0, 300.0, 1.0), 300.0)
close("groups: and never overshoots", core.fold_height(300.0, 0.0, 1.7), 0.0)

tokens = {"level": "L02", "abbrev": "PlantRm", "callout": "Plant Room"}
check("naming: the live example follows both rules",
      core.naming_example("CO_{level}_{nn}", "Callout_{abbrev}_{level} Detail {d}", tokens),
      ("CO_L02_01", "Callout_PlantRm_L02 Detail 1"))
check("naming: an empty rule falls back to the default",
      core.naming_example("", "", tokens),
      ("CO_L02_01", "Callout_PlantRm_L02 Detail 1"))
check("naming: the numbering start is honoured",
      core.naming_example("{level}-{nnn}", "{callout}", tokens, 7)[0], "L02-007")
check("naming: a mistyped token is pointed at",
      core.unknown_tokens("CO_{levle}_{nn}", core.SHEET_NUMBER_TOKENS), ["levle"])
check("naming: the good ones are not",
      core.unknown_tokens("{level}{abbrev}{callout}{n}{nn}{nnn}", core.SHEET_NUMBER_TOKENS), [])
check("naming: {d} belongs to the name, not the number",
      (core.unknown_tokens("{d}", core.SHEET_NUMBER_TOKENS),
       core.unknown_tokens("{d}", core.SHEET_NAME_TOKENS)), (["d"], []))
check("scale: views match the callout by default",
      core.view_scale_for({"scale": 20}, {}), 20.0)
check("scale: or a fixed one when asked",
      core.view_scale_for({"scale": 20}, {"view_scale_rule": "fixed", "view_scale_fixed": "100"}), 100.0)

# the section offsets open the sections up, and leave the 3D box alone
_band_row = {"level_mm": 0.0, "range_mm": (0.0, 3000.0), "next_level_mm": 3500.0}
_flat = {"3d_top_offset_mm": "0", "3d_bottom_offset_mm": "0"}
check("offsets: none set, the sections cut the 3D's band",
      ops.section_band(_band_row, _flat), (0.0, 3000.0))
check("offsets: below the bottom level and above the top",
      ops.section_band(_band_row, dict(_flat, **{"sec_below_mm": "300", "sec_above_mm": "500"})), (-300.0, 3500.0))
check("offsets: the 3D band itself does not move",
      ops.band_for(_band_row, dict(_flat, **{"sec_below_mm": "300", "sec_above_mm": "500"})), (0.0, 3000.0))
check("offsets: a negative offset pulls the cut in",
      ops.section_band(_band_row, dict(_flat, **{"sec_below_mm": "-200"})), (200.0, 3000.0))
check("offsets: but never to less than 100mm tall",
      ops.section_band(_band_row, dict(_flat, **{"sec_below_mm": "-2000", "sec_above_mm": "-2000"})),
      (1450.0, 1550.0))
_frames = geom.section_frames((-1000.0, -1000.0, 1000.0, 1000.0), 1, 0,
                              *ops.section_band(_band_row, dict(_flat, **{"sec_below_mm": "300", "sec_above_mm": "500"})))
check("offsets: the section is cut that much taller", _frames[0]["height"], 3800.0)

# room tags in the new sections - where each goes, and which rooms qualify
_crop = ((-10.0, 0.0, -2.0), (10.0, 12.0, 0.0))     # across, up, into the view
_room = geom.box_corners((-4.0, 1.0, -5.0), (6.0, 10.0, 5.0))
check("room tags: a room the section cuts gets a spot in the middle of the cut",
      geom.room_tag_spot(_room, _crop[0], _crop[1], 4.0), (1.0, 5.0))
check("room tags: a room beside the section is not tagged in it",
      geom.room_tag_spot(geom.box_corners((12.0, 1.0, -5.0), (16.0, 10.0, 5.0)),
                         _crop[0], _crop[1], 4.0), None)
check("room tags: nor one behind the far clip",
      geom.room_tag_spot(geom.box_corners((-4.0, 1.0, -9.0), (6.0, 10.0, -3.0)),
                         _crop[0], _crop[1], 4.0), None)
check("room tags: a room wider than the section is tagged inside the crop",
      geom.room_tag_spot(geom.box_corners((-30.0, 1.0, -5.0), (6.0, 10.0, 5.0)),
                         _crop[0], _crop[1], 4.0)[0], -2.0)
check("room tags: a short room gets its tag half way up rather than above it",
      geom.room_tag_spot(geom.box_corners((-4.0, 1.0, -5.0), (6.0, 3.0, 5.0)),
                         _crop[0], _crop[1], 4.0), (1.0, 2.0))
check("room tags: and the tag never sits right on the crop edge",
      geom.room_tag_spot(geom.box_corners((-4.0, -5.0, -5.0), (6.0, 0.5, 5.0)),
                         _crop[0], _crop[1], 4.0, 0.5)[1], 0.5)
check("room tags: on by default, with the project's default tag",
      (core.DEFAULTS["sec_tag_rooms"], core.DEFAULTS["sec_room_tag_type"]), ("1", ""))


class _NoTags(object):
    pass


check("room tags: switched off, nothing is looked at",
      ops.tag_rooms(None, {"settings": {"sec_tag_rooms": "0"}, "results": ops.Results()},
                    [{"kind": "section"}]), 0)
check("room tags: no sections made, nothing to tag",
      ops.tag_rooms(None, {"settings": {}, "results": ops.Results()}, [{"kind": "3d"}]), 0)
_said = ops.Results()
_ctx = {"settings": {}, "results": _said, "room_tag_type": None, "rooms": []}
ops.tag_rooms(None, _ctx, [{"kind": "section"}])
ops.tag_rooms(None, _ctx, [{"kind": "section"}])
check("room tags: no room tag loaded is said once, not once a sheet",
      len([line for line in _said.warnings if "room tag" in line]), 1)

# ---------------------------------------------------------------------------
# 2.2.0 - section scale, the custom setout, docked headers, the tall window
check("scale: '1:20' and '20' both read as 20",
      (core.parse_scale("1:20"), core.parse_scale("20"), core.parse_scale(" 1 : 50 ")), (20, 20, 50))
check("scale: blank or nonsense is not set",
      (core.parse_scale(""), core.parse_scale("(the project default)"), core.parse_scale("1:0")), (0, 0, 0))
check("scale: the sections follow the other views until given their own",
      core.section_scale_for({"scale": 50}, {}), 50.0)
check("scale: and take their own once it is set",
      core.section_scale_for({"scale": 50}, {"sec_scale": "20"}), 20.0)
check("scale: every offered scale reads back as itself",
      [core.parse_scale(core.scale_text(s)) for s in core.SCALES], list(core.SCALES))
_sized = geom.estimate_sizes(2500.0, 1500.0, 3000.0, 50, 250.0, 1, 0, section_scale=20)
close("scale: a section at 1:20 is drawn two and a half times the size",
      _sized["x"][0][0], (5000.0 + 500.0) / 20.0)
close("scale: while the plan stays at the callout's scale", _sized["callout"][0], 100.0)

def _write_settings(values):
    path = os.path.join(tempfile.gettempdir(), "c3d_setout_bench.txt")
    core.save_settings(dict(core.DEFAULTS, **values), path)
    return path


_custom = {}
core.set_custom_moves(_custom, {"X1": (120.4, 80.6), "3d": (600.0, 400.0)})
check("setout: the dragged positions survive the settings file",
      core.custom_moves(core.load_settings(_write_settings(_custom))), {"X1": (120.0, 81.0), "3d": (600.0, 400.0)})
check("setout: a damaged entry is skipped, not trusted",
      core.custom_moves({"layout_custom": "X1=10,20|Y1=oops|3d=5"}), {"X1": (10.0, 20.0)})
check("setout: an ordinary layout has no moves on top of it",
      core.resolve_layout({"layout_preset": "rows", "layout_custom": "X1=1,2"}, geom.preset_keys()),
      ("rows", {}))
check("setout: the custom setout is its base layout plus the moves",
      core.resolve_layout({"layout_preset": "custom", "layout_custom_base": "mirror",
                           "layout_custom": "X1=1,2"}, geom.preset_keys()),
      ("mirror", {"X1": (1.0, 2.0)}))
check("setout: a lost base falls back to the first layout",
      core.resolve_layout({"layout_preset": "custom", "layout_custom_base": "gone"},
                          geom.preset_keys())[0], "columns")
check("setout: an unknown layout falls back too",
      core.resolve_layout({"layout_preset": "nope"}, geom.preset_keys()), ("columns", {}))

check("docks: a header scrolled up goes to the top, one below to the bottom",
      core.dock_sides([-300.0, 120.0, 900.0], 40.0, 700.0), ["top", None, "bottom"])
check("docks: one half off the bottom is docked so it stays readable",
      core.dock_sides([680.0], 40.0, 700.0), ["bottom"])
check("docks: one exactly at the top is not docked", core.dock_sides([0.0], 40.0, 700.0), [None])
close("full: the panel takes what the rest of the group leaves",
      core.fill_height(800.0, 520.0, 300.0), 800.0 - 220.0 - 4.0)
close("full: never shorter than the grip allows", core.fill_height(200.0, 900.0, 100.0), 160.0)

_area = (0.0, 0.0, 1920.0, 1040.0)
_tall = core.tall_toggle(_area, 200.0, 600.0, None)
check("tall: a double click on the edge stretches to the screen's height",
      _tall[:2], (0.0, 1040.0))
check("tall: and remembers where it was", _tall[2], (200.0, 600.0))
check("tall: a second double click puts it back",
      core.tall_toggle(_area, 0.0, 1040.0, _tall[2]), (200.0, 600.0, None))

check("defaults: blank or the default entry reads as default",
      (ui.is_default("", "(the project default)"), ui.is_default("(the project default)", "(the project default)")),
      (True, True))
check("defaults: anything picked does not",
      ui.is_default("Building Section", "(the project default)"), False)

# ---------------------------------------------------------------------------
# 2.3.0 - what was selected in Revit narrows the table as the tool opens
_rows = [{"key": 11, "name": "Plant Room"}, {"key": 12, "name": "Riser 2"},
         {"key": 13, "name": "Kitchen"}]
check("selection: a view picked in the browser is found by its id",
      [row["key"] for row in core.match_selection(_rows, {12}, set())], [12])
check("selection: a callout marker picked in a view is found by its name",
      [row["key"] for row in core.match_selection(_rows, set(), {"kitchen"})], [13])
check("selection: by either, in the table's own order",
      [row["key"] for row in core.match_selection(_rows, {13}, {"plant room"})], [11, 13])
check("selection: nothing picked, nothing matched", core.match_selection(_rows, set(), set()), [])


class _SelId(object):
    def __init__(self, value):
        self.value = value


class _SelView(model.View):
    def __init__(self, key, name):
        self.Id = _Id(key)
        self.Name = name


class _SelSheet(model.ViewSheet):
    def __init__(self, key, placed):
        self.Id = _Id(key)
        self.Name = "A-101"
        self.placed = placed

    def GetAllPlacedViews(self):
        return [_Id(key) for key in self.placed]


class _SelViewport(object):
    def __init__(self, view_key):
        self.ViewId = _Id(view_key)


class _SelMarker(object):
    def __init__(self, name):
        self.Name = name
        self.Category = _Ns(Id=_Id(-2000279))


class _SelDoc(object):
    def __init__(self, elements):
        self.elements = elements

    def GetElement(self, element_id):
        return self.elements.get(core.eid_value(element_id))


_elements = {11: _SelView(11, "Plant Room"), 12: _SelView(12, "Riser 2"),
             13: _SelView(13, "Kitchen"), 50: _SelViewport(12), 60: _SelSheet(60, [11]),
             70: _SelMarker("Kitchen")}
_sel_doc = _SelDoc(_elements)
_real_bic_value = model._bic_value
model._bic_value = lambda doc, name: -2000279 if name == "OST_Viewers" else None


def _picked(*keys):
    uidoc = _Ns(Document=_sel_doc,
                Selection=_Ns(GetElementIds=lambda: [_Id(key) for key in keys]))
    return model.selection_targets(uidoc)


check("selection: a picked view is its own id", _picked(13)["keys"], {13})
check("selection: a picked viewport is the view it shows", _picked(50)["keys"], {12})
check("selection: a picked sheet is every view on it", _picked(60)["keys"], {11})
check("selection: a picked callout marker is matched by its name",
      (_picked(70)["keys"], _picked(70)["names"]), (set(), {"kitchen"}))
check("selection: the count is everything that was selected", _picked(13, 50, 70)["count"], 3)


class _BareMarker(object):
    """A marker whose category cannot be asked about, carrying the view name
    as a parameter rather than as its own name."""
    Name = ""

    def get_Parameter(self, which):
        return _Ns(AsString=lambda: "Riser 2")


_elements[80] = _BareMarker()
check("selection: a marker is matched by the view name it carries, category or not",
      _picked(80)["names"], {"riser 2"})
check("selection: several picked together are all kept",
      [row["key"] for row in core.match_selection(_rows, _picked(13, 50)["keys"],
                                                  _picked(70, 80)["names"])], [12, 13])
check("selection: nothing selected is nothing to narrow by",
      (_picked()["keys"], _picked()["names"]), (set(), set()))
check("selection: a Revit that will not say is nothing too",
      model.selection_targets(_Ns(Document=None, Selection=None))["count"], 0)
model._bic_value = _real_bic_value

# ---------------------------------------------------------------------------
# 2.4.0 - the callout, the 3D and the sections each take their own scale
check("scale: the callout keeps its own scale until one is asked for",
      core.callout_scale_for({"scale": 20}, {"view_scale_rule": "fixed", "view_scale_fixed": "100"}), 20.0)
check("scale: and takes the one asked for", core.callout_scale_for({"scale": 20}, {"callout_scale": "1:10"}), 10.0)
check("scale: the 3D follows the other views until given its own",
      core.three_d_scale_for({"scale": 20}, {}), 20.0)
check("scale: and takes its own once set", core.three_d_scale_for({"scale": 20}, {"3d_scale": "100"}), 100.0)
_three = geom.estimate_sizes(2500.0, 1500.0, 3000.0, 50, 250.0, 0, 0, three_d_scale=100)
check("scale: a 3D at 1:100 is drawn half the size of one at 1:50",
      round(_three["3d"][0] * 2.0, 3),
      round(geom.estimate_sizes(2500.0, 1500.0, 3000.0, 50, 250.0, 0, 0)["3d"][0], 3))


class _ScaleView(object):
    def __init__(self, held):
        self.Scale = 50
        self.held = held
        self.ViewTemplateId = _Id(900)
        self.Document = None

    def __setattr__(self, name, value):
        if name == "Scale" and getattr(self, "held", False):
            return                          # a template holding the scale swallows it
        object.__setattr__(self, name, value)


_real_controls = model.template_controls_scale
model.template_controls_scale = lambda doc, view: view.held
_scale_doc = _Ns(GetElement=lambda element_id: _Ns(Name="MEP - Sections"))
_free, _held = _ScaleView(False), _ScaleView(True)
_sctx = {"settings": {"3d_scale": "1:20"}, "results": ops.Results()}
check("scale: asked for and free, it is set", (ops.scale_where_free(_scale_doc, _sctx, _free, "3d_scale", 50, "3D"), _free.Scale), (True, 20))
check("scale: held by the template, it is left alone",
      (ops.scale_where_free(_scale_doc, _sctx, _held, "3d_scale", 50, "3D"), _held.Scale), (False, 50))
ops.scale_where_free(_scale_doc, _sctx, _ScaleView(True), "3d_scale", 50, "3D")
check("scale: and the template that held it is named, once",
      [line for line in _sctx["results"].notes if "MEP - Sections" in line],
      ["the 3D views kept their template's scale rather than 1:20 - 'MEP - Sections' holds the scale"])
_plain = _ScaleView(False)
ops.scale_where_free(_scale_doc, {"settings": {}, "results": ops.Results()}, _plain, "3d_scale", 100, "3D")
check("scale: nothing asked for, the old rule still applies", _plain.Scale, 100)
_callout = _ScaleView(False)
ops.scale_where_free(_scale_doc, {"settings": {}, "results": ops.Results()}, _callout, "callout_scale", 0, "Plant")
check("scale: and a callout with nothing asked for is not touched", _callout.Scale, 50)
model.template_controls_scale = _real_controls

# ---------------------------------------------------------------------------
# 2.5.1 - the views go where the title block is, not where 0,0 is
check("title block: a setout is moved onto the sheet where the paper starts",
      geom.shift_moves({"X1": (100.0, 50.0)}, (-841.0, 0.0)), {"X1": (-741.0, 50.0)})
check("title block: no setout, nothing to move", geom.shift_moves({}, (-841.0, 0.0)), {})
_frame_usable = (-826.0, 15.0, 706.0, 564.0)
_frame_layout = geom.layout_for("columns", _frame_usable, *(SIZES + (12.0, 6.0)))
check("title block: the layout starts at the title block's own corner",
      round(_frame_layout["callout"][0], 3), -826.0)
check("title block: and nothing is reported off the sheet that is on it",
      geom.recheck_fit(_frame_layout, _frame_usable)["overflow"], False)
check("title block: a box dragged below the paper is still caught",
      geom.recheck_fit(geom.apply_moves(_frame_layout, {"X1": (-600.0, -40.0)}),
                       _frame_usable)["overflow"], True)
check("title block: and one dragged back onto it clears the flag",
      geom.recheck_fit(dict(_frame_layout, overflow=True), _frame_usable)["overflow"], False)


class _TbBox(object):
    def __init__(self, low, high):
        self.Min = _Ns(X=low[0] / FT, Y=low[1] / FT)
        self.Max = _Ns(X=high[0] / FT, Y=high[1] / FT)


class _TbInstance(object):
    def __init__(self, low, high):
        self.box = _TbBox(low, high)

    def get_BoundingBox(self, view):
        return self.box


class _TbCollector(object):
    def __init__(self, items):
        self.items = items

    def OfCategory(self, category):
        return self

    def WhereElementIsNotElementType(self):
        return self

    def __iter__(self):
        return iter(self.items)


_real_collector = model.FilteredElementCollector
_real_bic = model._bic
model._bic = lambda name: name
model.FilteredElementCollector = lambda doc, view_id=None: _TbCollector(
    [_TbInstance((-841.0, 0.0), (0.0, 594.0))])
_tb_sheet = _Ns(Id=_Id(1), Outline=None)
check("title block: drawn from its bottom right, the paper runs left of 0,0",
      [round(value, 3) for value in model.sheet_frame_mm(None, _tb_sheet)], [-841.0, 0.0, 841.0, 594.0])
model.FilteredElementCollector = lambda doc, view_id=None: _TbCollector([])
_tb_outline = _Ns(Min=_Ns(U=-420.5 / FT, V=-297.0 / FT), Max=_Ns(U=420.5 / FT, V=297.0 / FT))
check("title block: with no title block to read, the sheet outline is used, corner and all",
      [round(value, 3) for value in model.sheet_frame_mm(None, _Ns(Id=_Id(1), Outline=_tb_outline))],
      [-420.5, -297.0, 841.0, 594.0])
check("title block: and with neither, an A1 from 0,0",
      model.sheet_frame_mm(None, _Ns(Id=_Id(1), Outline=None)), (0.0, 0.0, 841.0, 594.0))
model.FilteredElementCollector = _real_collector
model._bic = _real_bic

# ---------------------------------------------------------------------------
# 2.6.0 - dragged cuts, grids cut to the crop, titles under their views
check("cuts: with nothing dragged the cuts sit on the even spacing",
      geom.stations_for(2, 0.0, 3000.0, "X"), geom.section_stations(2, 0.0, 3000.0))
check("cuts: a dragged one sits where it was left, the rest stay even",
      geom.stations_for(2, 0.0, 3000.0, "X", {"X2": 0.9}), [1000.0, 2700.0])
check("cuts: an X drag does not move a Y cut",
      geom.stations_for(1, 0.0, 3000.0, "Y", {"X1": 0.9}), [1500.0])
check("cuts: a cut cannot be dragged onto the crop edge",
      geom.stations_for(1, 0.0, 1000.0, "X", {"X1": 1.4}), [980.0])
check("cuts: a fraction that is not a number is ignored",
      geom.stations_for(1, 0.0, 1000.0, "X", {"X1": "rubbish"}), [500.0])
close("cuts: a point on the span reads back as its fraction",
      geom.cut_fraction(750.0, 0.0, 1000.0), 0.75)
_cut_frames = geom.section_frames((-1000.0, -500.0, 1000.0, 500.0), 1, 1, 0.0, 3000.0,
                                  cuts={"X1": 0.25, "Y1": 0.75})
check("cuts: the run cuts the X section where it was dragged",
      round(_cut_frames[0]["station"], 3), -250.0)
check("cuts: and the Y section", round(_cut_frames[1]["station"], 3), 500.0)
check("cuts: the section's origin goes with it",
      (round(_cut_frames[0]["origin"][1], 3), round(_cut_frames[1]["origin"][0], 3)), (-250.0, 500.0))

check("grids: cut down to the crop, each end keeps its own side",
      geom.grid_ends((5.0, 2.0, 40.0), (5.0, 2.0, -10.0), 0.0, 12.0),
      ((5.0, 2.0, 12.0), (5.0, 2.0, 0.0)))
check("grids: drawn the other way up, the same",
      geom.grid_ends((5.0, 2.0, -10.0), (5.0, 2.0, 40.0), 0.0, 12.0),
      ((5.0, 2.0, 0.0), (5.0, 2.0, 12.0)))
check("grids: on by default", core.DEFAULTS["sec_crop_grids"], "1")
check("grids: switched off, nothing is touched",
      ops.crop_grids(None, {"settings": {"sec_crop_grids": "0"}, "results": ops.Results()},
                     [{"kind": "section"}]), 0)

check("titles: moved to sit the gap under the view, level with its left edge",
      geom.label_shift(((10.0, 50.0), (110.0, 120.0)), ((-20.0, 5.0), (60.0, 20.0)), 2.0),
      (30.0, 28.0))
check("titles: one already in place does not move",
      geom.label_shift(((10.0, 50.0), (110.0, 120.0)), ((10.0, 40.0), (90.0, 48.0)), 2.0),
      (0.0, 0.0))


class _TitleViewport(object):
    def __init__(self, box, label, titled=True):
        self.box = _Ns(MinimumPoint=_Ns(X=box[0][0], Y=box[0][1]),
                       MaximumPoint=_Ns(X=box[1][0], Y=box[1][1]))
        width = (label[1][0] - label[0][0]) if titled else 0.0
        self.label = _Ns(MinimumPoint=_Ns(X=label[0][0], Y=label[0][1]),
                         MaximumPoint=_Ns(X=label[0][0] + width, Y=label[1][1]))
        self.LabelOffset = _Ns(X=1.0, Y=-3.0)

    def GetBoxOutline(self):
        return self.box

    def GetLabelOutline(self):
        return self.label


_real_xyz = ops.XYZ
ops.XYZ = lambda x, y, z: _Ns(X=x, Y=y, Z=z)
_vp = _TitleViewport(((0.0, 1.0), (2.0, 3.0)), ((0.5, -1.0), (1.5, 0.0)))
check("titles: a viewport's title is moved by the shift on top of its offset",
      (ops.tidy_label(_vp, 0.0), round(_vp.LabelOffset.X, 6), round(_vp.LabelOffset.Y, 6)),
      (True, 0.5, -2.0))
_untitled = _TitleViewport(((0.0, 1.0), (2.0, 3.0)), ((0.5, -1.0), (1.5, 0.0)), titled=False)
check("titles: a viewport type with no title is left alone",
      (ops.tidy_label(_untitled, 2.0), _untitled.LabelOffset.Y), (False, -3.0))
check("titles: and a Revit without LabelOffset is not an error",
      ops.tidy_label(_Ns(), 2.0), False)
ops.XYZ = _real_xyz
check("titles: two millimetres under the view by default", core.DEFAULTS["title_gap_mm"], "2")

# a dialog shrinking takes its owner down, and brings it back when it closes
del ui._DRAWERS[:]
owner = _new_drawer()
dialog = _new_drawer()
dialog[1].Owner = owner[1]
dialog[0].shrink(); _pump()
check("drawer: shrinking a dialog takes its owner down with it",
      (owner[0].shrunk, dialog[0].shrunk), (True, True))
dialog[1].Closed.fire()
_pump()
check("drawer: and closing the dialog brings the owner back",
      (owner[0].shrunk, owner[1].Height), (False, 840.0))
check("drawer: without stealing focus from whatever is in front",
      owner[1].activated, 0)
check("drawer: a closed window leaves the list of live drawers",
      dialog[0] in ui._DRAWERS, False)

# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# a group slides open and shut, and ends on an automatic height
class _FoldBody(object):
    def __init__(self, natural):
        self.natural = natural
        self.Height = float("nan")
        self.Visibility = "V"
        self.ClipToBounds = False
        self.DesiredSize = _Ns(Height=0.0)

    @property
    def ActualHeight(self):
        if self.Visibility == "C":
            return 0.0
        return self.natural if _is_nan(self.Height) else self.Height

    def Measure(self, size):
        self.DesiredSize = _Ns(Height=self.natural)


class _FoldHeader(object):
    def __init__(self):
        self.Click = _Event()
        self.ActualWidth = 900.0


class _Chevron(object):
    RenderTransform = None


ui.Size = lambda w, h: (w, h)
ui.RotateTransform = lambda angle: angle
ui.Double = _Ns(NaN=float("nan"), PositiveInfinity=float("inf"))
told = []
fold_body, fold_header, chevron = _FoldBody(320.0), _FoldHeader(), _Chevron()
fold = ui.Fold("array", fold_header, fold_body, chevron, True,
               lambda key, opened: told.append((key, opened)))
check("fold: an open group shows its chevron pointing down", chevron.RenderTransform, 0.0)
check("fold: and clips what it slides", fold_body.ClipToBounds, True)
fold.toggle()
seen = []
_FakeTimer.live[-1].Tick.handlers.append(lambda s, a: seen.append(fold_body.Height))
_pump()
check("fold: shutting slides the height down, not a jump", len(seen) > 5, True)
check("fold: getting smaller all the way", seen == sorted(seen, reverse=True), True)
check("fold: and lands collapsed", (fold_body.Visibility, fold.sliding), ("C", False))
check("fold: with the chevron turned to point right", chevron.RenderTransform, -90.0)
check("fold: and its height let go", _is_nan(fold_body.Height), True)
fold.toggle()
_pump()
check("fold: opening lands visible at an automatic height, so the table can grow",
      (fold_body.Visibility, _is_nan(fold_body.Height)), ("V", True))
check("fold: the window is told each time, for remembering",
      told, [("array", False), ("array", True)])
fold.toggle()
fold.toggle()                                   # a second click mid-slide
_pump()
check("fold: a click during a slide is ignored rather than fighting it",
      (fold.opened, fold_body.Visibility), (False, "C"))
shut_at_start = ui.Fold("sheet", _FoldHeader(), _FoldBody(200.0), _Chevron(), False)
check("fold: a group remembered as shut starts collapsed", shut_at_start.body.Visibility, "C")
check("fold: nothing a tick threw", fold.errors, [])

def main():
    for label, got, want in FAILED:
        print("  FAIL  {0}\n          got  {1!r}\n          want {2!r}".format(label, got, want))
    print("\nCallout to 3D bench: {0} of {1} checks pass"
          .format(len(PASSED), len(PASSED) + len(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
