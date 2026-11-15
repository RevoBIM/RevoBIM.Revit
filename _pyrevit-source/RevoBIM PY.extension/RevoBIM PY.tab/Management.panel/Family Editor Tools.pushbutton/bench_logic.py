# =========================================================================
# Family Editor Tools - logic bench
#
#     python bench_logic.py
#     python bench_logic.py --selftest
#
# These are the REAL functions, not copies of them.  fet_core and
# fet_planes have no Revit API in them at all, and fet_ops is loaded
# against import_check's stub API, so everything that decides something -
# the shared parameter file parse, the settings round trip, the plane
# positions, the preview fit, the result tally - can be run against a
# table of cases with no Revit and no window.
#
# The selftest breaks each rule in a throwaway copy of the folder and
# confirms the test that covers it fails.
# =========================================================================

import os
import shutil
import sys
import tempfile

import import_check

HERE = os.path.dirname(os.path.abspath(__file__))

SPF_SAMPLE = u"""# This is a Revit shared parameter file.
# Do not edit manually.
*META\tVERSION\tMINVERSION
META\t2\t1
*GROUP\tID\tNAME
GROUP\t1\tDimensions
GROUP\t2\tIdentity
*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE\tHIDEWHENNOVALUE
PARAM\taaaaaaaa-0000-0000-0000-000000000001\tBGL_Width\tLENGTH\t\t1\t1\tThe overall width\t1\t0
PARAM\taaaaaaaa-0000-0000-0000-000000000002\tBGL_Depth\tLENGTH\t\t1\t1\t\t1\t0
PARAM\taaaaaaaa-0000-0000-0000-000000000003\tBGL_Asset Code\tTEXT\t\t2\t0\tAsset tag\t1\t0
PARAM\taaaaaaaa-0000-0000-0000-000000000003\tBGL_Asset Code Again\tTEXT\t\t2\t1\t\t1\t0
PARAM\taaaaaaaa-0000-0000-0000-000000000004\tBGL_Short
"""


class Bench(object):
    u"""The modules under test, loaded from a given folder."""

    def __init__(self, root):
        self.root = root
        saved = import_check.install_stubs()
        for name in list(sys.modules.keys()):
            if name.startswith(u"fet_") or name == u"theme":
                del sys.modules[name]
        sys.path.insert(0, root)
        try:
            self.core = __import__(u"fet_core")
            self.planes = __import__(u"fet_planes")
            self.ops = __import__(u"fet_ops")
            self.model = __import__(u"fet_model")
        finally:
            sys.path.remove(root)
            import_check.restore_stubs(saved)


# =========================================================================
# The shared parameter file
# =========================================================================

def test_spf_parses_the_columns(M):
    params, groups, problems = M.core.parse_shared_parameter_text(SPF_SAMPLE)
    names = [p.name for p in params]
    assert u"BGL_Width" in names, names
    width = [p for p in params if p.name == u"BGL_Width"][0]
    assert width.data_type == u"LENGTH", width.data_type
    assert width.description == u"The overall width", width.description
    assert width.visible is True


def test_spf_resolves_group_names(M):
    params, groups, problems = M.core.parse_shared_parameter_text(SPF_SAMPLE)
    width = [p for p in params if p.name == u"BGL_Width"][0]
    asset = [p for p in params if p.name == u"BGL_Asset Code"][0]
    assert width.group == u"Dimensions", width.group
    assert asset.group == u"Identity", asset.group


def test_spf_refuses_a_repeated_guid(M):
    params, groups, problems = M.core.parse_shared_parameter_text(SPF_SAMPLE)
    names = [p.name for p in params]
    assert u"BGL_Asset Code Again" not in names, names
    assert any(u"repeats a GUID" in p for p in problems), problems


def test_spf_reports_a_short_line(M):
    params, groups, problems = M.core.parse_shared_parameter_text(SPF_SAMPLE)
    assert any(u"too few columns" in p for p in problems), problems
    assert u"BGL_Short" not in [p.name for p in params]


def test_spf_hidden_flag(M):
    params, groups, problems = M.core.parse_shared_parameter_text(SPF_SAMPLE)
    asset = [p for p in params if p.name == u"BGL_Asset Code"][0]
    assert asset.visible is False


# =========================================================================
# Searching
# =========================================================================

def test_search_takes_every_word_in_any_order(M):
    assert M.core.matches_search(u"BGL_Wall Fire Rating", u"fire bgl")
    assert not M.core.matches_search(u"BGL_Wall Fire Rating", u"fire duct")
    assert M.core.matches_search(u"anything", u"   ")


def test_filter_params_by_group(M):
    params, groups, problems = M.core.parse_shared_parameter_text(SPF_SAMPLE)
    only = M.core.filter_params(params, u"", u"Identity")
    assert [p.name for p in only] == [u"BGL_Asset Code"], only


def test_natural_order(M):
    values = [u"P-10", u"P-9", u"P-100", u"P-2"]
    values.sort(key=M.core.natural_key)
    assert values == [u"P-2", u"P-9", u"P-10", u"P-100"], values


# =========================================================================
# Settings
# =========================================================================

def test_settings_split_on_the_first_equals_only(M):
    text = u"last_spf=C:\\jobs\\a=b\\shared.txt\ntheme=light\n"
    values = M.core.parse_settings_text(text)
    assert values[u"last_spf"] == u"C:\\jobs\\a=b\\shared.txt", values[u"last_spf"]
    assert values[u"theme"] == u"light"


def test_settings_fall_back_key_by_key(M):
    values = M.core.parse_settings_text(u"theme=light\nnonsense\n")
    assert values[u"theme"] == u"light"
    assert values[u"width_mm"] == M.core.DEFAULTS[u"width_mm"]


def test_settings_ignore_a_key_from_an_older_version(M):
    values = M.core.parse_settings_text(
        u"legacy_plane_mode=3\nbanana=yes\ntheme=dark\n")
    assert u"legacy_plane_mode" not in values, values
    assert u"banana" not in values, values
    assert values[u"theme"] == u"dark"


def test_settings_round_trip(M):
    values = dict(M.core.DEFAULTS)
    values[u"param_width"] = u"BGL_Width"
    again = M.core.parse_settings_text(M.core.settings_to_text(values))
    assert again[u"param_width"] == u"BGL_Width"
    assert again[u"settings_version"] == u"{0}".format(M.core.SETTINGS_VERSION)


def test_setting_helpers(M):
    values = dict(M.core.DEFAULTS)
    values[u"label_plane_dims"] = u"on"
    assert M.core.setting_on(values, u"label_plane_dims")
    values[u"label_plane_dims"] = u"off"
    assert not M.core.setting_on(values, u"label_plane_dims")
    assert M.core.setting_mm(values, u"width_mm") == 600.0


# =========================================================================
# Templates
# =========================================================================

def test_template_round_trip(M):
    rows = [M.core.TemplateRow(u"guid-1", u"BGL_Width", u"instance",
                               u"PG_GEOMETRY", u"LENGTH"),
            M.core.TemplateRow(u"guid-2", u"BGL_Asset", u"type",
                               u"PG_IDENTITY_DATA", u"TEXT")]
    text = M.core.template_to_text(u"Equipment", u"C:\\a=b\\shared.txt", rows)
    name, source, back, problems = M.core.parse_template_text(text)
    assert name == u"Equipment", name
    assert source == u"C:\\a=b\\shared.txt", source
    assert not problems, problems
    assert len(back) == 2
    assert back[0].is_instance is True
    assert back[1].is_instance is False
    assert back[1].group == u"PG_IDENTITY_DATA"


def test_template_reports_a_short_line(M):
    name, source, rows, problems = M.core.parse_template_text(
        u"template_name=x\nparam=guid|name\n")
    assert not rows, rows
    assert problems, problems


def test_template_file_name_is_made_safe(M):
    assert M.core.template_file_name(u"MEP / Equipment: v2") == \
        u"MEP _ Equipment_ v2.txt"
    assert M.core.template_file_name(u"   ") == u"template.txt"


# =========================================================================
# Presets
# =========================================================================

def test_presets_seed_and_round_trip(M):
    presets = M.core.parse_presets_text(
        u"material", u"\n".join(M.core.SEED_PRESETS[u"material"]))
    assert len(presets) == len(M.core.SEED_PRESETS[u"material"])
    again = M.core.parse_presets_text(u"material",
                                      M.core.presets_to_text(presets))
    assert [p.name for p in again] == [p.name for p in presets]
    assert again[0].get(u"class") == presets[0].get(u"class")


def test_presets_drop_a_repeat(M):
    text = u"BGL_Steel|1,1,1|0|0|Solid fill|Solid fill|Metal\n" \
           u"BGL_Steel|9,9,9|0|0|Solid fill|Solid fill|Metal\n"
    presets = M.core.parse_presets_text(u"material", text)
    assert len(presets) == 1, presets


def test_presets_tolerate_a_short_line(M):
    presets = M.core.parse_presets_text(u"linestyle", u"BGL_Hidden|3\n")
    assert presets[0].get(u"colour") == u""
    assert presets[0].get(u"scope") == u""


def test_parse_colour(M):
    assert M.core.parse_colour(u"192,192,196") == (192, 192, 196)
    assert M.core.parse_colour(u"#C0C0C4") == (192, 192, 196)
    assert M.core.parse_colour(u"300,-5,0") == (255, 0, 0)
    assert M.core.parse_colour(u"nonsense") is None
    assert M.core.parse_colour(u"") is None


def test_unique_name(M):
    assert M.core.unique_name(u"Width", []) == u"Width"
    assert M.core.unique_name(u"Width", [u"width"]) == u"Width New"
    assert M.core.unique_name(u"Width", [u"Width", u"Width New"]) == u"Width New 2"


def test_millimetres_to_feet(M):
    assert abs(M.core.mm_to_ft(304.8) - 1.0) < 1e-12
    assert abs(M.core.ft_to_mm(1.0) - 304.8) < 1e-9


# =========================================================================
# Standard planes
# =========================================================================

SIZES = {u"w": 600.0, u"d": 400.0, u"h": 900.0, u"c": 800.0,
         u"r": 300.0}


def test_resolve_offset_sums_its_terms(M):
    assert M.planes.resolve_offset([(-0.5, u"d"), (-1.0, u"c")], SIZES) == -1000.0
    assert M.planes.resolve_offset([(0.0, None)], SIZES) == 0.0


def test_centred_box_is_symmetric_about_the_origin(M):
    places = dict([(name, offset) for name, axis, offset, ref
                   in M.planes.plane_positions(u"centred_box", SIZES)])
    assert places[u"Left"] == -300.0, places
    assert places[u"Right"] == 300.0, places
    assert places[u"Front"] == -200.0, places
    assert places[u"Back"] == 200.0, places
    assert places[u"Center (Left/Right)"] == 0.0


def test_corner_layout_starts_at_the_origin(M):
    places = dict([(name, offset) for name, axis, offset, ref
                   in M.planes.plane_positions(u"corner_origin", SIZES)])
    assert places[u"Left"] == 0.0 and places[u"Front"] == 0.0, places
    assert places[u"Right"] == 600.0 and places[u"Back"] == 400.0, places


def test_clearance_sits_in_front_of_the_front_face(M):
    places = dict([(name, offset) for name, axis, offset, ref
                   in M.planes.plane_positions(u"box_with_clearance", SIZES)])
    assert places[u"Clearance"] < places[u"Front"], places
    assert places[u"Front"] - places[u"Clearance"] == 800.0, places


def test_reference_types_are_named(M):
    for key in M.planes.layout_keys():
        for name, axis, offset, ref in M.planes.plane_positions(key, SIZES):
            assert ref in M.planes.REF_NAMES, (key, name, ref)


def test_dimension_planes_read_low_to_high(M):
    for key in M.planes.layout_keys():
        for kind, axis, pairs, param, slot in M.planes.dimension_specs(key, SIZES):
            values = [offset for name, offset in pairs]
            assert values == sorted(values), (key, pairs)
            assert len(values) >= 2, (key, pairs)


def test_eq_dimensions_have_three_planes(M):
    for key in M.planes.layout_keys():
        for kind, axis, pairs, param, slot in M.planes.dimension_specs(key, SIZES):
            if kind == u"eq":
                assert len(pairs) == 3, (key, pairs)


def test_every_dimension_points_at_a_plane_the_layout_makes(M):
    for key in M.planes.layout_keys():
        made = set([name for name, axis, offset, ref
                    in M.planes.plane_positions(key, SIZES)])
        for spec in M.planes.get_layout(key)[u"dims"]:
            for name in spec[u"planes"]:
                assert name in made, (key, name)


def test_params_used_matches_the_labels(M):
    assert M.planes.params_used(u"centred_box") == [u"w", u"d"]
    assert M.planes.params_used(u"crosshair") == []
    assert u"c" in M.planes.params_used(u"box_with_clearance")


def test_step_layout_wraps_both_ways(M):
    keys = M.planes.layout_keys()
    assert M.planes.step_layout(keys[0], -1) == keys[-1]
    assert M.planes.step_layout(keys[-1], 1) == keys[0]
    assert M.planes.step_layout(keys[0], 1) == keys[1]


def test_unknown_layout_falls_back(M):
    assert M.planes.get_layout(u"nonsense")[u"key"] == M.planes.LAYOUTS[0][u"key"]


def test_preview_fits_its_box_at_every_shape(M):
    shapes = (SIZES,
              {u"w": 50.0, u"d": 5000.0, u"h": 100.0, u"c": 10.0, u"r": 20.0},
              {u"w": 5000.0, u"d": 50.0, u"h": 4000.0, u"c": 4000.0,
               u"r": 3000.0},
              {u"w": 0.0, u"d": 0.0, u"h": 0.0, u"c": 0.0, u"r": 0.0})
    for key in M.planes.layout_keys():
        for sizes in shapes:
            items = M.planes.preview_items(key, sizes)
            assert items, (key, sizes)
            assert M.planes.preview_in_bounds(items), (key, sizes)


def test_preview_draws_every_plane_and_the_origin(M):
    for key in M.planes.layout_keys():
        items = M.planes.preview_items(key, SIZES)
        planes = len([i for i in items if i[0] == u"plane"])
        assert planes == len(M.planes.get_layout(key)[u"planes"]), key
        assert any(i[0] == u"origin" for i in items), key


def test_preview_marks_the_centres_differently(M):
    items = M.planes.preview_items(u"centred_box", SIZES)
    styles = set([i[5] for i in items if i[0] == u"plane"])
    assert u"centre" in styles and u"face" in styles, styles


# =========================================================================
# Results
# =========================================================================

def test_result_tally(M):
    results = [M.ops.Result(M.ops.CREATED, u"a"),
               M.ops.Result(M.ops.CREATED, u"b"),
               M.ops.Result(M.ops.EXISTING, u"c"),
               M.ops.Result(M.ops.FAILED, u"d", u"refused")]
    tally = M.ops.counts(results)
    assert tally[M.ops.CREATED] == 2 and tally[M.ops.FAILED] == 1, tally
    assert M.ops.needs_a_look(results) is True
    line = M.ops.summary_line(results)
    assert u"2 created" in line and u"1 refused" in line, line


def test_a_clean_run_needs_no_look(M):
    results = [M.ops.Result(M.ops.CREATED, u"a"),
               M.ops.Result(M.ops.EXISTING, u"b")]
    assert M.ops.needs_a_look(results) is False
    assert M.ops.summary_line([]) == u"Nothing to do"


# =========================================================================
# Data type kinds and colours
# =========================================================================

def test_both_spellings_land_on_the_same_kind(M):
    u"""The file says LENGTH and Revit says Length; a swap can only be
    matched by eye if they get the same colour."""
    pairs = ((u"LENGTH", u"Length"),
             (u"YESNO", u"Yes/No"),
             (u"TEXT", u"Text"),
             (u"MATERIAL", u"Material"),
             (u"ANGLE", u"Angle"),
             (u"AREA", u"Area"),
             (u"VOLUME", u"Volume"),
             (u"INTEGER", u"Integer"),
             (u"NUMBER", u"Number"),
             (u"FAMILYTYPE", u"Family Type"),
             (u"HVAC_AIRFLOW", u"Air Flow"),
             (u"ELECTRICAL_CURRENT", u"Current"))
    for file_token, revit_label in pairs:
        kind = M.core.data_kind(file_token)
        # Not just "the two agree" - two spellings that both fall through
        # to Other agree perfectly and tell you nothing.
        assert kind != M.core.KIND_OTHER, (file_token, kind)
        assert kind == M.core.data_kind(revit_label), \
            (file_token, revit_label, kind, M.core.data_kind(revit_label))


def test_kinds_are_told_apart(M):
    u"""Named, not just different from each other - an assertion that only
    says two things differ passes when both of them break."""
    wanted = ((u"LENGTH", M.core.KIND_LENGTH),
              (u"AREA", M.core.KIND_AREA_VOLUME),
              (u"VOLUME", M.core.KIND_AREA_VOLUME),
              (u"INTEGER", M.core.KIND_INTEGER),
              (u"NUMBER", M.core.KIND_NUMBER),
              (u"YESNO", M.core.KIND_YESNO),
              (u"TEXT", M.core.KIND_TEXT),
              (u"MULTILINETEXT", M.core.KIND_TEXT),
              (u"MATERIAL", M.core.KIND_MATERIAL),
              (u"FAMILYTYPE", M.core.KIND_FAMILY_TYPE))
    for token, kind in wanted:
        assert M.core.data_kind(token) == kind, (token, M.core.data_kind(token))


def test_an_unknown_data_type_is_other(M):
    assert M.core.data_kind(u"WHATEVER_THIS_IS") == M.core.KIND_OTHER
    assert M.core.data_kind(u"") == M.core.KIND_OTHER
    assert M.core.data_kind(None) == M.core.KIND_OTHER


def test_every_kind_has_a_label_and_a_brush(M):
    for kind in M.core.KIND_ORDER:
        assert kind in M.core.KIND_LABEL, kind
        assert kind in M.core.KIND_BRUSH, kind
    assert len(set(M.core.KIND_BRUSH.values())) == len(M.core.KIND_ORDER)


def test_kinds_present_keeps_the_order_and_drops_repeats(M):
    found = M.core.kinds_present([u"TEXT", u"LENGTH", u"TEXT", u"Area"])
    assert found == [M.core.KIND_LENGTH, M.core.KIND_AREA_VOLUME,
                     M.core.KIND_TEXT], found


def test_a_clean_swap_is_same_kind_only(M):
    assert M.core.swap_is_clean(u"LENGTH", u"Length") is True
    assert M.core.swap_is_clean(u"TEXT", u"Length") is False


# =========================================================================
# New or replace
# =========================================================================

def test_a_replace_with_no_target_is_a_new_parameter(M):
    row = M.core.TemplateRow(u"g", u"BGL_Width", u"type", u"Data",
                             u"LENGTH", M.core.ACTION_REPLACE, u"")
    assert row.action == M.core.ACTION_NEW
    assert row.replaces is False


def test_a_replace_row_reports_itself(M):
    row = M.core.TemplateRow(u"g", u"BGL_Width", u"instance", u"Data",
                             u"LENGTH", M.core.ACTION_REPLACE, u"Width")
    assert row.replaces is True
    assert row.is_instance is True
    assert row.brush_key == M.core.KIND_BRUSH[M.core.KIND_LENGTH]


def test_template_carries_the_action_and_target(M):
    rows = [M.core.TemplateRow(u"g1", u"BGL_Width", u"instance", u"PG_GEOMETRY",
                               u"LENGTH", M.core.ACTION_REPLACE, u"Width"),
            M.core.TemplateRow(u"g2", u"BGL_Asset", u"type", u"PG_DATA",
                               u"TEXT")]
    text = M.core.template_to_text(u"Kit", u"C:\\a\\shared.txt", rows)
    name, source, back, problems = M.core.parse_template_text(text)
    assert not problems, problems
    assert back[0].replaces is True and back[0].target == u"Width"
    assert back[1].action == M.core.ACTION_NEW


def test_an_older_five_field_template_still_loads(M):
    u"""Templates written before 1.2.0 carry five fields, not seven."""
    text = (u"template_name=Old\n"
            u"source_file=C:\\a\\shared.txt\n"
            u"param=g1|BGL_Width|instance|PG_GEOMETRY|LENGTH\n")
    name, source, rows, problems = M.core.parse_template_text(text)
    assert not problems, problems
    assert len(rows) == 1
    assert rows[0].action == M.core.ACTION_NEW
    assert rows[0].is_instance is True


# =========================================================================
# Editing the family's parameters
# =========================================================================

def test_an_empty_edit_touches_nothing(M):
    edit = M.core.ParamEdit(u"Width")
    assert edit.touches_anything() is False
    assert edit.renames is False
    edit.formula = u""
    assert edit.touches_anything() is True


def test_a_rename_to_the_same_name_is_not_a_rename(M):
    edit = M.core.ParamEdit(u"Width", new_name=u"Width")
    assert edit.renames is False


def test_simple_renames_go_straight_through(M):
    steps, problems = M.core.plan_renames(
        [(u"A", u"A2"), (u"B", u"B2")], [u"A", u"B", u"C"])
    assert not problems, problems
    assert sorted(steps) == [(u"A", u"A2"), (u"B", u"B2")], steps


def test_swapping_two_names_goes_through_a_parked_name(M):
    u"""A to B and B to A one at a time fails on a clash with itself."""
    steps, problems = M.core.plan_renames(
        [(u"A", u"B"), (u"B", u"A")], [u"A", u"B"])
    assert not problems, problems
    assert len(steps) == 4, steps
    parked = [target for source, target in steps[:2]]
    assert all(p.startswith(M.core.PARK_PREFIX) for p in parked), steps
    ends = sorted([target for source, target in steps[2:]])
    assert ends == [u"A", u"B"], steps


def test_a_clash_with_a_name_nobody_is_moving_is_refused(M):
    steps, problems = M.core.plan_renames(
        [(u"A", u"C")], [u"A", u"B", u"C"])
    assert not steps, steps
    assert problems and u"already has that name" in problems[0], problems


def test_two_renames_onto_one_name_are_refused(M):
    steps, problems = M.core.plan_renames(
        [(u"A", u"Z"), (u"B", u"Z")], [u"A", u"B"])
    assert not steps, steps
    assert problems, problems


# =========================================================================
# Which parameter each page drives
# =========================================================================

def test_layout_params_round_trip(M):
    mapping = {u"centred_box": {u"w": u"BGL_Width", u"d": u"BGL_Depth"},
               u"revolve_elevation": {u"r": u"BGL_Radius", u"h": u"BGL_Ht"}}
    text = M.core.format_layout_params(mapping)
    back = M.core.parse_layout_params(text)
    assert back == mapping, (text, back)


def test_layout_params_survive_the_settings_file(M):
    u"""The value carries = and : and , - the settings loader splits on
    the first = only, so it has to come back intact."""
    mapping = {u"centred_box": {u"w": u"BGL_Width"}}
    values = dict(M.core.DEFAULTS)
    values[u"layout_params"] = M.core.format_layout_params(mapping)
    again = M.core.parse_settings_text(M.core.settings_to_text(values))
    assert M.core.parse_layout_params(again[u"layout_params"]) == mapping


def test_a_parameter_name_with_a_separator_is_refused(M):
    u"""A name carrying ; : , or = would come back as two broken halves."""
    text = M.core.format_layout_params(
        {u"centred_box": {u"w": u"Bad,Name", u"d": u"Good"}})
    back = M.core.parse_layout_params(text)
    assert back == {u"centred_box": {u"d": u"Good"}}, back


def test_unreadable_chunks_are_dropped_not_fatal(M):
    back = M.core.parse_layout_params(u"nonsense;centred_box:w=A;:;x:y")
    assert back == {u"centred_box": {u"w": u"A"}}, back


def test_a_page_falls_back_to_the_house_default_name(M):
    settings = dict(M.core.DEFAULTS)
    settings[u"param_width"] = u"Width"
    mapping = {u"centred_box": {u"w": u"BGL_Width"}}
    assert M.core.layout_param_name(mapping, u"centred_box", u"w",
                                    settings) == u"BGL_Width"
    assert M.core.layout_param_name(mapping, u"width_only", u"w",
                                    settings) == u"Width"
    assert M.core.layout_param_name({}, u"centred_box", u"h",
                                    settings) == u"Height"


def test_every_driven_key_has_a_label_and_a_default(M):
    for key in M.core.PLANE_PARAM_KEYS:
        assert key in M.core.PLANE_PARAM_LABEL, key
    for key in M.planes.layout_keys():
        for driven in M.planes.params_used(key):
            assert driven in M.core.PLANE_PARAM_KEYS, (key, driven)


# =========================================================================
# The revolve page
# =========================================================================

def test_the_revolve_page_is_an_elevation(M):
    layout = M.planes.get_layout(u"revolve_elevation")
    assert layout[u"view"] == u"elevation", layout[u"view"]
    assert u"Front" in M.planes.view_names_for(u"revolve_elevation")


def test_the_revolve_axis_sits_on_the_origin(M):
    places = dict([(name, offset) for name, axis, offset, ref
                   in M.planes.plane_positions(u"revolve_elevation", SIZES)])
    assert places[u"Center (Left/Right)"] == 0.0, places
    assert places[u"Radius"] == SIZES[u"r"], places
    assert places[u"Bottom"] == 0.0 and places[u"Top"] == SIZES[u"h"], places


def test_the_revolve_page_drives_a_radius_and_a_height(M):
    assert sorted(M.planes.params_used(u"revolve_elevation")) == [u"h", u"r"]


def test_every_layout_names_a_view_to_open(M):
    for key in M.planes.layout_keys():
        assert M.planes.view_names_for(key), key


# =========================================================================
# What a material has to arrive with
# =========================================================================

class FakeId(object):
    def __init__(self, value):
        self.Value = value


class FakeMaterial(object):
    def __init__(self, **values):
        for key in values:
            setattr(self, key, values[key])


def test_a_material_carries_its_assets_and_patterns(M):
    material = FakeMaterial(
        AppearanceAssetId=FakeId(11), ThermalAssetId=FakeId(12),
        StructuralAssetId=FakeId(13),
        SurfaceForegroundPatternId=FakeId(21),
        CutForegroundPatternId=FakeId(22))
    found = [M.core.eid_value(e)
             for e in M.model.material_dependencies(material)]
    assert sorted(found) == [11, 12, 13, 21, 22], found


def test_invalid_and_missing_ids_are_left_out(M):
    u"""An unset asset is ElementId.InvalidElementId, which reads as -1."""
    material = FakeMaterial(AppearanceAssetId=FakeId(11),
                            ThermalAssetId=FakeId(-1),
                            SurfacePatternId=None)
    found = [M.core.eid_value(e)
             for e in M.model.material_dependencies(material)]
    assert found == [11], found


def test_the_same_id_is_only_handed_over_once(M):
    u"""SurfacePatternId and SurfaceForegroundPatternId are the same thing
    spelled two ways across releases, so both answer and both must not end
    up in the copy set."""
    material = FakeMaterial(SurfaceForegroundPatternId=FakeId(21),
                            SurfacePatternId=FakeId(21),
                            CutPatternId=FakeId(22))
    found = [M.core.eid_value(e)
             for e in M.model.material_dependencies(material)]
    assert sorted(found) == [21, 22], found


def test_a_material_with_nothing_attached_needs_nothing(M):
    assert M.model.material_dependencies(FakeMaterial()) == []


def test_valid_id(M):
    assert M.model.valid_id(FakeId(7)) is True
    assert M.model.valid_id(FakeId(-1)) is False
    assert M.model.valid_id(None) is False


def test_a_scan_item_defaults_to_no_dependencies(M):
    item = M.model.ScanItem(u"text", u"BGL_2.5mm", None, u"2.5mm")
    assert item.depends == []
    assert item.asset_name == u""
    assert u"BGL_2.5mm" in item.searchable()


# =========================================================================
# Telling the real appearance asset from the family's own
# =========================================================================

class FakeProp(object):
    def __init__(self, name, value, connected=None):
        self.Name = name
        self.Value = value
        self._connected = connected
        self.NumberOfConnectedProperties = 1 if connected is not None else 0

    def GetSingleConnectedAsset(self):
        return self._connected


class FakeAsset(object):
    def __init__(self, name, props):
        self.Name = name
        self._props = list(props)

    def __iter__(self):
        return iter(self._props)


def test_two_identical_assets_fingerprint_the_same(M):
    left = FakeAsset(u"Generic", [FakeProp(u"generic_diffuse", u"255,0,0"),
                                  FakeProp(u"generic_glossiness", 0.4)])
    right = FakeAsset(u"Generic", [FakeProp(u"generic_diffuse", u"255,0,0"),
                                   FakeProp(u"generic_glossiness", 0.4)])
    assert M.model.asset_fingerprint(left) == M.model.asset_fingerprint(right)


def test_a_different_value_is_a_different_asset(M):
    u"""The family's own 'Red' and the project's 'Red' share a name and
    nothing else - which is exactly what the name based check missed."""
    left = FakeAsset(u"Generic", [FakeProp(u"generic_diffuse", u"255,0,0")])
    right = FakeAsset(u"Generic", [FakeProp(u"generic_diffuse", u"128,128,128")])
    assert M.model.asset_fingerprint(left) != M.model.asset_fingerprint(right)


def test_a_missing_property_is_a_different_asset(M):
    left = FakeAsset(u"Generic", [FakeProp(u"a", 1), FakeProp(u"b", 2)])
    right = FakeAsset(u"Generic", [FakeProp(u"a", 1)])
    assert M.model.asset_fingerprint(left) != M.model.asset_fingerprint(right)


def test_a_texture_counts(M):
    u"""Two materials that differ only in their bitmap have identical
    scalars, so the connected asset has to be walked as well."""
    one = FakeAsset(u"Bitmap", [FakeProp(u"unifiedbitmap_Bitmap", u"brick.png")])
    two = FakeAsset(u"Bitmap", [FakeProp(u"unifiedbitmap_Bitmap", u"steel.png")])
    left = FakeAsset(u"Generic", [FakeProp(u"generic_diffuse", u"map", one)])
    right = FakeAsset(u"Generic", [FakeProp(u"generic_diffuse", u"map", two)])
    assert M.model.asset_fingerprint(left) != M.model.asset_fingerprint(right)


def test_nothing_read_is_not_a_match(M):
    u"""A release that will not give up the rendering asset would
    otherwise read as 'these two match' and leave the wrong asset on."""
    assert M.model.same_asset(u"", u"") is False
    assert M.model.same_asset(u"abc", u"") is False
    assert M.model.same_asset(u"abc", u"abc") is True


def test_an_asset_that_will_not_be_read_fingerprints_empty(M):
    assert M.model.asset_fingerprint(None) == u""


def test_document_title_drops_the_extension(M):
    class FakeDoc(object):
        Title = u"BGL_MEP_2024_ver6.3-Template_ACC.rvt"
    assert M.model.document_title(FakeDoc()) == \
        u"BGL_MEP_2024_ver6.3-Template_ACC"


def test_the_asset_name_is_not_part_of_the_fingerprint(M):
    u"""The same appearance rebuilt under another element name is still the
    same appearance - including the name would make every rebuild read as
    a failure."""
    left = FakeAsset(u"PVC Red(3)", [FakeProp(u"generic_diffuse", u"255,0,0")])
    right = FakeAsset(u"Generic(4)", [FakeProp(u"generic_diffuse", u"255,0,0")])
    assert M.model.asset_fingerprint(left) == M.model.asset_fingerprint(right)


def test_the_schema_is_still_readable(M):
    assert M.model.asset_schema(FakeAsset(u"Generic", [])) == u"Generic"
    assert M.model.asset_schema(None) == u""


# =========================================================================
# Writing one asset's properties into another
# =========================================================================

class FakeSource(object):
    def __init__(self, doubles=None, value=None):
        self._doubles = doubles
        if value is not None:
            self.Value = value

    def GetValueAsDoubles(self):
        if self._doubles is None:
            raise Exception(u"not a double array")
        return self._doubles


class FakeTarget(object):
    def __init__(self, takes_doubles=False, takes_value=False):
        self.doubles = None
        self.value = None
        self._takes_doubles = takes_doubles
        self._takes_value = takes_value

    def SetValueAsDoubles(self, values):
        if not self._takes_doubles:
            raise Exception(u"read only")
        self.doubles = list(values)

    def __setattr__(self, name, value):
        if name == u"Value":
            if not self.__dict__.get(u"_takes_value"):
                raise Exception(u"read only")
            self.__dict__[u"value"] = value
            return
        self.__dict__[name] = value


def test_a_colour_goes_across_as_doubles(M):
    u"""A colour is four doubles, not a Value."""
    source = FakeSource(doubles=[1.0, 0.0, 0.0, 1.0])
    target = FakeTarget(takes_doubles=True)
    assert M.ops._copy_property(source, target) is True
    assert target.doubles == [1.0, 0.0, 0.0, 1.0], target.doubles


def test_a_scalar_falls_through_to_value(M):
    source = FakeSource(value=50)
    target = FakeTarget(takes_value=True)
    assert M.ops._copy_property(source, target) is True
    assert target.value == 50, target.value


def test_a_read_only_property_is_reported_not_thrown(M):
    source = FakeSource(value=50)
    target = FakeTarget()
    assert M.ops._copy_property(source, target) is False


def test_a_property_with_no_value_at_all_is_refused(M):
    assert M.ops._copy_property(FakeSource(), FakeTarget(takes_value=True)) \
        is False


# =========================================================================
# Writing a whole asset across
# =========================================================================

class FakeWProp(object):
    def __init__(self, name, doubles=None, connected=None, writable=True):
        self.Name = name
        self.doubles = doubles
        self.connected = connected
        self.writable = writable
        self.added = None

    @property
    def NumberOfConnectedProperties(self):
        return 1 if self.connected is not None else 0

    def GetValueAsDoubles(self):
        if self.doubles is None:
            raise Exception(u"not a double array")
        return self.doubles

    def SetValueAsDoubles(self, values):
        if not self.writable:
            raise Exception(u"read only")
        self.doubles = list(values)

    def GetSingleConnectedAsset(self):
        return self.connected

    def AddConnectedAsset(self, schema):
        self.added = schema
        self.connected = FakeWAsset(schema, [FakeWProp(u"bitmap",
                                                       doubles=[0.0])])


class FakeWAsset(object):
    def __init__(self, name, props):
        self.Name = name
        self.props = list(props)

    def __iter__(self):
        return iter(self.props)

    def FindByName(self, name):
        for prop in self.props:
            if prop.Name == name:
                return prop
        return None


def test_matching_properties_are_written(M):
    source = FakeWAsset(u"Generic", [FakeWProp(u"generic_diffuse",
                                               [1.0, 0.0, 0.0, 1.0])])
    target = FakeWAsset(u"Generic", [FakeWProp(u"generic_diffuse",
                                               [0.3, 0.3, 0.3, 1.0])])
    assert M.ops.write_asset(source, target) == 1
    assert target.FindByName(u"generic_diffuse").doubles == \
        [1.0, 0.0, 0.0, 1.0]


def test_nothing_in_common_writes_nothing(M):
    u"""Zero written is how a different schema is recognised - comparing
    the two schema NAMES was a guess that bailed out on assets that would
    have copied perfectly well."""
    source = FakeWAsset(u"Generic", [FakeWProp(u"generic_diffuse", [1.0])])
    target = FakeWAsset(u"Metal", [FakeWProp(u"metal_type", [2.0])])
    assert M.ops.write_asset(source, target) == 0
    assert target.FindByName(u"metal_type").doubles == [2.0]


def test_a_texture_is_walked_as_well(M):
    u"""Two materials that differ only in their bitmap have identical
    scalars, so the connected asset has to be written too."""
    source_map = FakeWAsset(u"UnifiedBitmap", [FakeWProp(u"bitmap", [7.0])])
    target_map = FakeWAsset(u"UnifiedBitmap", [FakeWProp(u"bitmap", [0.0])])
    source = FakeWAsset(u"Generic", [FakeWProp(u"generic_diffuse", [1.0],
                                               source_map)])
    target = FakeWAsset(u"Generic", [FakeWProp(u"generic_diffuse", [0.0],
                                               target_map)])
    assert M.ops.write_asset(source, target) == 2
    assert target_map.FindByName(u"bitmap").doubles == [7.0]


def test_a_missing_texture_slot_is_created(M):
    source_map = FakeWAsset(u"UnifiedBitmap", [FakeWProp(u"bitmap", [7.0])])
    source = FakeWAsset(u"Generic", [FakeWProp(u"generic_diffuse", [1.0],
                                               source_map)])
    target_prop = FakeWProp(u"generic_diffuse", [0.0])
    target = FakeWAsset(u"Generic", [target_prop])
    written = M.ops.write_asset(source, target)
    assert target_prop.added == u"UnifiedBitmap", target_prop.added
    assert written == 2, written


def test_a_read_only_property_does_not_stop_the_rest(M):
    source = FakeWAsset(u"Generic", [FakeWProp(u"a", [1.0]),
                                     FakeWProp(u"b", [2.0])])
    target = FakeWAsset(u"Generic", [FakeWProp(u"a", [0.0], writable=False),
                                     FakeWProp(u"b", [0.0])])
    assert M.ops.write_asset(source, target) == 1
    assert target.FindByName(u"b").doubles == [2.0]


# =========================================================================
# The diagnostic trace
# =========================================================================

def test_a_trace_reads_back_what_went_into_it(M):
    trace = M.core.Trace(u"Report")
    trace.heading(u"Environment")
    trace.pair(u"Revit", u"2024")
    trace.fail(u"the copy", u"Traceback\n  line one\n  line two")
    text = trace.to_text()
    assert text.startswith(u"Report\n======"), text[:40]
    assert u"Environment" in text
    assert u"Revit: 2024" in text
    assert u"FAILED the copy" in text
    assert u"line two" in text


def test_a_long_value_is_cut_short(M):
    u"""An asset property can hold a whole texture path, and a report
    nobody can read is a report nobody sends."""
    trace = M.core.Trace(u"Report")
    trace.pair(u"bitmap", u"x" * 2000)
    text = trace.to_text()
    assert u"more]" in text, text[-80:]
    assert len(text) < 1200, len(text)


def test_a_runaway_trace_stops_and_says_so(M):
    trace = M.core.Trace(u"Report")
    for index in range(M.core.MAX_TRACE_LINES + 50):
        trace.note(u"line {0}".format(index))
    assert trace.dropped == 50, trace.dropped
    assert u"further lines dropped" in trace.to_text()


def test_indenting_keeps_the_shape(M):
    trace = M.core.Trace(u"Report")
    trace.note(u"outer", 0)
    trace.note(u"inner", 2)
    assert u"\n    inner" in trace.to_text()


def test_identity_properties_are_left_out_of_the_comparison(M):
    u"""The thumbnail is a temp path with the process id in it and UIName
    follows the element name, so two copies of the same appearance never
    agree on them.  Comparing them made a perfect copy read as a failure."""
    left = FakeAsset(u"GenericSchema", [
        FakeProp(u"thumbnail", u"tmp:?MaterialThumbnails_PID_d398.png"),
        FakeProp(u"UIName", u"PVC Red(3)"),
        FakeProp(u"generic_diffuse", u"1.0,0.0,0.0,1.0")])
    right = FakeAsset(u"GenericSchema", [
        FakeProp(u"thumbnail", u"tmp:?MaterialThumbnails_PID_9a11.png"),
        FakeProp(u"UIName", u"PVC Red(3) (BGL_MEP)"),
        FakeProp(u"generic_diffuse", u"1.0,0.0,0.0,1.0")])
    assert M.model.asset_fingerprint(left) == M.model.asset_fingerprint(right)


def test_a_real_difference_still_shows_through(M):
    left = FakeAsset(u"GenericSchema", [
        FakeProp(u"thumbnail", u"a.png"),
        FakeProp(u"generic_diffuse", u"1.0,0.0,0.0,1.0")])
    right = FakeAsset(u"GenericSchema", [
        FakeProp(u"thumbnail", u"b.png"),
        FakeProp(u"generic_diffuse", u"0.3,0.3,0.3,1.0")])
    assert M.model.asset_fingerprint(left) != M.model.asset_fingerprint(right)


def test_volatile_names_are_matched_whatever_the_case(M):
    assert M.model.is_volatile(u"UIName") is True
    assert M.model.is_volatile(u"thumbnail") is True
    assert M.model.is_volatile(u" VersionGUID ") is True
    assert M.model.is_volatile(u"generic_diffuse") is False


def test_identity_properties_are_not_written_across(M):
    source = FakeWAsset(u"GenericSchema", [FakeWProp(u"thumbnail", [1.0]),
                                           FakeWProp(u"generic_diffuse", [1.0])])
    target = FakeWAsset(u"GenericSchema", [FakeWProp(u"thumbnail", [9.0]),
                                           FakeWProp(u"generic_diffuse", [0.0])])
    assert M.ops.write_asset(source, target) == 1
    assert target.FindByName(u"thumbnail").doubles == [9.0]
    assert target.FindByName(u"generic_diffuse").doubles == [1.0]


# =========================================================================
# Finding an asset of the right schema
# =========================================================================

class FakeSchemaAsset(object):
    def __init__(self, name, base_schema=None, props=None):
        self.Name = name
        self.props = list(props or [])
        if base_schema is not None:
            self.props.append(FakeProp(u"BaseSchema", base_schema))

    def __iter__(self):
        return iter(self.props)

    def FindByName(self, name):
        for prop in self.props:
            if prop.Name == name:
                return prop
        return None


def test_the_schema_comes_from_the_base_schema_property(M):
    u"""A library asset's Name is its own name - 'Aluminium - Anodised' -
    not its schema.  Matching on Name found nothing in a library of three
    thousand."""
    asset = FakeSchemaAsset(u"Aluminium - Anodised",
                            base_schema=u"GenericSchema")
    assert M.model.asset_base_schema(asset) == u"GenericSchema"


def test_the_schema_falls_back_to_the_name(M):
    assert M.model.asset_base_schema(
        FakeSchemaAsset(u"GenericSchema")) == u"GenericSchema"
    assert M.model.asset_base_schema(None) == u""


def test_schema_properties_are_left_out_of_the_comparison(M):
    u"""They are read only, so they never write across - comparing them
    made a look that transferred perfectly read back as different."""
    for name in (u"AdvancedUIDefinition", u"BaseSchema", u"localname",
                 u"category", u"PatternOffset"):
        assert M.model.is_ignored(name) is True, name
    assert M.model.is_ignored(u"generic_diffuse") is False


def test_a_schema_property_is_still_offered_to_the_write(M):
    u"""Ignored in the comparison, but not refused outright - a release
    that will take one loses nothing by it."""
    assert M.model.is_volatile(u"BaseSchema") is False
    assert M.model.is_volatile(u"thumbnail") is True


# =========================================================================
# When a plane dimension gets labelled
# =========================================================================

def test_a_picked_parameter_is_labelled_whatever_the_ticks_say(M):
    u"""The ticks govern INVENTING a parameter, not using one that was
    chosen on purpose."""
    assert M.core.should_label(u"BGL_Width", False, False) is True
    assert M.core.should_label(u"BGL_Width", True, True) is True


def test_with_nothing_picked_the_ticks_decide(M):
    assert M.core.should_label(u"", True, True) is True
    assert M.core.should_label(u"", False, True) is False
    assert M.core.should_label(u"", True, False) is False


def test_the_picked_parameter_is_read_off_the_page(M):
    mapping = {u"centred_box": {u"w": u"BGL_Width"}}
    assert M.core.assigned_param(mapping, u"centred_box", u"w") == u"BGL_Width"
    assert M.core.assigned_param(mapping, u"centred_box", u"d") == u""
    assert M.core.assigned_param(mapping, u"width_only", u"w") == u""
    assert M.core.assigned_param({}, u"centred_box", u"w") == u""


# =========================================================================
# The family icon view
# =========================================================================

def test_the_camera_looks_back_at_the_origin(M):
    u"""Revit wants the direction the camera LOOKS IN, which is the
    opposite of the corner it sits in."""
    corner, up, forward = M.core.orientation_for(u"top_back_left")
    for index in range(3):
        assert abs(corner[index] + forward[index]) < 1e-9, (corner, forward)
    assert corner[0] < 0 and corner[1] > 0 and corner[2] > 0, corner


def test_every_view_type_gives_a_usable_frame(M):
    for key, label, vector in M.core.VIEW_TYPES:
        corner, up, forward = M.core.orientation_for(key)
        length = sum([value * value for value in forward]) ** 0.5
        assert abs(length - 1.0) < 1e-9, (key, forward)
        dot = sum([up[i] * forward[i] for i in range(3)])
        assert abs(dot) < 1e-9, (key, up, forward, dot)
        assert sum([value * value for value in up]) ** 0.5 > 0.9, (key, up)


def test_a_straight_down_view_still_has_an_up(M):
    u"""The usual cross product gives nothing when the camera looks along
    Z, so that case is handed one."""
    corner, up, forward = M.core.orientation_for(u"top")
    assert sum([value * value for value in up]) ** 0.5 > 0.9, up
    # And square to the way it looks - the normalise helper falls back to
    # a unit vector when handed nothing, so length alone proves nothing.
    dot = sum([up[index] * forward[index] for index in range(3)])
    assert abs(dot) < 1e-9, (up, forward, dot)


def test_an_unknown_view_type_falls_back(M):
    assert M.core.view_type_by_key(u"nonsense")[0] == \
        M.core.VIEW_TYPES[0][0]


# =========================================================================
# Family naming
# =========================================================================

def test_the_name_is_built_with_underscores(M):
    assert M.core.build_family_name(
        [u"BGL", u"PFX", u"DOM", u"Waste Connection"]) == \
        u"BGL_PFX_DOM_Waste Connection"


def test_an_underscore_typed_into_a_box_is_not_a_separator(M):
    u"""It would read back as an extra part."""
    assert M.core.build_family_name([u"BGL", u"P_FX", u"DOM", u"Waste"]) == \
        u"BGL_P FX_DOM_Waste"


def test_spare_spaces_are_tidied(M):
    assert M.core.build_family_name(
        [u"  BGL ", u"PFX", u"DOM", u"Waste   Connection "]) == \
        u"BGL_PFX_DOM_Waste Connection"


def test_an_empty_box_leaves_the_name_incomplete(M):
    parts = [u"BGL", u"PFX", u"", u"Waste"]
    assert M.core.family_name_is_complete(parts) is False
    assert M.core.family_name_is_complete(
        [u"BGL", u"PFX", u"DOM", u"Waste"]) is True
    assert M.core.family_name_is_complete([u"BGL", u"PFX", u"  ", u"W"]) \
        is False


def test_abbreviations_round_trip(M):
    items = M.core.parse_abbreviation_lines(
        u"BGL = Building Group\nPFX=Pipe fitting\n\nDOM")
    assert items == [(u"BGL", u"Building Group"), (u"PFX", u"Pipe fitting"),
                     (u"DOM", u"")], items
    again = M.core.parse_abbreviations(M.core.format_abbreviations(items))
    assert again == items, again


def test_a_repeated_abbreviation_is_dropped(M):
    items = M.core.parse_abbreviation_lines(u"BGL = one\nbgl = two")
    assert len(items) == 1, items


def test_a_file_name_loses_the_characters_windows_refuses(M):
    assert M.core.safe_file_name(u"BGL_PFX_DOM_90/45 Bend") == \
        u"BGL_PFX_DOM_90-45 Bend"
    assert M.core.safe_file_name(u"   ") == u"Family"


def test_the_view_type_dropdown_reads_the_right_way_round(M):
    u"""The list is (key, label, corner) and the dropdown wants
    (key, label) - getting that pair backwards puts the key on screen and
    the label in the settings file."""
    for key, label, corner in M.core.VIEW_TYPES:
        assert M.core.view_type_by_key(key)[1] == label, key
        assert key != label, key


# =========================================================================
# The flex test
# =========================================================================

class FakeRow(object):
    def __init__(self, status, parameter=u"W", value=0.0):
        self.status = status
        self.parameter = parameter
        self.value = value


def test_the_ends_are_always_driven(M):
    u"""The minimum and the maximum are where a family breaks, so they are
    in every run whatever the step count."""
    assert M.core.flex_values(100, 500, 0) == [100.0, 500.0]
    values = M.core.flex_values(100, 500, 3)
    assert values[0] == 100.0 and values[-1] == 500.0, values
    assert len(values) == 5, values


def test_the_steps_are_evenly_spaced(M):
    assert M.core.flex_values(0, 100, 3) == [0.0, 25.0, 50.0, 75.0, 100.0]
    assert M.core.flex_values(0, 10, 1) == [0.0, 5.0, 10.0]


def test_ends_the_wrong_way_round_are_swapped(M):
    assert M.core.flex_values(500, 100, 1) == [100.0, 300.0, 500.0]


def test_a_range_of_nothing_is_one_test(M):
    u"""A 100 to 100 run is one round, not five identical ones."""
    assert M.core.flex_values(100, 100, 4) == [100.0]


def test_a_nonsense_step_count_does_not_break_the_run(M):
    assert M.core.flex_values(0, 10, u"") == [0.0, 10.0]
    assert M.core.flex_values(0, 10, -3) == [0.0, 10.0]
    assert len(M.core.flex_values(0, 10, 500)) == 22


def test_the_ends_are_offered_around_what_it_already_is(M):
    low, high = M.core.flex_spread(200, 50)
    assert (low, high) == (100.0, 300.0), (low, high)


def test_a_parameter_at_zero_gets_a_usable_range(M):
    u"""Half of nothing is nothing, which would be a run of one value."""
    low, high = M.core.flex_spread(0, 50)
    assert high > low > 0, (low, high)


def test_the_round_count_multiplies_by_the_types(M):
    specs = [(u"W", 100, 500), (u"D", 50, 50)]
    assert M.core.flex_test_count(1, specs, 3) == 6
    assert M.core.flex_test_count(4, specs, 3) == 24


def test_a_run_that_is_too_big_is_recognised(M):
    assert M.core.flex_is_too_big(M.core.MAX_FLEX_TESTS) is False
    assert M.core.flex_is_too_big(M.core.MAX_FLEX_TESTS + 1) is True


def test_the_summary_reads_worst_first(M):
    rows = [FakeRow(M.core.FLEX_OK), FakeRow(M.core.FLEX_OK),
            FakeRow(M.core.FLEX_WARNED), FakeRow(M.core.FLEX_BROKE)]
    assert M.core.flex_summary(rows) == u"1 broke, 1 warned, 2 fine"
    assert M.core.flex_summary([]) == u"Nothing was run"


def test_the_worst_result_is_what_the_run_is_called(M):
    assert M.core.flex_worst([FakeRow(M.core.FLEX_OK),
                              FakeRow(M.core.FLEX_WARNED)]) == \
        M.core.FLEX_WARNED
    assert M.core.flex_worst([FakeRow(M.core.FLEX_OK)]) == M.core.FLEX_OK
    assert M.core.flex_worst([]) == M.core.FLEX_OK


def test_the_rows_are_sorted_worst_first(M):
    rows = [FakeRow(M.core.FLEX_OK, u"A", 1.0),
            FakeRow(M.core.FLEX_BROKE, u"B", 2.0),
            FakeRow(M.core.FLEX_WARNED, u"C", 3.0)]
    order = [row.status for row in M.core.flex_rows_sorted(rows)]
    assert order == [M.core.FLEX_BROKE, M.core.FLEX_WARNED,
                     M.core.FLEX_OK], order


def test_every_outcome_is_explained(M):
    for status in M.core.FLEX_ORDER:
        assert status in M.core.FLEX_MEANING, status


TESTS = [(name, value) for name, value in sorted(globals().items())
         if name.startswith(u"test_")]


def run(root=HERE, quiet=False, only=None):
    bench = Bench(root)
    failed = []
    for name, test in TESTS:
        if only and name != only:
            continue
        try:
            test(bench)
        except Exception as error:
            failed.append((name, u"{0}: {1}".format(type(error).__name__, error)))
            if not quiet:
                sys.stdout.write(u"FAIL  {0}\n        {1}\n".format(
                    name, error))
        else:
            if not quiet:
                sys.stdout.write(u"ok    {0}\n".format(name))
    return failed


# =========================================================================
# The selftest
# =========================================================================

BREAKAGES = (
    (u"test_natural_order", u"fet_core.py",
     u"        if part.isdigit():", u"        if False:"),
    (u"test_spf_refuses_a_repeated_guid", u"fet_core.py",
     u"            if guid in seen:", u"            if False:"),
    (u"test_spf_resolves_group_names", u"fet_core.py",
     u"        item.group = groups.get(item.group, item.group)",
     u"        item.group = item.group"),
    (u"test_search_takes_every_word_in_any_order", u"fet_core.py",
     u"        if word not in hay:", u"        if False:"),
    (u"test_settings_split_on_the_first_equals_only", u"fet_core.py",
     u"        key, value = line.split(u\"=\", 1)",
     u"        key, value = line.split(u\"=\")"),
    (u"test_settings_ignore_a_key_from_an_older_version", u"fet_core.py",
     u"        if key in DEFAULTS:\n            out[key] = value.strip()",
     u"        if True:\n            out[key] = value.strip()"),
    (u"test_template_reports_a_short_line", u"fet_core.py",
     u"            if len(cells) < 4:", u"            if len(cells) < 1:"),
    (u"test_parse_colour", u"fet_core.py",
     u"        out.append(max(0, min(255, value)))", u"        out.append(value)"),
    (u"test_unique_name", u"fet_core.py",
     u"    if name.lower() not in existing:", u"    if True:"),
    (u"test_millimetres_to_feet", u"fet_core.py",
     u"    return float(value) / MM_PER_FOOT",
     u"    return float(value) * MM_PER_FOOT"),
    (u"test_presets_drop_a_repeat", u"fet_core.py",
     u"        if key in seen:\n            continue",
     u"        if False:\n            continue"),
    (u"test_centred_box_is_symmetric_about_the_origin", u"fet_planes.py",
     u"            total += float(factor) * float(sizes.get(key, 0.0))",
     u"            total += float(sizes.get(key, 0.0))"),
    (u"test_dimension_planes_read_low_to_high", u"fet_planes.py",
     u"        pairs.sort(key=lambda pair: pair[1])", u"        pairs.reverse()"),
    (u"test_step_layout_wraps_both_ways", u"fet_planes.py",
     u"    index = (layout_index(key) + int(delta)) % len(LAYOUTS)",
     u"    index = min(max(layout_index(key) + int(delta), 0), len(LAYOUTS) - 1)"),
    (u"test_preview_fits_its_box_at_every_shape", u"fet_planes.py",
     u"    scale = (1.0 - 2.0 * PREVIEW_MARGIN) / max(x_high - x_low, y_high - y_low, 1e-6)",
     u"    scale = 1.0 / max(x_high - x_low, 1e-6)"),
    (u"test_result_tally", u"fet_ops.py",
     u"        if item.status in out:", u"        if False:"),
    (u"test_both_spellings_land_on_the_same_kind", u"fet_core.py",
     u"    for char in _as_text(text).lower():",
     u"    for char in _as_text(text):"),
    (u"test_kinds_are_told_apart", u"fet_core.py",
     u"    (KIND_INTEGER, (u\"integer\",)),", u""),
    (u"test_an_unknown_data_type_is_other", u"fet_core.py",
     u"    return KIND_OTHER\n\n\ndef data_brush_key",
     u"    return KIND_TEXT\n\n\ndef data_brush_key"),
    (u"test_kinds_present_keeps_the_order_and_drops_repeats", u"fet_core.py",
     u"    return [kind for kind in KIND_ORDER if kind in found]",
     u"    return sorted(found)"),
    (u"test_a_replace_with_no_target_is_a_new_parameter", u"fet_core.py",
     u"            self.action = ACTION_NEW\n\n    @property\n    def is_instance",
     u"            self.action = ACTION_REPLACE\n\n    @property\n    def is_instance"),
    (u"test_an_older_five_field_template_still_loads", u"fet_core.py",
     u"            if len(cells) < 4:", u"            if len(cells) < 7:"),
    (u"test_swapping_two_names_goes_through_a_parked_name", u"fet_core.py",
     u"    needs_parking = any(wanted in moving for wanted in moving.values())",
     u"    needs_parking = False"),
    (u"test_a_clash_with_a_name_nobody_is_moving_is_refused", u"fet_core.py",
     u"        if wanted in held_elsewhere:", u"        if False:"),
    (u"test_an_empty_edit_touches_nothing", u"fet_core.py",
     u"                self.group is not None or self.formula is not None)",
     u"                self.group is not None or self.formula)"),
    (u"test_layout_params_round_trip", u"fet_core.py",
     u"            key, name = item.split(u\"=\", 1)",
     u"            key, name = item.split(u\"=\")[0], u\"\""),
    (u"test_a_parameter_name_with_a_separator_is_refused", u"fet_core.py",
     u"            if name and not [bad for bad in (u\";\", u\":\", u\",\", u\"=\")\n                             if bad in name]:",
     u"            if name:"),
    (u"test_a_page_falls_back_to_the_house_default_name", u"fet_core.py",
     u"    chosen = mapping.get(layout_key, {}).get(param_key, u\"\")",
     u"    chosen = u\"\""),
    (u"test_the_revolve_axis_sits_on_the_origin", u"fet_planes.py",
     u"            {u\"name\": u\"Radius\", u\"axis\": u\"x\", u\"off\": [(1.0, u\"r\")], u\"ref\": RIGHT},",
     u"            {u\"name\": u\"Radius\", u\"axis\": u\"x\", u\"off\": [(2.0, u\"r\")], u\"ref\": RIGHT},"),
    (u"test_a_material_carries_its_assets_and_patterns", u"fet_model.py",
     u"    for attribute in MATERIAL_ASSET_PROPERTIES + MATERIAL_PATTERN_PROPERTIES:",
     u"    for attribute in MATERIAL_ASSET_PROPERTIES:"),
    (u"test_invalid_and_missing_ids_are_left_out", u"fet_model.py",
     u"        if not valid_id(element_id):\n            continue",
     u"        if False:\n            continue"),
    (u"test_the_same_id_is_only_handed_over_once", u"fet_model.py",
     u"        if key in seen:\n            continue",
     u"        if False:\n            continue"),
    (u"test_a_different_value_is_a_different_asset", u"fet_model.py",
     u"        parts.append(_property_text(prop, depth))",
     u"        parts.append(u\"\")"),
    (u"test_the_ends_are_always_driven", u"fet_core.py",
     u"    out.append(high)", u"    pass"),
    (u"test_ends_the_wrong_way_round_are_swapped", u"fet_core.py",
     u"    if low > high:\n        low, high = high, low",
     u"    if False:\n        low, high = high, low"),
    (u"test_a_range_of_nothing_is_one_test", u"fet_core.py",
     u"        if not [kept for kept in cleaned if abs(kept - rounded) < 1e-6]:",
     u"        if True:"),
    (u"test_a_nonsense_step_count_does_not_break_the_run", u"fet_core.py",
     u"    count = max(0, min(count, 20))", u"    count = count"),
    (u"test_a_parameter_at_zero_gets_a_usable_range", u"fet_core.py",
     u"    if value <= 0:\n        return 100.0, 1000.0",
     u"    if False:\n        return 100.0, 1000.0"),
    (u"test_the_round_count_multiplies_by_the_types", u"fet_core.py",
     u"    return per_type * max(1, int(type_count or 1))",
     u"    return per_type"),
    (u"test_the_summary_reads_worst_first", u"fet_core.py",
     u"    for status in FLEX_ORDER:\n        count = tally.get(status, 0)",
     u"    for status in sorted(tally.keys()):\n        count = tally.get(status, 0)"),
    (u"test_the_rows_are_sorted_worst_first", u"fet_core.py",
     u"                  key=lambda row: (order.get(row.status, 99),",
     u"                  key=lambda row: (0,"),
    (u"test_the_camera_looks_back_at_the_origin", u"fet_core.py",
     u"    forward = (-corner[0], -corner[1], -corner[2])",
     u"    forward = (corner[0], corner[1], corner[2])"),
    (u"test_a_straight_down_view_still_has_an_up", u"fet_core.py",
     u"    if abs(forward[2]) > 0.999:\n        up = (0.0, 1.0, 0.0)",
     u"    if False:\n        up = (0.0, 1.0, 0.0)"),
    (u"test_an_underscore_typed_into_a_box_is_not_a_separator", u"fet_core.py",
     u"_as_text(text).replace(NAME_SEPARATOR, u\" \")",
     u"_as_text(text)"),
    (u"test_an_empty_box_leaves_the_name_incomplete", u"fet_core.py",
     u"    return len([1 for part in parts if clean_name_part(part)]) == len(parts) \\\n        and len(parts) > 0",
     u"    return True"),
    (u"test_a_repeated_abbreviation_is_dropped", u"fet_core.py",
     u"        if not code or code.lower() in seen:",
     u"        if not code:"),
    (u"test_a_file_name_loses_the_characters_windows_refuses", u"fet_core.py",
     u"        out.append(u\"-\" if char in ILLEGAL_FILE_CHARS else char)",
     u"        out.append(char)"),
    (u"test_a_picked_parameter_is_labelled_whatever_the_ticks_say",
     u"fet_core.py",
     u"    if assigned:\n        return True",
     u"    if False:\n        return True"),
    (u"test_with_nothing_picked_the_ticks_decide", u"fet_core.py",
     u"    return bool(label_dims) and bool(create_params)",
     u"    return True"),
    (u"test_the_schema_comes_from_the_base_schema_property", u"fet_model.py",
     u"        prop = asset.FindByName(u\"BaseSchema\")",
     u"        prop = asset.FindByName(u\"NotThere\")"),
    (u"test_schema_properties_are_left_out_of_the_comparison", u"fet_model.py",
     u"    return text in VOLATILE_PROPERTIES or text in SCHEMA_PROPERTIES",
     u"    return text in VOLATILE_PROPERTIES"),
    (u"test_identity_properties_are_left_out_of_the_comparison", u"fet_model.py",
     u"            if is_ignored(prop.Name):\n                continue",
     u"            if False:\n                continue"),
    (u"test_volatile_names_are_matched_whatever_the_case", u"fet_model.py",
     u"    return fet_core._as_text(name).strip().lower() in VOLATILE_PROPERTIES",
     u"    return fet_core._as_text(name) in VOLATILE_PROPERTIES"),
    (u"test_identity_properties_are_not_written_across", u"fet_ops.py",
     u"        if fet_model.is_volatile(name):\n            continue",
     u"        if False:\n            continue"),
    (u"test_a_long_value_is_cut_short", u"fet_core.py",
     u"    if len(text) <= limit:\n        return text",
     u"    if True:\n        return text"),
    (u"test_a_runaway_trace_stops_and_says_so", u"fet_core.py",
     u"        if len(self.lines) >= MAX_TRACE_LINES:",
     u"        if False:"),
    (u"test_indenting_keeps_the_shape", u"fet_core.py",
     u"        self.lines.append(u\"{0}{1}\".format(u\"  \" * int(indent),",
     u"        self.lines.append(u\"{0}{1}\".format(u\"\" * int(indent),"),
    (u"test_matching_properties_are_written", u"fet_ops.py",
     u"        if _copy_property(source_property, target):\n            written += 1",
     u"        if _copy_property(source_property, target):\n            written += 0"),
    (u"test_a_texture_is_walked_as_well", u"fet_ops.py",
     u"        written += write_asset(source_connected, target_connected, depth + 1)",
     u"        written += 0"),
    (u"test_a_missing_texture_slot_is_created", u"fet_ops.py",
     u"                target.AddConnectedAsset(source_connected.Name)",
     u"                pass"),
    (u"test_nothing_in_common_writes_nothing", u"fet_ops.py",
     u"        if target is None:\n            continue",
     u"        if target is None:\n            target = source_property"),
    (u"test_a_colour_goes_across_as_doubles", u"fet_ops.py",
     u"        values = source.GetValueAsDoubles()\n        target.SetValueAsDoubles(values)",
     u"        values = source.GetValueAsDoubles()\n        raise Exception(values)"),
    (u"test_a_scalar_falls_through_to_value", u"fet_ops.py",
     u"        target.Value = source.Value\n        return True",
     u"        return False"),
    (u"test_a_read_only_property_is_reported_not_thrown", u"fet_ops.py",
     u"    except Exception:\n        return False\n\n\ndef _connected(",
     u"    except Exception:\n        return True\n\n\ndef _connected("),
    (u"test_the_asset_name_is_not_part_of_the_fingerprint", u"fet_model.py",
     u"    if depth:\n        try:\n            parts.append(u\"{0}\".format(asset.Name))",
     u"    if True:\n        try:\n            parts.append(u\"{0}\".format(asset.Name))"),
    (u"test_a_texture_counts", u"fet_model.py",
     u"        if depth < FINGERPRINT_DEPTH and prop.NumberOfConnectedProperties > 0:",
     u"        if False:"),
    (u"test_a_missing_property_is_a_different_asset", u"fet_model.py",
     u"    for prop in asset_properties(asset):",
     u"    for prop in asset_properties(asset)[:1]:"),
    (u"test_nothing_read_is_not_a_match", u"fet_model.py",
     u"    if not left or not right:\n        return False",
     u"    if not left or not right:\n        return True"),
    (u"test_every_layout_names_a_view_to_open", u"fet_planes.py",
     u"    u\"elevation\": (u\"Front\", u\"Front Elevation\", u\"Back\"),",
     u"    u\"elevation\": (),"),
)


def selftest():
    caught = 0
    missed = []
    for test_name, file_name, old, new in BREAKAGES:
        root = tempfile.mkdtemp(prefix=u"fetbench")
        try:
            for item in os.listdir(HERE):
                source = os.path.join(HERE, item)
                if os.path.isfile(source):
                    shutil.copy2(source, os.path.join(root, item))
            path = os.path.join(root, file_name)
            handle = open(path, u"rb")
            try:
                text = handle.read().decode(u"utf-8")
            finally:
                handle.close()
            if old not in text:
                raise AssertionError(
                    u"the selftest could not find its anchor for "
                    u"{0}".format(test_name))
            handle = open(path, u"wb")
            try:
                handle.write(text.replace(old, new, 1).encode(u"utf-8"))
            finally:
                handle.close()
            failures = run(root, quiet=True, only=test_name)
            if failures:
                caught += 1
                sys.stdout.write(u"caught  {0}\n".format(test_name))
            else:
                missed.append(test_name)
                sys.stdout.write(u"MISSED  {0}\n".format(test_name))
        finally:
            shutil.rmtree(root, ignore_errors=True)
    sys.stdout.write(u"\n{0} of {1} breakages were caught\n".format(
        caught, len(BREAKAGES)))
    return len(missed)


if __name__ == u"__main__":
    if u"--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    bad = run()
    sys.stdout.write(u"\n{0} checks, {1} failed\n".format(len(TESTS), len(bad)))
    sys.exit(1 if bad else 0)
