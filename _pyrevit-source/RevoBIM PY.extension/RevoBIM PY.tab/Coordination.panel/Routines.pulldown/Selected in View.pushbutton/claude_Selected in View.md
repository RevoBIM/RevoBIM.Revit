# Selected in View — v1.1.0

A pushbutton in the **Routines** pulldown on the **RevoBIM PY** tab,
**Coordination** panel. One compact modeless window: tick the categories you
want to be pickable, and while the window is open every selection you make
keeps only those. No Apply button. Close the window and selection is normal.

## How the filter works

Revit has no API for a standing selection filter, so the tool hooks
`UIApplication.SelectionChanged` (Revit 2023+) while the window is open. Each
time a selection lands — click, window, crossing, Tab, Ctrl-add — every picked
element is tested and anything not allowed is taken straight back out with
`Selection.SetElementIds`. If Revit ever refuses the change inside the event,
it is queued through an `ExternalEvent` instead.

An element is taken out when:

| Case | Rule |
| --- | --- |
| Category unticked | dropped |
| Tag | dropped when its **tag type** is unticked; an unseen type follows its tag family (off only when every known type of the family is off); an unseen tag family is kept unless every tag is off |
| Linked models red | Revit links, linked CAD and point clouds dropped (a pinned link follows Linked, not Pinned) |
| Pinned elements red | pinned elements dropped |
| No category, or a category the list has not seen | kept — and Refresh turns orange |

Ticking changes nothing already selected: the rule applies to the **next**
selection. The footer reports each strip, e.g. `Kept 5, dropped 3 (2 Walls,
1 pinned).`

Revit's own status-bar toggles (Select links, Select pinned elements) still
decide what Revit lets you pick at all — the tool can only take things back
out. The button tooltips say so.

## The window

- **Header** — icon, RevoBIM in blue, tool name in orange, theme chip
  (Auto → Dark → Light; Auto follows the Revit canvas via
  `UIThemeManager.CurrentCanvasTheme` tested `is not None`, then
  `Application.BackgroundColor`, re-checked on activate), version, full
  screen, close.
- **Linked models / Pinned elements** — green pickable, red filtered, counts
  for the view in the tooltip. Default green.
- **All / None**, search box (every word must match, searches tag types too
  and opens their parent), **Refresh** (orange when a pick met a category the
  list has not seen).
- **View line** — the view and model the list was read from.
- **List** — sections **Tags** (always first), **Model**, **Annotation**, each
  with a coloured tick, a section tickbox and an on/total count. Rows: tickbox,
  colour swatch, name in its discipline colour, element count. Click anywhere on
  a row to toggle.
- **Tags** — every tag in the view under the one Tags heading, sub-grouped by
  **tag family** (e.g. BGL_Pipe Tag). Each family expands (arrow) into its
  types with an outlined swatch; the family shows a dash when part-ticked and
  ticks or unticks every type; the Tags heading ticks every family. A family
  used in several tag categories is one row, and its tooltip lists them.
  Tag rows are keyed `tag:<family name>`, children `(row key, type id)`.
- **Footer** — status line, Debug tick (on), Copy debug, `Picking n of m
  categories`.

Discipline colours: pipes/plumbing blue, ducts/mechanical green,
electrical/containment orange, structure red, architecture tan, generic and
spaces purple, datums teal, annotation grey. Tags take the colour of what they
tag.

Default all ticked on every open. Ticks are kept by category id, so they carry
across views and documents; a category new to the list starts ticked.

## Refresh on view change

`UIApplication.ViewActivated` re-reads the active view (Revit raises it in API
context, so it reads directly). Refresh from the window goes through the
`ExternalEvent`. Elements are collected with
`FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType()`; a
line style or other subcategory is folded into its parent; Internal
categories, RVT Links, Cameras, Work Plane Grid, Point Clouds and Raster Images
are never listed.

## Lifetime

`__persistentengine__ = True`. The window is owned by Revit's main window
(`WindowInteropHelper.Owner = uiapp.MainWindowHandle`) so it floats in front.
The window and the event delegates are stored in the AppDomain
(`RevoBIM.SelectedInView.window`, `.hooks`); running the button again brings the
open window forward, and a new run first unhooks anything an earlier run (or a
dead engine) left hooked. Delegates are created once and removed with the same
object.

## Folder layout

```
Coordination.panel\
  Routines.pulldown\
    Selected in View.pushbutton\
      script.py          thin loader, __persistentengine__, staged errors
      siv_clr.py         every clr.AddReference, imported first
      siv_core.py        version, settings, palettes, colours, every rule (no .NET)
      siv_revit.py       reading the view, element tests, canvas theme
      siv_ui.py          XAML, palette, icon, owner, egg
      siv_window.py      window, list, selection filter, ExternalEvent runner
      SelectedInView.xaml  Theme.xaml  icon.png  bundle.yaml  CHANGELOG.md
      bench_stubs.py     stub API, names in their real namespaces
      import_check.py    24 rules, --selftest 27 breakages
      bench_logic.py     29 checks against a fake model, --selftest 13 breakages
```

No `Routines.pulldown\bundle.yaml`, panel `bundle.yaml`, `startup.py` or
`lib\revobim` file is shipped.

## Settings

`%APPDATA%\RevoBIM\selected_in_view.txt`, key=value: `theme` (auto), `debug`
(1), window `left` / `top` / `width` / `height`. Debug log
`selected_in_view_debug.txt`; start-up failures `selected_in_view_error.txt`.

## Bench

`import_check.py` — XAML parses; no StaticResource; every DynamicResource and
SetResourceReference key defined; keyed styles on the right element type;
every looked-up name has an `x:Name`; no f-strings, print, bare
`.IntegerValue`, `System.Uri`, non-ASCII; `siv_clr` before any .NET import;
`siv_core` pure; every namespace's assembly referenced; RevitAPI not
referenced; no duplicate definitions; CHANGELOG has the version; thin
`script.py` with `__persistentengine__`; `Raise()` result read; chrome
(`WindowStyle="None"`, no Baseline); palettes match; SelectionChanged and
ViewActivated each unhooked in both places; enums looked up late; every module
loads on the stub API.

`bench_logic.py` — view read (links, point clouds, linked DWG counted, imported
DWG listed, cameras and internal excluded, line styles folded), Tags heading
first, tags grouped by family (one row across categories), unseen tag family,
tag types, colour table, default keeps all, category / links / pinned / tag
type drops, parent tick, unseen tag type, unseen category flagged, ticks across
views, summaries, search, settings round trip / damage / migration, theme
resolution incl. `UITheme.Dark` being falsy, background fallback, slow clicks,
`eid_value`.

## Open items

- Not yet confirmed in live Revit 2024–2027. The one thing to watch is
  whether `SetElementIds` inside `SelectionChanged` is accepted on every
  release — the debug log says `direct reselect refused; queuing` if not, and
  the ExternalEvent route takes over.
- Revit's status-bar Select links / Select pinned toggles cannot be read or set
  from the API, so the tool filters on top of them rather than replacing them.
- Elements picked inside a linked model by Tab (references, not host ids) are
  not seen by `SelectionChanged` and are not filtered.
