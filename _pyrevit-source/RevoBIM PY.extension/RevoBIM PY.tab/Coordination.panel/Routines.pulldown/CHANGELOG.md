# Isolate Service Type - changelog

## 1.7.0

- **A new hide replaces the last one.** Hiding again in a view puts that
  view's remembered hide back first, then records only the new one - no more
  stacking. The old one is put back inside the same transaction, *before*
  the tool works out what is newly hidden; the other order would leave
  anything in both selections out of the new record, where Reset could never
  bring it back. Stacking is still a setting.
- **Hide selection templates.** The category list gets a Template bar: pick
  a template to tick it, **Save template...** (a themed name box; the same
  name replaces), **Delete**. A template names categories, services,
  families, types and linked-model rows by link title - never element ids -
  so one template works in every view of every project. A link row reaches
  every instance of that link in the view, and a linked model the template
  needs is read for it. Rows a view has nothing for are named, not guessed.
  Stored per user in `%APPDATA%\RevoBIM\hide_templates.json`.
- **The last template is the default.** With nothing selected, Hide applies
  the last template straight away - one click, no list - and the Reset Hide
  window says which template it was. A template ticked and changed by hand
  is a new selection until it is saved, so it does not become the default.
  A setting opens the list with the last template ticked instead.
- **New selection...** in the Reset Hide window opens the list clean, on
  whatever view is open in Revit.
- `bench_logic.py` is up to 232 checks and 15 deliberate breakages.

## 1.6.0

- **Hide Service Type now remembers what it hides**, and a floating
  **Reset Hide** window puts it back. Revit's Temporary Hide is one layer per
  view that anyone's next temporary hide, isolate or reset wipes out, and it
  is gone when the model closes. This is the tool's own temporary hide:
  - Host elements and whole links are hidden with Revit's own Hide in View.
    **Only what was not already hidden is written down**, so Reset never
    unhides something somebody else hid on purpose.
  - Linked rows stay view filters; the filter's rules are written down, so a
    filter deleted on Reset is made again by Hide again.
  - The memory is per view, in `%APPDATA%\RevoBIM\hide_memory\<model>.json`
    (one per central model, shared by every local copy), and survives closing
    Revit.
  - A second hide in the same view adds to the first; one Reset puts back
    both.
- **Reset Hide window** - modeless, owned by Revit, top right of the screen
  and remembered where you leave it. The most recent hide gets one big
  **Reset Hide** button, which turns into **Hide again**; every other view
  with a remembered hide is listed below with its own button. **Forget**
  (shows it first if hidden) and **Reset all**. It watches the memory file,
  so a new hide shows up in it within a second.
  - Every press is a job on one `ExternalEvent`: Accepted runs, Pending
    queues behind the earlier request and the queue is never cleared,
    Denied/TimedOut drops only that job and says so, and a 20 s watchdog frees
    the window if Revit never picks it up.
  - Opened by Hide Service Type after a remembered hide, and by the new
    **RevoBIM Reset Hide** button (bind a key to it). A second press brings
    the open window forward. A window whose engine has gone (pyRevit reload)
    stops its heartbeat and is replaced rather than brought forward dead.
- Every other reset - the list's Reset view, Finish on nothing in Isolate -
  puts the remembered hide back too, and Reset leaves no orphan filters.
- **Fixed: settings migrations.** Only the newest migration was applied, so
  a settings file written by 1.3.0 and opened by anything after 1.4.0 kept
  pipes on Service Type. Every migration newer than the file now applies, in
  order.
- New setting: Hide Service Type puts elements away **remembered** (the new
  default; settings files are moved on), Revit's Temporary Hide, or Hide in
  View.
- `import_check.py` adds rule 18, **enum_assign** (no bare numbers on WPF
  enum properties, no `__import__`), and rule 19, **persistent_engine** (a
  button that leaves a floating window keeps its engine). 19 rules, all proved
  by breakage. `bench_logic.py` is up to 211 checks and 13 deliberate
  breakages.

## 1.5.0

- **Hide Service Type with nothing selected opens a category list** of what
  is drawn in the view, to tick and hide:
  - **This model** - service categories (the four discipline groups) split by
    service; every other model category split by family, then type.
  - **Linked models** - every loaded link drawn in the view, read only when
    its row is first opened. Pipes, ducts, cable tray and conduit by service;
    the rest by family, then type.
  - Search, Expand, Collapse, Clear ticks, a theme chip, a running count in
    the footer, and Reset view.
- **Linked rows hide through view filters.** Revit's API will not hide a
  linked element by id, temporarily or otherwise, and its only postable hide
  is permanent. Each ticked linked row becomes one `RevoBIM Temp Hide - ...`
  filter, named for exactly what it hides and reused on the next run; a whole
  link ticked hides the link instance itself, temporarily. A filter cannot tell
  host from link, so each linked row shows an orange **+N in this model** - how
  many host elements the same filter also catches - and the report repeats it.
- **Reset** (the list's button, or Finish on nothing in Isolate) now also
  takes this tool's filters off the view, deleting any no other view uses.
  Other filters are never touched.
- Rows Revit will not filter, a view template that owns the view's filters,
  and links shown By Linked View are all named rather than failing silently;
  a failed row is reported even with the quiet setting on.
- New setting: **Hide Service Type opens the category list instead**, on.
- The checkbox gains a part-ticked dash; clicking a part-ticked row ticks
  everything under it.
- `import_check.py` adds rule 17, **import_names**: every `from X import a`
  anywhere - including inside functions, which never run at load - must name
  something the API really has in X. `bench_logic.py` is up to 179 checks and
  11 deliberate breakages.

## 1.4.0

- **Fixed: Hide Service Type hid every pipe.** Pipes and ducts carry their
  service in **System Type**, not Service Type, so the tool found no value,
  and the blank-value rule widened the hide to the whole pipe group. Three
  changes, any one of which would have stopped it:
  - Duct and pipe now default to **System Type**; cable tray and conduit stay
    on Service Type.
  - When the configured parameter is blank, Revit's own built-in is tried
    (`RBS_PIPING_SYSTEM_TYPE_PARAM`, `RBS_DUCT_SYSTEM_TYPE_PARAM`,
    `RBS_CTC_SERVICE_TYPE`) - which also answers in a non-English Revit. A
    parameter that exists but is empty now counts as blank, not as an answer.
  - A picked element with no value is **left out and reported** by default.
    Taking in its whole group is still available, but only when asked for.
- Settings written by 1.3.0 are moved on: the pipe and duct parameter and the
  blank rule reset to the new defaults; anything chosen by hand elsewhere is
  kept.
- **Nothing selected: pick, then Finish.** Both tools open Revit's own
  multi-pick with Finish and Cancel on the Options Bar. Pick a tray and a pipe
  and each is matched by its own service. Finish with nothing picked resets
  the view; Escape changes nothing and opens no window. "Reset straight away"
  is a setting for anyone who preferred the old one-key toggle.
- The report lists the services first and insulation after them.
- `bench_logic.py` is up to 120 checks and 9 deliberate breakages, with the
  1.3.0 bug reproduced as a test: an empty shared "Service Type" sitting in
  front of a pipe's System Type.

## 1.3.0

- **New button: RevoBIM Hide Service Type.** The mirror of Isolate. Pick a
  vent pipe and every pipe, fitting, accessory, plumbing fixture and
  equipment on that service goes; everything else stays. Same four discipline
  groups, same parameters, same categories, same settings - only the action
  differs.
- The matching engine is now shared: `ist_core.resolve()` answers the
  question and `isolate()` / `hide()` act on the answer, so the two commands
  cannot drift apart.
- New setting, **Hide Service Type puts elements away**: temporarily (default,
  undone by the same reset) or as Hide in View (undone by Reveal Hidden
  Elements).
- Hiding never takes the section box with it, and what was picked is always
  hidden whatever the keep-the-selection setting says.
- An element Revit will not let the view hide is dropped and counted rather
  than taking the whole call down with it.
- `bench_logic.py` is up to 97 checks and 7 deliberate breakages;
  `import_check.py` now proves the ribbon name of both command buttons.

## 1.2.0

- **The section box of a 3D view is always kept**, picked or not. Temporary
  Hide/Isolate takes it away with everything else unless it is in the list,
  and there is no way to select it beforehand.
- New setting, **Say nothing about elements left out of the isolation**, off
  by default. On, the run stops opening its report to tell you what it
  widened or skipped; the isolation itself is unchanged. A refusal still
  reports, because in that case nothing happened.
- `bench_logic.py` is up to 83 checks and 6 deliberate breakages.

## 1.1.0

- **A selected element whose category carries no service type now isolates
  too.** Pick a cable tray and an electrical board together and the tray
  isolates by service type as normal while the board brings its category with
  it.
- New Settings section, **Categories with no service type**: the whole
  category (default), only that family, only that type, or leave it out and
  say so - which is what 1.0.0 did.
- A category un-ticked out of every discipline group now falls to the same
  rule rather than being ignored.
- An off-category element on its own is enough to run on; it no longer refuses.
- `bench_logic.py` is up to 75 checks and 5 deliberate breakages.

## 1.0.0

First release.

- A pulldown on the **RevoBIM PY** tab, **Coordination** panel, inside the
  existing **Routines** pulldown: **RevoBIM Isolate Service Type** and
  **RevoBIM Isolate Service Settings**.
- The command opens no window. It reads the saved settings, reads the
  selection, and hands the result to Revit's own Temporary Hide/Isolate.
- Four discipline groups - cable tray, conduit, duct, pipe - each with its own
  service type parameter (default `Service Type`) and its own list of
  categories, all editable in Settings and remembered.
- A mixed selection applies every group's rule at once.
- Insulation and lining travel with what they wrap.
- Run it with nothing selected and the isolation resets.
- Ships `import_check.py` and `bench_logic.py`.
