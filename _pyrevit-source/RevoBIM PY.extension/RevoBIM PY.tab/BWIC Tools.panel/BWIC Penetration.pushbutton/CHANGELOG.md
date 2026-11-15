# BWIC Penetration — changelog

## 2.19.0

### Clearance lives in Family settings only
- **The clearance and gap boxes are gone from the main window** (Wall
  Rectangular Clearance group, Wall and Slab circular Gap rows, Slab
  Rectangular Clearance group, Global Placement Clearance) and from Settings.
  The circular groups are now "Hole size" (round up, insulation); Global's is
  "Grouping".
- **Family settings has the clearance in a bold blue box**, mm each side (the
  gap around the pipe on a circular family).
- **Every family starts at 50 mm** until changed. Families saved before this
  use 50 mm. A blanked box is flagged.
- Global Placement uses the wall rectangular family's clearance.

### Family settings before anything runs
- **Place BWIC, Place Slab BWIC and Global Placement will not start until the
  family they use has its Family settings saved.** An orange "NOT STARTED"
  prompt, held for 6 s, names the family and tab and says what to do. The
  family card says so too, in orange.
- Slab Automatic needs both families set up.
- **Resize existing BWIC only accepts BWICs whose family is set up** -- a
  BWIC is never resized by guesswork. With none set up, it does not start.

### Set-up families green and first
- In every family list, families with saved Family settings are **green, with
  a tick, sorted to the top** (A to Z), then the rest as before. The lists
  re-sort as soon as Family settings are saved.

### Bench
- 8 new logic checks. New rules: nothing starts before its family is set up;
  resize accepts set-up families only; no clearance box left on the main
  window; set-up families green and first. 6 deliberate breakages, all
  caught.

## 2.18.0

### A clearance per family
- **Family settings has a Clearance row** (under Shape), in mm each side, for
  rectangular and circular families on the Wall and Slab tabs.
- **Blank follows the tab**, as before: the clearance on a rectangular tab,
  the gap on a circular one. The row says which figure that is.
- A family's own clearance is used wherever that family is placed or
  resized: wall rectangular and circular, slab rectangular and circular,
  Resize existing BWIC (the picked BWIC's family) and Global Placement (the
  wall rectangular family).
- 0 is a real clearance, not blank. Anything that is not a number of mm is
  flagged in Family settings and the tab's figure is used.
- The family card summary shows "Clearance n mm" when a family has its own.
- The debug log says, for each family, which clearance it used and where it
  came from.

### Bench
- 9 new logic checks. New rules: wall place, wall resize, round wall, round
  resize, slab and Global Placement each ask the family for its clearance;
  Family settings saves it. 6 deliberate breakages, all caught.

## 2.17.1

### Fixed: Finish Selection did nothing
- The click reached the tool (the log shows "Return sent"), but the Return
  it typed went to whatever had the keyboard -- the tool window itself, just
  clicked -- so Revit never saw it.
- **It now presses Revit's own Finish button on the Options Bar** instead of
  typing anything: first as a Windows button (BM_CLICK), else through UI
  Automation (Invoke), and only if neither finds it, Return posted straight
  to the active view's window. "Finish" or "&Finish" only -- never "Finish
  Edit Mode" or anything that merely starts the same way.
- It runs on its own thread once the click has been handled, as Revit only
  answers while its UI thread is free; nothing can escape that thread.
- The keyboard is handed back to Revit, so the next pick (the wall) answers
  straight away.
- The debug log says which way it pressed Finish, or, if it found nothing,
  what it did find -- send that log if it still does nothing.

### Blue border round the step prompt
- The step card under the buttons, and the floating one over Revit, have a
  blue border.

### Bench
- 5 new logic checks for which button counts as Finish. New rules: nothing
  types into whatever has the keyboard; Finish is pressed off the UI thread;
  no exception can escape that thread. 4 deliberate breakages, all caught.

## 2.17.0

### Step prompts in the tool window
- **The step card now sits at the bottom of the tool window, under Place
  BWIC** (and under the Slab buttons): step n of m, what to pick, how the
  step ends, then "BWIC placed" in green for 2 s. Messages when no run is
  going show there too.
- **While the window is shrunk to the taskbar the card floats over Revit**,
  as before, so a step is never shown where it cannot be seen. Shrinking or
  opening the window mid-step moves the card across.

### Finish Selection button
- **A green Finish Selection button under the step card**: the same as Finish
  on the Options Bar or Return. It is dimmed until a step is waiting on a
  selection, then lights up green with a glow.
- It can be pressed once per step, and only while a selection is waiting --
  Return in Revit with nothing waiting repeats the last command, so it never
  sends one then. Placing, a problem, Esc or the end of the run dims it.
- Not shown on Global Placement, which has nothing to select.

### Family lists by shape
- **Rectangular sections list only rectangular families, circular sections
  only circular ones.** A family with a Diameter or Radius length parameter
  is circular; anything else is rectangular.
- Instance parameters are only visible once a family has been placed, so a
  family never placed in the model also counts as circular if its name says
  circular or round.
- A saved choice of the other shape is kept, labelled [circular] or
  [rectangular], rather than swapped for another family.

### Bench
- 14 new logic checks. New rules: the lists are sorted by shape; the step
  card is docked and floats while parked; Finish Selection only sends Return
  while a selection is waiting, once, and dims when the run ends.
  9 deliberate breakages, all caught.

## 2.16.1

### Fixed: a Standard family sized through X+ / X- parameters
- A family set back to Standard could still be sized through the X+ / X-
  pairs from an earlier run. When its Standard settings left a size blank,
  the tool kept the last run's parameter name instead of going back to the
  default. Every size now resets on every run: the family's Standard
  parameter, else BGL_Length / BGL_Width / BGL_Height. Same fix for resizes.
- The debug log now lists the size parameters at the start of each run, so
  a log shows what a family was sized with.

### Fixed: a pipe's fall or angle grew the wall opening
- Straight runs were measured end to end. A 110 drainage pipe with a fall
  added the whole fall to the height (245 mm instead of 210), and a run
  crossing the wall at an angle added its spread along the wall to the width.
- Pipes, ducts, trays and conduit are now measured only where they are
  inside the wall: diameter (or width / height) + clearance each side, plus
  only the slope over the wall's own thickness. A run parallel to the wall is
  measured whole, as before. Fittings and accessories are unchanged.
- The debug log shows both: measured inside the wall, and over the whole
  runs.
- Global Placement already measured inside the wall and is unchanged.

### Bench
- 6 new logic checks for the in-wall stretch, including the drainage fall.
  New rules: wall openings measure runs inside the wall; a blank size name
  goes back to the default, never the last run's.

## 2.16.0

### A workset per sub tab
- **The Workset choice in Family settings has moved under the Standard |
  X+ / X- (Y+ / Y- on circular families) sub tabs**, and each sub tab keeps
  its own. Switch sub tab and the list shows that sub tab's workset.
- **The sub tab the family is set to decides the workset** its BWICs go on,
  for placing, Resize existing BWIC and Global Placement. Set a family to
  Y+ / Y- and it uses the Y+ / Y- workset; set it back to Standard and it uses
  Standard's.
- Each sub tab offers the same choices as before: As Settings, <active
  workset>, or any workset by name.
- A family saved with 2.15.0's single workset keeps it on both sub tabs.
- The card summary names the workset of the sub tab in use.

### Bench
- 6 new logic checks. New rules: Family settings saves both worksets;
  switching sub tab keeps the one chosen on the other; Global Placement gets
  the workset of the sub tab in use. 8 deliberate breakages, all caught.

## 2.15.0

### A workset per family
- **Family settings has a Workset row**, under Shape, for rectangular and
  circular families on both the Wall and Slab tabs.
- **As Settings** (the default) uses the workset chosen in Settings, as
  before, and shows which one that is. **<active workset>** leaves the BWIC on
  whichever workset is active, whatever Settings says. Any workset in the
  model can be picked by name.
- The family's choice wins over Settings for placing and for **Resize
  existing BWIC**, where the BWIC picked uses its own family's workset.
- **Global Placement** places the wall rectangular family, so it follows that
  family's workset too. A workset chosen by name is never swapped for a
  "BWIC" keyword match.
- A saved workset this model doesn't have is kept and marked "(not in this
  model)"; placing then notes "workset ... not found" and the BWIC lands on
  the active workset. A model that is not workshared ignores it.
- The family card summary ends with "Workset: ..." when a family has its own.

### Bench
- 8 new logic checks. New rule: every place and resize goes through
  place_on_workset, which asks the family first; Family settings saves the
  workset; Global Placement reads it. 5 deliberate breakages, all caught.

## 2.14.0

### Y+ / Y- for circular families
- **Family settings for circular families has Standard and Y+ / Y- now.**
  Standard is as before. Y+ / Y- has one group, **Y = Length**, with a Minus
  and a Plus parameter: the two add up to the thickness through, each taking
  half.
- On a **circular wall family** the pair is the thickness through the wall. On
  a **circular slab family** it is the vertical size through the floor.
- The diameter (or radius) stays a single parameter either way, and is still
  required. Only the through row is swapped for the pair.
- A round family whose names include a Y pair (WLG_Y_Minus, WLG_Y_Plus) starts
  out as Y+ / Y-; a plain sleeve with Diameter and Length stays Standard.

### Resize uses the picked BWIC's own family settings
- **Resize existing BWIC now sizes the BWIC you pick with that family's own
  Family settings**, not those of whichever family the tab has chosen. A
  different family, a round one or an X+ / X- one is sized with its own
  parameters.
- A family with no saved settings is sized by a guess from its own
  parameters, starting from today's settings -- so the default families keep
  their names exactly.
- **The opening keeps its family.** Whether it is round or rectangular comes
  from the family, not from the services selected. Before, a slab resize could
  swap a round opening for a rectangular one when a tray was added; it now
  re-fits the BWIC you picked.
- The pick accepts any BWIC family you have set up: those chosen on the tabs,
  plus any with saved Family settings. A round wall BWIC can be resized from
  the Rectangular tab; it uses the gap and round-up on the Circular tab.

### Bench
- 32 new logic checks. New rules: wall and slab resizes use and restore the
  picked BWIC's family; a resize looks up the family settings; the round
  figures always reach the core. The round-run restore rule now looks inside
  run_placement_loop itself -- the new resize restore had been satisfying it
  by accident, found by a deliberate breakage. 11 new deliberate breakages, all
  caught by the rule meant to catch them; the 74 earlier ones still are.

## 2.13.0

### X+ / X- families
- **Family settings for rectangular families has two kinds now: Standard and
  X+ / X-.** Standard is everything as before. X+ / X- is for families not
  driven equally from the centre, sized by a parameter on each side -- for
  example WLG_X_Minus and WLG_X_Plus.
- **Three groups: X = Width, Y = Length, Z = Height**, each with a Minus and a
  Plus parameter. Each side takes half the overall size, so Minus + Plus is the
  overall size and the two are always equal. On a wall, Y is the thickness
  through the wall; on a slab, X and Y are the plan sizes and Z the vertical
  height.
- **Every other rule still applies** -- clearance, rounding, rotation,
  centring by measurement, resize, the blockwork and fire rated types. The
  overall size is worked out exactly as before; only the final write splits it.
- **Suggest from names** recognises pairs (an axis letter standing on its own
  plus a minus or plus word), and a family whose only sizes are pairs starts
  out as X+ / X- the first time its settings are opened.
- Both sides are checked before either is written, so a pair is never left
  half sized. A pair missing a side, one parameter used for both sides, or a
  required axis with no pair is flagged in the dialog.
- Global Placement now uses the same size writer as the Wall and Slab tabs, so
  X+ / X- wall families work there too.
- Circular families are unchanged: they have no X+ / X- option.

### Bench
- 21 new logic checks on pairs. New rules: the size writer splits pairs and
  checks both sides before writing; nothing checks a size parameter directly;
  Global Placement has no writer of its own; and the "tab handler checks where
  SelectionChanged came from" rule now covers every window, not just the main
  one. 9 new deliberate breakages, all caught by the rule meant to catch them;
  the 65 earlier ones still are.

## 2.12.2

- **The information box under the buttons is gone**, and the debug row with it.
  The window is about 110px shorter.
- **Debug, Open log and Clear are in the Options group** on all three tabs.
  The three tick boxes are one setting: ticking it on any tab ticks it on all.
  Open log and Clear are always available; Open log says so if nothing has been
  logged yet.
- **Messages now show briefly on the step prompt** at the top of the Revit
  window -- "Pick a circular family first", "Family settings saved" and the
  like -- for three and a half seconds. During a run the prompt is already
  saying what is happening, so messages then go to the debug log only. The
  "Ready." message on opening is gone.
- The run is flagged before its opening message, so the prompt goes straight
  to step 1 rather than holding it behind a note.
- **Bench:** a run must be flagged before its first message and unflagged when
  it ends; report() must not show notes during a run; the status box must not
  come back. 6 new deliberate breakages, all caught; the 59 earlier ones still
  are.

## 2.12.1

- **Fixed: the tool would not open in 2.12.0** -- "'Content' property has
  already been set on 'Expander'". A collapsible group holds one element as its
  content, and twelve of the eighteen groups put a hint and their fields side by
  side inside it. Valid XML, so nothing complained until Revit loaded the
  window. Every group's contents now sit in one panel.
- **The bench now catches this whole class of fault**: any Expander, Border,
  ScrollViewer, Button, CheckBox, TabItem or other single-content control
  holding more than one element fails, naming the control. Proved by putting
  the shipped fault back.

## 2.12.0

### Families chosen where they are used
- **Family selection has moved out of Settings into the main window.** Each
  tab now opens on its family: preview image, the project's generic model
  families, the type, a one-line summary of how it sizes, and Family
  settings... -- the first group on every sub tab.
- The family lists are read again whenever one is opened, so a family loaded
  into the project while the tool is open turns up without restarting it. A
  saved family that is not loaded is kept and marked rather than swapped.
- A family choice is saved the moment it is made.
- Settings keeps clearances, round-ups, grouping distances, the placement rule,
  the type names for blockwork and fire rated walls, and the workset. Its
  "Show families" filter is gone: every list shows every generic model.

### Sub tabs
- **Wall: Rectangular | Circular.** The tab you are on decides what Place BWIC
  places; the button says "Place Circular BWIC" on the Circular tab.
- **Slab: Rectangular | Circular | Automatic.** The sub tab replaces the old
  Method dropdown -- the tab you are on is the method. Automatic shows both
  families it will use and how it splits services between them.

### Circular wall BWICs (new)
- A circular family of its own for walls, with its own Family settings: the
  parameter through the wall, and the diameter or radius.
- **A single pipe** gets its real outside diameter (insulation included, by
  choice) plus the gap each side, rounded up. **A group, or a service with no
  diameter,** gets the circle that encloses its cross-section -- the
  rectangle's diagonal, since a circle only as wide as its longer side would cut
  the corners off. DN100 steel at 50 mm gap and 10 mm steps: 220 mm. A 300 x 100
  tray: 420 mm.
- The round family is swapped in for the length of the run only and the
  rectangular one always put back, whatever the run ends with. Resize works on
  round BWICs too.
- The rectangular wall family now also has a type list: the default type, used
  where no blockwork or fire rated rule applies.

### Collapsible groups
- Every section on all three tabs is now a group that folds away from its
  header, with a chevron and a coloured tick -- blue for the main groups,
  orange for options and help. Each remembers whether it was left open.

### Fixed along the way
- **SelectionChanged bubbles in WPF**, so choosing a family inside a tab also
  fired the tab handlers above it. The main tab handler was quietly re-saving
  settings on every dropdown change. Every tab handler now checks where the
  event came from.

### Bench
- New rules: every tab handler checks where SelectionChanged came from; every
  group is in the open/closed memory; one family card per slot and none left in
  Settings; the circular wall run uses its profile, reaches the core, sizes by
  round_hole_mm and puts the rectangular family back. 12 new deliberate
  breakages, all caught by the rule meant to catch them; the 48 earlier ones
  still are.

## 2.11.0

### Step prompts for manual placement
- **A prompt says what to pick next.** Pressing Place BWIC, Resize, Place Slab
  Penetration or Resize on the Slab tab now shows a card at the top centre of
  the Revit window: *Step 1 of 2 - Select the services ... then click Finish on
  the Options Bar*, then *Step 2 of 2 - Click the wall* (or the floor). Resizing
  adds a first step for the BWIC or opening to re-fit.
- **"BWIC placed" shows for two seconds**, in green, then the prompt moves on to
  the next placement's first step. Press Esc and it closes. If nothing could be
  placed it says so in orange for three seconds. The tool window stays open
  throughout, as before.
- The prompt is **click-through and never takes focus**: the tool window taking
  focus is what once stopped Return finishing a selection, and the prompt must
  not bring that back. It sits below the ribbon and Options Bar, clear of Finish.
- The wording lives in one table in the core (`FLOWS`, `STEP_TEXT`), and the
  timing in `bwic_prompt.py`. A prompt can never stop a run: an unknown step
  falls back to a plain prompt instead of raising.

### Family settings
- **Each family slot in Settings is now a card**: the family's own preview image
  on the left, the generic model families loaded in the project in a list, the
  type, a one-line summary of how it sizes, and a **Family settings...** button.
  The wall family is chosen from the list rather than typed; a saved family that
  is not loaded is kept and marked rather than swapped for another.
- **Family settings** says how a family sizes itself: its shape, and which of its
  parameters takes each role -- through the wall, width, height, plan width and
  depth, diameter or radius, and for slab families vertical height, top height,
  offset, base and top level and offset, and the level code. Saved per family
  name in `%APPDATA%\RevoBIM PY\place_bwic_families.json`, so switching family
  brings its own settings back. **Suggest from names** fills the rows by matching
  Length, Width, Height, Diameter and so on.
- **Other families now size correctly.** A round wall family takes the larger of
  width and height as its diameter -- or half of it, when its parameter is a
  radius -- and slab families can be sized by radius too. Each slab opening uses
  its own family's settings, so a rectangular and a round family built
  differently can share one run.
- The eleven parameter pickers on the Settings tabs moved into Family settings,
  which can see each family's own parameters. Clearances, round-ups, gaps,
  grouping and the placement rule stay in Settings.
- **Nothing changes until you save a family's settings.** A family with none
  saved keeps every existing parameter setting; its card says "Not set up yet,
  so using:" and what that is.
- Global Placement reads the wall family's settings too, but still places
  rectangular openings only.

### Bench
- New `logic_bench.py`: 45 checks on the prompt's timing and the family
  profiles. New rules: every pick announces its step, every loop announces its
  end, every step named exists, and Apply, each slab opening and Global
  Placement all use the family profiles. 17 new deliberate breakages, all caught
  by the rule meant to catch them; the 30 earlier ones still are.

## 2.10.1

- **The dark theme now matches Revit's own dark colours**, sampled from the
  Revit 2024 Project Browser: blue-grey rather than neutral grey, on all three
  windows.

  | Role | Was | Now |
  |---|---|---|
  | Window | `#3B3B3B` | `#3C4454` |
  | Cards, tab body | `#454545` | `#323C48` |
  | Fields, status box | `#2E2E2E` / `#353535` | `#2D3441` |
  | Lines | `#5A5A5A` | `#505968` |
  | Dividers | `#4A4A4A` | `#404353` |
  | Text | `#E8E8E8` | `#EEF1F5` |
  | Muted text | `#A6A6A6` | `#9DA4B2` |
  | Window edge | `#4A4A50` | `#212932` |
  | Ghost button | `#4E4E4E` | `#4A5366` |
  | Disabled button / text | `#555555` / `#8E8E8E` | `#465062` / `#7B8290` |

- The accents -- RevoBIM blue, orange, red and the green reopen arrow -- are
  unchanged. Contrast was checked on every background: body text is 8.6 to 11
  to 1, and muted text on the window is 3.9 to 1, the same as before.

## 2.10.0

- **Global Placement tab**, merged in from the standalone BWIC Global
  Placement tool (v0.9.0). Pick the link, open the plan for the floor, press
  Run: every fire rated wall (any value in POP_PERF_FireRatingTarget) and every
  blockwork wall in that link gets a BWIC around each group of pipes and cable
  trays passing through it in the active view. Groups that already have a BWIC
  are skipped, overlaps are boxed in red and failures in amber for review.
- **The engine came across unchanged** as its own module, `bwic_global.py`, so
  its constants (`FAMILY_NAME`, `P_LENGTH`, `WORKSET_KEYWORD` and others) do
  not collide with the identically named ones in `bwic_core.py`. Its
  `configure()` hook means it now reads **the same Settings as the Wall tab**:
  family, fire rated and blockwork type names, size parameter names, round-up
  step and the workset chosen in Settings. Before, it had its own hard-coded
  copies, so changing the family in Settings would have left Global Placement
  on the old one.
- **Fixed in the merge: Global Placement would not have run on Revit 2026 or
  2027.** It read ElementIds through the integer property Revit removed in
  2026, in 14 places, including the category check every service passes
  through. They now go through the tool's existing `eid_value()` helper.
- **The results window** comes across with the tool's current chrome: rounded
  borderless shell, version top right, and the shrink-to-taskbar drawer, so
  all three windows behave the same. It is modeless; Select the flagged BWICs
  goes through its own external event.
- **Tab icons** on all three tabs -- brickwork, a slab with a service through
  it, and a globe for the view-wide sweep -- drawn as vector paths in the tab's
  own text colour, so they brighten with the label.
- Global Placement figures, ticks and the chosen link are remembered with the
  rest of the settings. A link selected in the model before opening the tool
  still wins. Its run notes now go into the tool's one debug log.
- **Bench:** the engine is checked by every existing rule. New rules: every
  module alias `script.py` uses (`gp.`, `drawer.`, not only `core.`) must
  define the name it reaches for, and a `*_click` handler that no button calls
  fails -- the reverse of the existing XAML check, which let a button with its
  Click removed pass. 7 new deliberate breakages, all caught; the 23 earlier
  ones still are.
- Remove the old **BWIC Global Placement** pushbutton folder if it is still in
  the extension, or there will be two ways to run the same engine.

## 2.9.0

- **Shrink to the taskbar, on every window.** A new button top right, beside
  close, on both the tool window and Settings. Pressing it slides the window
  down to the bottom of the screen like a drawer closing, leaving only its
  header bar floating clear of the taskbar so the model can be seen. The
  button turns into a **green up arrow** that opens it again.
- Built to the RevoBIM shrink-to-taskbar standard, in one shared helper,
  `bwic_drawer.py`, so the gesture is identical on both windows: Top and Height
  eased together on a 15 ms timer over 0.28 s, landing 8px above the working
  area, bars stacked 4px apart when more than one is parked.
- **Ways back:** the green arrow, a double click on the bar, Esc, Enter or F11
  while parked, or Ctrl+Shift+H, which toggles either way. The bar can still be
  dragged; if it has been moved, the window opens upward from where it now
  sits, kept on the screen, rather than jumping back.
- **Settings lifts the tool window with it.** Shrinking Settings parks the main
  window first and stacks above it, so the whole tool gets out of the way;
  reopening or closing Settings brings it back. Settings is modal, so while it
  is open Revit can be seen but not worked in -- the same limit every RevoBIM
  dialog has.
- Escape in Settings is now handled by the tool rather than pyRevit, so that
  while it is parked Escape reopens it instead of closing it with your edits.
- **Bench:** `import_check.py` fails if a window is built without a drawer, if
  a shrink button is drawn but not wired, if the slide never releases Top or
  Height, or if the parking arithmetic goes wrong -- including a second monitor
  above the primary, where clamping a negative top to zero sends the bar to the
  wrong screen. `drawer_bench.py` drives the whole shrink, park and reopen cycle
  against a stand-in window. 48 checks, and 20 deliberate breakages each caught
  by the rule meant to catch it.

## 2.8.0

- **Resize existing BWIC from selection, on the Slab tab.** Pick an existing
  slab opening, then the services passing through it, then the floor. It is
  re-sized, turned and re-centred to exactly the rules a new placement follows.
- **Placing and resizing share one code path.** The placement was split into
  "create the instance" and "apply everything to it", and resize reuses the
  second half whole, so a resized opening cannot drift from a newly placed one
  as the rules change.
- **The shape is re-decided from the services**, so a tray added to a group of
  pipes turns a round hole into a rectangular one. The family is swapped when
  that happens and the change is reported; if Revit refuses the swap the
  existing family is kept and the log says so.
- Everything selected belongs to the one opening being re-fitted, so the
  grouping rules are not applied -- picking the services is the user saying
  what belongs together.
- The opening is unpinned before it is moved and re-pinned afterwards if it
  was pinned to begin with.
- The slab resize accepts a pre-selected opening, as the wall resize does.

## 2.7.1

- **Fixed: the Place button was off the bottom of the screen on a short
  display.** The tab row was sized to its content, so the tab control could
  never shrink, and the ScrollViewers inside the tabs had been removed when the
  window was made to size itself. Content past the screen height was simply
  clipped. The tab row now takes the space that is left and each tab's contents
  scroll once the window reaches the height the screen allows.
- **The Slab tab is shorter.** The three vertical set-out controls share one
  grid instead of a heading and a row each, the hint panel that repeated the
  status line and the Place button's own tooltip is gone, and the captions are
  briefer. Roughly 150px saved; it now fits a 1080px screen outright and
  scrolls on anything shorter.
- The height cap leaves 60px clear rather than 40, so the window does not sit
  under the taskbar. Dragging any resize grip still hands sizing back to you.

## 2.7.0

- **One Finish, not two.** Picking linked services was a second selection
  session after the host one, so with "include services from linked models"
  ticked every placement asked to Finish twice. Host and linked services are
  now selected together in a single session: the filter accepts link instances
  as well as host elements, and each picked reference is resolved afterwards --
  a reference into a link carries the link instance as its ElementId and the
  real element as its LinkedElementId.
- Applies to both the wall and the slab tool. The separate linked-pick filter
  has been removed rather than left dormant.

## 2.6.3

- **Fixed: the wall tool failed with "Local variable 'levels' referenced
  before assignment".** The level calibration added in 2.6.1 was copied across
  from the slab loop, which builds a level list before the loop; the wall loop
  did not. Because `levels` was assigned a line later, Python treated it as a
  local and rejected the read — so the run died immediately after the wall
  pick, which is exactly where the log stopped.
- **`import_check.py` gained a use-before-assignment rule.** The existing
  symtable rule only catches a name assigned nowhere, so it had nothing to say
  here. The new one is scope aware: comprehension targets, nested function
  parameters and `global` declarations are all excluded, since each otherwise
  reads as a use before assignment. Proved by removing the fix and watching it
  fail.

## 2.6.2

- **Fixed: the window reported v1.9.3 while running current code.** Every
  version bump and changelog entry since 2.0.0 was lost. The 2.0.0 bump was
  chained behind `import_check.py` with `&&`; the check failed on that run, so
  the bump never executed, and every later bump then searched for a version
  string that had never been written and silently did nothing. The code itself
  was always current — only the number was wrong.
- `import_check.py` now checks that `__version__` matches the newest heading in
  this file, so the two cannot drift apart again.
- The entries below for 2.0.0 to 2.6.1 are reconstructed from those releases.

## 2.6.1

- **The wall tool now writes its failures to the debug log.** Its exception
  handler reported to the status box and pyRevit's logger but never to the log
  file, so a placement that threw left the log ending at the wall pick with no
  indication of what went wrong. Skips are logged too, and the wall type, the
  link it came from and every selected service are listed before placement, as
  the slab tool already did.
- **The log records which folder the code is running from.** A stale copy of
  the tool left in another pushbutton folder is easy to run by accident and was
  impossible to spot from the log.

## 2.6.0

- **Services pointing different ways no longer share an opening.** Proximity
  alone decided grouping, so two trays crossing at right angles were boxed into
  one opening — and no single rectangle can hug both. Two 600 x 100 trays at 90
  degrees needed a 600 x 650 opening for 0.12 m2 of actual service. They now
  get one opening each, turned to suit.
- Grouping needs the services to be **close AND pointing within 15 degrees** of
  each other, the angle read from each service's own footprint rather than any
  parameter. The tolerance is in Settings beside the grouping distance.
  Orientation repeats every 180 degrees, so the same tray drawn the other way
  round still counts as the same direction.
- The log names the pair and their angles whenever two services are close
  enough to group but too far apart in direction.

## 2.5.0

- **The rectangular opening is turned to suit the services.** Its orientation
  comes from the selected elements themselves: the tightest rectangle that
  contains their plan footprint at any angle, found from the convex hull edges.
  A 600 x 100 tray running at 30 degrees needed a 570 x 387 opening squared to
  the model; it now gets 600 x 100 turned to match, with the clearance even all
  round.
- **The centre comes from the same fit**, so the opening sits on the middle of
  the services rather than the middle of their bounding box, which is not the
  same point for anything at an angle.
- **The enclosure check is now real.** It was written in 2.4.0 but never
  applied: the anchor it was inserted against had changed two versions earlier,
  so the replacement matched nothing. It now tests against the opening's own
  frame rather than an axis aligned box, since a turned opening has a bounding
  box larger than itself.

## 2.4.0

- **Fixed: rectangular slab openings landed beside the services, not around
  them.** The opening was positioned by moving the instance's ORIGIN onto the
  centre of the services, which assumes the origin sits at the middle of the
  family's own geometry. It does not on these families — the same trap as the
  380mm vertical offset found earlier. The opening is now centred by
  measurement: the placed geometry's own centre is read and the instance moved
  until it sits on the centre of the selection.
- **Plan sizes are put on the right axes.** Which of the family's two plan
  parameters runs along model X depends on how the family was drawn, so the
  footprint is measured and the pair swapped when it came out the wrong way
  round.

## 2.3.1

- **Fixed: "global name 'clearance_ft' is not defined" stopped the slab tool.**
  The 2.2.0 rewrite of the family lookup replaced a block that also held the
  clearance, base offset and top offset parsing, so three names were used but
  never assigned.
- **`import_check.py` gained a `symtable` rule** flagging any name a function
  reaches for that is not assigned locally, passed in, imported, captured from
  an enclosing scope, defined at module level, or a builtin. Two earlier
  attempts at this rule were wrong in instructive ways: a name only *read*
  inside a function is reported by symtable as global whether or not the module
  defines it, and `get_identifiers()` lists names merely referenced in a scope
  as well as assigned ones.
- **The tool window opens where it is put again**, rather than moving itself to
  the side of the Revit window. Settings still opens beside the tool.

## 2.3.0

- **The workset has moved into Settings**, as one picker covering both tools
  rather than a dropdown on each tab.
- **Settings opens beside the tool window**, to its left, flipping to the right
  when there is no room.

## 2.2.1

- **Fixed: Place Slab Penetration could do nothing at all.** The check for a
  family only looked at the rectangular one, so with only a circular family set
  the button returned before doing anything. The check now follows the method
  and names which family is missing.
- **Every handler is guarded.** IronPython swallows an exception raised inside
  a WPF event handler: the click does nothing, with no traceback and nothing in
  the log. All handlers now report the failure to the status line and write a
  traceback to the debug log.
- **The debug log opens at the start of the run**, not after the family lookup.

## 2.2.0

- **The slab tool carries two families**, a rectangular one and a circular one,
  each with its own type, chosen in Settings.
- **The shape is decided per service.** Pipes, conduit and sprinklers are round;
  cable trays and ducts are rectangular. A Method dropdown overrides it:
  Automatic, All circular, or All rectangular.
- **Grouping rules, all editable in Settings:** trays and ducts within 100mm
  share one rectangular opening; a pipe within 150mm of such a group joins it;
  every other pipe gets its own circular hole. Distances are clear distance in
  plan, not centre to centre.

## 2.1.0

- **Circular holes are set out from the OUTSIDE diameter.** `Diameter` is the
  nominal size, which on steel and cast iron is smaller than the pipe actually
  is. The reader fell through to nominal wherever the built-in parameter did
  not resolve, and the name list had `Diameter` ahead of `Outside Diameter`. On
  DN100 steel that is a 114.3mm pipe treated as 100mm — a hole 20mm too small.
  PVC and copper were unaffected, which is why it did not show up in testing.
- **Insulation counts towards the outside diameter**, with a tick box to turn
  it off.

## 2.0.1

- **The circular gap is on the Slab tab**, shown only when the circular method
  is in use, alongside the round-up step.
- **The sizing rule is spelled out on screen.** The gap is a clearance all
  round, so the diameter grows by twice it. A worked example updates as you
  type. The behaviour has not changed; only the labelling.

## 2.0.0

- **Fixed: openings were assigned the wrong Revit level.** Revit exposes two
  elevations per level, `Elevation` and `ProjectElevation`, and which one is in
  the same coordinate space as element geometry depends on the project base
  point. This model needed `ProjectElevation`; the tool was reading the other,
  which put every level 87994mm from the geometry. That is why the nearest
  level always came out as the basement, why the "host and link may not share a
  datum" warning fired on every run, and why the base offset needed an 88374mm
  correction every time — 87994 plus the family's own 380mm origin offset.
  The property is now chosen by measurement at the moment of the click.
- **The window sizes itself to its contents**, capped to the screen.

## 1.9.3

- **Fixed: placing several openings at once placed none of them.** Every
  opening in a run shared one transaction, so a single service Revit refused
  rolled back all the others with it. Each opening now gets its own transaction
  inside a TransactionGroup.
- **Duplicate openings are skipped.**
- **Fixed a false warning on every placement** comparing the family's origin
  with the wanted base.

## 1.9.2

- **Fixed a white bar across the top of the window.** The window is now
  properly borderless — `AllowsTransparency` with a rounded dark shell — and
  carries its own eight resize grips.
- **Fixed: slab openings took the lowest level in the project.** They now take
  the nearest level, above or below.

## 1.9.1

- **Fixed: the buttons were off the bottom of the window.** The action buttons
  now sit below the tab control rather than inside it, each tab's contents
  scroll, and the window is resizable.

## 1.9.0

- **Renamed to BWIC Penetration.** pyRevit names a ribbon item after its
  folder, so delete the old `Place BWIC.pushbutton` folder or you will have two
  buttons. Settings and debug file names are deliberately unchanged.
- **The window opens on whichever tab you last used.**
- **Circular openings**, with the method taken from the family name or forced
  by a tick box.
- **Rectangular openings group** when services are within a settable distance.
- **Placed in 3D, the opening takes the level below it.**
- **The level code is written to BHE_Level** by the slab tool.

## 1.8.0

- **Two slab placement rules**, Two levels and Single level, kept apart in
  Settings.
- **The vertical height parameter is set to the floor thickness.**
- **Every parameter is picked from a dropdown read off the chosen family.**

## 1.7.0

- **Fixed: the floor's elevation was read 80 metres out.** A linked floor's
  bounding box was pushed through `GetTotalTransform()` by hand. The elevation
  now comes from the click point, which is in host coordinates whatever the
  link's placement.
- **Fixed: the size was never written.** The vertical family calls its two plan
  dimensions `BGL_Width` and `BGL_Height`, not `BGL_Length`.
- **The base offset is measured and corrected.**

## 1.6.0

- **Fixed: slab openings were placed tens of metres from the floor.** The
  position was derived from the level's elevation, and `level_below` silently
  fell back to the lowest level whenever nothing sat below the floor.
- **The opening is now set out from the floor itself**, never from the level.
- **"Set out from" dropdown** on the Slab tab.

## 1.5.0

- **Fixed: the slab family list hid most families.** The filter asked Revit
  whether a family was floor *hosted*, and defaulted to that. Almost no
  penetration family is hosted. The filter is now three way and defaults to All
  generic models.
- **Debug tick box** writing every decision to
  `%APPDATA%\RevoBIM PY\place_bwic_debug.log`.

## 1.4.0

- **Two tabs: Wall and Slab.**
- **Slab penetrations**, sized in plan with base and top set off the floor's
  own level.
- **Settings behind a gear in the header**, split Wall and Slab.
- **Split into `script.py` and `bwic_core.py`.**

## 1.3.1

- **Fixed: the Resize button was missing from the window in 1.3.0.** The style
  was added but the button markup itself never made it into the XAML.
- `import_check.py` ships with the tool and checks the XAML and the script
  against each other in both directions.

## 1.3.0

- **Resize existing BWIC from selection.** Pick an existing BWIC, then the
  services, then the wall, and it is resized and repositioned to the same rules
  as a new placement.

## 1.2.0

- **Conduit fittings can be selected**, along with pipe, duct, tray and flex
  fittings, accessories, terminals and equipment.
- **Fittings are measured from their real solids**, not their bounding box.
- `eid_value` helper added for `ElementId`, so the tool runs unchanged on Revit
  2026 and 2027.

## 1.1.1

- **Return now finishes a multiple selection** and moves straight on to the
  wall pick. The window was taking keyboard focus.

## 1.1.0

- **Ducts, pipes, trays and conduit are measured from their real edges**, with
  insulation included, instead of the bounding box.
- **Linked services can be added to a placement.**
- **Workset dropdown**, remembered between runs.

## 1.0.0

- Version number added, shown top right of the window.
- **Level now comes from the view** in a plan view.
- **Fixed the lowest-level bug** by setting every writable level parameter.
- **Level codes**: `Level 00` → `00`, anything containing Roof or RF → `RF`.
- Wall rules: `BLK` places `BWIC - Blockwork`, fire rated walls place
  `BWIC - Fire Rated Wall`.
- pyRevit console and Revit warning dialogs suppressed.
- Pinning off by default.
