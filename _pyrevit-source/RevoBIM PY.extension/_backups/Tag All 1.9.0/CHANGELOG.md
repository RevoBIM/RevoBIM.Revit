# Tag All - changelog

## 1.9.0

- **Default tags per family.** Every family row in the Categories tree has
  its own Default tag dropdown, lined up under its category's.
  - **Setting a category's default fills all its families with that tag** -
    including any set by hand before - and the tree redraws to show it.
  - **Then change any family on its own.** That family's rows go into
    Families to tag on its tag; the rest keep the category's.
  - A family following its category shows the tag in muted text; one set by
    hand shows it in full. Picking the category's own tag on a family puts it
    back to following. A family can be set to `<None>` while its category
    has a tag.
  - Remembered between sessions, as `defaulttag:<category>|<family>` lines
    beside the category's `defaulttag:<category>`. Existing settings carry on
    as they were.
  - Rows already in Families to tag are not changed by a new default; it
    applies to rows as they are added.
- Bench: **586 logic checks**, selftest **84 of 84**. import_check 45 rules,
  selftest **57 of 57**.

## 1.8.0

- **New option: Untangle tags vertically**, in Tagging options under Tag all
  not tagged. Off by default; remembered.
  - Once every tag in a view has been placed, the new tags are measured (with
    their leaders off, the same way the elbows are) and any that touch are
    moved apart along the view's up direction until none touch.
  - Taken from the top of the view down: the topmost tag stays where it is,
    and each tag that touches one above drops to just below it, keeping its
    side position. Tags side by side that do not touch are left alone.
  - The gap between stacked tags is 1 mm on paper, scaled by the view
    (100 mm in the model at 1:100), so it looks the same at any scale.
  - Moving a head leaves an elbow behind, so after the tags move the view is
    regenerated and every moved tag's elbow is set again, level with its
    tag's centre line as before.
  - All the tags in a view are untangled together, whichever chunk placed
    them. One transaction per view, inside the run's group, so Undo takes
    the whole run back as before.
  - Only the tags this run placed are moved; tags already in the view stay
    put and are not used as obstacles. Room Tags is unchanged.
  - The results list how many tags were moved in each view.
- Bench: **572 logic checks** (untangling, including sixty tags dropped at
  random ending with none touching and none moved up), selftest **81 of
  81**. import_check 45 rules, selftest **56 of 56**: untangle_view must
  measure with leaders off, regenerate before setting elbows, and run only
  after the view's tags are placed.

## 1.7.1

- **Ticked views and Sheets collapse the other groups**: Views / Sheets
  expands on the matching tab, and Categories and Families to tag both
  collapse (1.7.0 left Families to tag as it was).
- **The Categories tree opens fully expanded**: every category and every
  family is open, down to the types. Collapse all, or a click on a row's
  arrow, still shuts them, and they stay shut until Expand all or the next
  time the window opens.
- Bench: **556 logic checks**, selftest **78 of 78**. import_check 45 rules,
  selftest 55 of 55.

## 1.7.0

- **Tagging options sit inside Families to tag**, under the table, so they
  open and close with the families they apply to. Collapsed, the run still
  uses them as last set.
- **With every group collapsed, the window shrinks to fit the bars**: the
  footer and Tag All ride up under the last bar, sliding with the groups.
  Expand any group and the window grows back to the height it had - never
  further. Not on Room Tags (switching to it puts the full height back), and
  not while full screen or parked on the taskbar.
- **The linked models list starts collapsed** inside Categories. The badge
  still says how many are ticked, and All, None and Refresh still work.
- **Families in the Categories tree start expanded**, showing their types.
  Categories still start collapsed; Collapse all shuts families too, and a
  family shut by hand stays shut until Expand all.
- **Current view on the Views / Sheets bar collapses Views / Sheets and
  expands Categories**, so cycling Current view - Ticked views - Sheets -
  Current view ends back on the categories.
- Bench: **555 logic checks**, selftest **77 of 77**. import_check **45
  rules**, selftest **55 of 55**.

## 1.6.0

- **Groups slide open and shut like a drawer** (220 ms, the same easing as the
  shrink drawer). The final layout is worked out first, out of sight, so each
  group knows how tall it will land; while it slides the body inside is
  pinned at its full height and clipped, so it reads as a drawer drawn out
  rather than a panel being squashed. A click during a slide lands it first.
- **Click anywhere on a group's bar** to expand or collapse it, not just its
  title. Buttons on the bar (Remove, Clear, the source buttons) still do
  their own job and never toggle the group.
- **Opens with Categories expanded**, reading the current view, and Views /
  Sheets and Families to tag collapsed.
- **Current view / Ticked views / Sheets are buttons on the Views / Sheets
  bar**, the one in use lit in blue. They replace the Current view only and
  Ticked views radios on Family Tags (Room Tags keeps its radios).
  - **Current view** tags the open view; the groups stay as they are.
  - **Ticked views** expands Views / Sheets on the Views tab and collapses
    Categories.
  - **Sheets** expands Views / Sheets on the Sheets tab and collapses
    Categories.
  - Switching the Views / Sheets tab by hand lights the matching button.
  - The opening rules are unchanged: opened in a view it starts on Current
    view; opened on a sheet, or with views picked in Revit, it starts on
    those views, ticked.
- **Add ticked collapses Categories and expands Families to tag**, so the rows
  just added are in front of you with their tag dropdowns.
- The first time Categories is expanded by hand, Views / Sheets still
  collapses to make room; after that it is left alone.
- **The linked models list can be dragged taller** from the bar beneath it
  (40 to 600 px). The height is remembered; a double-click on the bar puts
  it back to the size it was built at.
- **A double-click on the window's top or bottom edge fills the monitor** the
  window is on, and a second double-click puts it back - the same as the
  header's double-click and F11. The side edges and corners only resize.
  This works on every Tag All window.
- Bench: **548 logic checks**, selftest **74 of 74**. import_check **45
  rules**, selftest **53 of 53**: the group rule now also checks that the
  header bar, Add ticked and the source buttons slide the groups, that the
  links grip and the edge double-click are wired.

## 1.5.0

- **Family Tags is three groups stacked top to bottom** - Views / Sheets,
  Categories, Families to tag - instead of three columns side by side. Each
  group collapses to its header and expands again from a click anywhere on
  the header; the chevron points down when open and right when shut.
- **Each group has its own icon**: a sheet holding a viewport for Views /
  Sheets, a small hierarchy for Categories, the tag for Families to tag. The
  blue and orange accent ticks stay beside them.
- **It opens with Views / Sheets expanded and the other two collapsed.** The
  first time Categories is expanded, Views / Sheets collapses to make room.
  After that, expanding Categories leaves Views / Sheets as it is. Families to
  tag never collapses anything.
- Open groups share the height between them; a collapsed one is only as tall
  as its header. The counts (types read, rows to tag) and the Remove / Clear
  buttons sit in the headers, so they show while a group is collapsed.
- **Tagging options stay at the bottom of the tab**, always showing, so the
  leader and offsets can be checked without expanding anything.
- The groups start in the same state every time the window opens; it is not
  remembered between sessions. Room Tags is unchanged.
- **Fixed: the Expand buttons showed the shrink drawer's up arrow.** ICONS drew
  `expand` twice and the second (the drawer's) silently won. The drawer's is
  `unshrink` now.
- Bench: **524 logic checks**, selftest **68 of 68** - the first-round rule,
  the start state and the filler row each have a deliberate breakage.
  import_check **45 rules**, selftest **48 of 48**; new rules: no icon drawn
  twice, and every group has its header, body and row and is wired through
  `core.toggle_family_group`.

## 1.4.2

- **Dark now uses the same Revit dark palette as the rest of the suite**
  (Pro Sheets, Sheet Manager, Project Browser Pro), sampled from Revit's dark
  Project Browser. 1.4.1 had its own reading of the same screenshot, which
  left Tag All a touch darker and dimmer than the tools beside it.

  | Part | Was | Now |
  | --- | --- | --- |
  | Window body | `#2E3542` | `#3C4454` - Revit's panel grey |
  | Cards | `#3C4454` | `#353D4B` - a shade under the body |
  | Header and footer bars | `#212932` | `#222933` - Revit's title bar |
  | Window edge | `#1B1F24` | `#515C6B` - Revit's window edge |
  | Borders | `#4D5666` | `#4A5464` |
  | Text | `#DCE3EA` | `#EEF0F4` - Revit's near-white |
  | Hover | `#465062` | `#444E5E` - Revit's hover |
  | Selection / highlight | `#2B5473` | `#3A7392` - Revit's active-row blue |
  | Blue | `#72BAF0` | `#5AAEEB` |
  | Muted text | `#ABB3BF` | `#ACB2B9` |
  | Disabled | `#7B8492` | `#6E7684` |

  Fields (`#2D3441`), table headings (`#323C48`), orange, red, violet and
  green are unchanged.
- Muted text is `#ACB2B9` rather than the suite's `#A4AAB1`, because Tag All's
  prompts put muted text straight on the window body, where `#A4AAB1` is
  4.2:1. `#ACB2B9` clears 4.5:1 and looks the same.
- Theme.xaml's default brushes carry the same values, so nothing flashes the
  old colours before the palette lands. The light theme is unchanged.
- Bench: **512 logic checks** (the dark palette is now held to eleven suite
  values, not six), selftest **65 of 65**; import_check 43 rules, selftest
  45 of 45.

## 1.4.1

- **The dark theme now matches Revit's own dark UI**, sampled from its
  Project Browser:

  | Part | Revit's colour |
  | --- | --- |
  | Cards and panels | `#3C4454` - Revit's panel grey |
  | Lists, inputs, search boxes | `#2D3441` - Revit's search box |
  | Header and footer bars | `#212932` - Revit's title bar |
  | The edge round the window | `#1B1F24` - Revit's toolbar strip |
  | Hairlines and borders | `#4D5666` - Revit's tree lines |
  | Table headings | `#323C48` - Revit's selected-row tone |
  | Text | `#DCE3EA` - Revit's off-white |

- **Accents lifted to stay readable on it.** Revit's panel is much lighter
  than the old near-black, so the old blue, orange, red, violet and muted
  grey fell to between 2.8:1 and 3.8:1 against it. Each is lifted just enough
  to clear 4.5:1 and stays recognisably the same colour.
- **Red is split in two**: `RedBrush` for red text, and `CloseHoverBrush` for
  the red behind the close cross, which keeps Windows' own close red so the
  white cross still reads.
- **Glyphs on a light accent are dark now** (`OnAccentBrush`) - the tick in a
  ticked box and the linked models count. White on the lifted blue and
  violet was 2:1.
- The light theme is unchanged.
- Bench: **507 logic checks**. Every pairing in the dark palette that carries
  text or a glyph is held to 4.5:1, and the surfaces are held to Revit's
  sampled values, so the palette cannot drift back.

## 1.4.0

- **Shrink to the taskbar, on every window** - the main window, the results
  window and every prompt. A new button at the top right, before full screen
  and close. Pressing it slides the window down to the bottom of its own
  screen like a drawer closing, leaving only its header bar floating 8 px
  clear of the taskbar so the model can be seen and worked in. The button
  becomes a **green up arrow**; press it, double-click the bar, or press
  Escape, Enter, F11 or **Ctrl+Shift+H** to bring the window back.
  - The parked bar still drags. Carried somewhere else, it opens upward from
    where it now sits rather than jumping back, held on its screen.
  - Several parked bars stack 4 px apart; a freed place is reused.
  - A prompt parks the window it belongs to first, so that window is not
    left covering the model, and brings it back when reopened or closed. The
    main window parks its open results window with it.
  - A prompt opened while the main window is parked - Done, would you like
    to open the sheet? - opens centred on the screen, not on the bar.
  - Full screen and the resize edges are refused while a window is parked.
  - Closing a parked window remembers its real size, not the bar's.
- Built to the RevoBIM drawer standard (theme reference; Pro Sheets
  1.49.0): Top and Height eased together on a 15 ms timer for 280 ms as
  plain values, so no animation is ever left holding them; MinHeight and
  SizeToContent relaxed for the slide and put back; the body pinned so it is
  drawn away rather than squashed; everything beside the header parked and
  put back exactly as it was, so a panel already hidden stays hidden.
- The drawer is `tagall_drawer.py`, with no WPF in it - every WPF call goes
  through a small platform object - so the bench drives whole slides against
  a stand-in window. That caught two real faults before they shipped:
  - **parking the main window with its results window open would have
    recursed for ever** - each window parked the other because neither was
    marked busy yet - which in Revit is a hang the moment shrink is pressed;
  - **a slide could finish more than once**, and each landing recorded the
    panels it had already parked as hidden, so they never came back.
- Bench: **43 rules and 470 logic checks**; the selftests catch all 45 rule
  breakages and all 61 logic breakages. New
  rules: every window carries a wired shrink drawer; no animation holds a
  window's Top or Height; every window's keys go to its drawer first, so
  Escape cannot close a parked window.

## 1.3.1

- **Resizable columns in the Sheets table**, on both tabs. Drag the edge of
  any heading; a hairline shows where each edge is and the cursor changes
  over it. The width moves between the two columns either side of the edge,
  like a splitter, so the table always fits its panel and never needs a
  sideways scroll bar. No column goes below the width its heading's sort
  badge, caret and filter box need.
- **Double-click an edge** to put every column back to its starting width.
- **Remembered per tab** - Family Tags and Room Tags keep their own widths.
  A saved set that no longer fits the table (a different column count, a
  damaged value) falls back to the defaults rather than laying it out wrong.
- Bench: **40 rules and 390 logic checks**. New rule: every sheet row
  registers its grid for column drags, so rows can never be left at the old
  widths while the header moves.

## 1.3.0

- **Sheets tab beside Views** on the Family Tags tab. Every sheet in the
  project, in a table with Number, Sheet name, two group columns and a
  count of the views on each sheet the tab can tag.
  - The two group columns read whichever **sheet** parameters are picked in
    the dropdowns above them - the Sheet Manager's own BGL_ grouping
    parameters first if the project has them - and the choice is
    remembered.
  - **Sort** by clicking a heading's name; click again to flip it,
    Shift+click to add a level beneath, up to six. Sorted headings turn
    orange and carry their place and direction (1▲, 2▼).
  - **Filter** with the same keyword box and Excel-style value list on each
    heading as the views table.
  - **Expand** a sheet to see the views placed on it - **collapsed until
    asked**, with Expand all and Collapse all. Views the tab cannot tag are
    greyed and say so.
  - **Tick a sheet** and Tag All works in every taggable view on it. A view
    on two ticked sheets is tagged once; a ticked sheet with nothing to tag
    on it is named in the status line.
- **The tab showing on the left is the one Tag All runs from**, and
  Categories reads from it. The button says which: "Tag All - 3 sheets",
  "Tag All - 12 views", or plain "Tag All" for the current view.
- **Room Tags' Sheets list is now the same table**, so both tabs filter,
  sort and expand the same way.
- **Progress bar moved into the footer**, beside Tag All, at a size you can
  see, with its percentage. The status line names the view being tagged and
  its place in the run - "Tagging L01 Drainage - view 3 of 12 - 140 of 900".
  It used to be a 5px strip under the header.
- **"Done - would you like to open the sheet?"** after a run from ticked
  sheets, with the run's summary. Open sheet(s) opens them in Revit; Not
  now leaves you where you are. The bar sits at 100% while it asks.
- Bench: **39 rules and 372 logic checks**. New rules: every setting the
  window saves is one load_settings keeps (a key missing from DEFAULTS is
  written and silently dropped on the next load - which the new sheet group
  settings were, until this rule); the tab handler ignores the selection
  changes that bubble up from dropdowns inside the tabs. New checks cover
  multi-level sorting, natural sheet-number order, blanks last in both
  directions, and the open-sheets prompt.

## 1.2.0

- **The view lists start on what the tool was opened on**, on both tabs:
  - **on a sheet** - the views placed on it, ticked, with **Show All Views**
    to list the rest (pressed again it reads **Show Sheet Views**);
  - **with viewports picked on that sheet** - just those views, ticked;
  - **with views or sheets picked in the Project Browser** - those, ticked,
    as before;
  - **in a view** - Current view only;
  - **anywhere else** (a schedule, a legend) - the whole list, Ticked views.
  Each tab answers for itself: a sheet with a plan and two sections starts
  Family Tags on all three and Room Tags on the plan alone. A pick neither
  tab can tag falls through to the next rule rather than leaving an empty
  list. The status line says which rule it started on. The sheet the tool
  opened on also comes in ticked on the Room Tags sheets list.
- **Fixed: viewports picked on a sheet were ignored.** Picking a view on a
  sheet selects its Viewport, not the view, and 1.1.0 only read views and
  sheets out of the selection.
- **Current view only on a sheet** now says to tick the views on it, rather
  than trying to tag the sheet itself.
- The view mode is no longer remembered between runs - what the tool opens
  on decides it. The two group parameters still are.
- **Default tag per category.** Each category row in Categories carries a
  Default tag dropdown, offering only the tags that suit that category. Its
  families start on that tag when they go into the table, and each row can
  still be changed by hand. Saved as soon as it is picked, and there next
  time. A default whose tag family has since been purged leaves new rows on
  <None> rather than guessing; setting it back to <None> forgets it.
- 1.0's remembered last picks (`tagtype:` lines in the settings file) are not
  carried forward, so an old pick never turns up as a default nobody set.
- Bench: **37 rules and 348 logic checks**. New rules: the opening read turns
  a picked viewport into its view; a dropdown is given its starting value
  before its handler is attached, so drawing the tree never reads as a pick.
  Writing the selftests for both caught each rule matching too loosely on
  its first draft - both now check the real code.

## 1.1.0

**Family Tags is laid out in three columns, left to right in the order the
job is done: Views | Categories | Families to tag.**

- **Views, full height on the left.** A table with four columns - View name,
  Family and type, View group, View group 2. The two group columns read
  whichever view parameters are picked in the **Group by / then** dropdowns
  at the top, and the list groups under them with collapsible headings,
  **Expand all** and **Collapse all**. Each column heading carries a keyword
  box and an Excel-style tick list, the same method as the other RevoBIM
  tables: a column's own filter is left out of its own list, the others
  narrow it, and a filtered caret turns orange. A heading's box ticks its
  whole group.
- **Current view only** at the top left greys the whole table out; **Ticked
  views** uses the table.
- **Views selected in Revit before opening** - in the Project Browser,
  typically - narrow the list to themselves and come in ticked, and the
  table starts on Ticked views. **Show All Views** lists the rest and leaves
  the ticks alone; pressed again it goes back to the selection. A sheet
  selected in Revit counts as the views placed on it.
- **Categories in the middle** lists what is in the views ticked on the left
  (or the current view), with **Linked models** kept at the top. Ticking
  views re-reads it by itself on the same settle as ticking a link. A link's
  bounding boxes are now worked out once per read rather than once per view.
- **Families to tag start at <None>.** Click a row to highlight it, Shift or
  Ctrl+click for more, then pick a tag - from **Tag for highlighted** above
  the table, or on any highlighted row - and it goes on every highlighted
  row that can take it. A row whose category cannot take that tag is left
  alone and named in the status line. **Remove** takes the highlighted rows
  out. Tag All asks before running with rows still at <None>.
- **Tagging options sit below the table**, across its full width in two
  halves, each option with a line saying what it does.
- **Clicking into X, Y or the elbow distance selects the number**, ready to
  type over.
- **Icons on every button**, drawn as line icons in one 16-unit box and
  stroked in the button's own text colour, so hover, disabled and both
  themes follow without a second palette.
- **Room Tags uses the same view table** - columns, group dropdowns, filters,
  collapse, Current view only, Show All Views and the selection-before-open
  narrowing - with the Views / Sheets switch moved into the left-hand card.
  Sheets selected in Revit come in ticked on the sheets list.
- The window opens at 1560 x 880, and a narrower size saved by 1.0 is
  widened to fit the three columns.
- Bench: **35 rules and 317 logic checks**. New rules: every button carries
  an icon; an iconized button's label never goes through Content; every
  icon is a valid path; the position boxes select their text on focus. New
  checks cover the column filters, the grouping and run order, the
  preselection, and the tag-to-highlight rules.

## 1.0.7

- **Room Tags can pick sheets instead of views.** A "List by Views / Sheets"
  switch beside Current view only. Ticking a sheet tags the rooms in every
  plan view placed on it; a view on two ticked sheets is tagged once, and a
  ticked sheet carrying nothing taggable is named rather than passed over.
  Sheets with no plan view on them are not listed at all, and the hint says
  how many that was. Each list keeps its own ticks, so switching across and
  back loses nothing, and which list you were on is remembered.
- **The highlight and the tick are now two different things**, in both view
  lists. This replaces 1.0.5's click-to-tick:
  - **click** highlights a row in blue, **Shift+click** highlights the run,
    **Ctrl+click** adds one, **Ctrl+Shift+click** adds a run;
  - **ticking the box of a highlighted row applies that tick to every
    highlighted row** - so twenty sheets is three actions: click the first,
    Shift+click the last, tick one of them;
  - ticking a row **outside** the highlight changes only that row, so a
    stray tick can never sweep a highlight that had been forgotten about;
  - a run does not move the anchor, so the same Shift+click can be repeated
    to widen or narrow one run.
- The status line after a sheets run says how many sheets came to how many
  plan views.
- Bench: **269 logic checks**, with `pick_rows`, `apply_tick` and
  `views_from_sheets` each against a table of cases, and six new deliberate
  breakages.

## 1.0.6

- **Ticking a linked model now reads it in by itself.** Refresh is still
  there for a re-read after the link reloads, but it is no longer something
  you have to remember.
- **The read waits for the ticking to stop** - 400ms of quiet - so ticking
  three models in a row, or pressing All, is one read of three rather than
  three reads of a growing set.
- **A tick during a tag run is deferred, not dropped.** The run owns the
  document, so the read happens when it finishes and the orange dot stays up
  until it does. Pressing Refresh by hand cancels any read already scheduled
  rather than queueing a second one.
- The line under the heading says so, and the orange dot now means "reading
  these in" rather than "press Refresh".

## 1.0.5

- **Range selection in both view lists.** Ticking twenty plan views one box
  at a time was the slow part of a room run.
  - **the whole row is the target**, not the 15px tick box;
  - **Shift+click** ticks the run from the last view clicked;
  - **Ctrl+Shift+click** unticks a run;
  - ticked rows carry the selection highlight as well as the tick, so a run
    reads as one block;
  - a line under the search box says so, rather than leaving it to be found.
- **A run adds to the selection, it never replaces it.** A Shift+click aimed
  slightly wrong costs a correction rather than every tick already made, and
  ticks on views the search is currently hiding are left alone.
- With no usable anchor - the first click of a session, or one whose anchor
  the search has since hidden - Shift falls back to a plain toggle rather
  than doing nothing.
- The rule itself is `pick_views` in `tagall_core`, with no WPF in it, and is
  bench-tested against a table of cases: **251 logic checks** now.

## 1.0.4

- **The linked models panel is no longer easy to miss.** It was a single
  collapsed line that read "Linked models (0 of 0)" and looked like a label
  rather than a control. Now:
  - **open by default** whenever the model has links, collapsed only when it
    has none;
  - a **violet spine** down the left of the card and a violet heading, tying
    it to the violet the linked families are listed in;
  - a **count badge** reading "2 of 3 ticked", or "3 available" before
    anything is ticked;
  - **All** and **None** buttons;
  - an **orange dot** beside Refresh the moment the ticks differ from what
    the tree was actually read with, so "I ticked a model and nothing
    happened" is visible rather than guessed at;
  - a line under the heading saying what Refresh is for and that linked
    families come out violet.
- The status line after a read now says how many of the models were links.

## 1.0.3

- **Fixed: the elbow was still not quite level.** Two things left, both about
  measuring the wrong thing:
  1. **The elbow was levelled with `TagHeadPosition`**, which is the tag
     family's *origin* - wherever that family happens to put it. A family
     whose origin sits at the bottom left of its text puts the elbow out by
     half the tag's height. The elbow is now levelled with the tag's own
     **horizontal centre line**, taken from its measured box.
  2. **A tag's bounding box in a view covers its leader as well as its
     text**, so with the leader on, the "outer edge" being measured was the
     far end of the leader, out by the element. The box is now read with the
     leaders **switched off** inside a `SubTransaction` that is then rolled
     back, which puts every leader back exactly as it was.
- **The anchor is the middle of the tag's outer edge on the side facing the
  element** - the family's horizontal centre line - and the elbow is that
  anchor moved straight back along the view's right direction and nothing
  else. Horizontal by construction, in sections as well as plans, whatever
  the family's origin is doing.
- Measuring costs **two regenerates per chunk of forty**, not two per tag,
  and is skipped entirely when the run is not placing elbows.
- Where a tag's size cannot be measured, the elbow falls back to the family
  origin and the run **says so** rather than quietly drifting.
- Bench: **31 rules and 234 logic checks**. New rule: the tag box is measured
  with the leader off - it fails if the leaders are not switched off, if the
  `SubTransaction` is not rolled back, if the box is read before a
  regenerate, or if the steps are in the wrong order.

## 1.0.2

- **Fixed: leader elbows were not horizontal.** What showed on screen was
  Revit's own automatic elbow, not the tool's, because three things were
  wrong at once and each would have been enough on its own:
  1. the elbow was set **straight after `IndependentTag.Create`**, before the
     tag had any computed geometry - so the head and box it was measured
     against were not real yet;
  2. `TagHeadPosition` was assigned **after** the elbow, which moves the head
     and leaves the elbow where it was - that is the long diagonal;
  3. the set-back was measured from the tag's **centre**, so on any tag wider
     than twice the elbow distance it landed inside the text.
  Now: create and position the head, `doc.Regenerate()` **once per chunk of
  forty**, then set each elbow from the head Revit actually reports, set back
  from the tag's **measured outer edge** on the side facing the element. The
  elbow carries the head's position in every direction except the view's
  right, so the elbow-to-tag segment is horizontal by construction - in
  sections as well as plans.
- **The elbow is read back and measured.** A void API call is not evidence:
  if Revit moves the elbow off level it is reported with how far off it is.
- **X at 0 says so.** With no sideways offset there is no side for an elbow
  to go, and an elbow would only kink a leader that is already straight; the
  run now says that rather than quietly doing nothing.
- **New bench rule: the elbow is only set after a regenerate** - it fails if
  anything but `apply_leader_elbow` sets an elbow, if the head and elbow are
  set in one pass, or if the elbows are set before the regenerate. 30 rules
  now, and 222 logic checks including the elbow geometry in plan and section.

## 1.0.1

- **Fixed: the window would not open at all.** `VerticalAlignment="Baseline"`
  in all three layouts - WPF has Top, Center, Bottom and Stretch and no
  Baseline, so `XamlReader.Load` threw and nothing in the tool ran. The two
  header lines are now bottom-aligned with a 1px lift on the smaller one,
  which is what Baseline was reaching for.
- **New bench rule: every enum attribute value is a real member.** A bad enum
  value is valid XML, so the XAML rule passed it straight through; it only
  fails inside `XamlReader.Load`. The rule covers VerticalAlignment,
  HorizontalAlignment, Orientation, Visibility, Stretch, ResizeMode, Cursor,
  FontWeight, scrollbar visibility and a dozen more, on plain attributes and
  on `<Setter Property= Value= />` alike. 29 rules now.

## 1.0.0

First release.

- **Family Tags tab.** Category > family > type tree with a keyword search,
  expand and collapse, and tri-level ticking. Ticked families go into a table
  on the right, each row carrying a dropdown of the tag families that suit its
  category - the category's own tags first, multi-category tags after.
- **Linked models.** Every loaded link is listed; tick the ones to read and
  press Refresh. Types from a link are listed in violet throughout, and their
  tags are placed in the host against a link reference.
- **Scope.** Current view or all project, re-read on the switch.
- **Add from Revit selection** takes the types of whatever is selected.
- **Tagging options.** Tag with leader; tag position from host offset X by Y in
  model millimetres; leader elbow with its own distance; remove previous tags
  and replace; tag all not tagged.
- **Views to tag.** Current view only, or a searchable ticked list.
- **Room Tags tab.** Model to read rooms from, room tag family and type, a
  searchable list of plan views, remove unassigned tags (the ones showing ?),
  and only tag rooms with no tag in the view.
- **Tag All** at the bottom, with a progress bar across the top of the window.
- Dark and light, following Revit's canvas theme by default; the header chip
  cycles Auto, Dark, Light and the choice is remembered.
- Three slow clicks on the RevoBIM logo.
- Bench: `import_check.py` (28 rules) and `bench_logic.py` (204 checks), both
  with a `--selftest` that breaks every rule and every rule-bearing function on
  purpose and confirms the bench notices.
