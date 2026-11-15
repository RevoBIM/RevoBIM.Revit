# Schematic Builder - changelog

## 3.4.0
- **Dark is now Revit's own dark theme**, using the values sampled from Revit's dark Project
  Browser (title bar `#222933`, body `#3C4454`, fields `#2D3441`, selection `#3A7392`, edge
  `#515C6B`), the same as Project Browser Pro, Filter Manager and Pro Sheets. On Revit's lighter
  body the house muted grey, blue, orange and red all fall under 4:1, so they are lifted
  (`#ADB3BA`, `#62B6F0`, `#F0A048`, `#FF948C`); the light palette's orange is darkened for the same
  reason on its header bar. Theme.xaml's default brushes carry the dark values, so a window never
  flashes the old colours before the palette lands.
- **The theme follows Revit's canvas by default.** Settings > General offers follow / dark / light;
  follow reads `UIThemeManager.CurrentCanvasTheme` (Revit 2024+) and falls back to dark where it
  cannot. Existing settings files are migrated onto follow (settings version 3). The header chip
  still flips dark and light, and now repaints every open window of the tool, not just its own.
- **Shrink to taskbar on every window** - the main window, Settings, Equipment, both pickers, the
  parameter templates and the message box. The button sits top right beside full screen and close;
  pressing it slides the window down to the bottom of the screen like a drawer, leaving only its
  header bar floating above the taskbar, and the button becomes a green up arrow that brings it
  back. `Ctrl+Shift+H` does the same. While parked, Escape, Enter, F11 and a double click on the
  bar reopen it rather than closing, submitting or maximising; the bar can be dragged, and it
  reopens upward from wherever it was left. A modal dialog that is shrunk takes its owner down
  with it, stacked beneath, and brings it back when it reopens or closes; a dialog that opens while
  its owner is parked centres on the screen instead of on the bar. Works on a monitor above or to
  the left of the primary, where the work area has negative coordinates.
- **Every window is built one way** - `sb_ui.open_window` - which parses the layout, merges the
  theme, shows the version, sets the owner and attaches the chrome (drag, close, full screen,
  grips, drawer), all found by name. That replaced six hand-written copies of the same dozen lines,
  and it is why every window got the drawer at once. All six layouts now carry the same header
  cluster and resize grips.
- **Streamlined**: five dead functions and fourteen unused imports removed, the three colour helpers
  folded into one, and full screen and the drawer share one work-area helper. The window modules are
  about 220 lines longer overall - the drawer is most of that - but there is now one path through
  the window code instead of six.
- **Bench**: five new static rules, each proved by breakage - every window has the standard header
  and grips; windows are only built through `open_window`; the drawer releases both animations when
  the slide ends; dark matches Revit's sampled values and every text colour reads at 4:1 on every
  body colour in both palettes; and no unused imports or dead definitions. 20 new logic checks on
  the park and reopen arithmetic (including monitors above and to the left of the primary) and on
  following the canvas, with three new deliberate breakages.

## 3.3.0
- **The parameter dropdowns are rebuilt on a sounder mechanism.** They filtered by rebuilding the
  combo's items on every keystroke, which raised `SelectionChanged` on each rebuild - so every
  caller with a handler on that combo acted on a keystroke - and fought the text box for the caret.
  They now filter the **view** (`Items.Filter`), leaving the list itself alone.
- Behaviour is now exactly: the drop-down opens **only when clicked**, never on its own; opening it
  always shows **every** value whatever is in the box; typing **narrows it in place** while it is
  open, every word having to appear somewhere in the entry; and a name that is in no list can still
  be typed and is kept.
- Every handler that a genuine refill can still fire - the Main LV picker, the browser grouping
  values, the template category, the equipment rows, the template names - is muted while the refill
  happens, so a rebuild can no longer be read as a choice.
- **The bench gained a cross-module name rule.** The rewrite above deleted a block of helpers that
  the rest of the tool still called, and nothing caught it; every `other_module.name` is now checked
  to exist, proved by deliberately misspelling one.

## 3.2.1
- **Fixed: Equipment would not open in 3.2.0** - `TypeError: __init__() got an unexpected keyword
  argument 'settings'`. The equipment dialog's own edits never reached disk: one bad anchor in the
  edit that added them aborted the script before it wrote the file, so the window was called with an
  argument its constructor had never gained. The STRETCH BY column and the template button were
  missing with it; both are there now.
- **The bench now checks constructor calls too.** Its call-arity rule only knew about module level
  functions, so a class called with an argument its `__init__` does not take passed clean. Classes
  are now recorded through their `__init__` minus `self`, and the rule is proved by breaking exactly
  the call that shipped broken.

## 3.2.0
- **A board is stretched to span its circuits.** The Equipment table gains a **STRETCH BY** column:
  pick one of the detail item family's own length parameters and the tool sets it to the width of
  that board's outgoing ways plus a little past the last circuit each end (9mm, a setting). Type
  parameters are listed but flagged, since setting one resizes every item of that type.
- **Parameter templates are now the single way parameters are mapped.** The Equipment table's last
  column is **PARAMETER TEMPLATE** and opens the template window: the saved templates down the left
  with New / Save / Save as / Delete, the rows of the chosen one on the right, and three answers for
  the equipment - use this template, use the shared list from Settings, or write nothing. The
  Married Element List uses the same templates, so one built in either place is available in both.
  Rows saved before templates keep working and are offered as the starting point for one.
- **The template rows start with a category.** Pick the category and the *from* dropdown narrows to
  that category's own parameters, read from `doc.ParameterBindings` plus a sampled instance;
  `(tokens and anything)` gives the tokens and every parameter in the project. All three boxes
  search by keyword and accept a typed name.
- **Ticking one of several selected married rows ticks them all**, the same rule the template cell
  already followed.
- **Boards are placed straight above the board feeding them** where the boards to their left allow,
  and the drawing spreads past the A1 width rather than pulling them out of line.
- Bench: 9 more logic checks on the seven-field row and the template reference, and a self-test
  proving the alignment rule is caught if it stops working.

## 3.1.1
- **"Boards with a panel schedule only" is now on the LV tab itself**, beside the Main LV picker,
  as well as in Settings > LV. It is one setting shown in two places, so unticking it either way
  takes effect immediately and the view line under the tab says which way it is set.

## 3.1.0
- **Fixed: no feeders were drawn.** The circuits were read through `MEPModel`, whose members have
  moved between releases, and a failure there was swallowed. They are now read straight out of the
  document (`FilteredElementCollector(doc).OfClass(ElectricalSystem)`), taking each circuit's
  `BaseEquipment` as the supplier and its `Elements` as the loads; the MEPModel route is kept only
  as a fallback.
- **The report now says why**, so a blank drawing is explainable: how many circuits exist in the
  project, how many have a supplying panel, how many of those panels are on the drawing, and how
  many became feeders - with a different sentence for each place the chain breaks.
- **A Main LV board can be nominated** from a dropdown on the LV tab. **Read panels** lists every
  electrical equipment instance in the model, marking the ones with no panel schedule, and the
  choice is remembered.
- **Boards are stacked in rows by their same-floor feeds.** The Main LV sits on the bottom row of
  its level and the boards it feeds sit on the row above, and so on - so a supplying board is
  always below the boards it feeds, as on a real LV schematic. The wire between them is the same
  orthogonal dog leg: out of the top, across between the rows, into the bottom.
- The Main LV's symbol is **stretched across its outgoing ways** where its detail item family is
  line based (a setting), which is what gives the long horizontal switchboard of the reference
  drawing.
- Row spacing is a setting (28mm), and the bench holds the row rule to 16 checks including that no
  wire crosses a board it does not serve, with a self-test proving that flattening the rows is
  caught.

## 3.0.0
- **LV Schematic - first cut.** The LV tab is built: the same pairing of model families to detail
  items, the same levels, rooms, browser grouping, parameter transfer and marrying as Ventilation,
  and then the feeders.
- **Only equipment with a panel schedule** is placed by default (Settings > LV), read from the
  project's `PanelScheduleView`s; anything paired but unscheduled is counted in the report.
- **Circuits become feeders.** Every circuit whose supplying panel and fed panel are both on the
  drawing is drawn as an orthogonal dog leg in the circuit line style: up out of the top of the
  supplier in its own lane, across in a jog band under the fed panel's level, up into its bottom.
- **18mm between feeders leaving one panel** (a setting), and the panel's slot on the drawing is
  widened to hold them, with the symbol centred in it.
- **Panels are moved clear of feeders rising through their level.** Levels are laid out bottom-up;
  each one shifts its rooms sideways off the lanes passing through it. The LV drawing grows to the
  right rather than wrapping into rows, and the level lines run its full width.
- **Jogs that would overlap under one level are staggered**, and that level's clearance above its
  line grows to fit them (30mm minimum, a setting).
- Feeders that go sideways (same level) run over the top of both panels; feeders that go down leave
  the bottom of the supplier. Both are routed but not yet kept clear of, so any crossing is counted
  in the report as the thing to look at next.
- `sb_lv.py` is pure Python: the bench holds it to 26 checks - orthogonal, four-point dog legs, 18mm
  apart, leaving the top and arriving at the bottom, the jog above the level line, no board on a
  lane, forty boards in one row with the drawing widened, and a self-test proving that switching
  lane avoidance off is caught.
- The Ventilation tab's equipment card gained the PARAMETERS column it was missing.

## 2.10.0
- **Opening a parameter dropdown always shows the whole list.** Picking an entry put its name in
  the box, which the search then read as a keystroke and narrowed the list to that one entry - so
  the next open showed a list of one. Opening by the arrow now restores the full list; typing still
  filters.
- **The lists hold every parameter of the category, not a sample.** They were built from whatever
  happened to be on the first six married elements. They now take everything bound to the model
  elements' categories and the detail items' category from `doc.ParameterBindings`, plus one
  sampled element per distinct type rather than per row, so a parameter that exists but is empty
  everywhere still appears.
- The line under the template says how many names came from each side.
- The keyword rule itself moved into `sb_logic.keyword_matches` so the bench can hold it to
  account: 7 checks, including that an empty box offers everything and that word order does not
  matter, and a deliberate breakage proving a naive substring match is caught.

## 2.9.0
- **The married list selects like a normal list**: click, shift-click for a run, ctrl-click to add
  or remove. An assignment applies to everything ticked **and** everything highlighted, so either
  way of picking rows works and they can be mixed.
- **The TEMPLATE column is a dropdown.** Click into any row's cell, pick a template, and it is
  given to that row - or, if that row is part of the current selection, to the whole selection at
  once. Picking `(none)` clears it. A template that has since been deleted still shows on the row
  it is assigned to, in red, rather than reading empty.
- **New** starts an empty template, and **Save as new** keeps the original and saves the rows under
  the name typed in the box, refusing a name that is already taken. **Save** still replaces the
  template of that name.
- A cell handler no longer rebuilds the list it was fired from - the sibling dropdowns are updated
  in place instead, since destroying the control mid-event is a good way to take WPF down.
- The bench's undefined-globals rule caught a missing `Control` import during this change, which is
  what it is there for.

## 2.8.0
- **A template can be assigned to a selection of married elements.** Tick as many rows as you like,
  pick the template, press **Assign template to ticked**; a TEMPLATE column shows what each detail
  item carries, green where the template exists and red where it has since been deleted.
  **Unassign** clears it from the ticked rows.
- Assignments are saved **per project** (keyed by the model title), so each job keeps its own
  pairing and they are all there next time the model opens. An assignment to a detail item that has
  been deleted is dropped on the next read.
- **Run applies each item's own template**, so one run can push different parameter sets onto
  different equipment. Anything ticked with no assignment falls back to the template on screen, and
  if there is none it is left out and counted rather than guessed at. The report gives a line per
  template plus the totals.
- **The template panel is resizable** - drag the bar between the list and the template to make
  either bigger.
- Bench: 10 more logic checks on the per-project assignments and the batching, and 2 more
  deliberate breakages.

## 2.7.0
- **Every detail item Create places is married to its model element.** The model element's id is
  written into a text instance parameter on the detail item, `BGL_Linked Element ID` by default and
  named in Settings > Parameters. Detail items whose family lacks the parameter are counted and
  reported, since they cannot be found again without it.
- **New tab, Married Element List**, green so it reads as the one that works the other way round.
  "Read the model" lists every detail item in the project carrying a value in that parameter: the
  drafting view it is on, the detail item, the linked id, the model element it resolves to, and a
  status that goes red where the id is not an element or the element no longer exists. Keyword
  search, tick all shown / none, double-click to tick.
- **Parameter templates.** As many from/to rows as wanted, saved under a name against the settings
  file and picked from a dropdown; dropdowns are seeded from the parameters actually on the married
  elements once the model has been read, and narrow as you type. The footer button becomes "Run
  template on ticked": each ticked detail item's model element is found again through the id and
  the template's values pushed across, with read-back, an "already correct" count, and the same
  type-parameter and missing-parameter reporting as Create. Ticked items whose element is gone are
  left out and said so.
- Bench: the templates and link id parsing are covered by 6 more logic checks and 1 more
  breakage; import_check gains a **15th rule, no unreachable code**, after a pasted block landed
  after a `return` and nothing noticed.

## 2.6.0
- **The room name sits closer to the corner**, and is set by two offsets of its own rather than
  sharing the room line offset: "Room name in from the left edge" and "down from the top edge",
  both 3mm by default. The room offset now only governs the clearance around the equipment.
- A long name still widens the room, but only to the name plus its own offset on the left and the
  room offset on the right, so the box no longer grows a wide margin on both sides.
- **Settings is now tabbed**: General, View names, Rooms, Styles, Levels, Spacing and Parameters.
  Nothing scrolls, each page holds one subject, and the window carries its own resize grips and a
  full screen button so it can be stretched.
- Every page keeps its own explanation of what the settings on it actually do.
- Bench: the room name checks now prove it sits nearer the corner than the room offset would put
  it; the settings tab and page names are checked against the layout by import_check.

## 2.5.0
- **The room name sits in the top left corner of the room box, indented from both edges**, with the
  equipment centred in the room beneath it. The indent is a setting (Room name indent, 10mm by
  default) beside the room line offset.
- The box is now whichever is wider: the equipment plus its offset each side, or the name plus its
  indent each side - so a long room name widens the room rather than running out of it.
- Text notes are anchored by their **top left corner** (`VerticalTextAlignment.Top`), so a label is
  placed by the corner rather than by guessing at its baseline. This applies to the level labels
  too, which sit above and left of their line.
- Bench: 9 more logic checks on the name's position, and 1 more deliberate breakage.

## 2.4.0
- **Levels move up to make room.** Level line spacing is no longer a fixed pitch: each level's band
  is laid out first, and the level above is placed clear of whatever it needed. A level that wraps
  into three rows of rooms simply pushes everything above it up. Where there is space to spare it
  is shared out evenly, so a light schematic still reads as evenly spaced lines.
- Nothing is clipped and nothing overlaps: rooms grow to fit their equipment, bands grow to fit
  their rooms, and levels grow to fit their bands. If the result is taller than the sheet it is
  still drawn in full and the report says by how much, rather than levels running into each other.
- The report now gives the drawing height against the sheet, and names the levels that were given
  extra room and how many rows they took.
- **Parameter dropdowns narrow as you type.** Every word typed has to appear somewhere in the
  entry, so "bgl mark" finds "BGL_Instance Mark". Clearing the box brings the full list back, and
  a name that is not in the list can still be typed. Applied to the mapping dialog's from and to
  boxes, both room parameter boxes in Settings, and the browser grouping values.
- Bench: 12 more logic checks on the stacking and wrapping, 2 more deliberate breakages.

## 2.3.0
- **The room name can be read straight off the element.** Settings now carries "Room name from":
  either the room the element sits in (host model, then every link - as before) or **a parameter on
  the element itself**. In element mode the equipment is grouped by that parameter's text, so
  anything reading the same name shares one room box, and equipment with the field blank is drawn
  without a box and counted. The dropdown is seeded with the parameters actually found on the
  paired equipment families, and is editable.
- **Parameter mapping per equipment row.** A fourth column in the Equipment table opens a mapping
  dialog for that row: use the shared list from Settings, write **nothing** (skip), or set out its
  own from/to list. The "from" dropdown is seeded with the parameters on that row's families plus
  the tokens; the "to" dropdown with the instance parameters read off a placed detail item of that
  type. Both are editable, so a name that could not be sampled can still be typed.
- Rows saved by 2.1.0 and 2.2.0 read unchanged and inherit the shared list.
- The Equipment card on the main window shows each row's mapping mode, and the report names any
  equipment set to skip.
- Bench: 12 more logic checks, 1 more deliberate breakage; the new module and layout are covered by
  every import_check rule.

## 2.2.0
- **Revit stays usable while the results are on screen.** The results and error windows are raised
  modeless. A WPF modal dialog disables every window on Revit's thread, so the report itself was
  what locked Revit until OK was pressed. The main window was already modeless; Settings, Equipment
  and the pickers stay modal on purpose while they are being edited.
- **An unticked level now really is left out.** Its line was already skipped, but the equipment on
  it was falling through to the lowest ticked level. Levels are now identified against every level
  in the project and then checked against the ticks, so equipment on an unticked level is left out
  and the count is reported per level.
- **"Element N could not be read" now says what could not be read.** Each field of an element is
  read on its own, so an awkward element loses a room name or a mark rather than dropping out of
  the schematic, and the report names the field and Revit's own message.
- A transfer target that exists only as a **type** parameter on the detail item is reported as such
  rather than as missing, since writing it would change every item of that type.
- Bench: 4 more logic checks and 1 more deliberate breakage.

## 2.1.0
- **Several model families can share one detail item.** The family column of the Equipment table
  now opens a multi-select picker: tick as many families (or family types) as the detail item
  stands for, with Tick all shown / None, and a running count. Ticks survive changing the category,
  keyword or "split by type" filter, so a selection can be built up across several searches.
- The row stores the whole selection (`family::type;;family::type`); rows saved by 2.0.0 are read
  unchanged, so nothing has to be re-paired.
- An element is never drawn twice when both a whole family and one of its types are ticked.
- The Equipment card shows the number of family selections and turns the cell red naming any family
  with no placed instances.
- Bench: 11 more logic checks on the pair encoding, and two more deliberate breakages proved.

## 2.0.0
- Rebuilt on the RevoBIM house pattern: `sb_clr` assembly module first, key=value settings at
  `%APPDATA%\RevoBIM\schematic_builder.txt`, `Theme.xaml` with dark and light palettes, staged loading
  in `script.py`, `import_check.py` (14 rules, all proved by breakage) and `bench_logic.py`.
- Tabs for Ventilation, LV, Drainage, Rainwater and Water Services schematics. Only Ventilation is
  built; the others are placeholders that still remember their browser grouping.
- Settings (header chip): scale (default 1:1), sheet size and margin, the five view name prefixes,
  level and room line styles, level and room text types, room name parameter, level label format,
  the level table (include tick + abbreviation), spacing, parameter transfer, results, theme.
- Project browser grouping per tab: up to three view parameters, value picked from those already in
  use or typed; written onto the new view; remembered.
- Equipment table (Ventilation): equipment type / family & type in the model / detail item, with a
  picker filterable by category, used-only and keyword, split by type or whole family.
- Ventilation build: evenly spaced level lines for the sheet size, level label above-left of each
  line, detail items placed above their level line clear of it, clustered by room with a room box
  at the offset in the room line style and the room name inside, wrapping into rows when the sheet
  width runs out, overflow reported. Level, room, mark, type mark and equipment type available for
  parameter transfer onto the detail items.
- Views named `<prefix> N` with the first free number.
- Detail item tagging from 1.x dropped for now (see open items).

## 1.1.0
- Line based detail items supported; view activated and zoomed; UI handlers guarded; per element
  sub-transactions removed; >1000 item warning; ExternalEvent raise result checked.

## 1.0.0
- First version: married model families to detail items, placed by host level in `WIP_Schematic<n>`.
