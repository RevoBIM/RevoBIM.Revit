# Style Manager - Changelog

Formerly Filter Manager. Version is stamped in `script.py` (`VERSION`), shown in
the window header and footer, and written into every Excel export and log file.

## [4.7.0] - 2026-11-04
### Added
- **Merge Groups.** Click the duplicate swatches along the bottom to pick groups -
  a picked swatch gets a tick and a white border, the others dim, and the table
  selects every row in the picked groups. Pick All and Clear sit beside them. The
  Merge Groups button lights orange with the count once anything is picked.
- Each picked group is merged into **the style used by the most elements**; a tie
  goes to the name that sorts first, so the choice never depends on read order.
  Hovering a swatch shows which style it will keep, and the red confirmation lists
  every group with its keeper and what merges into it, with use counts.
- Each group is merged on its own, so a group Revit refuses is reported and left
  as it was while the rest carry on. The tab is read back once at the end and
  returns showing the duplicates that remain.
- On tabs whose usage comes from Analyze (Object Styles), every style in the
  picked groups must be analysed first, since "most used" is otherwise unknown.
  Object styles and any merge of 50 or more styles ask before starting with the
  suggest-syncing warning.
- Bench rule 18 (each group in its own try) and logic checks for the keeper rule,
  each proved by a deliberate breakage.

## [4.6.0] - 2026-11-04
### Added
- **Duplicate Rules menu** beside Find Duplicates on every tab that looks for
  duplicates. Tick the settings that must match for two styles to count as
  duplicates; the table regroups instantly from what is already read (no model
  read), and the choice is remembered per tab. Tick all and Reset to defaults sit
  at the foot of the menu, and at least one rule always stays ticked. Rules per
  tab: filters (categories, logic, rules), line styles, text styles (13 settings),
  dimension styles (14), object styles (always within one parent category),
  materials, line patterns, filled regions, fill patterns, appearance assets,
  viewports and arrowheads.
- **Text Styles shows every type property**: colour, line weight, background
  (opaque / transparent), show border, leader / border offset, tab size and leader
  arrowhead join font, size, width factor, bold, italic and underline - all
  editable, all available as duplicate rules.
- **Excel import now ends with a prompt** giving the number of styles the
  workbook changed, the number of settings, a per-column breakdown, and any edits
  ignored as not writable. The changed rows are highlighted and shown on their
  own; nothing is written until APPLY CHANGES. The selection is cleared first so
  it cannot paint over the highlight.
- **bench_logic.py** runs the real duplicate, fill pattern, appearance asset and
  parameter analysis code from script.py under CPython against stub Revit
  objects. Both benches now have `--selftest`, which breaks the code on purpose
  and fails if a check misses it.

### Fixed
- **Fill patterns matched on target and orientation only**, so every drafting
  hatch with the same orientation was a "duplicate" of every other, and a merge
  would have replaced real patterns. The grid lines themselves - angle, spacing,
  shift, origin, dashes - are now compared, in any order.
- **Appearance assets matched on schema only**, so every Generic asset was a
  "duplicate" of every other. Every rendering property is now compared, texture
  maps included one level down; the asset's own name, description and keywords
  are left out.
- **Duplicates compared rounded display values.** Two text sizes the project
  rounds to the same figure matched. Readers now keep an exact form for comparing.
- **"Elements With A Value" could never read above 20** - counting stopped once
  20 examples were recorded. It now counts to 50 and reads "50+" beyond that.
- **Parameter analysis could count a different parameter with the same name.**
  Each parameter is now looked up by its own definition; the bench found and
  proved a second instance of this in the new code before it shipped.
- The merge warning about rows not sharing a duplicate group no longer appears on
  tabs that never look for duplicates (Fonts, View Templates, Scope Boxes, Global
  Parameters), which now hide the duplicate controls.

### Changed - efficiency
- **Rows are found through an index**, not by scanning. Select Unused, bulk
  rename, staging and selection each looked rows up one at a time, which made them
  quadratic: on a 2,600-row Parameters tab that was millions of comparisons.
- **Brushes are made once per colour and shared** instead of one per row on every
  refresh.
- **The status box is written a block at a time** - one cross-thread call and one
  repaint per report instead of one per line.
- **After Apply only the tabs that were written are read back**, not every tab
  that has been opened.
- **Parameter analysis stops a category once every parameter in it is known to be
  used**, and looks parameters up by definition rather than by walking each
  element's parameter list for a name.
- **Filter usage reads each view template once**, not once per view using it.
- **Element ids are read with `.Value` first.** The other order raised and caught
  an exception on every id on Revit 2026/2027.

## [4.5.4] - 2026-08-10
### Fixed
- **"Unused only" did nothing and reported "Cannot perform '=' operation on
  System.String and System.Int32".** The filter compared the usage column against
  the number 0, but on the two tabs where usage is worked out by Analyze that
  column holds text - an unanalysed row reads "?" and a built-in one reads "-".
  The clause is now built from the column's own declared type, quoted for a text
  column and unquoted for a numeric one. Checked against all eighteen tabs:
  Object Styles and Parameters quote it, the other sixteen do not.
- Ticking "Unused only" before anything has been analysed now says so, rather
  than showing an empty table with no explanation.

### Added
- **Bench rule 14: row filters must compare against a column of the matching
  type**, and a tab that counts usage through Analyze may not declare its usage
  column as an int. Verified by hard-coding the numeric comparison again and
  confirming the check rejected it.

## [4.5.3] - 2026-08-10
### Fixed
- **The Parameters tab listed nothing.** Its "Group Under" column was named
  `Group`, which is the name the table already uses for the duplicate group. The
  DataTable refused the second column, `refresh_table` threw, and the tab was left
  empty - the parameters had been read correctly all along. The column is now
  called `ParamGroup`; nothing changes on screen or in Excel.
- The reserved names the table keeps for itself are declared in one place, and a
  panel column that uses one is skipped and reported rather than taking the tab
  down.
- A tab that fails while reading now writes its traceback to the status box, not
  just a one-line summary.

### Added
- **Bench rule 13: no panel column may reuse a name the table reserves.**
  Verified by putting the clash back and confirming the check reported
  "ParameterPanel has a column named Group, which the table reserves". A scan of
  all eighteen panels found this was the only one.

## [4.5.2] - 2026-08-10
### Fixed
- **Every tab failed with "object has no attribute 'on_excel'".** The 4.5.1
  rewrite of `wire()` replaced everything between `def wire` and
  `def configure_panel`, and `build_excel_menu` and `on_excel` happened to sit
  between those two markers. They were deleted. The file still parsed and every
  bench rule still passed, because nothing was checking that the methods a class
  calls on itself actually exist.
  Both methods are restored, verified by diffing every class method against the
  last known-good build - two were missing, and nothing else.

### Added
- **Bench rule 12: every `self.something` a class uses must be defined on it or
  on a base.** This is the rule that would have caught the failure before it
  shipped. Verified by deleting `on_excel` on purpose and confirming the check
  reports exactly what Revit reported.

## [4.5.1] - 2026-08-10
### Fixed
- **"No tabs could be built" told nobody anything.** Every panel's failure was
  caught and its traceback stored, and then the window raised a bare summary that
  threw all of it away. The reasons are now included in the message, so a failure
  on another machine reports what actually went wrong.
- **A missing control could take a whole tab down.** Every handler in `wire()`
  now attaches through a tolerant hook, and each grid event and column is
  attached independently. A control the layout does not have costs that one
  feature and is named in the status box; it can no longer cost the tab.
- **Panels are built in named stages** - parsing the layout, finding the table,
  building the columns, wiring the controls - so the message says which stage
  failed rather than only that construction failed.
- **Column widths go through a helper** rather than constructing `DataGridLength`
  from a Python int, which is a documented way to miss the overload on some
  IronPython builds.
- **The colour column was still being built on tabs that had switched grouping
  off**, and the count of leading columns was left at one while two were added.
  Dropdown options were therefore being applied to the column next door. The
  4.5.0 edit that was meant to fix this silently matched nothing.

### Added
- Three more bench rules: the leading column count must match the columns
  actually built and none may be addressed by a hard-coded index; `wire()` must
  attach through the tolerant hook rather than directly; and no class may define
  the same method twice. Rule 9 was verified by removing a counter and confirming
  it reported "adds 2 leading column(s) but counts 1".

## [4.5.0] - 2026-08-10
### Fixed
- **The Parameters tab found nothing.** It was collecting `ParameterElement`,
  which only exists for shared parameters - a non-shared project parameter has no
  element of its own, so a model whose parameters are all project parameters came
  up empty. The list is now driven from `doc.ParameterBindings`, which is the
  authoritative record of what the project defines, with the collectors used
  afterwards only to pick up parameters that are defined but bound to nothing.
  Shared parameters that are bound appear once, not twice.

### Changed
- **The table now shows parameter properties**: name, whether it is shared or a
  project parameter, instance or type binding, discipline, type of parameter,
  the group it appears under, the categories it is bound to and how many, the
  shared GUID, and how many elements hold a value for it.
- **Duplicates are switched off on this tab.** Two parameters with the same data
  type are not duplicates - they hold different values on different elements - so
  Find Duplicates, the Duplicates only tick, the colour column and the legend are
  all gone here rather than offering something meaningless.
- After Analyze the status reads plainly as **Used** or **Unused**, and Select
  Unused picks out the analysed parameters nothing holds a value for.

## [4.4.0] - 2026-08-10
### Fixed
- **Selecting several types and changing one dropdown now changes all of them,
  and the rows stay highlighted while you do it.** Every attempt at this so far
  worked around the symptom instead of the cause. The cause is that a plain click
  on a DataGrid row collapses a multi-row selection to that one row, and it does
  so before the cell ever starts editing - so by the time a value was chosen there
  was only one row left selected.
  The click is now intercepted: when it lands on an editable cell inside a
  selection of several rows, the cell is put into edit mode by hand, the selection
  is restored exactly as it was, and the event is marked handled so WPF never gets
  to collapse it. The rows stay lit while the list is open, and the value lands on
  all of them.
- A dropdown cell now **opens its list on the first click**. The click that starts
  the edit is swallowed to protect the selection, so the list is dropped down in
  code rather than making you click a second time.
- **The selection survives the edit.** Staging a change rebuilds the table, which
  used to clear the highlight; the rows are now put back, so a set of types can be
  worked through one setting at a time.

## [4.3.0] - 2026-08-10
### Fixed
- **Changing one tag type's leader arrowhead changed every type in the family.**
  4.2.0 remembered the last multi-row selection it had seen and fell back to it
  whenever a cell edit found only one row selected. Clicking a single row that had
  been part of an earlier selection therefore brought that whole stale set back
  and edited all of it.
  The selection is now captured in the grid's preview mouse-down - as the click
  lands, before WPF collapses the selection - so it is the selection that was
  actually on screen when you reached for the dropdown, never an older one. It is
  cleared once the edit commits, so the next single edit is single.

### Changed
- **The Set for selection bar is gone.** Everything is driven from the cells:
  select the types you want, open the dropdown on any one of them, and only those
  rows take the value. Editing a row on its own changes that row alone.

## [4.2.1] - 2026-08-10
### Fixed
- **Leader arrowheads could not be changed on most tag types.** Whether a cell was
  editable was decided from whether it had printed a value, so a type whose leader
  arrowhead was set to nothing read as blank and was refused - reported as "10
  could not take it". Editability is now decided from the parameter itself,
  recorded when the type is read: present and not read-only means editable,
  whatever the cell shows. The same fix applies to the Arrowheads tab, where a
  blank tick size or angle was being refused for the same reason.
- A leader arrowhead that is set to nothing now reads **(none)** rather than
  blank, and **(none)** is offered in the dropdown, so an arrowhead can be cleared
  as well as changed.
- The refusal message now names the real reason - that the family does not expose
  the setting as a writable type parameter - and is no longer repeated once per
  click on the same row.

## [4.2.0] - 2026-08-10
### Added
- **Set for selection bar**, on Tag Styles and Arrowheads. Pick the setting, pick
  or type the value, press Set, and every selected row takes it. This is the
  reliable way to change leader arrowheads across a whole category at once.
- **In-cell mass editing now survives the click.** Clicking into a cell to open
  its dropdown collapses a multi-row selection to that one row, so a mass edit
  only ever reached one row. The panel now remembers the last multi-row selection
  and applies the edit to all of it.
- **Tag Styles groups by tagged category, with a collapsible header per category**
  showing the count. Click a header to fold that category away, or use Collapse
  All / Expand All. The row colour comes from the tagged category and the swatch
  from the tag family, so both readings are visible at once.
- **Category filter** on Tag Styles - a dropdown beside the search box narrowing
  the table to one tagged category.
- Clicking a colour in the legend selects every tag type in that category.

### Changed
- **Duplicate isolation is switched off on Tag Styles.** Two tag types sharing a
  font are not duplicates worth merging, so Find Duplicates and the Duplicates
  only tick are hidden there and the colours group by category and family instead.
- **ComboBoxes are now themed.** WPF's stock ComboBox ignores `Background` and
  falls back to the system theme, so its toggle, popup and items all needed
  control templates - otherwise every dropdown, including the in-cell ones added
  in 4.1.0, rendered as a white box.

## [4.1.1] - 2026-08-10
### Fixed
- **The tool would not start: `NameError: global name 'TagStylePanel' is not
  defined`.** The class was lost when the Arrowheads panel was rewritten - the
  replacement spanned from `ArrowheadPanel` to `ParameterPanel`, and Tag Styles
  had been inserted between the two. The backend was all still there; only the
  panel class had gone.
- **`System.Uri` had crept back in**, loading the tab icons through
  `BitmapImage.UriSource`. That type moved assemblies in Revit 2025 and importing
  it throws at module load on 2025 and later, so this build would have failed to
  start on those versions too. Icons now load from a `MemoryStream`, which also
  releases the file handle rather than locking the PNGs while Revit is open.

### Changed
- The ribbon is now built from a single `NAV_GROUPS` table of panel **names**,
  looked up at run time. A panel class that goes missing is reported in the
  status box and skipped, rather than stopping the window from opening.

### Added
- **`bench_check.py` ships with the tool**, and runs under plain CPython from the
  button folder. Eight rules: every panel named in `NAV_GROUPS` has a class;
  every panel provides read / write / merge_impl; every column set carries Name,
  Status and ElemId; every icon a panel asks for exists; every `find()` resolves
  to an `x:Name`; every XAML block parses as XML; no f-strings, `print`, bare
  `.IntegerValue` or `System.Uri`; and every global a function reaches for is
  defined. Rule 1 was verified by deleting `TagStylePanel` on purpose and
  confirming the check named it, and rule 7 found the `System.Uri` regression
  above on its first run.

## [4.1.0] - 2026-08-10
### Added
- **Progress bar with a percentage**, under the ribbon. It appears whenever a job
  runs and reports what is happening as well as how far through it is: which
  family is being opened, which category is being scanned, which tab is being
  read or written. It hides itself when the job finishes.
- **The standing long-run warning.** Anything that opens families, walks every
  element of a category, or writes a large batch now asks first:
  *"This could take some time, suggest syncing before running this command."*
  with Continue and Cancel. It covers object style analyze and merge, parameter
  analysis, the tag style read, and any apply of 150 or more staged changes.
- **Tag Styles tab.** Every tag family type in the project with the category it
  tags, its family and type name, leader arrowhead, font, size, width factor,
  bold / italic / underline, colour and background, plus how many tags are placed
  with it.
- **Mass editing by selection.** Ctrl-select any number of rows, change one cell,
  and every selected row takes that value. Dropdown cells - leader arrowhead,
  arrow style, and the Yes/No settings - are real combo boxes whose options come
  from what the model actually offers. Names are deliberately excluded, since
  setting one name on several rows would only auto-number them.
- **Arrowheads are now editable**: arrow style, arrow size, tick size, filled,
  closed, tick angle and line weight, all with the same mass-edit behaviour.
- **Parameters now finds used and unused.** Analyze walks every element of every
  category a parameter is bound to and counts those actually holding a value.
  Select Unused then picks out the analysed parameters nothing holds a value for,
  and Delete removes them - refusing to run until they have been analysed, so the
  confirmation can tell you what would be lost.

### Notes
- A blank cell on the Tag Styles tab means that tag family never exposed the
  setting as a type parameter, so there is nothing to write to. Those cells are
  not editable and say so rather than failing at Apply.

## [4.0.0] - 2026-08-10
### Changed
- **The tab strip is now a ribbon**, laid out and grouped the way Ideate
  StyleManager's is: Object Styles / Line Styles / Line Patterns | Filled Regions /
  Fill Patterns | Materials / Material Appearance Assets | Filters / View Templates /
  Viewports / Scope Boxes | Text Styles / Fonts | Dimensions / Arrowheads |
  Parameters / Global Parameters. Icon on the left, label on the right, thin
  dividers between groups, and it wraps to a second row on a narrow window.
- **Tabs load when first opened.** Reading seventeen tabs' worth of collectors at
  startup would be unusable on a real model, so only the tab on screen is read;
  the rest read the first time you open them. Apply refreshes only the tabs that
  have been opened.

### Added
Eleven new tabs, first round:
- **Line Patterns** - segments, and how many categories and subcategories draw
  with each. Merge repoints those categories before deleting the spares.
- **Filled Regions** - foreground and background pattern and colour, masking,
  line weight and boundary line style, with a count of placed regions. Merge
  retypes the regions.
- **Fill Patterns** - target and orientation, counted across materials and filled
  region types. Merge repoints both before deleting.
- **Material Appearance Assets** - asset schema and the materials using each.
  Merge repoints the materials.
- **View Templates** - view type, how many parameters the template controls, and
  how many views it drives. Merge moves those views onto the kept template.
- **Viewports** - title and extension settings and the title family, with placed
  view counts. Merge retypes the viewports.
- **Scope Boxes** - counted across the views cropped to them and the datums
  scoped to them.
- **Fonts** - derived from the text and dimension styles that reference them,
  since a font is not a Revit element. Merge rewrites those styles; there is
  nothing to delete and the tab says so.
- **Arrowheads** - style, size, filled and tick angle, counted from every type
  parameter that names an arrowhead or tick mark.
- **Parameters** - project and shared parameters with binding, data type, group,
  bound categories and GUID. Merge is deliberately not offered: combining two
  parameters is a data migration, not a style change.
- **Global Parameters** - data type, value, formula, reporting flag and what each
  one drives.

### Notes
- Several new tabs expose **the name only** for editing in this first round, where
  the remaining properties are set through Revit dialogs with no API equivalent.
  Each tab's Excel info sheet says which.
- View templates and scope boxes are not compared for duplicates yet, so their
  duplicate columns stay blank.

## [3.5.0] - 2026-08-10
### Changed
- **Duplicate group colours are now stable.** Groups were numbered by position on
  every read, so merging group B away renamed C to B and handed it B's colour -
  every remaining swatch quietly changed meaning. A group's letter and colour are
  now tied to its rule signature and kept for as long as it is still a duplicate.
  When a group is fully resolved its letter and colour are released and reported,
  and only a genuinely new group reuses that slot.
- **Ticking "Duplicates only" now sorts the table by duplicate group**, then by
  name, so each group's members sit together under one colour instead of being
  scattered alphabetically. Find Duplicates does the same.
- **After a merge the tab returns showing duplicates only, sorted by group**, so
  what is left to deal with is in front of you.
- Clicking any column header takes over from the automatic grouping, so the sort
  is a starting point rather than something that fights the user. Clicking the
  Dup column puts it back.
- The duplicate legend is now ordered by group letter rather than by whichever
  group happened to be read first.

## [3.4.0] - 2026-08-10
### Fixed
- **The delete warning for object styles was wrong.** It said deleting a
  subcategory deletes the geometry on it. It does not: the elements revert to the
  parent category style, which is the same result as merging them into the parent.
  The only exception is a subcategory that arrived with an import, where the
  imported geometry goes with it. The confirmation now says so and reports how
  many elements will revert.

### Added
- **Nested families are now handled.** The merge descends into families nested
  inside the families it opens, up to three levels, repointing their geometry and
  reloading each nested family into its parent before the parent is reloaded into
  the project. Previously a subcategory used only inside a nested family was left
  behind.
- **Analyze**, a deliberate step on the Object Styles tab, matching the way
  Ideate StyleManager works. Counting what uses an object style means opening
  every family of the parent category, which is too slow to run on every refresh,
  so usage shows as "?" until analysed. Analyze runs on the selected rows only.
  Merge and delete both require it first, so the confirmation can state what will
  move. Results survive a refresh.
- **Built-in subcategories are now listed**, marked as such, with usage shown as
  "-" because Revit will not report it. They cannot be renamed or deleted but
  they can be merge targets.
- **The merge target can now be any style in the parent category, not just one of
  the selected rows.** The merge window carries a "Selection set only" tick;
  unticking it widens the list to every subcategory of that parent plus the parent
  category itself. Merging into the parent category is the supported way to fold a
  stray subcategory back into the standard - elements revert to the category style.
- Duplicate matching on object styles now includes the parent category, so
  identically-drawn subcategories under different categories no longer group
  together.

## [3.3.0] - 2026-08-10
### Added
- **Object style merging now works.** v3.2.0 refused it on the grounds that
  subcategories cannot be reassigned from the API. That was wrong: subcategory
  assignment lives inside each family, so the merge is done by opening every
  family of the parent category, repointing its geometry onto the kept
  subcategory, deleting the spare subcategory in the family, and loading the
  family back over itself with `IFamilyLoadOptions`. Elements placed directly in
  the project are repointed first, and the spare subcategories are then removed
  from the project.
  - Only subcategories that **share a parent category** can be merged; a mixed
    selection is reported before the dialog opens.
  - A confirmation window explains that families will be edited and reloaded,
    with a **MERGE AND RELOAD FAMILIES** button rather than DELETE.
  - Progress is reported family by family in the status box, since a large model
    can take a while.
  - Families that cannot be opened - in-place families and system families - are
    named and skipped, and the spare subcategories are then **not** deleted, so
    nothing loses geometry.
  - The whole run happens outside any transaction, because `EditFamily` and
    `LoadFamily` both refuse to work with one open.

### Notes
- This cannot be undone with a single Ctrl+Z: each family reload is its own undo
  step. Save or sync before running it.
- Nested families are not descended into; a subcategory used only inside a nested
  family is left alone and its parent family reports no elements moved.

## [3.2.0] - 2026-08-10
### Added
- **Dimension Styles tab.** Every dimension type with font, text size, width
  factor, bold/italic/underline, units format, tick mark, dimension and tick line
  weights, witness line gap and extension, text offset and centreline symbol, plus
  how many dimensions use it. Duplicates match on the full formatting set. Merge
  retypes every dimension onto the kept style, groups included.
- **Object Styles tab.** Every model category and subcategory as Revit's own
  Object Styles dialog shows them: projection and cut line weight, line colour,
  projection and cut line pattern, and material. Subcategories are editable and
  deletable; top-level Revit categories are marked read-only for name and cannot
  be deleted. Merging is deliberately unavailable here - see below.
- **Materials tab.** Every material with class, category, shading colour,
  transparency, shininess, smoothness, surface and cut pattern and their colours,
  plus a reference count. Merge repoints every writable material-valued parameter
  onto the kept material before deleting the others.
- Icons for the three new tabs, in the same house style.

### Changed
- **Scrollbars are now dark.** WPF's stock ScrollBar ignores Background and falls
  back to the system theme, so it needed a full control template - thumb, track
  and hidden arrow buttons. Sliders are themed to match.
- **Export and Import are now one square Excel button** with a drawn sheet glyph
  (Borders and Grids, not a symbol font, so it cannot render as a box). Clicking
  it drops a two-item menu.

### Notes
- Object styles are categories rather than types, and Revit exposes no way to
  move geometry between subcategories from the API, so merging is not offered on
  that tab - the duplicate colours still identify matching graphics.
- Material merging can only repoint writable material parameters. Compound
  structure layers and painted faces are reported and the replaced material is
  kept rather than deleted while anything still references it.

## [3.1.0] - 2026-08-10
### Fixed
- **Renaming line styles now works.** `Category.Name` is read only in the Revit
  API, so every rename of a line subcategory - inline, bulk find and replace, or
  Excel import - silently failed. Renames now go through the subcategory's
  GraphicsStyle element, which is the supported route.
- **Deleting line styles now works.** Line subcategories are not Elements, so
  `Document.GetElement` returns nothing for them and the delete was being skipped
  as "already gone". The delete is now attempted regardless, with the name taken
  from the table.

### Added
- **Groups are kept when merging.** Curves and text notes inside a group used to
  fail with Revit's "element is in a group" error, which left them on the old
  style. Style Manager now rebuilds the group instead: it ungroups one instance
  of the affected group type, applies the change, groups the members back up,
  restores the original group type name, and repoints every other instance of the
  old type onto the rebuilt one. Nested groups are handled recursively, pinned
  groups are unpinned and re-pinned, and each group is processed in its own
  SubTransaction so a failure leaves that group exactly as it was.
- Model groups with attached detail groups are reported and skipped rather than
  silently detaching them.
- A merge no longer deletes the replaced style if any curve or note could not be
  moved, since deleting a line or text style also deletes the content using it.

## [3.0.1] - 2026-08-10
### Fixed
- Startup robustness after reports of a blank pyRevit output window on launch.
  - .NET type imports are now resolved one name per line, so a missing type names
    itself in the traceback instead of failing the whole import block.
  - `WindowChrome`, `BitmapImage` and the threading types are optional: if any is
    unavailable the tool drops that feature rather than refusing to start.
  - Every XAML block is parsed through a wrapper that reports which block failed.
  - DataGrid column widths are built as explicit `DataGridLength` values rather
    than relying on an implicit numeric conversion.
  - Each tab is built independently - if one fails the others still open and the
    reason is written to the status box.
  - Any remaining startup failure is caught, printed in full to the pyRevit output
    and saved to `Documents\RevoBIM PY\Logs\StyleManager_startup_error_*.log`.

## [3.0.0] - 2026-08-10
### Changed
- **Renamed to Style Manager** with a new icon. The old `Filter Manager.pushbutton`
  folder is replaced by `Style Manager.pushbutton` - delete the old one if your
  extension folder still has it.
- The window is now a **tabbed shell**. Each tab has its own icon, table, toolbar,
  duplicate legend and bulk rename bar, and shares the status box and the red
  APPLY bar. APPLY commits every tab in a single transaction.

### Added
- **Line Styles tab.** Every line subcategory with weight, colour, line pattern
  and the number of curves drawn with it. Duplicates are matched on appearance
  (weight + colour + pattern), so styles with different names but identical
  graphics group together. Merge repoints every curve onto the kept style before
  deleting the others. Name, weight, colour and pattern are editable; Revit's
  built-in line styles are marked read-only and cannot be deleted.
- **Text Styles tab.** Every text note type with font, size, bold, italic,
  underline, width factor, colour and background, plus the number of notes using
  it. Duplicates are matched on formatting. Merge repoints every text note onto
  the kept type. Name, font, size, bold, italic, underline and width are editable.
- **Delete Selected...** on every tab, with a red confirmation window listing
  exactly what is affected: for filters, every view and template that uses them;
  for line and text styles, how many curves or notes Revit will delete along with
  the style. The confirm button is red and says DELETE; nothing else triggers it.
- **Edit in Revit** now selects the filter or line style inside Revit's own
  dialog using UI Automation on a background thread, as well as posting the
  command and copying the name to the clipboard.
- Excel export and import work on all three tabs, driven by each tab's column
  spec, with the same orange-editable / grey-read-only colouring.

## [2.0.0] - 2026-08-09
### Changed
- Staged editing: nothing is written until APPLY CHANGES is pressed.
- All staged edits commit inside one transaction; parameter maps cached, name
  collisions resolved in memory, warnings swallowed during the commit.
- Usage sweep reused after an apply; Excel import diffs in memory.

### Added
- Large red APPLY CHANGES button with staged count, Discard Changes, close guard.
- Edit in Revit; merging blocked while edits are staged.

## [1.2.0] - 2026-08-09
### Added
- In-place rename and rule editing, row context menu, bulk find/replace,
  automatic (2), (3)... numbering on name collisions.

## [1.1.0] - 2026-08-09
### Added
- Open folder location prompt after export, differential import, changed-row
  highlighting and isolation.
### Fixed
- Light non-client strip along the top edge of the windows.

## [1.0.0] - 2026-08-09
### Added
- First release as Filter Manager: filter table, usage counts, duplicate
  detection and merging, Excel round trip.
