# Project Browser Pro - changelog

## 1.7.3 - 2026-11-04

- **Fixed: clicking in the search box put the cursor in the middle.**
  The scroller inside every text box had no template of its own, so in a
  docked pane Revit's own themed scroller style could take it over and
  centre the text - the cursor in an empty box sat in the middle. It now
  has its own template (`TextHostScroller`), so the text and cursor
  start at the left in the search box, Browser Organisation's parameter
  search and the inline rename box.

## 1.7.2 - 2026-10-23

- **Orange frame round the search box**, in the palette's orange (a
  deeper orange on the light theme). It stays orange while you type -
  the box's own edge, which turned blue on focus, is off. Browser
  Organisation's parameter search has the same frame.

## 1.7.1 - 2026-10-23

- **Fixed: docked panes showing only black.** pyRevit resets its start up
  sys.path once startup.py has run, and a pane builds its browser later,
  the first time it is shown - by then it could not find its own modules
  ("No module named pbp_browser" in the log), so the pane stayed empty.
  The tool now puts its own folder back on sys.path before the pane is
  built, on the first Idling event, before every event handler and
  before every Revit job.
- A pane that still cannot build now says why, with the error's last
  line and where the log is, instead of staying black. It tries again
  each time it is shown.

## 1.7.0 - 2026-10-20

- **Favourites: a Browser Organisation for each type.** Views, Legends,
  Sheets, Schedules, Panel Schedules and Families favourites can each be
  grouped their own way - Revit's organisation, your own parameters
  (any the type has), or none - apart from that type's own tab. Grouped
  favourites get headings coloured the same way as the tabs (levels,
  your own group colours, right click a heading to set one), saved with
  the project. Open it from the organisation button (on All it asks
  which type), by right clicking the Favourites tab, or by right
  clicking a favourite. Favourites start ungrouped, as before; whole
  folders made favourites still show as they are on their tab.
- **Folders start closed, and remember what you open.** Every tab opens
  as Collapse all leaves it (the type headings on All and Favourites
  stay open). Whatever you open or close - one folder, Expand all,
  Collapse all, a sheet set, a sub tab, a pinned copy - is remembered
  per tab and per project, and comes back next time and in every pane.
  A folder new to the model starts closed. (Setting `start_open` = 1
  brings back folders that start open.)
- **Families: your own heading colours.** Right click a Families group
  heading (Electrical, Pipe Fittings, a family...) and pick its colour,
  or use the organisation button / right click the Families tab for
  *Heading colours...*: the Browser Organisation window with every
  group listed and Auto colour, the grouping itself fixed. **Choose which
  levels are coloured** there too - Main group (1), Category (2),
  Family (3); main group and category by default. Saved with the
  project; the three colour modes apply as on the other tabs.

## 1.6.2 - 2026-10-20

- **Favourites: the header tabs, under the search box.** The same grey
  strip as the Legends tab, holding the header's own icons in their
  colours - All, Views, Legends, Sheets, Schedules, Panel Schedules,
  Families - each with how many favourites it holds (matches, while
  searching). All shows every type under its heading as before; a type
  shows just its favourites. The choice is remembered.
- **Search box: text starts at the left**, just past the magnifier. The
  alignment is now set outright on every text box (it is inherited, so
  a host above could move it), and the hint and the typed text line up.

## 1.6.1 - 2026-10-20

- **Legends and Drafting Views: sub tabs.** On the Legends tab (and its
  own pane) a grey strip under the search box switches between
  **Legends** and **Drafting Views**, each with its count, instead of
  the two masters stacked one above the other. The list shows one at a
  time, its headings starting at the left; the choice is remembered.
- While searching, each sub tab counts its matches, and an empty list
  says when the matches are on the other one.
- Selecting a drafting view in Revit while Legends is showing switches
  to Drafting Views to find it.
- The All tab keeps Legends and Drafting Views as two bold headings.
  Pins, favourite groups and heading colours are unchanged.

## 1.6.0 - 2026-10-20

Lighter on every change: closing views and changing view properties no
longer stall Revit while the browser catches up.

- **A change reads only what it touched.** Before, any change to a view
  re-read the whole model - every view, sheet, schedule and all ~2,400
  family types - in Revit's own thread (0.7-1.4 s on a typical model).
  Now Revit's change event notes what changed, by class, and the read
  that follows takes only that:
  - a view, sheet, schedule or family type modified (scale, detail level,
    crop, a parameter, a rename): that element alone, in milliseconds.
    If its row would draw the same, nothing is redrawn at all;
  - something added or deleted: its own tab, read again whole (a new
    sheet reads the sheets, not the families);
  - a viewport placed or removed: only what is placed on which sheet;
  - a view template renamed, a sheet renumbered: the views or placements
    those reach;
  - another model, a reload or sync, Revit's own browser organisation
    changed, or a change too big to look at: everything, as before.
- **Opening, closing or switching views moves only the dots.** Before,
  every one redrew every row of every pane. Now only the rows whose
  open / active dot changed are touched.
- **Redraws set only the cells that changed**, so a rename redraws a
  row, not the list (and the list no longer jumps).
- **Hidden panes wait.** A pane behind another or a closed pin keeps the
  news and draws once, when shown.
- **A tab's change leaves other tabs alone**: a family edit no longer
  redraws a pane showing the Sheets tab.
- Changing a tab's Browser Organisation reads that tab again, not the
  model.
- A view closed while a read was running is no longer missed.
- The debug report and log show what each read cost, section by section,
  and any redraw slower than 150 ms.

## 1.5.1 - 2026-10-20

- A view, legend or drafting view placed on a sheet has the inside of its
  frame icon filled blue (deeper blue on dark, light blue on light), the
  symbol on top - on every tab, and under a sheet opened to its views.

## 1.5.0 - 2026-10-20

- **Three heading colour modes**, cycled by the colour button (its dots
  show which): **Colour** (each trade's gradient, and the colours you
  give), **Greyscale** (grey bars), **Custom** (grey, except headings you
  give a colour - right click a heading, or Browser Organisation). 1.4's
  colour on / off reads as Colour / Greyscale.
- **Settings window** (the gear in the tool row): the colour mode; the
  highlight fill and text colour for each theme, and bold or not; your
  own colours (Add colour..., right click to remove). Every browser takes
  the change up.
- **Highlighted rows on the dark theme: white, bold text** by default.

## 1.4.0 - 2026-10-20

- **Auto follows Revit's UI theme** (ribbon, toolbars, palettes), not the
  canvas: a dark Revit with a light canvas gives a dark browser. The
  canvas is only read where the UI theme cannot be.
- **Light theme is Revit's light**: neutral, very light grey bars and frame
  (#F0F0F0 bars, #F5F5F5 body, #D4D4D4 edges), white list, no blue tint.
- **Colours off: grey bars.** The headings that were coloured keep their
  bars, in grey - a really faint grey on the light theme.
- **Browser Organisation colours**:
  - nine greys, black to near white, join the choices
  - Add colour... opens Windows' colour picker; the colour is kept with
    the choices for every tab and project (right click one of yours to
    remove it)
  - every value of every grouping level is listed, with Level chips to
    show one level - picking a level in the folder list picks it too -
    and any value can have its own colour, even on a level that is not
    coloured. Colours are stored per level and value (1.3's per-name
    colours still apply).
- **Right click a coloured heading** to change its colour right there:
  the same swatches, More colours... (picker), Automatic colour. Saved
  with the tab's organisation; every pane redraws.
- **Highlight**: right click anything > Highlight. Keep adding; they stay
  highlighted (marker yellow) until right click > Turn off highlight.
  Remove highlight takes one off. For this session only.

## 1.3.3 - 2026-10-20

- The header's fold arrow hides the footer too (status line, Debug, Copy
  report, Log, zoom) and brings it back with the header, in every browser
  - docked panels and floating windows. Remembered like the header.

## 1.3.2 - 2026-10-20

- **Print and Express float under the search box**, in a small shadowed
  bar at the top right of the list, and only while sheets are selected -
  one by one, or under a selected sheet heading - on any tab. It shows how
  many sheets, then Open folder (after an express print), Express and
  Print. The tool row no longer carries them.

## 1.3.1 - 2026-10-20

- **Fixed: dragging froze the browser and placed nothing.** 1.3.0 held
  the mouse itself during a drag and never heard the button come up once
  it left the window, so the browser stayed mid-drag. Dragging is now
  Windows' own drag and drop, which always ends: views dropped on a sheet
  (in any browser window) or on the sheet open in Revit are placed,
  centred; a heading dropped outside opens its pinned copy; Esc cancels.
  Each drag writes a start and end line to the debug log.
- **Place on the open sheet (centred)** in the right-click menu of views,
  legends and schedules - no drag needed.
- **Dock / Undock button** in the title line. In a floating window it
  docks the browser into Revit and closes the window; in a docked panel it
  hides the panel and opens a floating window the same size, beside it.
- **Docking on every machine**: Revit only takes a dockable panel from the
  block in the extension's startup.py. Where that block was never added
  (why one machine docked and another did not), Dock says so and offers
  to add it: startup.py is backed up, the block appended, nothing in it
  changed, never added twice. Restart Revit, then Dock. The block now
  ships inside the tool as startup_fragment.txt.

## 1.3.0 - 2026-10-20

- **Sheets open to their views**, as in Revit: a sheet with views,
  legends or schedules on it has a chevron and opens to list them (shut to
  start). Right click a heading > Show views on sheets / Hide views on
  sheets does every sheet in it.
- **Open sheet**: right click a view, legend or schedule placed on a sheet
  > Open sheet E-101 - ... (one item per sheet it is on).
- **Heading menu**: Collapse all inside / Expand all inside (the heading
  stays open); Add group to favourites / Remove group from favourites;
  on a sheet heading, Print all N sheets / Express print all N sheets.
- **Favourite groups**: a whole folder made a favourite shows under its
  type on Favourites with everything in it, in the same colours as on its
  own tab. Saved per project.
- **Print a sheet heading**: selecting a sheet heading lights Print and
  Express for every sheet under it.
- **Express needs the Pro Sheets hook**: Pro Sheets 1.47.0 has no express
  hook (1.38.0's was lost in a rebuild), so Express only opened its first
  page. The browser now checks for `ps_express.py` first and says what is
  missing instead of opening Pro Sheets. The prompt to give the Pro Sheets
  chat ships beside this version.
- **Browser Organisation**:
  - tick which folder levels are coloured main headings (default 1 and 2)
  - switching from Revit's organisation to parameters fills the levels and
    sort with Revit's own grouping parameters, ready to change
  - give any coloured group a colour of its own (list of the tab's groups,
    22 swatches, Automatic to go back)
- **Look**: the title and tool rows and the tab row are the same grey as
  the browser, told apart by a soft shadow under each row. The search box
  is darker with a magnifier, like Revit's.
- **View icons are plain**: every view, legend and drafting view is a
  plain frame in the text colour with a small symbol in the middle - the
  discipline its view template names, else its view type.
- **Legends and Drafting Views**: drafting views leave the Views tab and
  join the legends, under two fixed, collapsible master groups (Legends,
  Drafting Views) in large bold text.
- **Find Revit's selection here**: a view or sheet picked in Revit's own
  browser (Find in Project Browser included), a viewport or schedule on a
  sheet, is found in this browser - its folders open and it is selected.
  Family types are followed on the Families tab. Untick "Find Revit's
  selection here" in the right-click menu to stop it.
- **Drag views onto a sheet**: drag one or more views, legends or
  schedules onto a sheet in this browser, or onto the sheet open in
  Revit's view, and they are placed on it, centred on the title block. A
  view already on a sheet is named and left.
- **Open as its own window** takes the browser's size and opens beside it
  (left when there is room, else right). For a dockable pane this works
  when Revit floats it in a window; the debug log says which.

## 1.2.0 - 2026-10-20

- **Families tab grouped**: main group > category > family > type. The
  groups, in this order: Tags (every tag of every category), Annotations,
  Architecture, Structure, Electrical, Mechanical & Plumbing, Other.
  Categories shared by architecture and MEP (plumbing fixtures, lighting
  fixtures, mechanical equipment...) sit in their MEP group. Matched on the
  BuiltInCategory name, so it works in any Revit language. Each group has
  an icon (tag, dimension, house, I-beam, bolt, duct and pipe, dots).
- **Main headings stand out**: the first two levels are bigger and bold
  (13 / 12 pt), with taller rows, whether the colour button is on or off.
- **Colour gradients**: with the colour button on, main headings are solid
  rounded pills, shaded by trade - electrical (power, containment,
  lighting, fire alarm / security, data) greens, mechanical (ductwork,
  heating, pipework) blues, plumbing (drainage, water services, public
  health) browns, everything else violets. Each run of headings goes dark
  to light in browser order; main headings sit at the dark end. Text, icon
  and chevron turn black or white for contrast. A selected pill shows a
  blue edge. New discipline words: Lighting, Data / Comms, Mechanical,
  Plumbing / Public Health.
- **Legends tab** (and pane), between Views and Sheets. Legends no longer
  sit in the Views tab. Right click > Browser Organisation to group and
  sort them by parameters (Revit itself shows legends flat).
- **Drag a heading out** of the browser to open a copy of it in its own
  dockable pane. Eight pane slots ("RevoBIM Pinned 1" to "8") are
  registered at start up and reused once closed; with none free (or before
  a restart) the copy opens as a floating window. The copy keeps the
  browser's colours and follows the model. Dragging a type heading (All /
  Favourites) pops out that whole tab.
- **Rename in place**: click a selected item again (a slow double click)
  or press F2 and type over its name in the row. Enter or clicking away
  keeps it, Esc drops it. On a sheet, change the number, the name or both
  ("M-101 - Ground Floor"). Panel group headings rename the same way.
- **Zoom extents** on every view, legend and sheet opened from the browser.
- **Select in Revit as you click**: selecting items in the browser selects
  them in Revit once the selection settles. On by default; untick "Select
  in Revit as I click" in the right-click menu to stop it.
- Restart Revit after updating: the Legends and Pinned panes register at
  start up.

## 1.1.0 - 2026-10-19

- **Favourites tab** (star, after All), with a dockable pane of its own.
  Right click anything on any tab - views, sheets, schedules, panel
  schedules, family types - and Add to favourites. They are grouped by
  type (Views, Sheets, Schedules, Panel Schedules, Families), listed flat,
  sheets by number. Select and right click to Remove from favourites, or
  to Set colour (a row of ten swatches in the menu) / Clear colour: a
  coloured favourite sits on a pill of that colour. Collapse all / Expand
  all fold the type headings. Print and Express work here too.
- Favourites, their colours, panel groups and the sheet set are saved per
  project, by UniqueId, in
  `%APPDATA%\RevoBIM\project_browser_pro_marks\<project>.txt`, and shared
  by every pane at once.
- **Open selected**: select several views, sheets, schedules or panel
  schedules on any tab, right click, Open selected (N).
- **Sheet set filter** on the Sheets tab: the chip at the right of the
  organisation line shows All sheets or one set from Print > Sheet sets.
  The All tab always shows every sheet. A set deleted in Revit falls back
  to all sheets.
- **Panel schedule groups**: select panel schedules, right click, New
  group... or Move to group: X / Remove from group. Right click a group
  heading to Rename group... or Ungroup. Panels in no group sit under
  Ungrouped, last. With no groups the tab looks as before.
- **Discipline icons**: View Group and View Purpose headings on Views and
  Sheets get an icon and colour when their name says Pipework, Ductwork,
  Electrical Containment, Electrical Power, Heating, Drainage, Water
  Services, Fire Protection or Security / Fire Alarm (a second level
  heading that names none takes its main heading's). Each view's icon
  comes from its view template's name the same way. Matching is on whole
  words: VENT finds VENTILATION but not PREVENT, LV not SOLVENT.
- **Heading pills**: with the colour button on, only the main headings
  (the first two levels - View Group and View Purpose; Category on
  Families) are coloured, each on a rounded pill with a soft shadow, in
  its discipline's colour or a steady colour of its own. Views and deeper
  folders have no fill; the old colour bar beside each view is gone.
- Restart Revit after updating: the Favourites pane registers at start up,
  and the docked panes run the code loaded then.

## 1.0.9 - 2026-10-09

- Every tab opens fully expanded. The browser now remembers the folders
  you CLOSED rather than the ones you opened, so a folder that appears
  later - after a refresh, a new browser organisation or another project -
  is open too. Collapse all / Expand all and clicking a folder work as
  before; Collapse all on the All tab keeps the Views / Sheets / ...
  headings open.
- Express print now works end to end with Pro Sheets Exporter 1.38.0,
  which adds the headless hook (ps_express.py). When some files are
  written and some are not, the folder still opens and Pro Sheets' one
  line on what did not write ("1 did not write - M-03 [PDF]: offline") is
  shown in the status line.

## 1.0.8 - 2026-10-09

- Dark theme is now Revit's own dark theme, measured from Revit 2026's
  Properties palette: navy #222933 title and section bands, slate #3B4453
  body and list, #2E3440 bottom bar and menus, #444E5E separators and
  hover, #515C6B pane edges, Revit's #3A7392 selection blue, #9AA0A6
  read-only text. RevoBIM's blue / orange / green and the tab type colours
  stay on top. New palette key BottomBrush for the footer.
- The button now notices when the docked panels are still running an
  older version than the one installed (they are built from the code
  loaded when Revit started, so unzipping an update or reloading pyRevit
  does not change them) and says to restart Revit.

## 1.0.7 - 2026-10-09

- Dependent views are nested under their parent view: straight after it,
  12px further right, in name order - whatever the folder sort says, under
  Revit's organisation, a custom one or none. A dependent whose parent is in
  a different folder stays where it is.
- Parent views are bold. They get no fill or colour of their own.
- The active view is marked by an orange dot (it used to be bold); other
  open views keep the green dot. The dot's tooltip says which.
- Search: a dependent that matches brings its parent along for context.
  Select everything in a folder includes the dependents.

## 1.0.6 - 2026-10-09

- Express print shows nothing but a small progress strip at the bottom
  centre of Revit (sheet count, percentage, current sheet, a bar). When Pro
  Sheets says done, the strip closes and the export folder opens by itself.
  A failure, Pro Sheets never starting, or five minutes with no progress
  turns the strip red with the reason and a close button.
- Hand-off v2: the request asks Pro Sheets to run headless (no window, no
  pages, no report) and to leave the folder to the browser; Pro Sheets
  reports per-file progress with pbp_handoff.progress(). Polled four times
  a second while running. The percentage never shows 100 until Pro Sheets
  has confirmed the last file.
- Express button: printer icon left of the word, orange outline with
  orange text, faint orange fill on hover - set apart from the solid green
  Print button.
- Needs the Pro Sheets side wired in (see the tool doc) for the headless
  export itself; until then express says so after 25 seconds.

## 1.0.5 - 2026-10-09

- Compact top: the title is one line (RevoBIM, then the tool name, which
  trims with an ellipsis rather than running under the theme chip), a
  smaller logo, theme chip and version, and tighter tool buttons.
- New chevron at the right of the tab row folds the title line and the
  tool buttons away and brings them back; the tabs and the search bar
  stay. Remembered between sessions. A floating window keeps its title
  line folded or not, since that line holds its drag handle and close
  button.
- Tabs are icons only - no words - at 22px, redrawn on a finer grid to read
  without a label: layers (All), an eye (Views), a drawing sheet with a
  title block (Sheets), a table (Schedules), a board with a lightning bolt
  (Panel schedules) and a component cube (Families). Each type has its own
  colour: pink, blue, orange, green, violet, teal. Names and counts are in
  the tooltips.

## 1.0.4 - 2026-10-09

- Tabs moved into one row of icon tabs along the top of the browser:
  All, Views, Sheets, Schedules, Panel Sch, Families - a 20px icon over a
  short label, equal widths, blue underline on the chosen tab. Item counts
  moved to each tab's tooltip and to the line under the toolbar.
- The single-tab panes (Views, Sheets, ...) now open floating instead of
  tabbed behind the main pane. Stacked panes are what put Revit's own tab
  strip along the bottom of the dock - Revit draws that strip itself and the
  API offers no way to move it or give it icons.
- New palette keys PanelBrush (violet) and FamilyBrush (teal) for the panel
  schedule and family icons; All tab draws a layers glyph.
- Order on the All tab follows the tabs: views, sheets, schedules, panel
  schedules, families.
- Text in code is ASCII only (escape codes for the arrows and dots).

## 1.0.3 - 2026-10-09

- Fixed: Browser Organisation's two parameter lists turned white when
  "Revit's browser organisation" was chosen. A ListBox on the system
  template paints a white background when disabled, whatever its
  Background says; both list styles (PlainList, and a new BrowserList for
  the browser itself) now carry their own template and only fade.
- The Sort items by box fades with the rest of the panel instead of
  staying bright.
- New bench rule templated_controls: every list, button, tick box, scroll
  bar, menu and tooltip - in the layouts, in Theme.xaml and in styles set
  from code - must reach a style that replaces the Windows template.

## 1.0.2 - 2026-10-09

- Startup block also offers `__uicontrolledapplication__` (the spelling the
  Pro Sheets block uses) alongside `__uiControlledApplication__` and
  `__revit__`, so whichever name this pyRevit build provides is found.
  Merged into the extension's startup.py after the Family Viewer and Pro
  Sheets blocks and dry-run: 6 of 6 panes registered, nothing registered
  twice on a second load, both existing blocks unaffected.

## 1.0.1 - 2026-10-09

- Fixed: the browser would not open ("Cannot set unknown member
  'System.Windows.Controls.Border.FontFamily'"). The browser's root is a
  Border, which has no font of its own; the font is now set with the
  inherited TextElement.FontFamily / TextElement.FontSize.
- New bench rule xaml_members_known: every attribute in every layout, every
  attached-property owner and every Setter / Trigger property is checked
  against WPF's real members for that element, so this cannot ship again.
- Revit 2021-2023: Auto theme shows light where Revit has no dark theme
  (it fell back to dark); BrowserOrganization moved to its own guarded
  import so a release without it cannot stop the module loading; the
  version rule now requires every newer-API name to be imported alone,
  inside a try.
- The easter egg is armed with the floating window as its owner.

## 1.0.0 - 2026-10-09

First release.

- Dockable browser (tabbed behind Revit's Project Browser) with tabs All,
  Views, Sheets, Panel Schedules, Schedules and Families, each with a count.
- Every tab except All can be opened as its own dockable window (right
  click the tab, or the pop-out button), so each can be docked separately.
- Browser Organisation per tab (Views, Sheets, Panel Schedules, Schedules)
  from the tab's right click menu or the toolbar: Revit's own organisation,
  up to six parameter folder levels, or none, with a sort parameter and
  direction. Saved against the project.
- Search box: every word must match; folders holding a match open.
- Collapse all / Expand all, and a Colour button that colours each sub group.
- Ctrl + mouse wheel zooms everything inside (60% to 200%), Ctrl + 0 resets.
- Auto / Dark / Light chip top right, Auto following Revit's canvas theme.
- Sheets tab: Print goes green with sheets selected and opens Pro Sheets with
  them ready to print; Express runs Pro Sheets straight to export on its last
  settings (needs the Pro Sheets express hook) and shows Open folder when done.
- Open views carry a green dot, the active view is bold. Double click opens
  (views A-Z, then sheets, schedules, panel schedules); on a family type it
  places an instance. Right click: open, select in Revit, rename, copy name,
  place instance, select all instances.
- Debug tick (on by default for now), Copy report and Log in the footer.
- Falls back to a floating window when the startup block is not pasted.
- Revit 2024 to 2027 from one copy.
