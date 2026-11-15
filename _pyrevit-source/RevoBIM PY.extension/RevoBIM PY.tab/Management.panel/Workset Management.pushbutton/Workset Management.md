# Workset Management — v1.0.0

A pushbutton on the **RevoBIM PY** tab, **Management** panel. One themed window
in two halves: worksets created and renamed through a spreadsheet at the top,
and whole categories assigned onto worksets at the bottom.

## Problem it solves

Setting a job up means typing thirty workset names into Revit's Worksets dialog
one at a time, and then dragging elements onto them by category through filters
and selection sets. Both jobs are already written down somewhere else — the
workset schedule is in a spreadsheet on the job, and "cable tray goes on
E-Containment" is a rule, not a decision to be made per element.

So the names come from Excel and the elements come from a rule: pick a category,
pick a workset, apply.

## The window

Modal, because nothing needs picking in the view. Borderless RevoBIM chrome, the
version top right, **Save routine** and **Load routine** beside it.

## Workset creation — the spreadsheet round trip

**Create worksets in Excel** asks where to put the file and writes it:

| Column | Content |
| --- | --- |
| A | the workset id — the tool's own, do not edit |
| B | the workset name — **orange** for an existing workset, **green** for a new one |
| C | what to do with the row |

Every workset in the model comes out in an orange cell, and **ten green cells**
follow with the prompt to type a name. Edit an orange cell and that workset is
**renamed**; fill in a green cell and a workset is **created**.

Column A is what makes the rename possible: the tool matches the row back to the
workset by id rather than by name, which is the only way to tell "rename this
one" apart from "make a new one". A row whose id has been wiped is read as a new
workset. Worksets missing from the sheet are **never deleted** — Revit will not
delete a workset that holds elements, and a spreadsheet is the wrong place to
make that decision.

**Import Excel** reads the file back and lands the result in the main workset
list **in red**: a rename as `old → new`, a creation as the new name. Nothing has
touched the model at this point. **Apply workset changes** writes the lot in one
transaction. A name that already exists, or is longer than Revit allows, is
reported on the row rather than attempted.

The workbook is written and read as Office Open XML straight into a zip — no
Excel, no installed package. Reading handles both inline strings and the shared
string table, because Excel rewrites the file into shared strings the moment it
is saved.

## Workset assigner

Every workset down the page. Beside each one the **quantity of elements
currently on it in orange**, then a drop-down of every category in use in the
project, with a search box and a count against each entry.

**Cable Tray** and **Cable Tray Fittings** carry a **Service Type sub group** —
one row per value the model actually uses, read from the instance first and the
type second, with `Service Type`, `BGL_Service Type` and `Service` tried in that
order. **Ticking the parent ticks every sub group under it**; unticking one sub
group releases the parent, since the parent no longer means "all of them".

**A category assigned to one workset is not offered to any other.** The claim
map is rebuilt on every tick: a claimed category disappears from every other
workset's list, and a category whose sub groups are partly spoken for stays in
the list with the parent greyed and only the free sub groups tickable. A workset
whose categories are all claimed elsewhere says so rather than showing an empty
list.

**Apply categories to worksets** at the bottom writes
`ELEM_PARTITION_PARAM` across the lot in one transaction. Where a parent and one
of its sub groups both resolve to a workset the sub group wins, so nothing is
written twice.

## Routines

**Save routine** stores the whole category-to-workset map under a name, against
the project, in `%APPDATA%\RevoBIM\workset_routines\<project>.txt`. **Load
routine** puts it back. The map is saved by workset *name*, so it survives a
model being detached and re-saved, and a workset that no longer exists is
reported on load rather than dropped quietly.

## Decisions worth remembering

- **The id column is the whole rename mechanism.** Matching on name cannot
  distinguish a rename from a creation, which is exactly the case the tool
  exists to handle.
- **Nothing is written until Apply.** Import stages; the list going red is the
  staging. Two separate Apply buttons, so a category run cannot be lost to a
  refused workset creation.
- **Claims are rebuilt, not patched.** Every tick rebuilds the whole map from
  the rows, which is cheap and cannot drift; the popup list is built on open, so
  it is always current and nothing is rebuilt for a workset nobody looked at.
- **Sub groups come from the model, not from a list.** The Service Type values
  offered are the ones the model actually uses, so a job with three services
  gets three rows.
- **Empty categories are hidden by default** (`hide_empty_categories`), so the
  drop-down is the categories in the job rather than Revit's whole list.
- **`WorksetTable.RenameWorkset` for renames, `Workset.Create` for creates**,
  both inside one transaction with a failure preprocessor that deletes warnings.
- **`import_check.py` ships with the tool.** It loads the modules against a stub
  Revit API declaring every name in the namespace the real API puts it in, and
  rejects f-strings, `print` statements, bare `.IntegerValue`, bare `.None`
  member access, any `FindName` with no matching `x:Name`, and any
  `StaticResource` key the layout does not define.
- **`.None` is a syntax error in IronPython.** `WindowStyle.None` has to be
  reached with `getattr`, and the bench check enforces it.

## Refusals

Reported rather than attempted: a model that is not workshared, a rename onto a
name already in use, a workset name over 100 characters, an element whose
workset parameter is read-only (group members and view-owned elements), and an
element owned by another user.

## Folder layout

```
Management.panel\
  bundle.yaml
  Workset Management.pushbutton\
    script.py                 the window
    workset_mgmt_core.py      model read, workset writes, settings, routines
    xlsx_simple.py            minimal OOXML reader and writer, no dependencies
    WorksetManagement.xaml    layout, palette and control templates
    import_check.py           bench check against a stub Revit API
    bundle.yaml  icon.png  CHANGELOG.md
```

## Settings

| Setting | Default |
| --- | --- |
| Green rows written for new worksets | 10 |
| Hide categories with no elements | on |
| Service Type sub groups | on |
| Show results | only if something needs a look |

Plain `key=value` under `%APPDATA%\RevoBIM\workset_management.txt`, defaults
applied key by key.

## Open items for a future version

- Worksets are never deleted, and elements are never moved *off* a workset
  except by being moved onto another.
- Only Cable Tray and Cable Tray Fittings sub group by Service Type; the same
  pattern would suit duct and pipe System Type.
- No filter beyond category and Service Type — a workset that should take one
  level only still needs a manual pass.
- The spreadsheet carries names, not the category map. Exporting the assigner
  routine to the same workbook would make the whole setup one document.
- The window is modal; a live element count that follows the model would need
  the modeless pattern and `DocumentChanged`.
