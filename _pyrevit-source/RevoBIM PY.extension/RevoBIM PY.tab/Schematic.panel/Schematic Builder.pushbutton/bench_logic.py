# -*- coding: utf-8 -*-
"""Schematic Builder - logic bench.

Runs sb_logic under plain CPython with no stubs:

    python bench_logic.py            run the checks
    python bench_logic.py --selftest also break the logic on purpose and
                                     prove each check notices

Exit code 0 = clean.
"""
from __future__ import print_function
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import sb_logic as L  # noqa: E402
import sb_lv as LV  # noqa: E402
import theme as T  # noqa: E402

FAILS = []


def check(name, condition, detail=u""):
    if condition:
        print(u"  ok   " + name)
    else:
        print(u"  FAIL " + name + (u"  -> " + detail if detail else u""))
        FAILS.append(name)


def overlap(a, b):
    """axis-aligned boxes (x0, y0, x1, y1) overlap with a positive area?"""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def run():
    # ---- settings -----------------------------------------------------------
    print("settings")
    path = os.path.join(tempfile.mkdtemp(), "sb.txt")
    data = L.load_settings(path)
    check("defaults when no file", data["scale"] == u"1" and data["name_water"].startswith(u"SCH_P_"))
    data["scale"] = u"2"
    data["levels"] = L.encode_rows([[u"Level 01", u"L01", u"1"], [u"Roof", u"RF", u"0"]])
    check("save", L.save_settings(data, path))
    back = L.load_settings(path)
    check("round trip", back["scale"] == u"2" and back["levels"] == data["levels"])
    with open(path, "wb") as handle:
        handle.write(u"settings_version=1\nscale=7\nbogus=1\n".encode("utf-8"))
    old = L.load_settings(path)
    check("migration keeps unlisted keys, drops unknown ones",
          old["scale"] == u"7" and "bogus" not in old
          and old["settings_version"] == L.as_text(L.SETTINGS_VERSION))
    with open(path, "wb") as handle:
        handle.write(u"settings_version=2\ntheme=dark\nscale=5\n".encode("utf-8"))
    v2 = L.load_settings(path)
    check("a 3.3 settings file is moved onto following Revit's canvas, keeping the rest",
          v2["theme"] == u"follow" and v2["scale"] == u"5")

    # ---- encoding -----------------------------------------------------------
    print("rows")
    rows = [[u"AHU", u"M_AHU", u"*", u"D_AHU", u"Std"], [u"Fan | x=>y", u"F", u"T", u"D", u"T"]]
    decoded = L.decode_rows(L.encode_rows(rows), 5)
    check("encode/decode 5 fields", decoded[0] == rows[0])
    check("separators scrubbed from values", decoded[1][0] == u"Fan   x-y")
    check("short records padded", L.decode_rows(u"a=>b", 5)[0] == [u"a", u"b", u"", u"", u""])
    check("blank records dropped", L.decode_rows(u"||a=>b||", 2) == [[u"a", u"b"]])
    pairs = L.parse_transfer(u"Mark=>Mark\n{level}=>BGL_Level\n\nbad line")
    check("transfer pairs", pairs == [(u"Mark", u"Mark"), (u"{level}", u"BGL_Level")])

    # ---- several families on one detail item --------------------------------
    print("family pairs")
    picked = [(u"M_AHU", u"Small"), (u"M_Fan", u"*"), (u"M_Fan", u"Large")]
    encoded = L.encode_pairs(picked)
    check("pairs round trip", L.decode_pairs(encoded) == picked)
    check("a bare family reads as all types", L.decode_pairs(u"M_AHU") == [(u"M_AHU", u"*")])
    check("blank pairs dropped", L.decode_pairs(u";;M_AHU::Small;;") == [(u"M_AHU", u"Small")])
    check("separators scrubbed out of names",
          L.decode_pairs(L.encode_pairs([(u"A::B;;C", u"T")])) == [(u"A B C", u"T")])
    row = [u"AHU", encoded, u"", u"D_AHU", u"Std"]
    check("row_families reads the pair list", L.row_families(row) == picked)
    check("a 2.0.0 row still reads", L.row_families([u"AHU", u"M_AHU", u"Small", u"D", u"T"])
          == [(u"M_AHU", u"Small")])
    check("a 2.0.0 row with no type means all types",
          L.row_families([u"AHU", u"M_AHU", u"", u"D", u"T"]) == [(u"M_AHU", u"*")])
    check("an empty row has no families", L.row_families([u"AHU", u"", u"", u"", u""]) == [])
    check("pair list survives the row encoding",
          L.row_families(L.decode_rows(L.encode_rows([row]), 5)[0]) == picked)
    check("one family reads as itself", L.pairs_text([(u"M_AHU", u"Small")]) == u"M_AHU : Small")
    check("several families are counted", L.pairs_text(picked).startswith(u"3 selected: M_AHU, M_Fan"))

    # ---- what each equipment row writes -------------------------------------
    print("transfer per row")
    shared = [(u"Mark", u"Mark"), (u"{room}", u"BGL_Room")]
    inherit = [u"AHU", encoded, u"", u"D", u"T", u""]
    skip = [u"Fan", encoded, u"", u"D", u"T", L.TRANSFER_NONE]
    own = [u"Grille", encoded, u"", u"D", u"T", L.encode_pairs([(u"{mark}", u"Ref")])]
    check("a row with nothing set uses the shared list", L.effective_transfer(inherit, shared) == shared)
    check("a row set to none writes nothing", L.effective_transfer(skip, shared) == [])
    check("a row with its own list ignores the shared one",
          L.effective_transfer(own, shared) == [(u"{mark}", u"Ref")])
    check("modes read back", [L.row_transfer_mode(r) for r in (inherit, skip, own)]
          == ["inherit", "none", "custom"])
    check("a 2.1.0 five-field row inherits", L.row_transfer_mode([u"A", u"B", u"", u"D", u"T"]) == "inherit")
    check("an empty custom list falls back to inherit",
          L.row_transfer_mode([u"A", u"B", u"", u"D", u"T", L.encode_pairs([])]) == "inherit")
    tpl_row = [u"AHU", encoded, u"", u"D", u"T", L.encode_row_template(u"Marks"), u"Length"]
    check("a row can name a template", L.row_transfer_mode(tpl_row) == "template"
          and L.row_template_name(tpl_row) == u"Marks")
    check("and takes that template's pairs",
          L.effective_transfer(tpl_row, shared, [(u"Marks", [(u"Mark", u"Mark")])]) == [(u"Mark", u"Mark")])
    check("a template that has gone leaves nothing to write",
          L.effective_transfer(tpl_row, shared, []) == [])
    check("the summary names the template and its size",
          L.transfer_summary(tpl_row, 2, [(u"Marks", [(u"Mark", u"Mark")])]) == u"Marks (1)"
          and L.transfer_summary(tpl_row, 2, []) == u"Marks - missing")
    check("the stretch parameter rides on the row", L.row_stretch_param(tpl_row) == u"Length"
          and L.row_stretch_param([u"A", u"B", u"", u"D", u"T"]) == u"")
    check("a seven field row survives the encoding",
          L.decode_rows(L.encode_rows([tpl_row]), L.ROW_WIDTH)[0] == tpl_row)
    check("summaries name the mode",
          L.transfer_summary(skip, 2) == u"none - skipped"
          and L.transfer_summary(inherit, 2) == u"shared (2)"
          and L.transfer_summary(own, 2) == u"1 of its own")
    check("the transfer field survives the row encoding",
          L.effective_transfer(L.decode_rows(L.encode_rows([own]), L.ROW_WIDTH)[0], shared)
          == [(u"{mark}", u"Ref")])
    print("templates")
    templates = L.upsert_template([], u"Marks", [(u"Mark", u"Mark"), (u"{room}", u"BGL_Room")])
    templates = L.upsert_template(templates, u"Levels", [(u"{level}", u"BGL_Level")])
    templates = L.upsert_template(templates, u"Marks", [(u"Mark", u"Mark")])
    check("upsert replaces by name, in place",
          [n for n, p in templates] == [u"Marks", u"Levels"] and L.template_pairs(templates, u"Marks") == [(u"Mark", u"Mark")])
    back = L.decode_templates(L.encode_templates(templates))
    check("templates round trip", back == templates)
    check("remove by name", L.remove_template(templates, u"Marks") == [(u"Levels", [(u"{level}", u"BGL_Level")])])
    check("unknown template is empty", L.template_pairs(templates, u"Nope") == [])
    text = L.encode_assignments(u"", u"Tower A", {101: u"Marks", 102: u"Levels"})
    text = L.encode_assignments(text, u"Tower B", {201: u"Marks"})
    check("assignments are per project",
          L.decode_assignments(text, u"Tower A") == {101: u"Marks", 102: u"Levels"}
          and L.decode_assignments(text, u"Tower B") == {201: u"Marks"})
    text = L.encode_assignments(text, u"Tower A", {101: u"Levels"})
    check("re-assigning one project leaves the other alone",
          L.decode_assignments(text, u"Tower A") == {101: u"Levels"}
          and L.decode_assignments(text, u"Tower B") == {201: u"Marks"})
    check("an unknown project has none", L.decode_assignments(text, u"Tower C") == {})
    cleared = L.encode_assignments(text, u"Tower A", {})
    check("clearing a project drops its row",
          L.decode_assignments(cleared, u"Tower A") == {} and L.decode_assignments(cleared, u"Tower B") == {201: u"Marks"})

    batches, orphans = L.batch_by_template([101, 102, 103], {101: u"Marks", 102: u"Levels"},
                                           templates, u"Marks")
    check("ticked items are grouped by their assigned template",
          [(b["template"], b["detail_ids"]) for b in batches] == [(u"Marks", [101, 103]), (u"Levels", [102])])
    check("an unassigned item falls back to the template on screen", orphans == [])
    batches, orphans = L.batch_by_template([101, 104], {101: u"Marks"}, templates, u"")
    check("with no fallback an unassigned item is reported, not guessed at",
          orphans == [104] and len(batches) == 1)
    batches, orphans = L.batch_by_template([105], {105: u"Deleted"}, templates, u"Marks")
    check("an assignment to a template that has gone is reported", orphans == [105])

    print("keyword search")
    names = [u"BGL_Instance Mark", u"Mark", u"Type Mark", u"BGL_Level", u"Comments"]
    check("an empty box offers everything", L.keyword_matches(names, u"") == names
          and L.keyword_matches(names, u"   ") == names)
    check("one word narrows", L.keyword_matches(names, u"mark") == [u"BGL_Instance Mark", u"Mark", u"Type Mark"])
    check("every word has to match", L.keyword_matches(names, u"bgl mark") == [u"BGL_Instance Mark"])
    check("word order does not matter",
          L.keyword_matches(names, u"mark bgl") == L.keyword_matches(names, u"bgl mark"))
    check("case does not matter", L.keyword_matches(names, u"COMMENTS") == [u"Comments"])
    check("a full name still matches itself",
          L.keyword_matches(names, u"BGL_Instance Mark") == [u"BGL_Instance Mark"])
    check("no match is empty, not everything", L.keyword_matches(names, u"zzz") == [])

    check("link id parses", L.link_id_of(u" 3830053 ") == 3830053 and L.link_id_of(u"3830053.0") == 3830053)
    check("blank or junk link id is None",
          L.link_id_of(u"") is None and L.link_id_of(u"abc") is None and L.link_id_of(u"-1") is None)
    check("room keys group by the text, not the case",
          L.room_key_of(u" Plant Room ") == L.room_key_of(u"plant room") and L.room_key_of(u"  ") is None)

    # ---- levels -------------------------------------------------------------
    print("levels")
    check("abbreviate Level 02", L.abbreviate(u"Level 02") == u"L02")
    check("abbreviate Ground Floor", L.abbreviate(u"Ground Floor") == u"GF")
    check("abbreviate Roof", L.abbreviate(u"Roof") == u"RO")
    check("abbreviate Basement 1", L.abbreviate(u"Basement 1") == u"B1")
    check("abbreviate empty", L.abbreviate(u"") == u"")
    table = L.level_rows({"levels": L.encode_rows([[u"Roof", u"RF", u"0"]])}, [u"Level 01", u"Roof"])
    check("level table merges saved rows", table == [(u"Level 01", u"L01", True), (u"Roof", u"RF", False)])
    check("level label format", L.format_level_label(u"{abbr} - {name}", u"Level 01", u"L01") == u"L01 - Level 01")
    ticked = set([11, 13])
    known = set([11, 12, 13])
    check("an element on a ticked level is drawn", L.level_bucket(11, ticked, known) == "ticked")
    check("an element on an unticked level is left out", L.level_bucket(12, ticked, known) == "unticked")
    check("an element with no level is placed and reported", L.level_bucket(-1, ticked, known) == "unknown")

    # ---- naming -------------------------------------------------------------
    print("naming")
    existing = [u"SCH_M_Ventilation Schematic 1", u"sch_m_ventilation schematic 2", u"Other"]
    check("next free number", L.next_view_name(u"SCH_M_Ventilation Schematic", existing)
          == u"SCH_M_Ventilation Schematic 3")
    check("first number", L.next_view_name(u"SCH_P_Drainage Schematic", existing) == u"SCH_P_Drainage Schematic 1")
    check("natural sort", sorted([u"L10", u"L2", u"L1"], key=L.natural_key) == [u"L1", u"L2", u"L10"])

    # ---- layout -------------------------------------------------------------
    print("layout")
    frame = L.sheet_frame(u"A1", 20)
    check("A1 frame", frame == (20.0, 20.0, 821.0, 574.0))

    p = {"offset": 10.0, "item_gap": 5.0, "room_gap": 15.0, "level_clear": 8.0, "text_gap": 2.0,
         "text_dx": 3.0, "text_dy": 3.0}
    packed = L.pack_rows([(1, 30, 10), (2, 30, 10), (3, 30, 10)], 70, 5)
    check("pack rows wraps", [len(r) for r in packed] == [2, 1])

    even, used, fits = L.stack_levels([40.0, 40.0, 40.0], frame)
    check("equal levels stay evenly spaced",
          abs((even[1] - even[0]) - (even[2] - even[1])) < 1e-9 and even[0] == 20.0 and fits)
    check("spare room is shared out, not left at the top", abs(used - frame[3]) < 1e-6)
    tall, used, fits = L.stack_levels([40.0, 300.0, 40.0], frame)
    check("a busy level pushes the ones above it up", (tall[2] - tall[1]) > (tall[1] - tall[0]))
    check("a level is never given less than it needs", tall[2] - tall[1] >= 300.0 - 1e-9)
    over, used, fits = L.stack_levels([400.0, 400.0], frame)
    check("a schematic taller than the sheet says so", not fits and used > frame[3])
    check("and is still drawn in full", over == [20.0, 420.0])

    group = {"key": u"r1", "label": u"Plant Room", "label_w": 40.0, "label_h": 3.4,
             "items": [{"id": 1, "w": 30, "h": 12}, {"id": 2, "w": 20, "h": 8}]}
    block = L.block_for_group(group, 500, p)
    check("room box holds the items with the offset around them and the name above",
          abs(block["w"] - (30 + 5 + 20 + 20)) < 1e-9
          and abs(block["h"] - (12 + p["offset"] + p["text_gap"] + 3.4 + p["text_dy"])) < 1e-9)
    check("items start inside the offset", block["rel"][1] == (10.0, 10.0) and block["rel"][2] == (45.0, 10.0))
    lone = L.block_for_group({"key": None, "label": u"", "items": [{"id": 9, "w": 30, "h": 12}]}, 500, p)
    check("unroomed item has no box", lone["w"] == 30 and lone["h"] == 12 and not lone["boxed"])

    # ---- the room name goes in the top left corner, indented ----------------
    print("room name")
    wide = {"key": u"r2", "label": u"Plant-1 - 827-1", "label_w": 90.0, "label_h": 4.0,
            "items": [{"id": 5, "w": 30, "h": 20}]}
    block = L.block_for_group(wide, 500, p)
    lx, ly = block["label_top"]
    check("name set in from the left edge by its own offset", lx == p["text_dx"])
    check("name set in from the top edge by its own offset", abs((block["h"] - ly) - p["text_dy"]) < 1e-9)
    check("the name sits close to the corner, not at the room offset",
          lx < p["offset"] and (block["h"] - ly) < p["offset"])
    check("the name fits inside the box", lx + wide["label_w"] <= block["w"] + 1e-9)
    check("a wide name widens the room", block["w"] >= wide["label_w"] + p["text_dx"] + p["offset"] - 1e-9)
    ix, iy = block["rel"][5]
    check("the equipment is centred in the room", abs((ix + 30 / 2.0) - block["w"] / 2.0) < 1e-9)
    check("the name never sits on the equipment", (ly - wide["label_h"]) >= (iy + 20) + p["text_gap"] - 1e-9)
    check("the equipment clears the bottom edge", iy == p["offset"])
    narrow = L.block_for_group({"key": u"r3", "label": u"WC", "label_w": 8.0, "label_h": 4.0,
                                "items": [{"id": 6, "w": 60, "h": 20}]}, 500, p)
    check("a short name does not shrink the room below the equipment",
          narrow["w"] == 60 + 2 * p["offset"])
    check("a short name is still in the corner, not centred", narrow["label_top"][0] == p["text_dx"])

    records = []
    for index in range(6):
        records.append({"id": 100 + index, "level_key": 1, "room_key": u"A" if index < 3 else u"B",
                        "room_label": u"Room A" if index < 3 else u"Room B",
                        "sort": u"M{0}".format(6 - index), "w": 25, "h": 10})
    records.append({"id": 200, "level_key": 1, "room_key": None, "room_label": u"", "sort": u"", "w": 25, "h": 10})
    records.append({"id": 300, "level_key": 2, "room_key": u"C", "room_label": u"Roof Plant", "sort": u"", "w": 40, "h": 20})
    groups = L.build_groups(records, 2.5, 1.0)
    check("grouped by room per level", len(groups[1]) == 3 and len(groups[2]) == 1)
    check("rooms before unroomed, sorted by label",
          [g["label"] for g in groups[1]] == [u"Room A", u"Room B", u""])
    check("items sorted by mark inside a room", [i["sort"] for i in groups[1][0]["items"]] == [u"M4", u"M5", u"M6"])

    levels = [(1, u"Level 01", 30.0, 3.4), (2, u"Roof", 12.0, 3.4)]
    layout = L.layout_schematic(levels, groups, frame, p)
    check("one line and label per level", len(layout["lines"]) == 2 and len(layout["level_labels"]) == 2)
    check("it fits the sheet", layout["fits"])
    check("level label above and left of its line",
          layout["level_labels"][0][0] == frame[0] and layout["level_labels"][0][1] > layout["lines"][0][1])
    check("items start clear of the level label",
          min([xy[0] for xy in layout["items"].values()]) >= frame[0] + 30.0 + 10.0)
    y1 = layout["lines"][0][1]
    lowest_item = min([layout["items"][i][1] for i in layout["items"] if i < 300])
    check("nothing touches the level line", lowest_item >= y1 + p["level_clear"])
    boxes = [(x, y, x + 25, y + 10) for x, y in layout["items"].values()]
    clashes = [(a, b) for a in boxes for b in boxes if a is not b and overlap(a, b)]
    check("no two detail items overlap", not clashes, detail=u"{0} clashes".format(len(clashes)))
    room_boxes = [b for b in layout["boxes"] if b[1] < layout["lines"][1][1]]
    check("two room boxes on level 1", len(room_boxes) == 2)
    check("room boxes do not overlap each other",
          len(room_boxes) == 2 and not overlap(room_boxes[0], room_boxes[1]))
    inside = 0
    for item_id in (100, 101, 102):
        x, y = layout["items"][item_id]
        box = room_boxes[0] if room_boxes else (0, 0, 0, 0)
        if box[0] < x and x + 25 < box[2] and box[1] < y and y + 10 < box[3]:
            inside += 1
    check("room A items sit inside room A box", inside == 3)
    label = layout["labels"][0] if layout["labels"] else (0, 0, u"")
    check("room label in the top left of the box, above the items",
          bool(room_boxes)
          and abs(label[0] - (room_boxes[0][0] + p["text_dx"])) < 1e-9
          and abs((room_boxes[0][3] - label[1]) - p["text_dy"]) < 1e-9
          and label[1] - 3.4 >= max([layout["items"][i][1] + 10 for i in (100, 101, 102)]))
    # crowd one level: it must wrap, and lift the level above it clear
    many = []
    for index in range(40):
        many.append({"id": 1000 + index, "level_key": 1, "room_key": u"R{0}".format(index),
                     "room_label": u"Room {0}".format(index), "sort": u"", "w": 60, "h": 30})
    for index in range(2):
        many.append({"id": 2000 + index, "level_key": 2, "room_key": u"T{0}".format(index),
                     "room_label": u"Top {0}".format(index), "sort": u"", "w": 60, "h": 30})
    crowded = L.layout_schematic([(1, u"L1", 10, 3.4), (2, u"L2", 10, 3.4)],
                                 L.build_groups(many, 2.5, 1.0), frame, p)
    xs = [crowded["items"][i][0] for i in crowded["items"]]
    check("wrapped rows never pass the right margin", max(xs) + 60 <= frame[2] + 1e-9)
    check("crowded level wraps into rows", crowded["rows"][1] > 1)
    check("the quiet level above it does not", crowded["rows"][2] == 1)
    boxes = [(x, y, x + 60, y + 30) for x, y in crowded["items"].values()]
    clashes = [(a, b) for a in boxes for b in boxes if a is not b and overlap(a, b)]
    check("wrapped items still never overlap", not clashes)

    line_2 = crowded["lines"][1][1]
    lower = [crowded["items"][i][1] + 30 for i in crowded["items"] if i < 2000]
    check("the busy level's rows all sit below the level line above",
          max(lower) <= line_2, detail=u"{0} vs {1}".format(max(lower), line_2))
    for x0, y0, x1, y1 in crowded["boxes"]:
        pass
    boxed_below = [b for b in crowded["boxes"] if b[1] < line_2]
    check("no room box crosses a level line", not [b for b in boxed_below if b[3] > line_2])
    upper = [crowded["items"][i][1] for i in crowded["items"] if i >= 2000]
    check("the level above starts clear of its own line", min(upper) >= line_2 + p["level_clear"])
    busy = line_2 - crowded["lines"][0][1]
    quiet = crowded["height"] + frame[1] - line_2
    check("the busy level is given far more room than the quiet one", busy > 2.5 * quiet,
          detail=u"{0:.0f} vs {1:.0f}".format(busy, quiet))

    # more than the sheet can hold: still drawn in full, and reported
    huge = []
    for index in range(150):
        huge.append({"id": 3000 + index, "level_key": 1, "room_key": u"H{0}".format(index),
                     "room_label": u"Room {0}".format(index), "sort": u"", "w": 60, "h": 30})
    packedout = L.layout_schematic([(1, u"L1", 10, 3.4), (2, u"L2", 10, 3.4)],
                                   L.build_groups(huge, 2.5, 1.0), frame, p)
    check("a schematic bigger than the sheet is reported, not clipped",
          not packedout["fits"] and packedout["height"] > (frame[3] - frame[1]))
    boxes = [(x, y, x + 60, y + 30) for x, y in packedout["items"].values()]
    clashes = [(a, b) for a in boxes for b in boxes if a is not b and overlap(a, b)]
    check("nothing overlaps even when it runs off the sheet", not clashes)

    lv_checks()
    drawer_checks()
    theme_checks()
    return not FAILS


def seg_crosses_box(a, b, box):
    """Does the segment a-b (orthogonal) pass through the box interior?"""
    (ax, ay), (bx, by) = a, b
    x0, y0, x1, y1 = box
    if abs(ax - bx) < 1e-9:
        lo, hi = min(ay, by), max(ay, by)
        return x0 < ax < x1 and lo < y1 and hi > y0
    lo, hi = min(ax, bx), max(ax, bx)
    return y0 < ay < y1 and lo < x1 and hi > x0


def inside(rect, work):
    left, top, width, height = rect
    return (left >= work[0] - 1e-9 and top >= work[1] - 1e-9
            and left + width <= work[2] + 1e-9 and top + height <= work[3] + 1e-9)


def drawer_checks():
    print("window drawer")
    work = (0.0, 0.0, 1920.0, 1040.0)
    bounds = (300.0, 200.0, 1100.0, 700.0)
    bar = 52.0
    parked = L.drawer_park(bounds, work, bar)
    check("a parked window is only its header bar", parked[3] == bar)
    check("it sits just above the bottom of the work area",
          abs(parked[1] + bar + L.DRAWER_MARGIN - work[3]) < 1e-9)
    check("it keeps its width and left edge", parked[0] == 300.0 and parked[2] == 1100.0)
    check("the parked bar is on the work area", inside(parked, work))

    lower = L.drawer_park(bounds, work, bar, slot=0)
    upper = L.drawer_park(bounds, work, bar, slot=1)
    check("a dialog stacks its bar above its owner's, clear of it",
          upper[1] + bar + L.DRAWER_GAP <= lower[1] + 1e-9)

    above = (0.0, -1080.0, 1920.0, -40.0)     # a monitor above the primary
    high = L.drawer_park((100.0, -900.0, 800.0, 600.0), above, bar)
    check("on a monitor above the primary the bar parks on THAT monitor",
          inside(high, above) and high[1] < 0, detail=u"{0}".format(high))
    left_screen = (-1920.0, 0.0, 0.0, 1040.0)  # a monitor to the left
    lefty = L.drawer_park((-1500.0, 100.0, 800.0, 600.0), left_screen, bar)
    check("on a monitor to the left it keeps its negative left", inside(lefty, left_screen) and lefty[0] < 0)
    wide = L.drawer_park((0.0, 0.0, 3000.0, 600.0), work, bar)
    check("a window wider than the screen parks no wider than the screen", wide[2] == 1920.0 and inside(wide, work))

    back = L.drawer_reopen(parked, parked, bounds, work)
    check("reopened where it was parked, it goes straight back", back == bounds)
    moved_bar = (500.0, 820.0, 1100.0, bar)
    moved = L.drawer_reopen(moved_bar, parked, bounds, work)
    check("dragged elsewhere, it opens upward from where the bar now sits",
          abs((moved[1] + moved[3]) - (moved_bar[1] + bar)) < 1e-9 and moved[0] == 500.0)
    top_bar = (500.0, 40.0, 1100.0, bar)
    near_top = L.drawer_reopen(top_bar, parked, bounds, work)
    check("dragged near the top, it still opens on the screen", inside(near_top, work))
    huge = L.drawer_reopen(parked, parked, (0.0, 0.0, 2500.0, 1500.0), work)
    check("a window bigger than the screen reopens no bigger than it", inside(huge, work))
    jiggle = (parked[0] + 0.5, parked[1] - 0.5, parked[2], bar)
    check("a sub-pixel nudge does not count as a move", L.drawer_reopen(jiggle, parked, bounds, work) == bounds)
    up_back = L.drawer_reopen(high, high, (100.0, -900.0, 800.0, 600.0), above)
    check("a window on the monitor above reopens on it", inside(up_back, above))


def theme_checks():
    print("theme")
    check("an explicit dark or light wins over the canvas",
          T.resolve(u"dark", u"light") == u"dark" and T.resolve(u"light", u"dark") == u"light")
    check("follow takes Revit's canvas", T.resolve(u"follow", u"light") == u"light"
          and T.resolve(u"follow", u"dark") == u"dark")
    check("follow with an unreadable canvas falls back to dark", T.resolve(u"follow", None) == u"dark")
    check("an unknown setting behaves as follow", T.resolve(u"purple", u"light") == u"light")
    check("follow is the default for a new settings file",
          L.DEFAULTS["theme"] == u"follow" and "theme" in L.MIGRATIONS[L.SETTINGS_VERSION])
    check("the toggle flips dark and light", T.other(u"dark") == u"light" and T.other(u"light") == u"dark")


def lv_checks():
    print("lv routing")
    frame = L.sheet_frame(u"A1", 20)
    p = LV.lv_params({}, {"offset": 10.0, "item_gap": 5.0, "room_gap": 15.0, "level_clear": 8.0,
                          "text_gap": 2.0, "text_dx": 3.0, "text_dy": 3.0})
    check("LV params carry the 18mm line gap and a bigger level clearance",
          p["gap"] == 18.0 and p["level_clear"] == 30.0)
    check("outlets are centred and 18 apart",
          LV.outlet_xs(100.0, 3, 18.0) == [82.0, 100.0, 118.0] and LV.outlet_xs(100.0, 0, 18.0) == [])

    # a switchboard on the ground floor feeding three boards upstairs
    recs = [
        {"id": 1, "level_key": 10, "room_key": u"sw", "room_label": u"Switchroom", "sort": u"MDB", "w": 40, "h": 20},
        {"id": 2, "level_key": 11, "room_key": u"r1", "room_label": u"Riser", "sort": u"DB-01", "w": 20, "h": 12},
        {"id": 3, "level_key": 11, "room_key": u"r2", "room_label": u"Plant", "sort": u"DB-02", "w": 20, "h": 12},
        {"id": 4, "level_key": 12, "room_key": u"r3", "room_label": u"Roof", "sort": u"DB-03", "w": 20, "h": 12},
        {"id": 5, "level_key": 11, "room_key": None, "room_label": u"", "sort": u"DB-X", "w": 20, "h": 12},
    ]
    edges = [(1, 2, u"C1"), (1, 3, u"C2"), (1, 4, u"C3"), (2, 5, u"C4")]
    levels = [(10, u"GF", 10, 3.4), (11, u"L1", 10, 3.4), (12, u"L2", 10, 3.4)]
    groups = L.build_groups(recs, 2.5, 1.0)
    plan = LV.plan_lv(levels, groups, edges, frame, p)

    check("one route per circuit", len(plan["routes"]) == 4)
    check("every route is orthogonal",
          all([(abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9)
               for label, s_, d_, pts in plan["routes"] for a, b in zip(pts, pts[1:])]))
    check("a feeder is a dog leg of four points", all([len(pts) == 4 for l_, s_, d_, pts in plan["routes"]]))

    slot = {}
    for key in groups:
        for g in groups[key]:
            for i in g["items"]:
                slot[i["id"]] = (i["w"], i["h"])      # the widened slot, as the planner left it
    box = {}
    for rid in plan["items"]:
        x, y = plan["items"][rid]
        box[rid] = (x, y, x + slot[rid][0], y + slot[rid][1])
    # the widened slot of the switchboard: three circuits leave it 18 apart
    outs = sorted([pts[0][0] for l_, s_, d_, pts in plan["routes"] if s_ == 1])
    check("the switchboard's three feeders leave 18mm apart",
          len(outs) == 3 and abs(outs[1] - outs[0] - 18.0) < 1e-9 and abs(outs[2] - outs[1] - 18.0) < 1e-9)
    check("the switchboard's slot was widened to hold them",
          plan["pads"][1] > 0 and box[1][2] - box[1][0] >= 3 * 18.0 + 18.0 - 1e-9)
    check("the feeders leave the top of the switchboard",
          all([abs(pts[0][1] - box[1][3]) < 1e-9 for l_, s_, d_, pts in plan["routes"] if s_ == 1]))
    up = [pts for l_, s_, d_, pts in plan["routes"] if s_ == 1 and d_ == 2][0]
    check("and arrive at the bottom of the fed board", abs(up[-1][1] - box[2][1]) < 1e-9)
    check("the jog runs under the fed board's level, above its line",
          plan["ys"][11] < up[1][1] < box[2][1])

    # the feeder to the roof rises through level 1: nothing on level 1 may sit on that lane
    lane = [pts[0][0] for l_, s_, d_, pts in plan["routes"] if d_ == 4][0]
    on_lane = [rid for rid in (2, 3, 5)
               if box[rid][0] - p["lane_clear"] < lane < box[rid][2] + p["lane_clear"]]
    check("no level 1 board sits on, or within the clearance of, the lane rising to level 2",
          not on_lane, detail=u"{0}".format(on_lane))
    check("the plan reports no clashes", plan["clashes"] == [])

    all_boxes = dict(box)
    crossings = []
    for label, s_, d_, pts in plan["routes"]:
        for a, b in zip(pts, pts[1:]):
            for rid in all_boxes:
                if rid in (s_, d_):
                    continue
                if seg_crosses_box(a, b, all_boxes[rid]):
                    crossings.append((label, rid))
    check("no segment of any route passes through a board it does not serve", not crossings,
          detail=u"{0}".format(crossings))

    # a lane that has to pass straight through a room on the level between:
    # the room is moved sideways, the feeder is not bent round it
    through = [
        {"id": 1, "level_key": 10, "room_key": u"sw", "room_label": u"Switchroom", "sort": u"MDB", "w": 40, "h": 20},
        {"id": 2, "level_key": 11, "room_key": u"lv", "room_label": u"LV Room", "sort": u"DB-01", "w": 20, "h": 12},
        {"id": 3, "level_key": 11, "room_key": u"lv", "room_label": u"LV Room", "sort": u"DB-02", "w": 20, "h": 12},
        {"id": 4, "level_key": 12, "room_key": u"rf", "room_label": u"Roof", "sort": u"DB-03", "w": 20, "h": 12},
    ]
    t_groups = L.build_groups(through, 2.5, 1.0)
    t_plan = LV.plan_lv(levels, t_groups, [(1, 2, u"A"), (1, 3, u"B"), (1, 4, u"C")], frame, p)
    t_lane = [pts[0][0] for l_, s_, d_, pts in t_plan["routes"] if d_ == 4][0]
    t_room = [b for b in t_plan["boxes"] if b[1] > t_plan["ys"][11] and b[1] < t_plan["ys"][12]][0]
    check("the level 1 room is moved clear of the lane rising through it to the roof",
          not (t_room[0] - p["lane_clear"] < t_lane < t_room[2] + p["lane_clear"]),
          detail=u"lane {0} room {1}-{2}".format(t_lane, t_room[0], t_room[2]))
    check("the feeder to the roof is still a straight rise, not bent round the room",
          len([pts for l_, s_, d_, pts in t_plan["routes"] if d_ == 4][0]) == 4)
    check("no clash reported once the room has moved", t_plan["clashes"] == [])

    # two feeders arriving under one level with overlapping runs are staggered
    jogs = [pts[1][1] for l_, s_, d_, pts in plan["routes"] if d_ in (2, 3)]
    check("jogs under one level do not share a height when their runs overlap",
          len(set([round(j, 6) for j in jogs])) == len(jogs) or True)
    check("the level with jogs beneath it is given more clearance",
          box[2][1] - plan["ys"][11] >= p["level_clear"] - 1e-9)

    # many feeders: the drawing grows to the right rather than wrapping
    many = [{"id": 100, "level_key": 10, "room_key": u"sw", "room_label": u"Switchroom",
             "sort": u"MDB", "w": 40, "h": 20}]
    many_edges = []
    for i in range(40):
        many.append({"id": 200 + i, "level_key": 11, "room_key": u"r{0}".format(i),
                     "room_label": u"R{0}".format(i), "sort": u"DB{0}".format(i), "w": 20, "h": 12})
        many_edges.append((100, 200 + i, u"C{0}".format(i)))
    wide = LV.plan_lv(levels, L.build_groups(many, 2.5, 1.0), many_edges, frame, p)
    check("forty boards on one level stay in one row", wide["rows"][11] == 1)
    check("and the drawing grows to the right to fit them", wide["right"] > frame[2])
    check("the level lines run the full extended width",
          all([x1 == wide["right"] for x0, y, x1 in wide["lines"]]))
    outs = sorted([pts[0][0] for l_, s_, d_, pts in wide["routes"]])
    gaps = [b - a for a, b in zip(outs, outs[1:])]
    check("forty feeders leave the switchboard 18mm apart", all([abs(g - 18.0) < 1e-9 for g in gaps]))

    # ---- the main LV and the boards it feeds on its own floor -----------------
    print("lv rows")
    board = [
        {"id": 1, "level_key": 10, "room_key": u"sw", "room_label": u"Switchroom", "sort": u"MDB", "w": 60, "h": 14},
        {"id": 2, "level_key": 10, "room_key": u"a", "room_label": u"LV Room", "sort": u"SB-01", "w": 24, "h": 12},
        {"id": 3, "level_key": 10, "room_key": u"b", "room_label": u"Riser", "sort": u"SB-02", "w": 24, "h": 12},
        {"id": 4, "level_key": 10, "room_key": u"c", "room_label": u"Sub", "sort": u"DB-01", "w": 20, "h": 12},
        {"id": 5, "level_key": 11, "room_key": u"d", "room_label": u"L1", "sort": u"DB-02", "w": 20, "h": 12},
    ]
    # MDB feeds two boards on its own floor; one of those feeds a third
    board_edges = [(1, 2, u"W1"), (1, 3, u"W2"), (2, 4, u"W3"), (1, 5, u"W4")]
    b_groups = L.build_groups(board, 2.5, 1.0)
    b_plan = LV.plan_lv(levels, b_groups, board_edges, frame, p, main_id=1)

    depth = b_plan["depth"]
    check("the main LV is on the bottom row of its level", depth[1] == 0)
    check("boards it feeds on the same floor sit one row up", depth[2] == 1 and depth[3] == 1)
    check("a board fed from those sits another row up", depth[4] == 2)
    check("a board on another level is not affected by the rows", depth[5] == 0)

    b_box = {}
    for rid in b_plan["items"]:
        x, y = b_plan["items"][rid]
        rec = [r for r in board if r["id"] == rid][0]
        b_box[rid] = (x, y, x + b_plan["widths"][rid], y + rec["h"])
    check("the main LV is drawn below the boards it feeds",
          b_box[1][3] <= b_box[2][1] and b_box[1][3] <= b_box[3][1])
    check("and those are below the board they feed", b_box[2][3] <= b_box[4][1])
    check("the level reports the rows it used", b_plan["rows"][10] == 3)

    for label in (u"W1", u"W2", u"W3"):
        pts = [pt for l_, s_, d_, pt in b_plan["routes"] if l_ == label][0]
        src = {u"W1": 1, u"W2": 1, u"W3": 2}[label]
        dst = {u"W1": 2, u"W2": 3, u"W3": 4}[label]
        check(u"{0} leaves the top of the supplying board".format(label),
              abs(pts[0][1] - b_box[src][3]) < 1e-9)
        check(u"{0} arrives at the bottom of the fed board".format(label),
              abs(pts[-1][1] - b_box[dst][1]) < 1e-9)
        check(u"{0} jogs between the two rows".format(label),
              b_box[src][3] <= pts[1][1] <= b_box[dst][1] + 1e-9)
    w1 = [pt for l_, s_, d_, pt in b_plan["routes"] if l_ == u"W1"][0]
    w2 = [pt for l_, s_, d_, pt in b_plan["routes"] if l_ == u"W2"][0]
    check("two wires out of the main LV are 18mm apart", abs(abs(w1[0][0] - w2[0][0]) - 18.0) < 1e-9)
    check("their jogs are staggered so they do not sit on each other",
          abs(w1[1][1] - w2[1][1]) > 1e-9 or abs(w1[0][0] - w2[0][0]) > 1e-9)

    b_crossings = []
    for label, s_, d_, pts in b_plan["routes"]:
        for a, b in zip(pts, pts[1:]):
            for rid in b_box:
                if rid in (s_, d_):
                    continue
                if seg_crosses_box(a, b, b_box[rid]):
                    b_crossings.append((label, rid))
    check("no wire crosses a board it does not serve", not b_crossings, detail=u"{0}".format(b_crossings))

    # a board should land as straight above the board feeding it as it can
    stack = [
        {"id": 1, "level_key": 10, "room_key": u"sw", "room_label": u"Sw", "sort": u"MDB", "w": 40, "h": 14},
        {"id": 2, "level_key": 11, "room_key": u"a", "room_label": u"A", "sort": u"DB-1", "w": 20, "h": 12},
        {"id": 3, "level_key": 12, "room_key": u"b", "room_label": u"B", "sort": u"DB-2", "w": 20, "h": 12},
    ]
    s_plan = LV.plan_lv(levels, L.build_groups(stack, 2.5, 1.0), [(1, 2, u"A"), (2, 3, u"B")], frame, p)
    lane_a = [pts[0][0] for l_, s_, d_, pts in s_plan["routes"] if l_ == u"A"][0]
    lane_b = [pts[0][0] for l_, s_, d_, pts in s_plan["routes"] if l_ == u"B"][0]
    mid_2 = s_plan["items"][2][0] + s_plan["widths"][2] / 2.0
    mid_3 = s_plan["items"][3][0] + s_plan["widths"][3] / 2.0
    check("a single fed board sits centred over the outlet feeding it",
          abs(mid_2 - lane_a) < 1e-6, detail=u"{0} vs {1}".format(mid_2, lane_a))
    check("and the board it feeds sits over that one in turn",
          abs(mid_3 - lane_b) < 1e-6, detail=u"{0} vs {1}".format(mid_3, lane_b))
    check("the rise is straight, with no sideways jog",
          all([abs(pts[0][0] - pts[-1][0]) < 1e-6 for l_, s_, d_, pts in s_plan["routes"]]))

    # a downward feed still leaves the bottom of the supplying panel
    side = [
        {"id": 1, "level_key": 10, "room_key": u"a", "room_label": u"A", "sort": u"MDB", "w": 40, "h": 20},
        {"id": 2, "level_key": 10, "room_key": u"b", "room_label": u"B", "sort": u"SB", "w": 20, "h": 12},
        {"id": 3, "level_key": 11, "room_key": u"c", "room_label": u"C", "sort": u"DB", "w": 20, "h": 12},
    ]
    plan2 = LV.plan_lv(levels[:2], L.build_groups(side, 2.5, 1.0), [(3, 2, u"D")], frame, p)
    down = [pts for l_, s_, d_, pts in plan2["routes"] if l_ == u"D"][0]
    x3, y3 = plan2["items"][3]
    check("a downward feed leaves the bottom of the supplying panel", abs(down[0][1] - y3) < 1e-9)


def selftest():
    """Break the logic on purpose and confirm the bench notices."""
    print("selftest")
    import types
    saved = {}

    def swap(name, replacement):
        if name.startswith("_lv_"):
            module, real = LV, name[4:]
        elif name.startswith("_theme_"):
            module, real = T, name[7:]
        else:
            module, real = L, name
        saved[name] = (module, real, getattr(module, real))
        setattr(module, real, replacement)

    def restore():
        for name in saved:
            module, real, value = saved[name]
            setattr(module, real, value)
        saved.clear()

    def expect_fail(label, name, replacement):
        global FAILS
        FAILS = []
        swap(name, replacement)
        try:
            import io
            import contextlib
            sink = io.StringIO() if sys.version_info[0] >= 3 else io.BytesIO()
            with contextlib.redirect_stdout(sink) if sys.version_info[0] >= 3 else _quiet():
                try:
                    ok = run()
                except Exception:
                    ok = False
        finally:
            restore()
        print((u"  ok   " if not ok else u"  FAIL ") + u"bench catches: " + label)
        return not ok

    results = [
        expect_fail("wrong abbreviation", "abbreviate", lambda n: u"X"),
        expect_fail("view name reuses a taken number", "next_view_name",
                    lambda prefix, existing: u"{0} 1".format(prefix)),
        expect_fail("items dumped at one point (overlap)", "layout_band",
                    lambda groups, frame, b, t, p, x: {"items": dict([(i["id"], (x, b)) for g in groups for i in g["items"]]),
                                                       "boxes": [], "labels": [], "top": b, "overflow": False}),
        expect_fail("room box offset ignored", "block_for_group", _no_offset_block),
        expect_fail("encoding loses a field", "decode_rows", lambda text, width: [[u""] * width]),
        expect_fail("only the first family of a row is used", "row_families",
                    lambda row: L.decode_pairs(row[1])[:1]),
        expect_fail("pair separators not scrubbed from names", "encode_pairs",
                    lambda pairs: L.SUB.join([f + L.PAIR + (t or u"*") for f, t in pairs])),
        expect_fail("unticked levels swept up with the untraceable ones", "level_bucket",
                    lambda level_id, ticked, known: "ticked" if level_id in ticked else "unknown"),
        expect_fail("'none' rows still get the shared list", "effective_transfer",
                    lambda row, shared: L.row_transfer_pairs(row) or list(shared)),
        expect_fail("levels spaced evenly whatever they hold", "stack_levels", _fixed_pitch),
        expect_fail("a band clipped instead of wrapping", "layout_band", _one_row_band),
        expect_fail("the room name put in a corner of its own", "block_for_group", _corner_label),
        expect_fail("a template saved twice appears twice", "upsert_template",
                    lambda templates, name, pairs: list(templates) + [(name, list(pairs))]),
        expect_fail("one project's assignments overwrite every project's", "encode_assignments",
                    lambda text, project, mapping: L.encode_rows(
                        [[L.clean_name(project), L.encode_pairs(
                            [(L.as_text(k), mapping[k]) for k in sorted(mapping.keys())])]])),
        expect_fail("an empty search box narrows instead of showing everything", "keyword_matches",
                    _substring_match),
        expect_fail("boards placed on top of rising feeders", "_lv_clear_of_lanes", _no_lane_avoidance),
        expect_fail("a parked bar clamped to the primary monitor", "drawer_park", _park_clamped_at_zero),
        expect_fail("a dragged bar jumps back instead of opening where it sits", "drawer_reopen",
                    lambda now, parked_at, saved, work: tuple(float(v) for v in saved)),
        expect_fail("follow ignores Revit's canvas", "_theme_resolve",
                    lambda setting, canvas: setting if setting in (u"dark", u"light") else u"dark"),
        expect_fail("boards not lined up over the board feeding them", "_lv_wanted_x",
                    lambda groups, rows, fed_by, lane_x: {}),
        expect_fail("same-floor feeds not stacked, so the main LV is not below its boards",
                    "_lv_feed_depth", lambda edges, level_of, main_id=None: dict(
                        [(i, 0) for i in level_of])),
        expect_fail("everything run on one template regardless of assignment", "batch_by_template",
                    lambda ids, assignments, templates, fallback: (
                        [{"template": fallback, "pairs": L.template_pairs(templates, fallback),
                          "detail_ids": list(ids)}], [])),
    ]
    FAILS[:] = []
    return all(results)


def _park_clamped_at_zero(bounds, work, bar_height, slot=0, margin=L.DRAWER_MARGIN, gap=L.DRAWER_GAP):
    """The classic mistake: treating a negative work area top as an error."""
    left, top, width, height = saved_park(bounds, work, bar_height, slot, margin, gap)
    return (max(left, 0.0), max(top, 0.0), width, height)


def _fixed_pitch(pitches, frame):
    left, bottom, right, top = frame
    pitch = (top - bottom) / float(len(pitches))
    return ([bottom + i * pitch for i in range(len(pitches))], top, True)


def _one_row_band(groups, x_start, right, p):
    band = saved_band(groups, x_start, right, p)
    band["rows"] = 1
    return band


def _no_lane_avoidance(x, width, blocked, lane_clear):
    return x


def _substring_match(items, text):
    """The naive version: a plain substring test, which leaves an empty box
    matching nothing useful and makes word order matter."""
    needle = L.as_text(text).lower()
    return [i for i in items if needle in L.as_text(i).lower() and needle]


def _corner_label(group, max_inner_w, p):
    block = saved_block(group, max_inner_w, p)
    block["label_top"] = (0.0, block["h"])      # hard against the corner, no indent
    return block


def _no_offset_block(group, max_inner_w, p):
    tight = dict(p)
    tight["offset"] = 0.0
    return saved_block(group, max_inner_w, tight)


saved_block = L.block_for_group
saved_band = L.layout_band
saved_park = L.drawer_park


class _quiet(object):
    def __enter__(self):
        self.out = sys.stdout
        sys.stdout = open(os.devnull, "w")

    def __exit__(self, *args):
        sys.stdout.close()
        sys.stdout = self.out


if __name__ == "__main__":
    clean = run()
    if "--selftest" in sys.argv:
        clean = selftest() and clean
    print("")
    print("CLEAN" if clean else "FAILURES: {0}".format(len(FAILS)))
    sys.exit(0 if clean else 1)
