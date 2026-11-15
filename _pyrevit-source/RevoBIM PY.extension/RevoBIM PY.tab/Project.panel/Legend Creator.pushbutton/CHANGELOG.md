# Legend Creator — changelog

## 3.0.0

Same tool, same buttons, same results - rebuilt so it is quicker to load,
easier to fix and harder to break.

### Changed
- **Split into modules.** The 4,535-line `script.py` is now a 56-line loader
  and ten `lgc_*.py` modules, each with one job:

  | Module | Job |
  |---|---|
  | `lgc_clr` | every .NET assembly reference, made once, first |
  | `lgc_logic` | constants and pure rules - scaling, colours, labels, grouping |
  | `lgc_core` | version, settings, the debug trace, `err_text`, `eid_value` |
  | `lgc_drawer` | shrink to the taskbar |
  | `lgc_model` | reading the model |
  | `lgc_build` | writing legends, styles and regions; opening and revealing |
  | `lgc_theme` | Revit theme, palettes, loading a window |
  | `lgc_windows` | the picker and the summary |
  | `lgc_report` | the debug report and its window |
  | `lgc_app` | one run, start to finish |

  The modules import in one direction only, with no loops. The version now
  lives in `lgc_core.py`.
- **One shared `Theme.xaml`.** Every brush and style was copied into all
  three windows; it is now one file spliced into each at load. The layouts
  went from 1,562 lines to 691.
- **The document is bound per run.** pyRevit can keep modules loaded between
  runs, so the active model is handed to each module at the start of every
  run rather than captured once at import - switching or reopening models
  can never leave the tool reading the old one. The debug trace also starts
  clean each run.
- **A crash at any stage is reported.** The loader says which stage failed
  (references, loading the modules, or the run) and shows the full debug
  report, or a plain alert with the traceback if even that could not load.
- Rules that were written out twice (pipe grouping, `Abbreviation -
  Description`, theme choice and cycling, reading Revit's theme) are now one
  function each in `lgc_logic`, used by the tool and tested by the bench.

### Fixed
- **Escape on a parked bar closed the window.** pyRevit's own Escape handler
  ran before the drawer saw the key. Windows now load with that handler off;
  Escape reopens a parked bar, and closes the main window only when it is
  open.
- The summary's *Open* and the report's *Copy* buttons asked for the green
  style by name - they had been relying on a per-window default that the
  shared theme no longer gives every button.

### Bench
- `bench_logic.py` imports the real modules instead of keeping copies, so it
  can no longer drift from what ships. New tests: theme splicing for every
  window, text contrast on every surface in both palettes (4.5:1 minimum),
  Theme.xaml's defaults matching the dark palette, view-name numbering and
  text case.
- `import_check.py` runs its code rules on every module and its window rules
  on each layout with the theme spliced in. New rules: no import loops; the
  pure modules load without Revit; no undefined or unused names (pyflakes);
  every module reading `doc` is bound per run; `script.py` stays a loader;
  one `__version__`; windows load through `load_window`; the main window
  handles Escape after the drawer; the bench keeps no copies.

## 2.13.0

### Changed
- **Dark theme matches Revit's own.** Sampled from Revit's Project Browser by
  the most common pixels in each area, so anti-aliasing does not skew it:

  | Role | Was | Now (Revit) |
  |---|---|---|
  | Window / panel | `#232326` | `#3C4454` |
  | Fields and lists | `#1C1C1F` | `#2D3441` |
  | Header and footer bars | `#1C1C1F` | `#212932` |
  | Cards | `#2B2B2E` | `#353D4B` |
  | Text | `#E4E4E4` | `#F0F0F8` |
  | Muted text | `#9A9A9E` | `#AEB4BB` |

  Text colours come from the neutral glyph cores, since ClearType fringes are
  tinted. Muted is Revit's icon grey `#A8AEB5` lifted just enough to clear
  4.5:1 on the lighter panel (it measured 4.37). Borders, controls and the
  scrollbar are stepped up from the panel in the same blue-grey. The brand
  accents and the blue selection stay - Revit's own selected row, `#323C48`,
  is too faint to find a highlighted dropdown item by.
- Every text pairing re-measured on the new palette: lowest 4.68:1 (muted on
  the panel), wordmark 5.38, Create button 5.48.

## 2.12.0

### Added
- **Shrink to the taskbar, on every window** - the picker, the summary and
  the debug report. A button in the top right, beside close, slides the
  window down to the bottom of its screen like a drawer closing, leaving only
  its header bar floating 8px clear of the taskbar. The button turns into a
  **green up arrow**; press it to slide the window back up.
- Also reopens with a **double click on the bar**, **Enter** or **Escape**;
  **Ctrl+Shift+H** toggles either way. The bar can be dragged, and opens
  upward from wherever it was left, kept on screen.
- The theme chip and close still work on the parked bar.

### How it is built
House pattern, as in Pro Sheets, Filter Manager and View Manager. One
`WindowDrawer` helper, handed to every window class through `make_drawer`;
a `NullDrawer` stands in and the button hides if it cannot be built, so a
shrink button can never cost the tool.

- `Top` and `Height` eased together over 0.28 s on a 15 ms
  `DispatcherTimer`, ease-out cubic. Not a Storyboard, which on a borderless
  window fights the layout pass and holds its end value over every later
  assignment.
- `MinHeight` and `SizeToContent` relaxed for the slide and put back after;
  both would veto a shrinking `Height` and leave the window half shut.
- The body is pinned at full height while it slides, so it is drawn away
  under the header rather than squashed; collapsed only once the bar lands,
  resize grips included, and each part put back to the visibility it had.
- Parks on the working area of the screen the window is actually on, DPI
  allowed for, via Windows Forms `Screen.FromHandle`.
- Bars stack 4px apart, each taking the lowest free slot.
- A frame that throws ends the slide at once and lands the window at the end
  state; a timer that cannot start lands it immediately.
- While parked, Create, Open legend and Copy report reopen the window rather
  than acting, so an Enter on a bar nobody is looking at cannot create
  anything.

### Fixed (found by the new bench, before shipping)
- Bars stacked by *counting* the parked ones: reopen the bottom bar while the
  one above stays parked, shrink it again, and it landed exactly on top of
  the other. Now the lowest free slot.
- The assembly rule mapped `System.Windows.Forms` to the WPF assemblies, so
  a missing Windows Forms reference would have passed the bench and failed
  at runtime. It is now its own entry.

### Bench
- `bench_logic.py` drives the **real** `WindowDrawer`, lifted from
  `script.py`, against a stand-in window that refuses a Height below its
  MinHeight, a clock that moves 20 ms a read and a timer that runs its ticks
  at once: round trip, gestures, a moved bar, stacking, a monitor above the
  primary, a throwing frame, no timer.
- `import_check.py` rule `check_drawers`: every window class builds a drawer
  and binds its button, every drag handler asks the drawer first, every
  layout with a header has a `ShrinkBtn` whose Tag trigger matches the
  script's `SHRUNK` value and draws the up arrow in the palette green.
- 26 deliberate breakages, all caught.

## 2.11.0

From the first debug report, on Revit 2026.5 / pyRevit 7.0 / IronPython 2.7.12
on .NET 10. Every Revit API member the tool uses was present and nothing was
absorbed - the tool worked, but on that model it had nothing to make and said
so too quietly.

### Fixed
- **"Nothing happens" when Create cannot run.** The reason now shows in
  orange in the footer and **Create is greyed out** until it is fixed, on
  both tabs: no legend component in the model, no matching filters on this
  template, no system types in use, nothing ticked. Previously a refused
  Create changed a grey status line and nothing else. Every refusal also goes
  to the debug log.
- **The containment template was chosen silently.** The model had no
  `04_Documentation_Floorplan_Containment`, so the tool fell back to the
  first template alphabetically - a duct template with no containment
  filters - and showed an empty list without saying why. It now picks, in
  order, the template used last time, the kind's default, then the template
  holding the most matching filters; each template with matches shows the
  count in the dropdown; and the choice and its reason are logged.
- **Phase filter could keep exactly the wrong elements.** An element with no
  phase was compared as id 0, the same value an unreadable wanted phase gives,
  so an unreadable phase would have listed only phase-less elements. Elements
  with no phase are now never kept by a phase filter, and a wanted phase that
  is not a real id lists every phase and says so in the log.

### Debug report
- Records what was pressed: tab changes, legend type, Create (and whether it
  was refused, with the reason), Cancel or close, theme changes.
- The family scan line now gives elements read, how many had no phase, how
  many were on another phase, and the phase ids by name.

### Bench
- Template choice and the phase verdict are pure functions with tests built
  from the 2026 report, both checked against drift from the script.
- New rule: the footer line is only written through `say()` / `refuse()`, so
  a refusal cannot go back to being a quiet grey message.

## 2.10.1

### Fixed
- **The RevoBIM command search showed the tool as "|-" and "not loaded".**
  `bundle.yaml` gave the title as a YAML block scalar (`title: |-` with the
  words on the lines below) and the tooltip as a folded one (`tooltip: >`).
  pyRevit's own YAML reader copes with both, but the command search reads
  the bundle line by line, so it saw the title as `|-`, could not match it
  to any loaded command, and reported the tool not loaded however often
  pyRevit was reloaded. Title and tooltip are now plain single lines, and
  `__title__` in the script is `Legend Creator` on one line - which is also
  the house rule, for Revit's Keyboard Shortcuts list.

### Bench
- New rule: `bundle.yaml` is one-line `key: value` entries only, no block
  scalars or continuation lines, and its title matches `__title__`.
- New rule: `script.py` must parse under the Python 2.7 and 3.4 grammars of
  pyRevit's IronPython engines, not only the desktop CPython running the
  bench - pyRevit parses the script while building the ribbon, and a 2.7
  syntax error means the button silently is not there. Uses parso 0.7.1,
  and says loudly when it is not installed rather than passing.

## 2.10.0

### Debug report
- **A report window you can paste straight into the chat.** It opens when
  the Debug tick is on - after a run, or when the window is closed without
  creating - and **on any crash, Debug or not**, because a crash can happen
  before the window and its tick ever appear. The report is copied to the
  clipboard as it opens, saved to
  `%APPDATA%\RevoBIM\legend_creator_debug_report.txt` when Debug is on, and
  falls back to a plain alert if the themed window itself will not load.
- **What it contains:** the crash with its .NET stack (first, when there is
  one); Revit version, build and update, language, pyRevit, Python engine,
  .NET runtime, Windows; the document, legend views and components; a probe
  of every Revit API member the tool uses, marked ok or MISSING on this
  Revit, including every BuiltInParameter and BuiltInCategory the script
  names, read from the script itself so the list cannot fall behind;
  settings; and a timed trace of the run.
- **The trace says why, not just what:** each template filter kept or
  skipped and on what grounds, each duct and pipe system with its label,
  colour and raw classification text, how many system types each search
  route found, the theme value Revit reported, and how far window
  construction got.
- **Absorbed errors are now recorded.** 91 handlers that used to drop an
  error silently - `pass`, `continue`, `return`, or a fallback such as
  `value = None` - now note where it happened and what it was, deduplicated
  with a count. A member missing on one Revit release previously made the
  tool quietly do less with no message at all; it now shows up by name.
- Debug follows the saved tick from the first line of the run, so a failure
  before the window opens is still in the file.

### Bench
- New rule: an except block that only absorbs must call `swallowed()`
  (allow-list for input parsing and the recorder itself). It found 11 more
  silent handlers than the first text-based sweep did, including the type
  parameter reader and the filter override read.
- New rule: the entry point re-raises `SystemExit` - pyRevit's normal exit -
  before reporting everything else as a crash.
- New rule: functions `bench_logic.py` copies from `script.py` must not
  drift, compared on their code with docstrings ignored.
- `.IntegerValue` rule rewritten on the AST - it matched the word inside a
  string.
- Logic test runs the **real report code**, lifted from `script.py`, against
  a Revit stub with nothing in it, and requires a full report rather than an
  exception. It found the BuiltInParameter probe looking the enum up outside
  its guard, which would have crashed the crash report.

## 2.9.0

### Revit 2025, 2026 and 2027
- **Duct and pipe legends no longer rebuild ElementIds from numbers.**
  `DB.ElementId(int)` uses the Int32 constructor Revit 2026 removed; the
  system types in use are now kept as the ElementIds Revit handed back.
- **Millimetres convert with plain `mm / 304.8`.** The old fallback went
  through `DisplayUnitType`, removed in Revit 2022.
- **No `clr.AddReference('RevitAPIUI')`**, and `UIThemeManager` is reached by
  `getattr` on the namespace, so a release without it falls back instead of
  throwing.
- **Error text goes through `err_text()`**, which cannot itself raise on a
  .NET message holding non-ASCII text.
- Bench rule `CROSS_VERSION_FORBIDDEN` blocks each of the above, matched
  against code only - an explanation of the rule in a comment does not trip
  it, and a rule cannot pass by matching its own docstring.

### Added
- **Debug tick in the footer, off by default.** Off, a run writes nothing to
  disk. On, it writes `%APPDATA%\RevoBIM\legend_creator_debug.txt`, stamped
  with the tool, Revit, pyRevit and engine versions, plus a traceback if the
  tool crashes. The summary says where to look, or to tick Debug and re-run.
- **The summary asks whether to open the legend** - Open legend / Not now -
  instead of opening it unasked. Asked in the summary itself, so it is still
  the only window after a run.
- **The first new legend is found in the Project Browser** whatever the
  answer: the pane is shown if closed, the view selected, and the browser
  tree scrolled to it and selected. The API cannot scroll the browser, so
  that last step uses UI Automation on a worker thread while Revit's message
  loop keeps turning, and gives up after 4 seconds rather than risk a hang.
  Each step's outcome goes to the debug log.

### Bench
- Assembly rule now maps namespace to assembly (`ASSEMBLY_FOR`) and counts
  imports inside functions - it missed `System.Windows.Automation` because
  it only knew the WPF trio.
- Read-back rule now requires the read to come *after* the write. A
  pre-check `if not pane.IsShown()` satisfied the old version on its own.
- New rule: settings shown on both tabs (theme, debug) must be saved by both
  create paths.
- Logic tests for the unit conversion and for error text that cannot be
  printed.

## 2.8.0

### Added
- **The new legend opens when the run finishes**, before the summary
  appears. The system tab opens the legend it built; the family tab opens
  the first one, since it can build several.
- The switch happens **after the transaction has committed** - changing the
  active view inside an open transaction throws - and is **read back**
  afterwards, because assigning `ActiveView` is a void call that can quietly
  do nothing. `RequestViewChange` is kept as a fallback, second because it
  is queued rather than immediate. Whether the view actually opened is
  written to the log either way.

### Bench
- New static rule: a function listed in `READBACK_REQUIRED` must read the
  model back after writing to it, so a silent no-op cannot report as
  success. Verified by deleting the read-back and by renaming the function
  away.

## 2.7.0

### Changed
- **Line weight 3 by default**, on the swatch line styles, the filled region
  types and the centreline alike. Editable in the window, 1 to 16, and
  remembered. Out-of-range or rubbish values are coerced rather than
  refused.
- **A re-run now overwrites what it finds.** Existing line styles and filled
  region types have their colour, pattern and line weight written
  unconditionally, so a hand edit between runs does not survive and the
  legend goes back to matching the model. Previously a property was only
  written when it differed, and line weight was never written at all.
- The log says what each style did - created, overwritten with what changed,
  or overwritten with nothing different - one line per style, so a re-run
  can be read back afterwards.

### Bench
- Tests for weight clamping and the overwrite rule.
- New static rule: `apply_region_style` must write ForegroundPatternColor,
  ForegroundPatternId, LineWeight and IsMasking, and `apply_line_style` must
  write LineColor and SetLineWeight. Dropping one of those is invisible at
  runtime - the element already exists, nothing throws, and it silently
  keeps whatever it had. The rule looks for an assignment rather than a
  mention, because both functions read the current value first and a
  substring test passed even with the write deleted.

## 2.6.0

### Changed
- **Pipe swatches are 75mm high at 1:50** (300mm at the 1:200 reference), so
  a pipe run reads as a thin band rather than the block a cable tray does.
  Containment and Ductwork stay at 700mm.
- **Swatch height is now held per kind** and swapped when the kind changes,
  since the three kinds want genuinely different heights. Saved as one
  packed value, `containment=700;ductwork=700;pipework=300`; a damaged or
  missing entry falls back to that kind's own default rather than to a
  single shared number. Editing the box still works and is remembered
  against the kind it was typed for.
- **The centreline uses a dashed line pattern**, `LEG_Centreline 5-2-2-2` -
  dash 5mm, space 2mm, dash 2mm, space 2mm, named for the pattern it makes.
  Line patterns are defined in paper millimetres, so those lengths are the
  same on the sheet at every view scale and are deliberately not scaled with
  the swatch. An existing pattern of that name is updated, not duplicated.

### Bench
- Tests for the packed per-kind heights, the 75mm-at-1:50 rule and the
  pattern segments, each verified by deliberate breakage.
- New static rule: every `SYSTEM_KINDS` entry must carry the full set of
  fields. A missing one is a `KeyError` partway through a run, after
  elements have already been created - now caught on the bench, by name.
- The AST helpers stopped using `ast.Str.s`, deprecated from Python 3.12 and
  gone in 3.14, so the bench keeps running on a modern desktop Python.

## 2.5.0

### Added
- **Pipework Legend**, driven by the pipe system types in use and their
  Graphic Overrides colour, like Ductwork. Swatches are a coloured outline
  with a **grey centreline** running through the middle and past both ends.
- **Grouped by system classification.** Domestic (hot and cold together),
  Hydronic (flow and return together), Sanitary & Vent, Fire Protection,
  then Other. Each group gets its own header - `DOMESTIC PIPEWORK LEGEND`,
  `HYDRONIC PIPEWORK LEGEND` and so on - and the groups run down the view in
  that order. The classification is matched on keywords rather than enum
  members, whose names vary by release.
- Labels use the Ductwork rule: **Abbreviation - Description**.
- The preview names each row's group, so the grouping is visible before
  anything is built.

### Changed
- **Line styles are named from the abbreviation**, so `LEG_PIPE_SVP` rather
  than the full label. An existing style has its colour updated only - never
  duplicated. The grey centreline is one shared `LEG_Centreline` style.
  Ductwork moved to the same rule.
- **Every prompt after the run is suppressed except the summary.** The
  pyRevit output window is gone; the run writes to
  `%APPDATA%\RevoBIM\legend_creator.log` instead. Revit's own dialogs are
  answered by a `DialogBoxShowing` handler - hooked once and switched with a
  flag, since unsubscribing an IronPython bound method is not reliable - and
  warnings are deleted by an `IFailuresPreprocessor` on every transaction.
  Which dialogs were answered is written to the log, because a run that goes
  quiet because Revit asked something is otherwise unexplainable.
- The summary window now appears even when nothing was drawn, saying so,
  rather than the run ending with no feedback at all.

### Bench
- Tests for pipe classification, grouping and the layout cursor, each
  verified by deliberate breakage - including one that checks no group's
  swatches can overlap the next group's header.

## 2.4.0

### Added
- **Ductwork Legend**, the second configured system legend. It finds every
  **duct system type actually in use** in the model, takes each one's
  **Graphic Overrides line colour**, and draws it as an **outline swatch
  with no fill** - four detail lines on a coloured line style, since a duct
  reads as an outline rather than a block of colour and there is no
  per-curve colour override in Revit.
- Labels are **Abbreviation - Description**, so `IA - INTAKE AIR`. Either
  half alone is used where the other is blank, and a type with neither falls
  back to its own name.
- Line styles are named `LEG_DUCT_<label>` and reused: an existing one has
  its colour brought up to date rather than being duplicated. Characters
  Revit refuses in an element name are replaced first.
- The legend is named **WIP_Ductwork Legend** by default, and each kind now
  carries its own default view name.

### Changed
- `SYSTEM_KINDS` entries gained `source` (where the rows come from - view
  template filters, or duct system types) and `style` (`fill` or `outline`),
  so a new kind stays a table entry rather than new branching.
- Used duct system types are found two ways and unioned: `MechanicalSystem`
  elements, which only exist where Revit has formed a system, plus the
  system type parameter on ducts, fittings, accessories and terminals.
- The system colour is read from `LineColor` where the release exposes it,
  falling back to the packed integer on the parameter (`R + G*256 +
  B*65536`).
- The view template picker greys out for a duct legend rather than
  disappearing, since it genuinely does not apply there.

### Bench
- Tests for the `Abbreviation - Description` rule, the name sanitiser and
  the packed-colour decode, each verified by deliberate breakage - including
  the byte order, which would otherwise silently swap red and blue.

## 2.3.0

### Changed
- **The theme follows Revit's canvas theme** by default, read from
  `UIThemeManager`. The chip in the header now cycles **Auto -> Dark ->
  Light -> Auto**: Auto tracks Revit, the other two pin the tool whatever
  Revit is doing. The choice is remembered as a mode, so Auto stays Auto and
  keeps following rather than freezing on whichever palette it saw last.
- `UIThemeManager` arrived in Revit 2024 and exposes the canvas theme
  separately from the UI theme. Both are read and the canvas wins, since
  that is what the drawing area actually looks like. Every route is guarded,
  and a release that reports nothing falls back to dark with the chip's
  tooltip saying so.
- The enum is read as text rather than compared against its members, whose
  names have not been stable across releases. The bench covers the shapes it
  has printed as - `Dark`, `UITheme.Dark`, `CanvasTheme.Dark`.
- The `theme` setting is replaced by `theme_mode`, holding `auto`, `dark` or
  `light`. An unrecognised value falls back to `auto`.

### Added
- Bench tests for theme resolution and the three-state cycle, each verified
  by deliberate breakage.

## 2.2.2

### Fixed
- **The header and footer were unreachable.** The `TabControl` had lost its
  `Grid.Row="1"` while a stale attribute was being cleaned up, so the tab
  content drew in row 0 *on top of the header* - burying the close button,
  the theme chip and the drag bar together - and pushed the footer off the
  bottom. One missing attribute, four symptoms, and no error anywhere,
  because a child with no `Grid.Row` silently defaults to row 0.
- **The window now keeps itself on screen.** With no system chrome, Windows
  will not rein it in: on a scaled display it could open taller than the
  working area and put its own footer out of reach, with the drag bar hidden
  and no way to recover. It now clamps to the working area on open, lowering
  `MinHeight` first so the clamp can take effect, and centres on whichever
  monitor it lands on. Verified at 100%, 125% and 150% scaling, on a 1366x768
  laptop, and on a monitor at negative coordinates.
- Default size reduced to 820 x 640, minimum to 600 x 560.

### Changed
- New bench rule: no two children of a multi-cell `Grid` may share a cell.
  It tests the row and column together, so the eight resize grips - which
  share rows and share columns but never a cell - still pass, while the
  missing `Grid.Row` above is caught by name. Verified against that exact
  breakage and three variants.

## 2.2.1

### Fixed
- **The tool would not open**, failing in `wpf.LoadComponent` with "Add value
  to dictionary of type 'System.Windows.ResourceDictionary' threw an
  exception". 2.2.0 added a `SolidColorBrush` keyed `Pill` while a `Style`
  of that key already existed, and WPF refuses a duplicate key with a
  message naming neither the key nor the file. The brush is now `PillBrush`.
- **The window can now be stretched, and the footer follows.** WPF cannot
  resize a borderless `AllowsTransparency` window - nothing in the
  transparent frame is hit testable, so the resize border never fires
  however `ResizeMode` is set. The window carries its own eight `Thumb`
  grips instead, in an overlay with no `Background` so only the edges are
  hit testable and the middle stays clickable. The layout was already
  Auto / star / Auto, so the footer tracks the bottom edge as it moves.

### Changed
- Three more bench rules, each verified by deliberate breakage: no
  duplicate `x:Key` in a layout, every grip has its `DragDelta` bound, and
  the `DynamicResource` check now runs per layout rather than pooling every
  layout's keys - pooled, one dictionary could borrow another's declaration
  and the gap would not show until runtime.

## 2.2.0

### Fixed
- **The window could not be dragged.** The header's `MouseLeftButtonDown`
  was wired as a XAML attribute, which is not dependable through pyRevit's
  loader - the handler simply never fired, with no error to show for it.
  Every event in the tool is now bound from Python with `+=`, which is the
  house convention for exactly this reason.

### Added
- **Light and dark**, switched from the chip in the header and remembered
  between runs. Every colour in the layouts is a `DynamicResource` and the
  palette is written straight onto `window.Resources`, which sits in front
  of anything merged, so the swap repaints an open window with no reload and
  no loss of state. Rows built in code are rebuilt on the switch, since
  their brushes are set directly rather than looked up.
- The light palette is not the dark one inverted: the accents are darkened
  because the dark ones are chosen to sit on near-black and wash out on
  white.

### Changed
- Dark Create button text darkened to `#0E2214`. The old off-white sat at a
  2.80 contrast ratio on the green, under the 3.0 floor for large text; it
  is now 5.48.
- Four new bench rules, each verified by deliberate breakage: no event
  wiring in XAML, both palettes carry identical keys, every brush a layout
  declares is set by the palettes, and every declared button and header bar
  is actually bound. The last one was rewritten after the first version
  passed vacuously - keyed on the class using a control, it stopped checking
  the moment the binding was deleted, since that removed the only reference.

## 2.1.1

### Fixed
- **System Colour Legend crashed on open** with `ValueError: invalid literal
  for int() with base 16: 'X1'`. Revit returns a .NET `Byte` for
  `Color.Red`, and under IronPython `'{0:02X}'.format(<Byte>)` hands
  formatting to .NET, which reads `02X` as a *custom* format string — digit
  placeholder, then a literal `2X` — rather than "two hex digits". The
  string it produced did not parse back as hex. Colour channels are now
  coerced to Python ints the moment they leave Revit, and the hex string is
  built with `%` formatting, which cannot be intercepted that way.
- `brush()` no longer raises on a malformed colour. A swatch is cosmetic and
  must not take the window down; a bad value falls back to grey.

### Added
- `bench_logic.py`, covering colour conversion, label tidying and the
  scaling maths. It imitates a .NET `Byte` so the crash above is reproduced
  on the bench, and was verified by restoring the bug and watching it fail.

## 2.1.0

### Added
- **Tabs.** The tool is now two tabs: **Family Legend** (everything to date)
  and **System Colour Legend**.
- **System Colour Legend — Containment.** Reads a view template, takes the
  filters on Cable Tray categories whose name contains "Containment", and
  builds a legend from their override colours: a filled region swatch per
  filter, 2500 x 700mm at 1:200, with the filter's rule value beside it in
  caps and a `CONTAINMENT LEGEND` heading, underlined, above.
- Filled region types are named `LEG_CONT_<name>`. An existing type of that
  name is reused and its colour and pattern brought up to date rather than
  duplicated; the report says which were created, which updated and which
  were already right.
- Live preview of the matched filters with their real colours, tick to
  include. Filters with no colour override are listed grey and flagged
  rather than dropped without explanation.
- Legend type dropdown, ready for Pipework and Ductwork; both are declared
  in `SYSTEM_KINDS` and marked not configured until their template and
  naming token are filled in.
- Swatch size, row pitch and text gap are editable, quoted at 1:200 and
  rescaled the same way the family tab does it.
- Separate text style for the heading and the names.

### Changed
- The seed requirement is now per tab: the system tab only needs a legend
  view to duplicate, since filled regions and text need no legend component.
- Settings are merged on save, so one tab can no longer discard the other's.
- Bench check gained three rules — every `FindResource` key exists, every
  settings key read has a default, and any lowercase `self.x` Python never
  assigns must be declared as `x:Name`. The last replaced a suffix-matching
  rule that silently missed `self.tabs`.

## 2.0.0

Rebuilt against the RevoBIM PY house theme reference, plus four new options.

### Added
- **Scale.** Chosen from 1:1 to 1:1000, default 1:100. The row, text and
  column distances restate themselves when the scale changes so the layout
  stays the same size on paper — 900mm at 1:100 becomes 450mm at 1:50, both
  9mm on the sheet. Distances are stored at the 1:100 reference, so repeated
  scale changes never compound. A hand-typed override is carried across a
  scale change rather than lost.
- **Phase filter**, defaulting to New Construction. Only types placed on the
  chosen phase are listed, and the type counts update with it.
- **Text style** picker — any text note type in the project.
- **Name from** picker — the type parameter the description text is read
  from, defaulting to Description, plus `<Type Name>` and `<Family : Type>`.
- **Add all selected to one legend.** One `WIP_COMBINED` legend with each
  category in its own column, at an adjustable column spacing.
- Row spacing and text offset are now editable rather than fixed.
- `import_check.py` bench check, and a `CHANGELOG.md`.

### Changed
- House palette, chrome, header and footer per the theme reference.
  `__version__` shows top right of both windows.
- Settings persist as key=value at `%APPDATA%\RevoBIM\legend_creator.txt`,
  falling back key by key; unknown keys are ignored.
- One transaction per legend inside a transaction group, so one failed
  category no longer costs the others. Cancellable progress bar.

## 1.1.0

### Added
- Description text case: as written, UPPERCASE or Camel Case. Camel Case
  leaves tokens containing digits alone, so FD30 and 900x2100 survive.
- Completion window.

## 1.0.1

### Fixed
- **Revit crash on run.** The duplicated legend was emptied with a
  view-scoped `FilteredElementCollector`, which also returns the view's own
  `SketchPlane`. Deleting it left a null work plane and the next element
  created in the view took Revit down at native level — no managed
  exception, nothing catchable. Clearing is now restricted to an explicit
  list of drafting categories and never touches views or sketch planes.
- Categories that cannot be drawn as a legend component (Revit Links, Model
  Groups, Masses, Parts, Topography, Rebar, Piping and Duct Systems, Rooms,
  Spaces, Point Clouds) are filtered out of the list rather than offered.
- Halved the regenerate calls per component.

## 1.0.0

- First release. One legend per ticked category, components stacked 900mm
  apart with the Description parameter 1000mm to the right.
