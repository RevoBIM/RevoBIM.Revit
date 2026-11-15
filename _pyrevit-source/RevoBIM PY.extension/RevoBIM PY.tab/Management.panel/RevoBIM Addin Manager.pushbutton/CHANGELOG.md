# RevoBIM Addin Manager - changelog

## 1.5.2

- **Adding a favourite takes you to it.** Add to favourites, from the list,
  switches to the grid, scrolls to the new tile and pops it in - so there is no
  hunting for where it went.
- **Press and hold a favourite to pick it up.** Hold it still for about a
  third of a second, or start dragging, and it lifts: it grows a little with a
  small overshoot and its shadow deepens, so it is plainly off the grid. It
  then follows the cursor freely. The others **slide** out of its way rather
  than jumping, and letting go **settles** it into its slot. A press let go
  before it lifts is still a click.
- Built to the house animation rules: frames from `CompositionTarget.Rendering`
  with time taken from the frame, render transforms only (nothing is laid out
  per frame), no WPF animation objects, one stored frame handler so it comes
  off cleanly, a slow frame clamped so a Revit hiccup never makes a tile jump.
  Slots are read with `LayoutInformation.GetLayoutSlot`, which ignores render
  transforms, so a tile mid-slide never throws the drop slot off.
- Bench: the tween engine driven against a fake clock - lands exactly, once,
  stops, ignores a repeated frame, clamps a slow one, replaces from where it
  is, hooks the frame loop on and off once, and lands everything when the grid
  is rebuilt mid-flight - with breakages.

## 1.5.1

Favourites never appeared - and pins, the Quick Access Toolbar list and folded
groups never stuck either.

- **An addin's internal key had "|" inside it** (`extension|tab|panel|title`),
  and the settings file stores lists by joining entries with "|". So every
  saved key was read back as four fragments, none of which matched any addin.
  Adding a favourite saved it; the grid then found nothing. The same fault has
  silently broken Pin to the top, the Quick Access Toolbar list and the
  remembered folded groups since 1.3.0.
- Keys now join their parts with `::`. **Favourites, pins and the toolbar list
  saved in the old form are rebuilt**, four fragments to a key, so what you
  added comes back rather than being lost. Folded groups cannot be rebuilt
  (their keys vary in length) and simply start open.
- Saving a list entry that contains the list separator now **raises** instead
  of quietly splitting it.
- Bench: a real addin key round trips through the settings list - the check
  that would have caught this - plus the rebuild of old fragments, each with a
  breakage.

## 1.5.0

Favourites, laid out like apps on a phone.

- **A yellow star at the top left of the tool row** switches between every
  addin and the favourites grid. Lit while the grid shows; the view is
  remembered.
- **Right click any addin - in the list or the grid - for Add to favourites /
  Remove from favourites.**
- **The grid**: uniform tiles, filled from the top left across and then down.
  Each is the addin's own icon, a size up from the list's, on a small raised
  card with a soft shadow so it reads as something to press, and its name in
  small text underneath, wrapping to two lines. Click to run it.
- **Show or hide the names** with the button that appears at the top right in
  favourites, or by right clicking the empty space between tiles. Remembered.
- **Drag a tile to reorder.** Press and move a few pixels and it lifts; the
  others close up and open around it as it passes, and it lands where it is
  let go. A press that does not move is a click. The order is remembered, and
  a new favourite always goes on the end - the next free spot.
- **The search box is hidden in favourites**, to give the grid the room; the
  expand/collapse button goes too, since there are no groups.
- A favourite whose folder has gone is kept, not shown, and comes back to its
  old place if the folder returns. Not-loaded addins show faded.
- The drag captures the mouse on the grid rather than the tile, which is taken
  out and put back as it moves; tiles move within the grid's own children, so
  nothing is rebuilt under the cursor.
- Bench: new favourites fill in reading order, removing closes the gap,
  dragging forward and back lands exactly on the drop slot, a drop in the empty
  space after the tiles lands last, and a reorder keeps hidden favourites in
  their places - each with a breakage that proves the check.

## 1.4.4

A compact header, to give the list the room.

- **Two tight rows instead of four.** The name now sits on one line -
  **RevoBIM** in blue, **Addin Manager** in orange - with the version and the
  window controls beside it. The logo square is gone.
- **Every tool is a square icon button** on the second row, where Auto and
  Settings used to be: fold, smaller icons, bigger icons and refresh on the
  left; footer, theme and settings on the right. The separate toolbar row
  under the search box is gone.
- **Expand and Collapse are one button.** It collapses every group while any
  is open, and expands them all once everything is shut; its arrows and
  tooltip say which it will do.
- **The theme button shows the mode as a glyph** - half-filled circle for
  Auto, moon for Dark, sun for Light - with the mode in its tooltip.
- **The search box has an orange edge**, matching Project Browser Pro, and
  keeps it when focused.
- The name stays a drag handle on the floating window, and three slow clicks
  on it still open the arcade.
- Window controls are square, 24px.

## 1.4.3

- **A button top right shows or hides the status footer**, beside the
  version. Lit while the footer shows; remembered between sessions
  (`show_footer`). Pressed while the window is parked, it opens the window
  first - the drawer is holding the footer's visibility to put back, and a
  change underneath would be undone.
- **Escaped line breaks no longer leave a stray "n" in descriptions.** A
  `\n` in a tool's `__doc__` had its backslash stripped and its "n" kept, so
  BWIC Penetration read "Wall and Slab tabs. n n Wall:". Escapes are now
  turned into spaces before anything else is stripped. Benched, with a
  breakage.

## 1.4.2

The docked pane reported `ImportError: No module named rba_pane`.

- **pyRevit resets the start up engine's sys.path once startup.py has run.**
  The docked panel is built later, when the pane is first shown, and by then
  the tool folder the startup block added has gone again - so the build's
  `import rba_pane` found nothing. `rba_dock` now remembers its own folder
  while it is being imported at start up and puts it back on sys.path just
  before building the panel.
- **Every other import that waited for a click moved to the top of its
  module**: right click (`rba_menu`), Settings (`rba_settings`), the Quick
  Access Toolbar (`rba_qat`), the floating window and the drawer's screen
  lookup. Imported up front, each sits in sys.modules where the reset cannot
  touch it; left inside their handlers, each would have been the next failure.
- Bench rule: no module of the tool's is first imported inside a function,
  bar the panel build straight after the path is put back.

## 1.4.1

The docked pane showed solid black and did nothing.

- **The pane's host was never painted.** 1.4.0 handed Revit an empty Border
  with no background, which Revit draws black, and built the panel only on
  that Border's Loaded event. A failed build showed its message as a TextBlock
  with default black text - black on black - so a panel that was never built
  and one that failed to build looked identical and said nothing.
- The host is now painted with the palette at once and says "Starting...",
  so an empty pane is never what you see.
- The panel is built on **Loaded, IsVisibleChanged, or once more from the
  dispatcher**, whichever comes first, so a dock host that never raises one of
  them cannot strand it.
- **A failure is shown inside the pane** in readable colours, with the full
  traceback and a Copy details button, and saved to
  `%APPDATA%\RevoBIM\revobim_addins_pane_error.txt`.
- **The button says when Revit is still running an older docked panel.** A
  docked pane runs the code Revit loaded at start up; unzipping an update or a
  pyRevit reload does not replace it, only a Revit restart does. The pane now
  records its version, and the button says so once per session when it
  differs from what is installed.
- Bench rule: the pane host is painted, built on more than one event, and its
  messages set their own text colour.

## 1.4.0

Shrink to the taskbar on every window, docking that works, and a polish pass.

### Docking - why it still floated, and the fix

- **The startup block named one host object, and on some pyRevit builds that
  name does not exist.** 1.2.0 to 1.3.0 called
  `register(__uiControlledApplication__)`; where pyRevit does not define that
  name the line raised `NameError`, the wrapper swallowed it, and the pane was
  simply never registered - with nothing written anywhere. The new block looks
  up `__uiControlledApplication__`, `__uicontrolledapplication__` and
  `__revit__` through a guard, offers all three, and `rba_dock.register` uses
  whichever actually has `RegisterDockablePane`. Where none has it but one
  carries the controlled application, it registers from
  `ApplicationInitialized` instead - still inside start up.
- **Every attempt is logged** to `%APPDATA%\RevoBIM\revobim_addins_startup.txt`:
  each candidate, its type, which one registered, and any refusal. It carries
  the Revit process id, so the floating window can say *which* case it is in -
  "restart Revit to dock" (the block did not run this session) versus "see the
  startup log" (it ran and could not register) - instead of a generic "paste
  the fragment".
- **The button never registers any more.** Registering from a command is
  accepted and the pane is never created, after which `GetDockablePane` throws
  for the rest of the session. 1.1.0 to 1.3.0 tried it on every press.
- **The registered state lives in the AppDomain** and Revit is asked
  (`DockablePane.PaneIsRegistered`), because the pane lives in the startup
  engine and the button in its own - a module flag set in one is invisible in
  the other, and a pyRevit reload resets it.
- **The pane builds lazily**: Revit is handed an empty `Border` at start up and
  the panel is built inside it on first show. Start up costs next to nothing,
  and a failure building the panel lands as a message inside the pane rather
  than taking the registration down with it.
- **A docked pane re-reads the folder every time it is shown**
  (`IsVisibleChanged`), since the button that shows it runs in another engine
  and cannot ask it to.

### The floating window docks too

- **Dock left / dock right** buttons in the header snap the window to that edge
  of Revit's drawing area, full height, and it follows Revit when Revit is
  moved or resized. Press the lit button again to float it back where it was;
  drag the header and it lifts off under the cursor - a plain click on the
  header does not. Docked, only the width is the user's to change.
- It uses the same `dock` setting as the real pane, so whichever route a
  session takes, the panel comes up on the same side.

### Shrink to the taskbar - every window

- The floating window, the Settings dialog and the keyboard shortcut prompt all
  carry a **shrink** button top right. It slides the window down to the bottom
  of its screen like a drawer closing, leaving only its header bar floating
  8px clear of the taskbar; the button becomes a **green up arrow**. The arrow,
  a double click on the bar, Escape, Enter, F11 or **Ctrl+Shift+H** bring it
  back. The bar drags, and opens upward from wherever it was carried, kept on
  that screen. Bars stack 4px apart; a freed slot is reused.
- A dialog **takes the floating window down first**, so the main window is not
  left standing over Revit, and parks its own bar above it. Reopening or
  closing the dialog brings the main window back. Settings and the prompt are
  modal: shrinking shows the model, but Revit stays locked until they are
  answered - that is what modal means.
- In the shortcut prompt **Ctrl+Shift+H is captured as a shortcut** while the
  prompt is open, since it is a perfectly good one to assign; parked, it still
  brings the prompt back.
- Built once as `rba_drawer`, to the house standard's five traps: eased by
  hand on a 15 ms timer (no animation left holding the window), MinHeight and
  SizeToContent relaxed and put back, body pinned for the slide, grips parked
  with the window, keys redirected while parked. A frame that throws lands the
  window rather than leaving it half way. Docked in Revit the pane has no
  shrink button - Revit owns that frame.
- Glyphs are Paths, never symbol-font characters.

### Revit's own dark colours, and the dark bar in light mode

- **The dark palette is now Revit's**, sampled from its Project Browser: slate
  panel `#3B4453`, fields `#2C3440`, header and footer bars `#222933`, hover
  `#414B5A`, edges `#515C6B`, text `#F5F5F5`. A docked panel now sits beside
  Revit's own browsers as one surface. The house accents are unchanged.
- **The dark bar across the top of a light window is gone.** It was 1.3.0's
  separate title strip, painted with the theme once when the window opened, so
  switching theme repainted the panel but not the strip. The strip is gone, the
  window frame repaints on every theme change, and the frame edge - hard coded
  `#4A4A50`, dark in both themes - is a palette key (`BrdWindow`) on every
  window. A bench rule now fails any colour written straight into a layout.

### Fixes from an independent review

- **Alt shortcuts can be captured.** Held with Alt, WPF reports every key as
  `Key.System` with the real one in `SystemKey`; the prompt read only `Key`,
  so Alt+letter and Ctrl+Alt+letter were silently dropped.
- **A dialog keeps keyboard focus after it reopens.** Reopening it brought the
  main window back too, whose landing activated a window the modal dialog had
  disabled - Escape and typing stopped reaching the dialog. A disabled window
  is no longer activated.
- The docked-window log could fill every half second if one of Revit's window
  rectangles would not read; each failure is now logged once.
- The floating window no longer reads the folder twice on opening, or again
  every time Revit is restored from minimised.
- The right-click menu carries the theme's templates, rather than drawing as
  the system menu.
- A pane set to start floating gets a real rectangle, not an empty one.
- A quick flick on a docked header still lifts the window off (mouse capture).
- In the startup block, a failure after a successful registration no longer
  overwrites the log with an error.

### Polish

- **One header, not two.** The floating window had a title strip above the
  pane's own header; the pane's header is now the window's header, its window
  controls (dock, shrink, full screen, close) collapsed when Revit docks it.
- **The open window is found again from any engine.** It is kept in the
  AppDomain as a version-stamped `present` action, so a second press of the
  ribbon button - even after a pyRevit reload - brings the open window back
  (reopening it if parked) instead of opening a second copy.
- **Theme changes reach the window frame.** The palette was written only onto
  the panel, so switching theme left the floating window's frame and grips the
  old colour.
- Dialogs are **owned** to the floating window, or to Revit's main window when
  docked, so they cannot slip behind Revit. Escape cancels Settings.
- The window **remembers where it floated**, and comes back there if that is
  still on a screen, else centred.
- Clicking the RevoBIM logo never drags the window, without costing the easter
  egg a click.
- Settings changes made in the panel no longer trigger a second, redundant
  reload from the watch timer.
- One copy each of the screen work area, DPI scale and window ownership helpers
  (`rba_ui`), used by every window.

### Bench

- `import_check.py`: 29 rules, each caught by its own deliberate breakage. New:
  every module that opens a Window gives it a drawer; every shrink button
  carries both glyphs with the up arrow green and hidden; the drawer wires its
  button, keys and close; no WPF animation anywhere; the pane is registered
  only by `rba_dock.register`, which takes `*candidates` and asks each. A
  breakage whose anchor has moved now reports as a failed proof instead of
  crashing the run.
- `bench_logic.py`: 144 checks, 18 breakages caught. Whole slides are driven
  against a stand-in window, clock and timer: landing position, the five traps,
  stacking and slot reuse, owners, keys, a dragged bar, a frame that throws,
  and a monitor above the primary with a negative work-area top.

## 1.3.0

A right click menu on every addin row.

- **Pin to the top.** Pinned addins get their own group above everything else,
  in the order they were pinned rather than alphabetically - a pinned list is a
  list somebody arranged, and re-sorting it would move things out from under
  the hand reaching for them. They stay in their normal group as well. Saved
  per user; the group collapses like any other.
- **Add to Revit's Quick Access Toolbar.** There is no API for the QAT: Revit
  keeps it in `UIState.dat`, which is binary and undocumented, and asking for a
  way to edit it programmatically is a standing Revit Idea rather than a
  feature. What works is AdWindows - the ribbon Revit draws is a
  `RibbonControl` whose `QuickAccessToolBar.Items` will take a button. Two
  consequences, both handled rather than hoped for: the item has to be a
  **clone** (a WPF element has one parent, so adding the live ribbon item takes
  it off the ribbon), and it **does not persist**, because Revit rebuilds its
  toolbar from `UIState.dat` at start up. The tool keeps its own list and
  **re-applies it every time the panel reads the folder**. Every call is
  verified by reading the collection back - a void API call is not evidence.
- **Assign a keyboard shortcut.** A prompt captures the keys, live: letters
  typed one after another make a Revit sequence like `VG`, and holding Ctrl,
  Shift or Alt makes a combination instead - which replaces the sequence,
  because Revit will not take both at once. **A clash is reported as it is
  typed**, naming the command and the ribbon path that already holds it, and
  Assign becomes "Assign anyway". Remove takes the shortcut off. The menu shows
  the current shortcut beside its label.
- The shortcut is written into Revit's own
  `%APPDATA%\Autodesk\Revit\Autodesk Revit <version>\KeyboardShortcuts.xml`,
  because there is no API for it either, and the command id comes from the live
  ribbon item - the only place it exists. **The file is parsed with a regex
  rather than an XML round trip**: it is machine written and flat, a round trip
  reorders and re-quotes every attribute in the file, and a shortcut file Revit
  then rejects costs the user every shortcut they have. One backup is kept
  beside it. It takes effect at the next Revit start.
- **Open Revit's Keyboard Shortcuts** posts Revit's own dialog with the addin's
  name on the clipboard, since its list cannot be pointed at a command from
  outside. Where the command cannot be posted, the menu path is named rather
  than the button doing nothing.
- Copy its name, and open its folder.
- `ContextMenu`, `MenuItem` and `Separator` are templated in `Theme.xaml`. The
  stock ones ignore `Background` and render as the OS menu, which in a dark
  panel is a white slab.

## 1.2.0

The tool no longer depends on a dockable pane being available.

- **Revit only sets a dockable pane up during start up.** `SetupDockablePane`
  is called while the Revit user interface is being built, so a pane
  registered after that is accepted by `RegisterDockablePane` and then never
  actually created - `GetDockablePane` throws and there is nothing to show.
  That was the "Revit would not hand back the pane" in 1.1.0. Registering from
  the command is still attempted, because it costs nothing and a release that
  allows it gets real docking with no setup.
- **Floating window fallback.** Where no pane comes back, the same control is
  hosted in a modeless window instead: owned to Revit's main window so it
  cannot slip behind, its own eight resize grips, full screen by bounds on
  F11 / the button / a double click on its strip, and its size remembered. The
  footer says it is floating and what to paste for docking.
- `__persistentengine__ = True` on the loader, without which pyRevit tears the
  engine down when the command returns and leaves the window on screen with
  every handler in it dead. A bench rule ties the two together.
- **A modeless window writes a note when it opens and the first handler that
  runs clears it.** A note still sitting there at the next launch means the
  last window never came alive, which nothing inside that window could ever
  have reported.
- A pane built for a registration Revit then would not honour is **stopped**,
  so its watch timer is not left rescanning the extensions folder every second
  and a half for the rest of the session with nothing on screen.
- Pressing the button with the window open and in front hides it; with the
  window open but behind Revit, it brings it back.

## 1.1.0

Renamed from **RevoBIM Addins**, and no longer needs anything pasted into
`startup.py` to work.

- **The pane registers itself on first click.** `RegisterDockablePane` is on
  `UIApplication` as well as on `UIControlledApplication`, so the button does
  it, guarded by `DockablePane.PaneIsRegistered` - asked every time, not once,
  because a pyRevit reload hands the tool a fresh engine with its module level
  flag back at False while Revit still holds the pane from before. The startup
  fragment is now an optimisation (the pane exists in **View > User Interface**
  before the button is ever pressed), not a requirement.
- **Two tier search.** The box searches names. Underneath the name matches, a
  **Matches what they do** section lists addins whose name does not match but
  whose description does, each carrying the line that matched it. Kept as two
  passes rather than one pooled haystack: pooled, a word buried in a
  description drags an addin up beside an exact name match and the list stops
  being ranked at all.
- **Descriptions are read properly.** The bundle tooltip, the `__doc__`
  assignment (single line, or a parenthesised run of strings) and `script.py`'s
  own module docstring are all pooled, because the tools in this extension are
  not consistent about which they use.
- **Settings are nested in the pane**, behind the Settings chip in its header.
  The second ribbon button is gone and the tool is a single pushbutton again.
- The settings and debug file names keep their old spelling on purpose - a
  missing settings file falls back to the defaults silently, so renaming it
  would quietly throw every saved setting away. A bench rule pins it.
- Bench check up to 23 rules, including the tool name agreeing across the
  folder, `TOOL_NAME`, the ribbon title and the pane header.

## 1.0.0

First release.

- Dockable pane, left or right, registered through `IDockablePaneProvider`.
  The ribbon button shows and hides it.
- Vertical list of every pyRevit addin found in the nominated folders, read
  straight from the folder tree rather than from a list kept by hand.
- Search box at the top, debounced 220ms.
- Collapsible groups, by panel, tab or extension, remembered between sessions.
- Resizable icons: 16, 24, 32, 48 and 64px. `icon.dark.png` is used in
  preference in dark mode where a tool ships one.
- Dark and light, with **Auto** as the default: the palette follows Revit's own
  canvas theme, re-read every 2.5 seconds.
- A `FileSystemWatcher` on each nominated folder re-reads the list when a tool
  folder is added, renamed or deleted, coalesced through a settle delay.
- An addin present in the folder but not on the ribbon is listed greyed and
  says "not loaded - reload pyRevit".
- Three slow clicks on the RevoBIM logo open the arcade.
- `import_check.py` and `bench_logic.py`, every rule proved by `--selftest`.
