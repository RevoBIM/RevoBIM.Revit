# RevoBIM PY - Style Manager

**Tab:** RevoBIM PY  **Panel:** Management  **Version:** 4.7.0
**Tested against:** Revit 2024.3.6, pyRevit 2.7.12, IronPython 2.7, metric mm

Formerly Filter Manager. If your extension folder still contains
`Management.panel/Filter Manager.pushbutton`, delete it after installing.

## Bench checks
Two benches sit beside the script and run under plain CPython. `bench_check.py`
checks the script's structure; `bench_logic.py` runs the real duplicate, pattern,
asset and parameter-analysis code against stub Revit objects. Both take
`--selftest`, which breaks the code on purpose and fails if a check misses it.

`bench_check.py`:

```
cd "...\Management.panel\Style Manager.pushbutton"
python bench_check.py
```

It parses the script without importing it and checks that every panel named in
the ribbon has a class, that every method a class calls on itself is defined, that each provides the methods the framework calls, that
column sets and icons are complete, that every `find()` has a matching `x:Name`,
that all XAML parses, and that no f-strings, `print`, bare `.IntegerValue` or
`System.Uri` have crept in. Run it after any edit.

## If it will not start
The tool now catches any startup failure and prints the full traceback to the
pyRevit output window, with a copy saved to
`Documents\RevoBIM PY\Logs\StyleManager_startup_error_*.log`. Send that text on
and it can be fixed directly. A single failing tab no longer stops the others.

## Install
Unzip so that `RevoBIM PY.extension` merges into your existing pyRevit
extensions folder, then reload pyRevit. The tool appears under
**RevoBIM PY > Management > Style Manager**.

**Export and Import** share one square Excel button on each tab - click it for the
two options.

Every tab has the same controls: Refresh, Find Duplicates, Merge Selected,
Delete Selected, Export/Import Excel, Select Unused, search, the three isolation
toggles, and the bulk rename bar. The status box, the pending summary and the red
APPLY bar are shared across all three.

## The tabs
A ribbon across the top, grouped the way Ideate StyleManager groups them:

| Group | Tabs |
|---|---|
| Graphics | Object Styles, Line Styles, Line Patterns |
| Regions | Filled Regions, Fill Patterns |
| Materials | Materials, Material Appearance Assets |
| Views | Filters, View Templates, Viewports, Scope Boxes |
| Tags | Tag Styles |
| Text | Text Styles, Fonts |
| Dimensions | Dimensions, Arrowheads |
| Parameters | Parameters, Global Parameters |

Every tab shares the same controls - Refresh, Analyze, Find Duplicates, Merge,
Delete, the Excel button, Select Unused, search, the isolation toggles and the
bulk rename bar - plus the shared status box and red APPLY bar.

**Tabs load when you first open them.** Reading all seventeen at startup would be
unusable on a real model, so only the tab on screen is read up front.

Some of the newer tabs expose **the name only** for editing in this first round,
where the rest of the properties are set through Revit dialogs that have no API
equivalent. Each tab's Excel info sheet says which columns are editable.

Two tabs deliberately do not merge: **Fonts** cannot be deleted at all (a font is
not an element - merging rewrites the styles that use it), and **Parameters** is
not offered, because combining two parameters means migrating values rather than
repointing a style.

## Progress and long jobs
A progress bar with a percentage sits under the ribbon whenever a job is running,
naming what it is doing - the family being opened, the category being scanned, the
tab being read. Anything that opens families, walks a whole category or writes a
large batch asks first: *"This could take some time, suggest syncing before
running this command."*

## Editing one row or many
It is all driven from the cells:

1. Select the rows you want - one, a ctrl-picked handful, or Ctrl+A for all.
2. Click the cell you want to change on **any one of them**. The rows stay
   highlighted and, for a dropdown, the list opens on that first click.
3. Pick the value. Every highlighted row takes it.

Edit a row on its own and only that row changes. The selection survives the edit,
so you can carry on through the other settings for the same set of types. Nothing
reaches the model until **APPLY CHANGES**. It works on any editable column. Dropdown cells - leader arrowhead,
arrow style, the Yes/No settings - are combo boxes whose options come from what
the model actually offers. Names are excluded on purpose: one name across several
rows would only get auto-numbered.

Nothing is written until APPLY CHANGES, so a mass edit can be reviewed and
discarded like any other staged change.

## Staged edits and Apply
Every edit - inline rename, property edit, bulk find/replace, Excel import - is
**staged in memory** on whichever tab it was made. Staged rows turn orange and
show `Pending`. Nothing is written until the red **APPLY CHANGES** button is
pressed, and it commits every tab in a **single transaction** so Revit
regenerates once. **Discard Changes** drops everything without touching the
model, and closing the window with staged edits asks first.

## Editing
- **Rename:** click a selected row again (click, pause, click), press **F2**, or
  right-click > **Rename**. Enter commits, Esc cancels.
- **Other editable cells** work the same way: rules, categories and logic on the
  Filters tab; weight, colour and pattern on Line Styles; font, size, bold,
  italic, underline and width on Text Styles.
- **Bulk rename:** select rows, fill in Find and Replace with, press Apply.
- Name collisions get `(2)`, `(3)`... appended automatically and are reported.

## Parameters
Every parameter the project defines, read from the binding table so non-shared
project parameters are listed alongside shared ones, plus anything defined but
bound to no category. The columns are the parameter's own properties: shared or
project, instance or type, discipline, type of parameter, group, bound categories
and GUID.

**Analyze** walks every element of every category a parameter is bound to and
counts those holding a value, after which the status reads Used or Unused.
**Select Unused** then picks out the ones nothing uses, and Delete removes them -
it refuses to run on parameters that have not been analysed, so the confirmation
can always say what would be lost.

Duplicates are deliberately off here, and merging is not offered: combining two
parameters means migrating values, not repointing a style.

## Analyze
The **Object Styles** tab counts usage on demand rather than on every refresh,
because working out what uses a subcategory means opening every family of the
parent category. Until you press **Analyze** on a selection, usage reads `?`;
built-in styles read `-`, since Revit does not report their usage at all. Merge
and delete both ask you to analyse first so the confirmation can tell you exactly
how many elements will move. Analysis results survive a refresh.

Every other tab counts usage as part of the normal read, so Analyze is not needed
there.

## Merging
On **Object Styles**, merging works by editing families. Subcategory assignment
lives inside each family rather than in the project, so Style Manager opens every
family of the parent category, repoints its geometry onto the kept subcategory,
deletes the spare subcategory there, and loads the family back over itself.
Elements placed directly in the project are repointed first.

Families **nested inside** those families are descended into as well, up to three
levels, and reloaded into their parent before the parent is reloaded into the
project.

The **merge target does not have to be one of the rows you selected.** The merge
window has a "Selection set only" tick; untick it to choose any subcategory of the
same parent, or the **parent category itself**. Merging into the parent category is
how you fold a stray subcategory back into the standard, since elements revert to
the category style. Revit's own built-in subcategories can be targets too, even
though they cannot be renamed or deleted.

Three things to know before running it: only subcategories **sharing a parent
category** can be merged; it **cannot be undone with one Ctrl+Z** because each
family reload is its own undo step, so save or sync first; and in-place and
system families cannot be opened, so they are named and skipped and the spare
subcategories are then kept rather than deleted.

On **Materials** the merge repoints every writable material-valued parameter. It
cannot reach compound structure layers or painted faces; those are reported, and
the replaced material is kept rather than deleted while anything still uses it.

Select two or more rows, then **Merge Selected...** and choose which to keep.
- Filters: every view and template is repointed to the kept filter, graphic
  overrides carried across where the kept filter was not already present.
- Line styles: every curve drawn with the dropped styles is moved onto the kept
  style first, so no geometry is lost.
- Text styles: every text note is retyped onto the kept type first.

## Deleting
**Delete Selected...** opens a red confirmation window listing the impact before
anything happens, and the confirm button is red and says DELETE.

What Revit actually does varies by style, and the confirmation says which applies:

- deleting a **filter** just removes it from the views that used it;
- deleting a **line**, **text** or **dimension style** deletes the lines, notes or
  dimensions drawn with it - merge them onto another style first;
- deleting a custom **object style** subcategory does **not** delete geometry: the
  elements revert to the parent category style. The exception is a subcategory
  that came in with an import, where the imported geometry goes with it;
- deleting a **material** leaves elements to fall back to their category material.

Revit's own built-in line styles are read-only and cannot be renamed or deleted;
they are marked as such in the table.

## Groups
Revit refuses to modify an element inside a group, and offers no "edit group"
API. When a merge affects curves or text notes inside a group, Style Manager
rebuilds the group rather than asking you to ungroup: one instance of the
affected group type is ungrouped, the change is applied, the members are grouped
back up, the original group type name is restored and every other instance of the
old type is repointed onto the rebuilt one. Nested groups recurse, pinned groups
are re-pinned, and each group runs in its own SubTransaction so a failure leaves
that group untouched and reports why.

Two limits worth knowing: model groups with **attached detail groups** are
skipped rather than risk detaching them, and if anything could not be moved the
merge will not delete the replaced style, because deleting a line or text style
deletes the content still using it.

## Edit in Revit
Available on the Filters and Line Styles tabs. It posts Revit's own dialog, then
uses UI Automation on a background thread to scroll to and select the row you had
highlighted, and puts the name on the clipboard as a fallback. Automation depends
on the dialog layout of your Revit build and language, so treat the selection as
best-effort - the dialog always opens and the clipboard always works.

## Excel round trip
Orange cells are editable, grey are read only, the header row is frozen and the
range is a filterable table. Export asks where to save, remembers the folder, and
offers **Open folder location** when it finishes. Import reads the sheet matching
the tab, compares it against the model and stages only what actually changed;
anything not writable is reported and ignored.

Filters sheet rules format, one per line (Alt+Enter):
`[Parameter Name] operator value` with operators `equals`, `not equals`,
`contains`, `does not contain`, `begins with`, `does not begin with`,
`ends with`, `does not end with`, `>`, `>=`, `<`, `<=`, `has value`,
`has no value`. Numeric values are in project display units. Leave Filter Id
blank or type `NEW` to create a filter.

Logs are written to `Documents\RevoBIM PY\Logs`, settings to
`%APPDATA%\RevoBIM PY\style_manager_settings.json`.
