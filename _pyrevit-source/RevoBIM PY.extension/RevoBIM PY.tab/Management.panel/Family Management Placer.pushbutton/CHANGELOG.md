# Family Management Placer — version history

Version is displayed top-right of the tool window and in the footer of the
completion dialog. `TOOL_VERSION` lives at the top of `script.py`.

## 1.10.0
- **The tool now finishes silently.** No results dialog, and the window closes
  once the families are placed - which brings it back in line with the house
  convention the completion dialog was always an exception to.
- Two new settings under **After placement**: *Show the results summary* and
  *Keep the tool open after placing*, both off by default, both remembered.
- Three cases deliberately ignore those settings, because suppressing them
  would leave a run looking like it did nothing: a **failure** is always
  reported and always leaves the window open; an **escaped pick** or a
  **refused view** leaves the window open for another go.
- The summary line reports what will happen after a run.

## 1.9.0
- **Settings moved into their own modal window**, opened from a gear icon at
  the top right of the main window beside the close button. The main window is
  now the family browser at full width and drops from 960 to 700 px.
- The gear is drawn from a `Path`, not set in a symbol font, so it cannot
  render as an empty box on a machine without that font.
- **Cancel really discards.** The settings window edits a copy and only writes
  back to the tool on Save. **Reset defaults** restores the defaults at the
  current scale without closing.
- Settings are held in one dictionary rather than read off the controls, so
  the values survive the settings window being closed and reopened, and the
  scale rescales them whether or not that window is open.
- A summary line under the view scope shows the scale, spacings, tagging,
  headings and workset at a glance, so the gear only needs opening to change
  something.

## 1.8.0
- **3D text headings removed.** Category headings are now plain **text notes**,
  which removes the whole Model Text problem: no family to load, nothing to
  write a parameter into, and nothing to go silently blank.
- **Text style dropdown** listing the project's text note types, remembered
  between sessions. A remembered style missing from the current model falls
  back to the first available and says so.
- **Heading height above the first placement** defaults to **1500 mm at 1:50**
  (3000 mm at 1:100) and scales with the view like the other distances. The
  field carries its 1:50 equivalent underneath.
- Headings can be turned off with a tick box. The dialog reports the style used
  and flags any heading that could not be placed.
- Removed with the feature: the family search box, family type picker, text
  parameter box and the `Category` parameter handling.

## 1.7.0
- **Generic Models : Model Text is now the heading family**, with the value
  written into its **Category** parameter. Both are the defaults, and the
  family is auto-selected on load whenever it is loaded in the project - the
  picker only needs touching to override it.
- **Fixed a collision that would have written nothing.** `Category` is also a
  built-in read-only parameter, and `LookupParameter` returns one object - the
  built-in one - so the family's own Category parameter was never reached.
  Every parameter of that name is now checked via `GetParameters`, read-only
  ones stepped over, and the write read back.
- The search box defaults to `Model Text` and the panel says when the family
  is not loaded, rather than silently falling back to text notes.

## 1.6.0
- **Fixed: tags not offsetting from the family in drafting views.** Revit
  ignores the creation point for some categories - detail items among them -
  and parks the tag head on the element. Tags are now repositioned explicitly
  through `TagHeadPosition` in a second pass after a regenerate, which is when
  it takes, and the result is read back. Offsets are also measured from where
  the instance actually landed rather than from the point it was asked for.
- **Fixed: 3D text headings not generating in floor plans.** Revit cannot
  create Model Text in a project document through the API - `NewModelText` is
  on `FamilyItemFactory`, which only exists in a family document. The attempt
  was failing into a silent `except` and dropping to a text note.
- **3D text family picker in Settings**, as a replacement: choose any family
  type, with a search box, and name the text parameter the category name is
  written into. `Text`, `TEXT`, `Model Text`, `Label`, `Value` and `BGL_Text`
  are tried as fallbacks, instance before type, and the write is read back.
- Headings fall back to text notes when no family is chosen, and the dialog
  says which route each heading took, which parameter was written, and how
  many tags reached their offset.
- 3D text depth setting removed - depth belongs to the chosen family's type.

## 1.5.0 - upgrade fix
- **Fixed: `'Req' object has no attribute 'text_offset'` after upgrading in a
  running Revit session.** The ExternalEvent handler was parked in the AppDomain
  under a key with no version in it. That handler outlives the script and keeps
  its own build's globals, so after dropping in a new script the *previous*
  version's placement code ran against a request built by the *new* window - and
  the completion dialog reported the old version number, which is the giveaway.
  The AppDomain keys are now stamped with the version and the handler carries a
  matching stamp, so an upgraded script always gets a handler of its own.
- The request carries its version and the handler refuses a mismatched one with
  a plain "restart Revit" message instead of a traceback. Nothing is placed.
- Every optional value in `execute_placement` is read through a default-backed
  lookup, so a future mismatch degrades rather than throws.

## 1.4.0
- **Scale is taken from the active view** when the tool opens and on every
  Reload. A view scale outside the standard steps (1:20, 1:200 and so on) is
  added to the list rather than snapped away, and the panel says where the
  number came from.
- **Tag offsets split in two**, both shown in the window and both scaled:
  **family tag vertical offset** (10 mm at 1:1, so 1000 mm at 1:100) and
  **type tag horizontal offset** (20 mm at 1:1, so 2000 mm at 1:100). Each
  field carries its 1:1 equivalent underneath.
- **Workset is a dropdown** of the model's user worksets plus
  `< active workset >`, and the choice is remembered. A remembered workset that
  is not in the current model says so and falls back to the active one.
  Non-workshared models disable the control.
- **Choices now persist** between sessions: workset, both tag types, tagging
  and 3D text switches, model text type, text depth and group gap. Distances
  still restart from the defaults, since the scale is read from the view on
  open — this replaces the blanket reset-on-close from 1.3.0.

## 1.3.0
- **View scale box** at the top of the settings panel: 1:100, 1:50, 1:25, 1:10,
  1:1. All spacings are authored at 1:100 and rescale live when the scale
  changes, preserving any manual edits (a value is converted out of the old
  factor and into the new one, so the round trip back to 1:100 is exact).
- Scaled settings: text offset, family vertical spacing, category column
  spacing, heading offset. Family group gap is a percentage and 3D text depth
  is a type property, so neither is scaled.
- **Closing the window resets everything** to the 1:100 defaults, so the tool
  always reopens in a known state.
- Completion dialog footer now reports the scale the run used.

## 1.2.0
- Default category column spacing 4000 mm -> **10000 mm**.
- Default family group gap 10% -> **100%**.
- Category headings now look for **Model Text : 1000mm Family Category** rather
  than the first Model Text Type found. The type name is editable, and the
  panel confirms on load whether it exists in the project.
- New **heading offset** setting, default **2000 mm** above the first placement
  (was tied to the family vertical spacing).
- Completion dialog reports which model text type was actually used.

## 1.1.0
- Family grouping: types of the same family are kept as one block, and each new
  family group in a column drops by an extra percentage of the family vertical
  spacing. New editable field **Family group gap (%)**, default 10%.
- Family-name Multi-Category tag now sits **above** the first instance of each
  family group (was: left of the column), offset by the text offset distance.
  Type-name tag is unchanged, to the right of every instance.

## 1.0.0 — initial release
- Modeless dark WPF browser: Category → Family → Type, tri-state checkboxes,
  live filter box, expand/collapse, select all / clear.
- Active-view aware: floor / ceiling / engineering plans show all placeable
  families; drafting views show view-based families only.
- Editable layout: tag text offset (1000 mm), family vertical spacing
  (1000 mm), category column spacing (4000 mm).
- Multi-Category tag pickers for family-name and type-name tags. Family-name
  tag placed once per family, on the first type only.
- 3D model text category headings, automatic text-note fallback in drafting
  views or where no Model Text Type exists.
- Elements created on the "Family Container" workset when present, otherwise
  the active workset. Workset name is editable.
- Single-step undo via TransactionGroup; per-element SubTransactions so one
  bad family cannot abort the run.
- Themed completion dialog with a per-category placed / skipped breakdown.
- Settings persist to `%APPDATA%\RevoBIM PY\family_management_placer_settings.json`.
