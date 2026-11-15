# -*- coding: utf-8 -*-
"""Bench test of the rules themselves, under plain CPython.

    python bench_logic.py

The Revit API is stubbed but the tri-state logic, the selection maths, the
space label rule and the settings round trip are the real shipped code.
"""

import os
import sys
import tempfile

import import_check   # reuse its stub installer

HERE = os.path.dirname(os.path.abspath(__file__))

import_check.install_stubs()
sys.path.insert(0, HERE)

import snte_core as core   # noqa: E402

passed = 0
problems = []


def check(label, got, want):
    global passed
    if got == want:
        passed += 1
    else:
        problems.append("{0}: got {1!r}, wanted {2!r}".format(label, got, want))


def truthy(label, got):
    check(label, bool(got), True)


# ---------------------------------------------------------------------------
#  a fake model tree
# ---------------------------------------------------------------------------
class FakeId(object):
    def __init__(self, value):
        self.Value = value
        self.IntegerValue = value

    def __eq__(self, other):
        return isinstance(other, FakeId) and other.Value == self.Value

    def __hash__(self):
        return hash(self.Value)


def build_tree():
    """Two categories, the first with two families."""
    cat_a = core.CategoryNode(FakeId(-2008000), "Pipes")
    fam_a1 = core.FamilyNode("Pipe Types", cat_a)
    fam_a2 = core.FamilyNode("Flex Pipe Types", cat_a)
    cat_a.families["Pipe Types"] = fam_a1
    cat_a.families["Flex Pipe Types"] = fam_a2

    t1 = core.TypeNode(1, "Standard", fam_a1)
    t1.element_ids = [FakeId(101), FakeId(102), FakeId(103)]
    t2 = core.TypeNode(2, "Insulated", fam_a1)
    t2.element_ids = [FakeId(104)]
    fam_a1.types[1] = t1
    fam_a1.types[2] = t2

    t3 = core.TypeNode(3, "Flex Standard", fam_a2)
    t3.element_ids = [FakeId(105), FakeId(106)]
    fam_a2.types[3] = t3

    cat_b = core.CategoryNode(FakeId(-2008010), "Cable Trays")
    fam_b1 = core.FamilyNode("Cable Tray with Fittings", cat_b)
    cat_b.families["Cable Tray with Fittings"] = fam_b1
    t4 = core.TypeNode(4, "Ladder", fam_b1)
    t4.element_ids = [FakeId(201)]
    fam_b1.types[4] = t4

    return [cat_a, cat_b], (t1, t2, t3, t4)


# ---------------------------------------------------------------------------
#  counts
# ---------------------------------------------------------------------------
nodes, types = build_tree()
t1, t2, t3, t4 = types

check("category count rolls up families", nodes[0].count, 6)
check("family count rolls up types", nodes[0].families["Pipe Types"].count, 4)
check("second category count", nodes[1].count, 1)

# ---------------------------------------------------------------------------
#  tri-state
# ---------------------------------------------------------------------------
check("nothing ticked is False", nodes[0].state(), False)

t1.set_state(True)
check("one type of two makes the family partial",
      nodes[0].families["Pipe Types"].state(), None)
check("a partial family makes the category partial", nodes[0].state(), None)

t2.set_state(True)
check("both types make the family True",
      nodes[0].families["Pipe Types"].state(), True)
check("one full family and one empty is still partial", nodes[0].state(), None)

t3.set_state(True)
check("every family full makes the category True", nodes[0].state(), True)

nodes[0].set_state(False)
check("setting a category clears every type below it", nodes[0].state(), False)
check("  and the individual type with it", t1.checked, False)

nodes[0].families["Flex Pipe Types"].set_state(True)
check("setting a family ticks only its own types", t3.checked, True)
check("  and leaves its siblings alone", t1.checked, False)

# ---------------------------------------------------------------------------
#  selection
# ---------------------------------------------------------------------------
cats, tcount, elements = core.selection_counts(nodes)
check("one family ticked - categories", cats, 1)
check("one family ticked - types", tcount, 1)
check("one family ticked - elements", elements, 2)

ids = core.selected_element_ids(nodes)
check("only the ticked type's elements are collected", len(ids), 2)
check("  and they are the right ones",
      sorted([i.Value for i in ids]), [105, 106])

t4.set_state(True)
cats, tcount, elements = core.selection_counts(nodes)
check("a type in a second category counts that category", cats, 2)
check("  types across both", tcount, 2)
check("  elements across both", elements, 3)

selected = core.selected_categories(nodes)
check("selected_categories returns both", len(selected), 2)

nodes[1].set_state(False)
selected = core.selected_categories(nodes)
check("a category with nothing ticked drops out", len(selected), 1)

# ---------------------------------------------------------------------------
#  searching
# ---------------------------------------------------------------------------
truthy("a category matches on its own name", nodes[0].match("pipe"))
truthy("a category matches on a family name", nodes[1].match("fittings"))
truthy("a category matches on a type name", nodes[1].match("ladder"))
check("a category that matches nothing", nodes[1].match("zzz"), False)
truthy("a family matches on a type name",
       nodes[0].families["Pipe Types"].match("insulated"))

# ---------------------------------------------------------------------------
#  what the search shows, and how far it opens
# ---------------------------------------------------------------------------
def plan(cat_nodes, keyword):
    """Mirrors TreeBuilder.rebuild / _add_children without any WPF, so the
    filtering and expansion rule can be tested on the bench."""
    keyword = (keyword or "").strip().lower()
    out = []
    for cnode in cat_nodes:
        if keyword and not cnode.match(keyword):
            continue
        own = (not keyword) or (keyword in cnode.name.lower())
        entry = {"name": cnode.name, "expanded": not own, "families": []}
        if not own:
            for fnode in cnode.family_list:
                fown = keyword in fnode.name.lower()
                if not fown and not fnode.match(keyword):
                    continue
                fentry = {"name": fnode.name, "expanded": not fown,
                          "types": []}
                if not fown:
                    for tnode in fnode.type_list:
                        if tnode.match(keyword):
                            fentry["types"].append(tnode.name)
                entry["families"].append(fentry)
        out.append(entry)
    return out


nodes2, types2 = build_tree()

view = plan(nodes2, "")
check("no search shows every category", len(view), 2)
check("  and opens nothing", [c["expanded"] for c in view], [False, False])

view = plan(nodes2, "pipe")
check("a category-name hit shows that category", len(view), 1)
check("  named correctly", view[0]["name"], "Pipes")
check("  and leaves it closed, the match is already visible",
      view[0]["expanded"], False)

view = plan(nodes2, "flex")
check("a family-name hit still lists the category", len(view), 1)
check("  opens the category", view[0]["expanded"], True)
check("  shows only the matching family",
      [f["name"] for f in view[0]["families"]], ["Flex Pipe Types"])
check("  and stops there, the family name is the match",
      view[0]["families"][0]["expanded"], False)

view = plan(nodes2, "insulated")
check("a type-name hit lists the category", len(view), 1)
check("  opens the category", view[0]["expanded"], True)
check("  shows only the family holding it",
      [f["name"] for f in view[0]["families"]], ["Pipe Types"])
check("  opens that family too", view[0]["families"][0]["expanded"], True)
check("  and shows only the matching type",
      view[0]["families"][0]["types"], ["Insulated"])

view = plan(nodes2, "ladder")
check("a type hit in the second category finds it", len(view), 1)
check("  the right category", view[0]["name"], "Cable Trays")
check("  opened down to the type",
      view[0]["families"][0]["types"], ["Ladder"])

view = plan(nodes2, "zzz")
check("a search matching nothing shows nothing", len(view), 0)

view = plan(nodes2, "types")
check("a keyword matching two families under one category shows it once",
      len(view), 1)
check("  with both matching families listed",
      sorted([f["name"] for f in view[0]["families"]]),
      ["Flex Pipe Types", "Pipe Types"])

view = plan(nodes2, "cable")
check("a keyword hitting a category name and a family name elsewhere",
      len(view), 1)
check("  matched on the category name, so it stays closed",
      view[0]["expanded"], False)

# ---------------------------------------------------------------------------
#  natural sort, used for stacking several spaces
# ---------------------------------------------------------------------------
labels = ["Office - 10", "Office - 2", "Office - 1"]
check("spaces sort naturally, not alphabetically",
      sorted(labels, key=core.natural_key),
      ["Office - 1", "Office - 2", "Office - 10"])

check("the join uses ' / '",
      core.SPACE_DELIM.join(["Office - 1", "Store - 2"]),
      "Office - 1 / Store - 2")
check("name and number are joined by ' - '", core.PART_DELIM, " - ")

# ---------------------------------------------------------------------------
#  eid_value across Revit versions
# ---------------------------------------------------------------------------
class OnlyValue(object):
    Value = 42


class OnlyInteger(object):
    def __getattr__(self, name):
        if name == "Value":
            raise AttributeError("gone in 2026")
        raise AttributeError(name)

    IntegerValue = 7


check("eid_value prefers .Value", core.eid_value(OnlyValue()), 42)
check("eid_value falls back to .IntegerValue",
      core.eid_value(OnlyInteger()), 7)
check("eid_value copes with None", core.eid_value(None), 0)

# ---------------------------------------------------------------------------
#  settings
# ---------------------------------------------------------------------------
tmpdir = tempfile.mkdtemp()
core.SETTINGS_PATH = os.path.join(tmpdir, "space_name_to_element.txt")
core.SETTINGS_DIR = tmpdir

defaults = core.load_settings()
check("a missing file gives the defaults",
      defaults["parameter"], "BGL_Room name")
check("  and the default theme", defaults["theme"], "dark")

defaults["parameter"] = "BGL_Space Ref"
defaults["theme"] = "light"
truthy("settings save", core.save_settings(defaults))

again = core.load_settings()
check("the parameter is remembered", again["parameter"], "BGL_Space Ref")
check("the theme is remembered", again["theme"], "light")

handle = open(core.SETTINGS_PATH, "a")
handle.write("something_from_an_old_version=1\nnot a pair at all\n")
handle.close()
survived = core.load_settings()
check("an unknown key does not break the load",
      survived["parameter"], "BGL_Space Ref")
check("  and neither does a junk line", survived["theme"], "light")

handle = open(core.SETTINGS_PATH, "w")
handle.write("parameter=BGL_A = B\n")
handle.close()
check("the loader splits on the first '=' only",
      core.load_settings()["parameter"], "BGL_A = B")

check("as_bool on '1'", core.as_bool("1"), True)
check("as_bool on '0'", core.as_bool("0"), False)
check("as_bool on 'true'", core.as_bool("true"), True)
check("as_bool on rubbish", core.as_bool("banana"), False)

# ---------------------------------------------------------------------------
#  report
# ---------------------------------------------------------------------------
total = passed + len(problems)
if problems:
    sys.stdout.write("FAILED - {0} of {1} checks\n".format(len(problems), total))
    for item in problems:
        sys.stdout.write("  " + item + "\n")
    sys.exit(1)

sys.stdout.write("All {0} checks pass.\n".format(total))
