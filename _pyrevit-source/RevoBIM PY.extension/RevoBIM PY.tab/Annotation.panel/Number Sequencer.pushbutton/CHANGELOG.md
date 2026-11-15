# Number Sequencer - changelog

## 1.13.2 - 2026-10-23

- Step 2 is now **2.1 Isolate 3D, 2.2 Group systems, 2.3 Pick start,
  2.4 Auto Re-order**.
- **Tag Views or Sheets window**: **6.1 Tag family** (the tag choice) above
  **6.2 Sheets or views to tag in**, where Sheets and Views are **tabs**
  (counts on the tab names; the last one used opens) instead of side by side.
  The window opens narrower (900 wide).

## 1.13.1 - 2026-10-23

- **Step 2 has its own row** under Duct / Pipe, in order: **2.1 Isolate 3D**
  (filled green, with its 3D view beside it), **Group systems** (a green
  button with its name), **2.2 Pick start** (filled green until a start is
  picked, then orange), **2.3 Auto Re-order** - each sub-step in a small red
  square. Isolate Systems 2D stays where it was.
- **Run Sequence waits for a start** on the System Selector: greyed out (and
  says why) until a start is picked.

## 1.13.0 - 2026-10-23

- **Fix: tagging after numbering placed nothing.** The tag chosen (Air
  Terminal Tags) cannot tag fabrication ductwork, so every element was
  skipped (the debug's "tag skipped 183"). Now each element gets a tag that
  can take it: the chosen tag where it can, else the first loaded tag made
  for its category (Fabrication Ductwork Tags, Duct Tags, ...), else a
  multi-category tag. The note under the tag says which other tags will be
  used, and the status after a run says how many were already tagged and how
  many had no tag for their category.
- **Tag untagged only** tick box under the tag choice, on by default: an
  element already tagged in a view is left alone. Off: it gets this tag too
  (never the same tag twice).
- **Opening Tag Views or Sheets switches tagging on.**
- **Sheets: Number column fits the longest sheet number**, and the column
  headings (Number, Name, Views) have drag handles to make Number and Views
  wider or narrower.

## 1.12.5 - 2026-10-22

- **Collapse all / Expand all** at the top right of the tab bar folds every
  section on the open tab (or opens them all); the window shrinks or grows
  once, by the total.
- Step squares have a thick red edge (2.5 px) round the white square, now
  26 px.

## 1.12.4 - 2026-10-22

- **The window follows its sections.** Folding a section shrinks the window by
  the height it gave up (the bottom edge comes up); opening it grows the
  window back (never past the bottom of the screen). Not in full screen or
  while shrunk to a bar. The window opens at the size it was closed at.
  Minimum height lowered to 360 so it can shrink.
- **Step numbers** are red on a white square (still bold, 14 pt, shadowed).

## 1.12.3 - 2026-10-22

- Step numbers are red, a size bigger (14 pt in a 24 px square), and each
  blue square has a soft drop shadow.

## 1.12.2 - 2026-10-22

- **Step numbers** - each section heading has a blue square with a white bold
  number, the order to work through: System Selector 1 Families, 2 Systems;
  Sequencer 1 Systems, 2 Families; then 3 Start point, 4 Parameter,
  5 Sequence, 6 Tag Views or Sheets, 7 Run Sequence.

## 1.12.1 - 2026-10-22

- **Tag Views or Sheets** button is green (green outline and text, like Pick
  start and Auto Re-order), so it reads as a step to take before Run Sequence.

## 1.12.0 - 2026-10-22

- **Tag Views or Sheets opens like the other RevoBIM windows** - it pours out
  of its button (the Mac genie), and Apply or its close button pours it back.
- **The tag choice sits above both sides** of that window, and a **splitter**
  between Sheets and Views sets how wide each is (half each to start).
- **Double-click the top or bottom edge** of either window to stretch it to
  the monitor's full height; double-click again to put it back.
- **Shrink to a bar** - a new button top right of both windows slides the
  window down to the bottom of the screen, leaving just its header bar
  floating, so Revit can be seen. The button turns into a **green up arrow**
  that slides it back (a double-click on the bar does too).

## 1.11.0 - 2026-10-22

- **Pick start / Auto Re-order** (System Selector) sit under the Duct /
  Pipe buttons. **Pick start** is green until a start is picked, then orange
  ("Start picked" - press to pick another). **Auto Re-order** (was Auto next)
  only comes on once a start is picked, and is green whenever a re-order can
  help: after picking the start, removing or restoring elements, grouping,
  ungrouping or re-ordering inside a group. It works the whole order out again
  from the start - every system and group nearest-next - then goes plain until
  something changes. Shift: just the next one.
- **Remove from sequence** has its name back and is red (filled red, with the
  count, while elements are selected).
- **Tag Views or Sheets** - the tag drawer is gone. A big button under the
  sequence settings (with "tags on - 9 view(s) ticked" beside it) opens its
  own, bigger window: Tags and Sheets on the left, the views on the right, the
  same theme button top right. **Apply** (bottom right) goes back to the main
  window, whose green button now reads **Run Sequence** (bigger).
- **Open what you tagged.** After a run that tagged in ticked views, the tool
  asks whether to open them: a sheet whose views are all ticked opens as the
  sheet, the other ticked views on their own, one tab each.

## 1.10.0 - 2026-10-22

- **Isolate 3D moves the section box to the systems.** When the 3D view's
  section box is on, it is fitted to the isolated systems (their extent plus
  300 mm) on every press, and again whenever the systems change (Refresh in a
  new view, ticks, removals). The view's own box is kept and put back on
  Reset 3D isolate and when the tool closes.
- **Isolate Systems 2D / Isolate 3D** sit side by side; either one turns
  Colour systems on (and off again with its reset, unless you turned it on).
- **A more compact window** - one column, the tag drawer closed:
  - System Selector: **families first**, sized to show every family (up to
    half the pane, never squeezing the systems table), then the **systems**.
  - Every systems tool on **one row**: Isolate Systems 2D, Isolate 3D, the 3D
    view, Colour | Up, Down, Top, Bottom, Auto order | Group, Ungroup,
    Reorder in group | Tick all, Untick all, Remove, Restore. Most are icons
    (hover for the name); counts show beside them.
  - **Start point**, then **Parameter**, then **Sequence** (one row: format,
    start at, count) below the systems, shared by both tabs.
- **Every section folds away** with the chevron on its heading - it slides
  shut and open - and stays as you left it next time.
- **Tags live in the tag drawer.** The Tags settings moved into the Tag in
  views column, which opens closed: the handle on the right ("TAG IN VIEWS",
  orange "TAGS ON" when tagging is on, with the ticked view count) slides it
  out, the window growing to make room (to the left as well near the screen
  edge) and giving the room back when it closes.

## 1.9.1 - 2026-10-22

- **Fix: colours left on the view after closing.** The closed window is now
  held until its tidy-up has run (before, nothing referenced it, so it - and
  the request to put the view back - could be thrown away before Revit ran
  it). The tidy-up takes the colours off first, each step on its own, so a
  view that will not reset can no longer leave them on; if Revit refuses the
  request it is done the next time Revit is idle.
- **Colours left from before are found and taken off.** The tool's colouring
  now carries an invisible mark (1% surface transparency). Reading a view
  finds elements still carrying the tool's colours from an earlier session
  (marked, or - for colours left by 1.9.0 and earlier - one colour from the
  tool's palette on lines and patterns alike); the Colour button then reads
  **Clear colours (n from before)** and one press takes them off. Colour
  systems on then off also takes them off (they are recorded as "no
  override", not put back). Run and closing the window take them off too.
  Someone's own colour overrides (a colour the tool never uses) are left
  alone.

## 1.9.0 - 2026-10-16

- **Group systems** (System Selector, new GROUP row). Select elements of two
  or more systems in the view (the button lights orange, "Group systems (n)")
  or select two or more rows in the table, then press Group systems. A group
  is numbered as one block: its members sit together in the list, marked by a
  Group column ("G1  2/3") and a gap above and below.
- **Group colours.** A group is drawn in one hue, darkest first to lightest
  last, so the shade shows the order; re-ordering inside the group re-shades it
  straight away (table and view). Each group keeps its first member's hue when
  that is clear of the other groups, else takes the hue furthest from them;
  lone systems near a group's hue are moved to a clearly different colour.
  Grouping turns the colours on.
- **Reorder in group** puts the selected systems' groups (every group when
  none is selected) in nearest-next order: first the member nearest where the
  systems before it finish (or the one holding a picked start), then each next
  the nearest to where the last finished. Unticked members go to its end.
- **Auto order** moves groups as one, in their own order: after each group or
  system, the next is the group or system whose start is nearest where the
  last finished. **Auto next** and **Pick start** place whole groups too (a
  start picked inside a group leads it).
- **Moving with groups.** Shift+Up / Down: a member steps inside its group,
  and a step past its end takes it out; a lone system or a whole group steps
  over a whole neighbouring group and never falls into it. Drag: a system
  dropped between two members joins their group, a member dragged away leaves
  it, a whole group dropped inside another goes on after it. Right-click >
  **Select its group** selects every member. **Ungroup** breaks up the
  selected systems' groups. A system removed from the sequence keeps its group
  and goes back into it on Restore.
- **Tag in views: Sheets.** A sheet list (search by number or name) above the
  views. Click a sheet (Ctrl / Shift for several) to show only the views placed
  on it and tick them for tagging; a sheet's tick box ticks or unticks its
  views and shows all / some / none ticked; double-click opens the sheet.
  **Clear sheets** shows every view again (ticks stay).

## 1.8.0 - 2026-10-16

- **Isolate in 3D** (System Selector). Opens a 3D view, isolates the ticked
  systems there (the families ticked below, with their tags) and colours each
  system its swatch colour, the start in magenta, then zooms to fit. The
  picker beside it chooses the view: **Default 3D view** ({3D - you} in a
  workshared model, else {3D}; made if the model has none) or any 3D view.
  The choice is remembered.
- While on, the button reads **Reset 3D isolate** (orange) and the 3D view
  follows the table - ticking, unticking, the family list and Remove from
  sequence all update it. Selecting elements in the 3D view and pressing
  Remove takes them out there too. Opening the 3D view no longer lights
  Refresh.
- Reset isolate and Clear colours leave the 3D view alone (it has its own
  button); Run turns its colours off; closing the window resets it.
- **The selector tools are grouped into three captioned rows:** VIEW (Isolate
  systems, Colour systems, Isolate in 3D, 3D view), ORDER (Up, Down, Top,
  Bottom, Auto order) and INCLUDE (Tick all, Untick all, Remove from sequence,
  Restore removed).

## 1.7.0 - 2026-10-16

- **Tag in views lists sections and 3D views** as well as floor plans (no
  templates). A new **Type** column shows Floor plan / Section / 3D, with its
  own text filter, sort and value-list funnel.
- **Show: Floor plans / Sections / 3D views** tick boxes above the list - all
  on, or any one on its own. They and the Type column's value list are the
  same filter, kept in step, and remembered.
- Ticked sections and 3D views take tags like plans. A 3D view must be locked
  to take tags - an unlocked one shows "3D (unlocked)" in Type and is reported
  if ticked. The active-view fallback on the System Selector stays plans only.

## 1.6.0 - 2026-10-15

- **Tag in views: Excel-style value lists on every heading.** A funnel button
  on View, View Group 1 and View Group 2 drops down every value in that column
  (blank shown as "(blank)") with how many views carry it, a search box, and
  **Select all** / **Clear all** (acting on what the search shows). Untick a
  value to hide its views; everything ticked means no filter, nothing ticked
  shows nothing. The list offers the values the other columns let through,
  and still lists its own unticked ones so they can be ticked back. A funnel
  turns orange while its column hides anything.
- **Clear filters** clears every column's text and value filter.

## 1.5.1 - 2026-10-15

- **Tag in views has its own column** to the right of the sequencing options,
  so the view list gets the full height and more width. A splitter either side
  of the options column sets the balance. The window opens wider (1500) but
  never bigger than the screen's work area.
- The sequencing options column scrolls if the window is made short.

## 1.5.0 - 2026-10-15

System Selector:
- **Pick start** now puts its system at #1 and lights **Auto next** (orange,
  with how many systems are left to place).
- **Auto next** makes the call: of the ticked systems not yet placed, the one
  whose nearest open end is closest to where the last placed system finishes
  numbering goes straight after it, is selected and selected in Revit; the
  status gives the distance. Press again for the next. **Shift + Auto next**
  places all the rest the same way. Without a picked start it chains from #1.
- The old Auto (back to the automatic start) is on the right-click menu as
  **Clear picked start**.

Both tabs:
- **Tag in views** below Tags: every floor plan (no templates) with columns
  View, View Group 1 and View Group 2. Each group column shows a view
  parameter chosen from the drop-down in its heading (defaults to the first
  parameters mentioning group / discipline / series; remembered). Type under a
  heading to filter that column; click View or Sort to sort (again to
  reverse). Tick shown / Untick all; double-click a view to open it. Ticks are
  remembered per view.
- When tagging, every ticked view gets tags on the numbered elements it shows
  (its own visibility, inside its crop); with nothing ticked the active view
  is tagged as before.
- **Find views with this system** narrows the list to the floor plans that show
  the selected system(s); All views shows them all again.
- A dependent view is tagged through its parent (dependents show the
  parent's tags), once. A view list from another document is refused, never
  used. Choosing (none) for a group column sticks. Ticks of other projects'
  views are kept.
- Reviewed before delivery: per-view visibility scanned every category (now
  one collector per view on just the wanted categories, views whose crop
  misses the system skipped, Find stops at the first hit), a double-click
  flipping the tick, (none) snapping back, stale view ids aborting a Run,
  duplicate tags through dependent views, ticks lost across projects, and a
  silent failure opening a view - all fixed.

## 1.4.0 - 2026-10-13

- **Only systems still in the view are listed.** A system whose every element
  has been removed from the sequence drops off the list straight away.
  Restore removed brings them back where they were, shows the hidden elements
  again and reads the view again.
- **Refresh works after Remove.** Hidden elements are meant to go, so Refresh
  now reads the view and leaves out the systems they took with them (it still
  waits while the tool's own isolate is on, which hides the unticked systems).
- **Right-click a system** (or several selected):
  - **Move to...** - a prompt for the position number (# in the list, 1 to the
    number of ticked systems), pre-filled with where it is now; Enter moves,
    Escape cancels.
  - **Move to top**.
  - **Move to next** - straight after where the last move landed (shown as
    "Move to next (#6)"), so systems can be put in order one after another.
    Every kind of move counts: Move to, Top, Shift+Up/Down, drag, Top/Bottom.
  Right-clicking a row that is not selected selects it first.
- The menu and the prompt follow the dark / light theme.
- Restore removed brings back everything removed on both tabs (unhiding a view
  shows what either tab hid in it), puts each system back straight after the
  row it followed, then reads the view again if it was the hidden one.
- Reviewed before delivery: restore order after several removals, Restore
  greyed out after a Refresh, Restore on one tab unhiding the other's, the
  re-read after Restore being dropped while busy, Move to next surviving a
  refresh, a gap after an unticked system, and the prompt's range - all fixed.

## 1.3.1 - 2026-10-13

- **Too many systems listed** (live report, Revit 2026, 1642 fabrication
  ductwork parts in view, 147 rows). The log showed only 139 connections
  between 1642 parts: the fabrication parts sit end to end but are not
  connected in Revit, so every part with no System Name became its own
  "No system" row. Now:
  - open connectors that touch (within 5 mm) and face each other are joined
    before grouping, so butted parts form one run - and the walk follows them;
  - only elements inside the view's crop region (or a 3D view's section box)
    are read - Revit's view collector can return elements beyond the crop;
  - the debug log now says how many connections Revit has, how many were
    joined, how many elements were outside the crop, how the elements were
    labelled (Revit system / System Name only / neither) and lists the rows.
- **Pick in the view, find in the list**: select an element in Revit and its
  system's row is selected and scrolled to (several rows if the pick spans
  systems). The Revit selection is left as you made it. A pick on the other
  kind (pipe while on Duct Systems) switches sub-tab if that kind is read.

## 1.3.0 - 2026-10-13

System Selector:
- **Select several systems**: Ctrl+click toggles a row, Shift+click selects a
  range (Ctrl+Shift adds the range). The selected systems are selected in
  Revit together. Ticking a selected row ticks every selected row.
- **Up / Down arrow keys** step the selection through the systems (wrapping
  round) and select each in Revit. **Shift+Up / Shift+Down** move the selected
  systems. The Up / Down buttons do the same: a plain press steps, Shift+press
  moves. Top / Bottom move the selected systems.
- **Sleeker drag**: the dragged rows fade, a blue insertion line shows above or
  below the row under the cursor (upper / lower half), the table scrolls near
  its edges, every selected row moves together, and dropping below the last
  row moves them to the end. The current row carries a blue edge.
- **Isolate** is one button: Isolate systems / Reset isolate (orange when on).
  It shows only the families ticked in the tree, in the ticked systems, minus
  removed elements - no accessories or terminals - with every tag on them.
  It turns the colours on too; resetting turns them off again if the isolate
  turned them on. Ticking, unticking or removing while isolated re-isolates.
- **Colour** is one button: Colour systems / Clear colours (orange when on).
- **Pick start** turns the colours on and draws the start in magenta at a
  heavy line weight - a colour no system is given. The first element numbered
  and every picked start are drawn this way; the row shows "(start)".
- **Remove from sequence**: select elements in the view and the button lights
  orange with the count (Revit's SelectionChanged event, 2023+; the tool's own
  selections are ignored). Pressing it leaves them out of the numbering and
  hides them - re-isolating without them when isolated, a temporary hide
  otherwise. **Restore removed** puts them all back.
- **Changing view** lights Refresh orange ("Refresh - view changed", from
  Revit's ViewActivated event, with a check when the window is activated).
  Refresh reads the systems in the new view - plan, section, 3D or any other -
  keeping the order, ticks and colours of systems already listed.
- **Closing the tool resets every isolate it made** and puts the colours back.
- Revit events are hooked when the window opens and unhooked when it closes;
  anything an earlier load left hooked is unhooked first.
- Closing tidies every open document the tool touched, not just the active
  one. Refresh refuses only in a view the tool itself isolated or hid in.
- Re-ordering never re-colours the view (the colour check ignores order).
- Reviewed independently before delivery: refresh after returning to an
  isolated view, tags missed on re-isolate, Remove after a row click, hides
  reset in the wrong view, toggles dropped while busy, other documents left
  coloured, kind switching with the toggles on, re-colouring on every move,
  drops below the last row, and the on-button unreadable on hover - all fixed.

Everywhere:
- **Icons** on every button and tab (vector paths drawn in the button's own
  colour, so hover, disabled and the light theme follow), including Apply /
  Run and the results window.

## 1.2.0 - 2026-10-13

- **System Selector tab** beside the Sequencer tab, with **Duct Systems** and
  **Pipe Systems** sub-tabs. Lists every system in the active view with its
  system references (name, system type, abbreviation, classification), its
  element count and the number range it will get.
  - Fabrication ductwork / pipework is included: parts Revit gives no system
    take the system of the run they are joined to; anything still loose is
    listed as "No system - <service>".
  - Duct / pipe accessories are walked through so a damper never splits a
    run, but are never numbered or selected. Equipment, air terminals,
    fixtures and sprinklers are never selected or numbered either.
  - Click a row to select that system in Revit, double-click to zoom to it.
  - Re-order by dragging a row, or Up / Down / Top / Bottom; Auto order keeps
    the first system and takes the nearest next. The table order is the
    numbering order. Untick a system to leave it out.
  - Numbering starts at the picked start (Pick start), else the auto start;
    each next system starts at its open end nearest where the previous one
    finished, and the numbers run on.
  - Leave out... / Put back... pick single elements out of (or back into) the
    numbering; Clear left out resets.
  - Category > Family > Type tree of the ticked systems, as on the Sequencer.
  - **Isolate systems** temporarily isolates the ticked systems with every tag
    on them (and the terminals on them); Reset isolate.
  - **Colour systems** overrides each system in the view with a unique colour,
    the same colour as its swatch in the table. Each element's own override is
    recorded first and put back by Clear colours, by Run, or when the window
    closes.
  - The parameter, format, start number, direction and tag options are shared
    with the Sequencer tab. **Run** bottom right. Tags go on plan views only.
- Family tree moved into its own module, used by both tabs.
- Selecting in Revit from the window never blocks it; quick clicks only send
  the last selection.

## 1.1.0 - 2026-10-09

- **Several systems in one sequence.** A Systems list sits above the
  families: each row shows its order badge, system name, the number range it
  will get and its element count. Numbers run on from one system into the next.
  - **Add selection** adds every duct system in the Revit selection (tab-select
    several). Each connected system becomes its own row, ordered from the
    start point, then the system nearest to where the last one finished, then
    the next nearest.
  - **Pick systems** keeps picking: click the first element of each system in
    the order to number them, Esc when done. Each click is that system's start.
  - Up / Down / Remove / Clear on the list; click a row to choose it (Start
    point acts on the chosen system), double-click to select it in Revit.
  - Equipment never joins two systems together - it goes with the system on
    its biggest connection.
  - Pressing the ribbon button with the window open adds the selection.
- **Parameter dropdown you type into.** Click the box and the full list opens;
  type and the list narrows to parameter names containing the text (names
  starting with it first). Up / Down / Enter or click to choose, Esc goes back.
  Typing never changes the chosen parameter; an exact name typed counts when
  you leave the box. Each line shows text / integer and how many elements
  carry it.
- Parameter counts follow the elements still in the sequence after a system is
  removed.

## 1.0.0 - 2026-10-08

- First release. Annotation panel, RevoBIM PY tab.
- Modeless window owned by Revit; every read and write through one ExternalEvent.
- Reads the Revit selection on open (a tab-selected duct system, or a selected
  duct system element) or **Pick system** - click the first element and the
  connected run is read with numbering starting there.
- Families listed Category > Family > Type, collapsible, a colour per family,
  tri-state ticks; unticked types are walked through but not numbered and are
  remembered.
- Walk: starts at the equipment connection, else the biggest open end, or a
  picked start. At every junction each branch leg is numbered in full (nearest
  first) before the main carries on - biggest outlet, straightest on a tie.
  Taps on a duct count as branches. A start picked mid-run numbers forward,
  then the run behind it. Separate pieces follow on.
- Any writable text or integer instance parameter, keyword search that never
  changes the choice; format 001 / 01 / 1; start number counting up or down
  (never below 0).
- Optional tag of every numbered element in the active view with a chosen
  tag type; skips elements already carrying that tag; says up front how many
  the tag's category can take.
- Workshared: borrows before writing and names anyone holding an element.
  One transaction with a sub-transaction per element, per-element fallback,
  values read back after the transaction group closes.
- Silent on a clean run; a themed results window only when something needs a
  look (double-click a line to select it in Revit).
- Auto / Dark / Light theme chip top right, Auto follows the Revit canvas.
  Version top right, full screen, resize grips, Debug + Copy debug.
