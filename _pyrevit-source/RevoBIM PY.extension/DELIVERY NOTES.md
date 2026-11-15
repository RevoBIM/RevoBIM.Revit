# Pro Sheets Exporter 1.18.1 — delivery notes

## Installing

The zip contains one folder, `RevoBIM PY.extension`. Merge it into your
pyRevit extensions directory over the top of what is already there, then
reload pyRevit. Everything lands inside:

```
RevoBIM PY.extension\RevoBIM PY.tab\Sheet Tools.panel\Pro Sheets Exporter.pushbutton\
```

## Shared files: nothing in this delivery touches one

Checked against the shared-files rule before zipping. Every file in this
delivery sits inside the tool's own pushbutton folder. In particular:

| Shared and singular file | Shipped here? |
| --- | --- |
| `startup.py` | **no** - but 1.9.0 needs a block pasted into it, see above |
| `hooks\*.py` | **no** |
| `lib\revobim\__init__.py` | **no** |
| `Sheet Tools.panel\bundle.yaml` | **no** — the panel already exists, so its bundle is left alone |
| `lib\revobim\egg\` | **no** |

The easter egg is armed the way the other tools arm it, with one difference
from 1.2.2 onwards: **only the main window arms it, and only on the logo**.
Arming every dialog and report made clicking Close three times enough to
start the game. `egg_hook.attach` is called from inside a try/except, with
the signature read by reflection so the logo is passed as the element and
the window never is, so this remains one more anchor rather than a
dependency. If `revobim.egg` is not installed the call is skipped silently.

If the game still appears on **other** RevoBIM tools, the arming in the
shared `startup.py` and `hooks\*.py` is where to look. Those are shared files
this delivery deliberately does not ship.

## Where it puts things

| What | Where |
| --- | --- |
| Global settings (theme, default printer, last template) | `%APPDATA%\RevoBIM\pro_sheets_exporter.txt` |
| Export templates, per project | `%APPDATA%\RevoBIM\prosheets_profiles\<project>\<name>.txt` |
| Crash log, if it ever fails to open | `%APPDATA%\RevoBIM\logs\pro_sheets_exporter_last_error.txt` |

All plain `key=value` text, hand-editable, and a damaged file falls back to
the defaults key by key rather than refusing to load.

## Setting up a new machine

**The tool asks, the first time it opens on a computer.** Everything it
asks about is per machine and none of it travels in a template, which
is exactly why a template that works on one desk can fail on the next
with nothing to show for it but "no file appeared".

Three questions: how PDFs get written, where exports land by default,
and - if a print driver is chosen - which folder that driver saves to.
**Test it** reports what would stop a run without writing anything.
Closing without saving means it asks again next time, deliberately.

It is in the header as **Set up** afterwards, so a machine can be
sorted out later or changed.

If a run could not possibly write a PDF - a print driver selected with
no folder to collect from - Export refuses to start and offers to
switch to Revit's own exporter. That state used to run, fail on the
first sheet, and stop. Suppress dialogs does not silence the refusal.

**Revit's own exporter is what an unconfigured machine gets.** Versions
1.9.1 to 1.13.0 picked up `diroots.prosheets` automatically where it
was installed, which is right for a machine already set up for it and
wrong for a fresh one - the driver writes nothing until "Driver saves
to" is filled in. It is offered in setup now, with that folder on the
same screen, rather than chosen on your behalf.

## PDFs: Revit's own exporter, unless you say otherwise

From 1.16.0 that is the default on every machine, not only new ones.
Upgrading clears any printer an older build chose for itself — 1.9.1 to
1.13.0 picked one automatically, and on every machine it was tried on
it wrote nothing. A template asking for a driver no longer overrides
this either, so one shared `.rbtpl` cannot put a team back on PDF24.

To use a driver on a machine: **Set up** → A print driver → pick it and
give it its folder. That also clears the "always use Revit's own
exporter" tick, since choosing a driver is the opt out.

Revit 2021 and earlier are unaffected — there is no built-in exporter
to fall back to, so a driver is kept whatever the setting says.

## If you were on 1.14.1 or earlier and the driver wrote nothing

That was the tool, not your driver. `SubmitPrint` was being called with
a transaction still open, and Revit 2024 and later return from that
immediately and successfully having printed nothing at all. Fixed in
1.15.0. Everything below about staging folders is still true, but it
could never have worked while nothing was reaching the driver.

## "Driver saves to" is the driver's folder, not yours

The single most common way to lose an afternoon with this tool. That
box tells the tool **where to look**; it cannot tell the driver where
to put things, because that is a setting inside the driver. Typing the
folder you want your PDFs in is the natural thing to do and it cannot
work — the tool collects from that folder and renames into your export
folder, so if the driver is not writing there, nothing is collected and
every sheet reports "no file appeared".

Three steps, in this order:

1. In the driver's own settings, turn **on** automatic saving and give
   it an output folder of its own — `C:\PDF24_Staging`, not Documents
   and not your export folder.
2. Print anything to that printer once, so it writes a file. A Notepad
   page will do.
3. In **Set up**, press **Find it**. It looks for PDFs written in the
   last ten minutes and fills the box in. Browse only if you already
   know the folder.

A driver set to *ask* where to save can never work with this tool.
Either turn automatic saving on, or use Revit's own exporter.

**Prove the driver works before blaming the tool.** Open Notepad, type
a word, print it to that printer. If a PDF does not appear in the
staging folder on its own, with no prompt, the driver is not set up and
no amount of configuring this tool will help. Thirty seconds, and it
settles the question completely.

**Give it time.** A big A0 layout can take Revit ten seconds to spool
and the driver longer again to convert. The tool waits six times the
render time, at least a minute, and says in the debug log how long it
is prepared to wait. If files turn up in the staging folder after a run
has given up, the report says so — that is a driver slower than the
wait, not a failure.

## Before the first real run

Two things are worth five minutes:

0. **Check the Printer dropdown for `diroots.prosheets` first.** If
   ProSheets is installed on the machine, that is its own private PDF24
   instance, already set not to ask where to save, and the tool now picks
   it as the default when nothing else has been chosen. It still writes
   to PDF24's output folder rather than the path Revit asks for, so
   "Driver saves to" still has to be set - but the half that usually
   costs an afternoon, stopping the Save As dialog, is already done.

1. **If you are using PDF24 rather than Revit's own exporter**, open the
   PDF24 printer's preferences in Windows and set it *not* to ask where to
   save. A driver that prompts will sit there waiting on the first sheet and
   the tool will report that no file appeared. Revit's own exporter, which is
   the other entry at the top of the Printer dropdown, needs nothing set up
   and is the faster of the two.
2. **Check the paper sizes** the driver offers include the sizes your title
   blocks use. The size is read from each title block's own width and height,
   matched to a standard size in the right orientation, and a sheet that is
   not a standard size is fitted up to the smallest one that contains it and
   labelled "(fitted)". The tool refuses a sheet whose size the driver does
   not offer rather than printing it at the wrong scale — that refusal is the
   safe behaviour, but it is better to add the size than to meet it mid-run.

3. **Give the staging folder a folder of its own.** Collecting takes whatever
   new PDF appears while a run is going, so pointing it at your Desktop means
   a PDF saved there by anything else gets renamed and filed with your
   sheets. The tool warns when you pick a folder you use for other things.

## Columns on the Selection page

A sheet list starts with Sheet Number, Sheet Name, Revision, Size,
Current Revision Date, the sheet series, the discipline and Custom File
Name, sorted by the series — unless a template you loaded was saved
with a sort of its own, which it keeps, and the status line says so. The last three come from what **Set up**
was told this project calls them — the usual `BGL_` names are picked up
automatically, and a project with neither simply does not get those
columns. A template with its own columns still wins.

Right click any column heading for **Add column...** and pick one or more
parameters from the searchable list. Each row shows what the parameter
resolves to on a real sheet, so an empty one is obvious before you add it.
The new column lands **beside the heading you right clicked**, not on the far
right. Right clicking a column you added offers to remove it.

Every heading has its own **search box**. They narrow rather than widen, the
way Excel's do: every box with something in it has to match. "Clear every
column search" is on the right click menu once anything is typed.

Clicking a heading **sorts** by it and outlines it in orange with a `1▲`
badge; clicking again flips the direction. **Shift click** another heading
to sort on top of the first, up to six levels, each in its own colour —
orange, blue, green, violet, teal, amber — so which level is which is
readable without counting.

Sorting also gives **every value in that column a colour of its own**,
repeated or not, and makes the repeated ones collapsible — no separate
step. The cells of the sorted column carry the colour and the rest of the
row takes a wash of it, so a block can be followed down the page without
the colour fighting the text. Twelve hues, generated rather than listed,
cycling after that.

**Every value gets a heading**, including the ones that appear once, so
anything can be collapsed. Each shows **[ - ] Collapse** with the count,
in blue and a size up; click it to collapse or expand, or click its
**tick box to tick the whole group** — hidden members of a collapsed
group included. Tick the last sheet in a group by hand and the heading
lights up; untick any one and it clears. **Collapse all** lights up while
there is something to collapse.

**Highlight a block of rows and tick any one of them** — click, shift
click or ctrl click as usual — and the whole block follows, the way a
spreadsheet does. A tick on a row outside the highlighted block is just
itself.

One thing worth knowing: sorting by a column where nothing repeats, such
as Sheet Number, gives a heading above every row and doubles the length
of the list. That is the sort you do to find one sheet, so untick
**Group matching values** for it — which turns the whole thing off for
the sort you are on. **The next sort turns it back on**, on the grounds
that sorting a column and colouring its values are the same intent; the
tick box is a "not for this one" rather than a setting that sticks.

The column order, the sort stack, the grouping, the column widths and the
window size are all saved with the template. Window size and column widths
are also remembered globally per machine, which is what a plain launch
uses.

## Sheet series and discipline

**Set up** asks which parameters this project uses for them, offering
the ones the sheets actually carry and pre-selecting `BGL_Sheet Series`
and `BGL_Sheet Discipline` where the model has them. They drive three
things: two columns on the Selection list, the sort it opens in, and
the last folder level exports land in.

A saved name a particular model does not have is kept and offered with
a note, not dropped — otherwise one odd project would quietly change
the setting for every project after it.

## Dark and light

The chip top right has three states: **Auto**, **Dark**, **Light**. Auto
is the default and follows Revit's canvas, live — change Revit's theme
with the window open and the window follows within a couple of seconds.
The chip reads "Auto (dark)" so it is clear both which mode is set and
what it currently resolves to.

Before 1.10.0 the window matched Revit on open but the chip saved the
resolved palette rather than the mode, so one click pinned it for good.
**Everybody starts on Auto after this upgrade**, whatever the chip was
last left on. That is deliberate: the old setting cannot tell a
deliberate pin apart from one the bug made, so 1.10.0 reads a new
setting and leaves the old one alone rather than guessing. Pin it again
with the chip if you want it pinned.

## What a run looks like now

Export starts on the first press — no confirmation. The Create tab
comes forward and each row goes **green as its file lands**, red if it
fails, so a long issue can be watched rather than guessed at. A row
that fails stays red even if another format on the same sheet
succeeds.

The one thing that still stops a run before it starts is a print
driver with no folder to collect from. That is not a confirmation and
is not suppressed.

## Subfolder tokens

The default, which a template can override:

```
{Project Name}\{Year}-{Month}-{Day}_{Hour}_{Minute}\{BGL_Sheet Series}
```

**Add parameter** on the Create tab opens a searchable list of every sheet
and project parameter, plus date and time tokens, with the value each one
has on the first ticked sheet. Add them as folder levels or onto the level
being built; the preview shows the real path before you commit to it.

Date and time can also be written as strftime codes. They follow strftime,
so **`%m` is the month and `%M` is the minute** — the named tokens
(`{Month}`, `{Minute}`) exist precisely so nobody has to remember that.

## Moving to another computer

Settings, templates and the remembered "Driver saves to" folder all live in
`%APPDATA%\RevoBIM\` on each machine, so a new computer starts fresh. That is
deliberate for the driver folder, which differs per machine, but it means the
first driver run on a new machine is expected to fail once and be picked up
by the scan.

**Templates travel as a file.** The two arrow buttons beside the template
dropdown save every template for the project into one `.rbtpl` file and load
them back on another machine. Importing offers Merge or Replace all, and a
repeated name gains `(1)`, `(2)` rather than overwriting. The file is plain
text with an `@template=<name>` line before each one, so it diffs and edits
by hand.

## One paste needed for the right click entry

Everything in this delivery works as soon as the zip is merged, **except**
the **Print Selected** entry on the right click menu. That one needs a block
pasted into a file this delivery deliberately does not ship.

1. Open `startup_fragment.py` in the tool's folder. It is not loaded by
   anything - it exists to hold the block and explain it.
2. Copy the banded block out of it.
3. Paste it at the end of your existing
   `RevoBIM PY.extension\startup.py`. **Do not overwrite that file** -
   the easter egg is armed in it, among other things.
4. Restart Revit. pyRevit reload is not enough: the registration only
   happens during Revit's own startup.

Then right click a sheet in the Project Browser and **Print Selected** is at
the bottom of the menu.

Revit 2024 and earlier: paste it anyway. The block is dormant there and
writes one line to the log saying so.

If the entry does not appear, the log says why:
`%APPDATA%\RevoBIM\logs\pro_sheets_exporter_context_menu.txt`. It is
rewritten at each Revit start and names the version it saw, whether it
registered, and what it could not find. The tool also writes to it when it
opens on 2025 or later and finds the entry missing, so an overwritten
`startup.py` leaves a trace rather than a feature that quietly disappeared.

### What it can and cannot do

Revit only lets an add-in **append** to its context menu. The entry goes at
the bottom; there is no way to put it further up or to change what Revit
already puts there.

The entry is always present rather than appearing only when sheets are
selected. That is deliberate: Autodesk have an open bug, REVIT-251042,
where adding nothing still leaves an empty flyout hanging in the Project
Browser, so an always-present entry beats a blank sub-menu.

## Formats

| Format | State | Needs |
| --- | --- | --- |
| PDF | live | nothing, or a print driver if you prefer one |
| DWG | live | nothing |
| NWC | live | a ticked 3D view, and the Navisworks exporter add-in |
| IFC | live | a ticked 3D view |
| DWF | reserved | - |

Each tile carries a drawing of its own — a page of text for PDF, a
wireframe in yellow on blue for DWG, two overlapping models for NWC, a
structure with its nodes for IFC. They are original marks, not the
Acrobat, AutoCAD, Navisworks or buildingSMART logos, which are
trademarks their owners control and not something a tool should ship
copies of on your behalf.

If your organisation is licensed to use the real marks, each tile is a
`Canvas` of four or five elements inside `ProSheets.xaml`, under
`x:Name="PdfTile"` and the rest. Replace the contents of the Canvas with
an `<Image Source="..."/>` and keep the Button and its name as they are
— the name is what the registry in `ps_window` wires up, and the bench
rule `format_registry` will tell you if it stops matching.

DGN and IMG were removed in 1.8.0. They had been drawn on the tab and
greyed since 1.0.0 with nothing behind them.

**NWC and IFC only appear once a 3D view is ticked.** Both export one
view at a time and Navisworks has no concept of a sheet, so in Sheets
mode both tiles are greyed and the tab says why. Tick eight views with
one 3D among them and only the 3D one goes to NWC and IFC; the others
still go to PDF and DWG, and the report says how many were skipped.

The **Navisworks exporter add-in** ships with Navisworks Manage or
Simulate, not with Revit. Without it the first view fails and the run
stops rather than repeating a ten-second failure once per view.

Three buttons on the IFC panel - File Header Information, Project Address
and Classification Settings - explain rather than edit. Revit stores all
three against the project and the exporter reads them from there on every
export including this one; there is no per-run override in the API, so a
value typed into this tool would be thrown away. Each button says where
to set it once in Revit.

**IFC setups** live in `%APPDATA%\RevoBIM\ifc_setups\` as `.rbifc`
files, not per project, because an IFC setup is a house standard rather
than something about one job. Export writes one, Import reads one from
anywhere and keeps a copy there, and whatever is in that folder fills the
Current Setup dropdown. Note this is the tool's own plain text format;
Revit's exported IFC setup is a different thing and cannot be read here.

## Sheets and Views

The two modes now carry different columns. Sheets is unchanged. Views
starts with **View Name** and **Custom File Name** and nothing else,
because a view has no sheet number, no revision and no paper size - those
three columns were permanently empty and took half the grid.

Right clicking a heading in Views mode offers **view** parameters, since
the list is built from whatever is on screen.

Each mode keeps its own columns, widths, sort stack and column searches,
so switching across and back loses neither. A template saved against
sheets and loaded in Views has its sheet-only columns dropped and its
parameter columns kept; the other way round puts Sheet Number, Revision
and Size back rather than leaving the grid short.

## Running the bench check

From the tool's folder, under plain CPython - no Revit needed:

```
python import_check.py            31 rules over the whole tool
python import_check.py --selftest breaks each rule to prove it fires
```

Both are clean as delivered, and all sixty one breakages fire.

1.0.1 added the rule that would have caught the "No module named Data"
crash in 1.0.0: it maps every `System.*` and `Autodesk.*` import back to
the assembly providing it and fails when `ps_refs` does not reference that
assembly. `System.Data` is a separate assembly from `System`, and under
IronPython a namespace does not exist until its assembly is referenced.

1.8.0 adds `format_registry`, which holds the one-row-per-format table
against the Format tab, and `mode_columns`, which holds the sheet and view
column sets to their contract.

1.9.0 adds `context_menu_gate`, which fails if anything 2025-only reaches
the top of `ps_context` - that module is imported from the shared
`startup.py`, so an import that throws on Revit 2024 stops pyRevit loading
every tool in the extension - and `shared_files`, which walks the whole
delivery and fails on a `startup.py`, a `hooks` folder, a
`lib\revobim\__init__.py` or a `<Panel>.panel\bundle.yaml`. That second one
is the project's shared-files rule made mechanical and is worth copying into
every other RevoBIM tool's bench.

## Using PDF24 (or any driver that saves where it likes)

PDF24's printer port is a named pipe into the PDF24 service, not a file port,
so Revit's print-to-file redirect cannot reach it. The job goes down the pipe
whatever path Revit sets. That is not a setting you can change — it is how the
driver is built.

The way round it, which is what ProSheets does too, is to let the driver save
where it wants and rename afterwards:

**Shortcut:** run one sheet through the driver first and let it fail. The
report scans for PDFs written in the last few minutes and, where they are all
in one place, offers a **Use that folder** button that fills in "Driver saves
to" for you. Then you only need step 1 below if the driver is still prompting.

1. In **PDF24 Settings → PDF Printer → Auto Save**, turn on *"Automatically
   save documents after printed"*. Set the **Output Directory** to a staging
   folder of its own — `C:\PDF24_Staging`, not your issue folder. Give the
   **Filename** a timestamp, e.g. `$fileName_%Y%m%d_%H%M%S`, so nothing
   overwrites while it is sitting there.
2. In the tool, Format tab, set **Driver saves to** to that same folder. It
   is remembered against that printer, so switching drivers and back brings
   the right folder with it.
3. Export. Each sheet is collected from the staging folder and moved to the
   name your naming rules asked for.

The driver names the file, the tool renames it. If PDF24 is still asking
where to save, nothing is collected and the report says so in those words.

**Revit built-in PDF export** remains the simpler answer where you do not need
PDF24's own output settings: no driver, no staging, exact file names.

## If a PDF does not appear

A debug log is written on every run, whether or not anything went wrong, to
`%APPDATA%\RevoBIM\logs\pro_sheets_exporter_debug.txt`. It names the driver, the
paper sizes it offers, which paper each sheet matched, whether the API took
the output path, whether the submit threw, and whether anything arrived. That
distinguishes "the driver refused" from "the driver saved it somewhere else",
which look the same from outside. The **Debug log** tickbox on the Create tab
puts the same content in the report window as well.

If the driver accepted the job and nothing arrived, switch the printer to
**Revit built-in PDF export** to rule the driver out. If that writes the file,
the driver is prompting or redirecting and no Revit-side setting will change
it.

## What is not in this version

DWF is drawn on the Format tab and disabled. It is the only one of the
original seven still pending; DGN and IMG are gone rather than waiting.

There is still no "skip sheets whose revision has not changed" option,
and no export log written beside the files. Say the word and they go in
next.
