# -*- coding: utf-8 -*-
"""Auto RevCloud - bench tests for settings and reporting, plain CPython.

The comparison rules live in arc_compare.py and are covered by
bench_compare.py. This one covers arc_core: the settings file, the category
list and the report. Run from the pushbutton folder:

    python bench_logic.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import arc_core as C

PASS = [0]
FAIL = []


def check(label, got, want):
    if got == want:
        PASS[0] += 1
    else:
        FAIL.append(u"{0}\n     got  {1}\n     want {2}".format(label, got, want))


def check_true(label, got):
    check(label, bool(got), True)


def check_false(label, got):
    check(label, bool(got), False)


# ==========================================================================
# settings
# ==========================================================================

def test_settings():
    loaded = C.merge_settings({})
    check(u"settings: defaults complete", len(loaded), len(C.DEFAULTS))
    check(u"settings: theme follows Revit by default", loaded[u"theme"], u"auto")

    # move_tol_mm on purpose: a file with no settings_version reads as version
    # 0, so every migrated key is reset and would not prove anything here.
    # settings_version stamped, or the migrations fire and reset the very
    # keys being tested - which is right, and is covered separately below.
    parsed = C.parse_settings_text(
        u"settings_version=7\ntheme=light\nnonsense line\nmove_tol_mm=20\n")
    merged = C.merge_settings(parsed)
    check(u"settings: a good key is kept", merged[u"theme"], u"light")
    check(u"settings: a damaged line does not stop the load",
          merged[u"move_tol_mm"], u"20")
    check(u"settings: a missing key falls back",
          merged[u"offset_mm"], C.DEFAULT_MAP[u"offset_mm"])

    merged = C.merge_settings(C.parse_settings_text(
        u"settings_version=7\ntheme=dark\nfuture=7\n"))
    check(u"settings: an unknown key is ignored", u"future" in merged, False)
    check(u"settings: a known key still loads", merged[u"theme"], u"dark")

    path = os.path.join(tempfile.mkdtemp(prefix=u"arc_bench_"), u"s.txt")
    original = C.merge_settings({})
    original[u"move_tol_mm"] = u"12"
    C.save_settings(original, path)
    check(u"settings: round trip", C.load_settings(path)[u"move_tol_mm"], u"12")
    check(u"settings: a missing file is the defaults, silently",
          C.load_settings(path + u".nope")[u"theme"], u"auto")

    check(u"settings: as_int", C.as_int({u"a": u"150"}, u"a", 0), 150)
    check(u"settings: as_int falls back on rubbish",
          C.as_int({u"a": u"x"}, u"a", 7), 7)
    check_true(u"settings: as_bool on", C.as_bool({u"a": u"1"}, u"a"))
    check_false(u"settings: as_bool off", C.as_bool({u"a": u"0"}, u"a"))

    # the migration that comes with the change of method
    check(u"settings: version 7", C.DEFAULT_MAP[u"settings_version"], u"7")
    old = {u"settings_version": u"3", u"merge_mm": u"5", u"theme": u"light",
           u"max_clouds": u"9"}
    moved = C.merge_settings(old)
    check(u"settings: a distance tuned for the raster method is reset",
          moved[u"merge_mm"], C.DEFAULT_MAP[u"merge_mm"])
    check(u"settings: a theme held under the old two-way chip goes back to auto",
          moved[u"theme"], u"auto")
    check(u"settings: a key no migration touches is kept",
          moved[u"show_results"], C.DEFAULT_MAP[u"show_results"])
    check(u"settings: the tightened tolerances are applied over an old file",
          moved[u"move_tol_mm"], u"1")
    check(u"settings: the id method is the default and is restored",
          moved[u"match_method"], u"id")
    check(u"settings: the raised cloud cap is applied too",
          moved[u"max_clouds"], u"250")

    # ...and a current file is left entirely alone
    current = {u"settings_version": u"7", u"theme": u"light", u"merge_mm": u"20"}
    kept = C.merge_settings(current)
    check(u"settings: a current file keeps its theme", kept[u"theme"], u"light")
    check(u"settings: and its distances", kept[u"merge_mm"], u"20")


# ==========================================================================
# categories
# ==========================================================================

def test_categories():
    for name in (u"Pipes", u"Ducts", u"Cable Trays", u"Mechanical Equipment",
                 u"Electrical Equipment", u"Electrical Fixtures",
                 u"Data Devices", u"Fire Alarm Devices",
                 u"Generic Models", u"Lines", u"Detail Items"):
        check(u"categories: '{0}' is in the default list".format(name),
              name in C.DEFAULT_CATEGORIES, True)

    joined = C.format_categories([u"Pipes", u"Ducts"])
    check(u"categories: joined with pipes", joined, u"Pipes|Ducts")
    check(u"categories: read back", C.parse_categories(joined), [u"Pipes", u"Ducts"])
    check(u"categories: one per line is read too",
          C.parse_categories(u"Pipes\r\nDucts\r\n"), [u"Pipes", u"Ducts"])
    check(u"categories: blanks dropped",
          C.parse_categories(u"Pipes||\n\nDucts"), [u"Pipes", u"Ducts"])
    check(u"categories: duplicates dropped, order kept",
          C.parse_categories(u"Pipes|Ducts|pipes"), [u"Pipes", u"Ducts"])
    check(u"categories: nothing is an empty list", C.parse_categories(u""), [])

    old_default = C.format_categories(C.PREVIOUS_CATEGORY_DEFAULTS[0])
    upgraded = C.merge_settings({u"compare_categories": old_default})
    check(u"categories: an untouched list is brought up to date",
          C.parse_categories(upgraded[u"compare_categories"]),
          C.DEFAULT_CATEGORIES)

    kept = C.merge_settings({u"compare_categories": u"Pipes|Ducts"})
    check(u"categories: a customised list is left alone",
          C.parse_categories(kept[u"compare_categories"]), [u"Pipes", u"Ducts"])

    trimmed = C.PREVIOUS_CATEGORY_DEFAULTS[0][:-1]
    kept = C.merge_settings({u"compare_categories": C.format_categories(trimmed)})
    check(u"categories: the old default minus a name counts as customised",
          C.parse_categories(kept[u"compare_categories"]), trimmed)

    empty = C.merge_settings({u"compare_categories": u""})
    check(u"categories: an empty list falls back to the defaults",
          C.parse_categories(empty[u"compare_categories"]), C.DEFAULT_CATEGORIES)

    text = C.settings_text(C.merge_settings({}))
    back = C.merge_settings(C.parse_settings_text(text))
    check(u"categories: survives the settings file",
          C.parse_categories(back[u"compare_categories"]), C.DEFAULT_CATEGORIES)


# ==========================================================================
# names and reporting
# ==========================================================================

def test_category_templates():
    """Saved category selections, in their own file."""
    text = u"Drainage=Pipes|Pipe Fittings\nContainment=Cable Trays|Conduits\n"
    templates = C.parse_templates(text)
    check(u"templates: both read", [n for n, _v in templates],
          [u"Drainage", u"Containment"])
    check(u"templates: the values come back",
          C.template_named(templates, u"Drainage"), [u"Pipes", u"Pipe Fittings"])
    check(u"templates: looked up whatever the case",
          C.template_named(templates, u"drainage"), [u"Pipes", u"Pipe Fittings"])
    check(u"templates: an unknown name is None",
          C.template_named(templates, u"Nope"), None)

    # a name with an = in it round trips, which is why this is its own file
    odd = C.parse_templates(u"Level 00 = ground=Pipes|Ducts\n")
    check(u"templates: a name containing '=' keeps everything before the first",
          [n for n, _v in odd], [u"Level 00 = ground".partition(u"=")[0].strip()])

    # rubbish lines are skipped rather than breaking the load
    messy = C.parse_templates(u"# a comment\n\nnonsense\nGood=Pipes\n")
    check(u"templates: only the good line survives",
          [n for n, _v in messy], [u"Good"])

    # a template with no categories is not a template
    check(u"templates: an empty one is dropped",
          C.parse_templates(u"Empty=\n"), [])

    # add, replace and delete
    templates = C.put_template(templates, u"Drainage", [u"Pipes"])
    check(u"templates: replacing keeps its place",
          [n for n, _v in templates], [u"Drainage", u"Containment"])
    check(u"templates: and takes the new values",
          C.template_named(templates, u"Drainage"), [u"Pipes"])

    templates = C.put_template(templates, u"Electrical", [u"Cable Trays"])
    check(u"templates: a new one goes on the end",
          [n for n, _v in templates],
          [u"Drainage", u"Containment", u"Electrical"])

    templates = C.drop_template(templates, u"containment")
    check(u"templates: deleting is case-insensitive",
          [n for n, _v in templates], [u"Drainage", u"Electrical"])

    # a nameless template is refused rather than saved as blank
    check(u"templates: a blank name is refused",
          C.put_template(templates, u"  ", [u"Pipes"]), templates)

    # full round trip through the file format
    back = C.parse_templates(C.format_templates(templates))
    check(u"templates: round trip", back, templates)

    # a missing file is no templates, silently
    check(u"templates: a missing file is empty",
          C.load_templates(u"/nonexistent/nope.txt"), [])


def test_natural_key():
    names = [u"M-10", u"M-2", u"M-1", u"E-2"]
    check(u"natural: numeric order, not alphabetical",
          sorted(names, key=C.natural_key), [u"E-2", u"M-1", u"M-2", u"M-10"])


def test_describe_exception():
    check(u"describe: type and message",
          C.describe_exception(ValueError(u"bad input")), u"ValueError: bad input")
    check(u"describe: a message-less exception still names its type",
          C.describe_exception(ValueError()), u"ValueError")


def test_collapse():
    check(u"collapse: repeats fold with a count",
          C.collapse([u"a", u"a", u"a"]), [u"a  (x3)"])
    check(u"collapse: a single line is untouched", C.collapse([u"a"]), [u"a"])
    check(u"collapse: order is kept and only repeats are counted",
          C.collapse([u"b", u"a", u"b"]), [u"b  (x2)", u"a"])
    check(u"collapse: nothing in, nothing out", C.collapse([]), [])


def test_summarise():
    clean = [{u"number": u"M-101 - Level 00", u"against": u"Previous.rvt",
              u"clouds": 3, u"notes": [], u"info": [], u"error": None}]
    needed, text = C.summarise(clean)
    check_false(u"summary: a clean run does not interrupt", needed)
    check_true(u"summary: it still says what happened", u"M-101" in text)
    check_true(u"summary: and what it compared against", u"Previous.rvt" in text)
    check_true(u"summary: the head counts views, not sheets", u"view(s)" in text)

    failed = [{u"number": u"M-101", u"against": u"P.rvt", u"clouds": 0,
               u"notes": [], u"info": [], u"error": u"the link is not loaded"}]
    needed, text = C.summarise(failed)
    check_true(u"summary: a failure needs a look", needed)
    check_true(u"summary: the reason is in the text", u"not loaded" in text)

    noted = [{u"number": u"M-102", u"against": u"P.rvt", u"clouds": 2,
              u"notes": [u"a cloud was refused"], u"info": [], u"error": None}]
    needed, _text = C.summarise(noted)
    check_true(u"summary: a note needs a look", needed)

    infoed = [{u"number": u"M-103", u"against": u"P.rvt", u"clouds": 1,
               u"notes": [], u"info": [u"420 elements in the view"],
               u"error": None}]
    needed, text = C.summarise(infoed)
    check_false(u"summary: routine info does not interrupt", needed)
    check_true(u"summary: but is written down", u"420 elements" in text)


TESTS = [test_settings, test_categories, test_category_templates,
         test_natural_key,
         test_describe_exception, test_collapse, test_summarise]


def main():
    for test in TESTS:
        test()
    if FAIL:
        sys.stdout.write(u"bench_logic: {0} of {1} checks FAILED\n".format(
            len(FAIL), len(FAIL) + PASS[0]))
        for line in FAIL:
            sys.stdout.write(u"  - " + line + u"\n")
        return 1
    sys.stdout.write(u"bench_logic: all {0} checks pass\n".format(PASS[0]))
    return 0


if __name__ == u"__main__":
    sys.exit(main())
