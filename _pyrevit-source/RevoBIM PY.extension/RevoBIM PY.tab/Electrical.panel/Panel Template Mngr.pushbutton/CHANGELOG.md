# Panel Schedule Template Manager - changelog

Version numbering is short semantic.  `__version__` lives at the top of
`pstm_core.py`; both pushbuttons and every window read it from there, so bumping
that one line is the only edit a release needs.

## 1.9.0 - shrink any window to the taskbar

Every window the tool opens - the main window, Settings, and every prompt,
chooser and the Rename dialog - now has a **shrink button** in the top right,
beside full screen and close. Pressing it slides the window down to the bottom
of the screen like a drawer closing, leaving only its header bar floating clear
of the taskbar, so Revit can be seen and worked in. The button turns into a
**green up arrow** that opens it again. `Ctrl+Shift+H` does the same, and a
double click on the parked bar brings it back.

It is the same gesture as Pro Sheets, Filter Manager, View Manager and Hanger
Automation - same 280 ms curve, same 8 px landing above the taskbar, same 4 px
stacking - built once as `pstm_drawer.py` and handed to all five windows.

**Two things specific to this tool:**

- **It works while a job is running.** Apply and Regenerate used to make the
  whole window deaf for the length of a run, because pumping the dispatcher to
  move the progress bar also pumps clicks. Now everything goes deaf *except
  the shrink button* - a long Apply over 600 panels is exactly when you want to
  put the window away and watch Revit, and shrinking touches nothing but the
  window's own geometry. The bar is not draggable mid-job (that would start a
  modal loop inside Revit's API context), but it can be brought back.
- **Changes waiting for Apply stay waiting.** Shrinking is not closing - there
  is no prompt, and nothing is dropped.

**When a job finishes while the window is shrunk**, its summary opens in the
middle of the screen you are working on, not centred on a 50 px bar at the
bottom of it (which would put most of the dialog off the screen).

**Shrinking a dialog takes the main window down with it**, stacked beneath, so
the main window does not just sit over Revit. Bringing the dialog back - or
closing it - brings the main window back behind it. Note that the dialogs are
modal: shrinking one lets you *see* the model, but Revit stays locked until the
dialog is answered.

While a window is parked: Escape, Enter and F11 bring it back instead of
reaching a close prompt or filling the screen; the full screen button does the
same; the resize grips are parked with it so they cannot swallow the click on
the arrow. A bar that has been dragged somewhere opens upward from where it now
sits, kept on its own screen - including a second monitor above the primary,
where the work-area top is negative.

### The bench

`drawer_check.py` drives the real drawer against a stand-in window - 19 checks,
and `--breakages` breaks the drawer **26 ways** on purpose to prove every check
bites. All 26 caught.

Building it found a blind spot worth knowing about: the fake timer first ran
its ticks *inside* `Start()`, so an exception escaping a tick was caught by the
slide's own fallback and the bench passed. A real `DispatcherTimer` never calls
`Tick` from inside `Start()`, and in Revit that drawer would be stranded
mid-slide for good. The fake now hands escaped tick exceptions to a "dispatcher"
the way WPF does, and the breakage that removes the tick's fallback is caught.

`import_check.py` gained a `check_drawers` rule - every layout has a styled
`ShrinkButton`, every class that loads a layout makes a `Drawer`, every
`wire_drag` hands over its drawer, the drawer wires the button and releases
both animated properties, the shrink button is not in the busy-deaf list, and
the main window's header, keys and full screen defer to a parked drawer. Nine
deliberate breakages, all caught for the right reason.

**And a bench fix:** the undefined-global rule failed on v1.8.1's own clean
source under Python 3.12+. PEP 709 inlines comprehensions into the enclosing
scope, so the `k` in a module-level `[k for k in ...]` appears in the module's
symbol table as an unbound global. The tool was never affected - it runs on
IronPython - but the bench now knows a comprehension binds its target, and
still catches a deleted function.

## 1.8.1 - right click a template to edit it in Revit

Right click a template in the Panel Assignment list: **Edit template in Revit**
opens it in Revit's own editor and closes the tool, so you land in edit mode
with nothing in the way. **Copy template name** is there too.

**A caveat that is Revit's, not the tool's.** `PanelScheduleTemplate` derives
from `Element`, not from `View` - the class documentation is explicit - and
there is no postable command for the template editor either. So there is no API
route to open the editor on a chosen template, except on releases where the
template is also exposed as a `PanelScheduleView` with `IsPanelScheduleTemplate()`
true. Both the id and the name are looked for, so it opens wherever the release
allows it.

**Where Revit will not, the tool says so rather than doing nothing.** It names
the two clicks that do it by hand - Manage, Panel Schedule Templates, Edit a
Template - and puts the template's name on the clipboard so it can be pasted
into that dialog. A right click that silently did nothing would have been worse
than no right click at all.

The right click menu is themed like the rest of the tool rather than arriving in
default Windows white on the dark palette.

Bench case added: a template exposed as a view is found by id and by name, and a
plain template element is **not** reported as openable. Verified by making it
claim any element would open.

## 1.8.0 - Regenerate Templates

An orange **Regenerate Templates** button in the bottom left. Editing a template
does not reach the schedules already made from it, so a panel schedule sitting
on a sheet keeps showing what it showed the day it was generated. This re-pours
**every panel schedule in the project from the template it is already on**,
which is what makes the sheets current.

`GenerateInstanceFromTemplate` is documented as assigning the template's data to
the instance, so calling it with the view's **own** template is the regenerate.
This is the one place in the tool where re-pouring the current template is the
point rather than the bug - in 1.6.1 that same behaviour, reached by accident
through the wrong overload, was what made Apply do nothing.

It behaves like Apply in every way that matters:

- **batched transactions**, so one schedule Revit will not have cannot roll back
  the rest - the chunk is replayed one at a time and the one at fault is named;
- **panels somebody else owns are skipped and named**, not attempted;
- a schedule with no template on it is reported rather than silently passed over;
- the summary says how many were regenerated out of how many, and how many of
  those are on sheets.

It asks first, and the prompt says the thing worth knowing before you press it:
**a re-poured schedule takes its layout from the template**, so anything moved
about on an individual schedule by hand goes back to what the template says.

New in the theme: `OrangeButton`, a solid orange button, with an
`OrangeHoverBrush` in both palettes.

Two cases added to `batch_check.py`: the right schedules are attempted, each
with its **own** template id, the locked one and the templateless one reported
separately, and the double attempt on a bad chunk shown to be the retry doing
its job. Verified by pouring the wrong template and by taking the lock check
out.

## 1.7.1 - renamed to Panel Template Mngr

The ribbon button, both window headers, the error dialog and the folder are now
**Panel Template Mngr**. The tooltip still opens with the full name, so anybody
hovering it still finds out what it is.

**Your settings are kept.** The settings file is still
`%APPDATA%\RevoBIM\panel_schedule_template_manager.txt` under its old name, on
purpose: a missing settings file falls back to the defaults without complaining,
so renaming it would have quietly thrown away the chosen ways and phases
parameters and the column set. There is a comment on it saying so.

**Delete the old `Panel Schedule Template Manager.pushbutton` folder.** The
folder is renamed, and pyRevit names a ribbon button after its folder - leave
both and you get two buttons.

The bench now checks the name in one place against the folder, the ribbon title
and the window header, so the next rename cannot leave the old one showing in
the place somebody screenshots. Verified by breaking each of the three.

## 1.7.0 - panels somebody else has are left alone, and said so

A panel checked out by another user, or sitting on a workset somebody else
owns, is now **skipped rather than attempted**, and the run carries on through
the rest.

**In the table** the row goes grey and its note reads `LOCKED - workset
"Electrical" is owned by jsmith` or `LOCKED - checked out by jsmith`. The
footer counts them alongside the changes waiting.

**Two different things lock an element** and both are asked about, because
checking only one misses half the cases:

- somebody has borrowed the element itself - `GetCheckoutStatus` reports
  `OwnedByOtherUser`, and `GetWorksharingTooltipInfo` gives their name;
- nobody has borrowed it but its whole **workset** is owned by somebody, in
  which case the element's own checkout status is perfectly clean and only
  `Workset.Owner` gives it away.

The panel **and** its schedule view are both checked - the swap writes to the
view, but making a schedule for a board that has none writes to the panel.

**A locked row never takes a pending change.** Auto Assign steps over it and
says how many it stepped over; picking a template for a multi-row selection
sets the ones that are free and names the reason the others were left. A change
the table said was waiting that Apply could only skip would have been a lie in
the table.

**Apply asks again at the moment it writes.** Revit's documentation is explicit
that worksharing status comes from a local cache of central, so the answer the
window got when it opened can be an hour stale. Anything locked at the point of
writing is reported as left alone, separately from real failures - being locked
is not a failure, it is somebody else's turn.

Covered in `batch_check.py`: two locked panels in a batch of seven, the other
five written, the two reported by name and reason, and nothing in the failed
list. Verified by taking the check out again and watching all seven get written.

## 1.6.2 - single phase starts at one way

Ticking **Single phase panel** did step the list in ones, but it still started
at **3**, so the list read 3, 4, 5, 6 and the small boards were missing. The
minimum in Settings is written in *slots* for three phase boards, and it was
being applied to a list where one slot is one way - hiding every single phase
board under three ways.

Single phase now counts **1, 2, 3, 4 ...** up to the maximum. Three phase is
unchanged: multiples of the step from Settings, honouring the minimum. The line
under the list says which of the two it is doing.

## 1.6.1 - one bad panel no longer costs you the other forty-six

**"A managed exception was thrown by Revit or by one of its external
applications."** Apply put every panel in **one transaction**, so the moment
Revit refused one of them the whole thing rolled back and nothing was written -
which is exactly what "Nothing was changed" was telling you, truthfully and
uselessly. It gets worse the more panels you select, which is why it showed up
on Auto Assign Selected over a large batch.

Apply now runs in **three passes and many small transactions**:

1. the template is swapped on every panel, **in chunks of twenty**;
2. those are committed - a commit regenerates - and then every panel is **read
   back** to see which ones actually moved;
3. the ones that did not are **rebuilt one transaction each**, because a delete
   and a create is the risky part and must not be able to take anything else
   down with it.

**A chunk Revit refuses is rolled back and then replayed one panel at a time**,
so the one at fault is named and only that one is lost. All of it sits inside a
`TransactionGroup`, so Revit's undo still sees a single step.

**And the most likely reason Revit was refusing at all is now caught before the
call.** Revit's own Change Template dialog only offers templates that suit the
panel; hand the API one that does not and you get that same managed exception.
The template's schedule type is checked against the panel's first, and a
mismatch is reported as a sentence naming the panel and the reason rather than
as a native exception.

Merge got the same treatment - it moves panels too - and it will only delete the
emptied templates if every panel really did move off them.

There is a bench test for this now (`batch_check.py`), against a fake Revit that
throws the way the real one did: one bad panel in ten, two bad panels in
different chunks, a panel that silently refuses, all bad, none bad. It was
verified by putting the old all-or-nothing behaviour back and confirming the
tests fail.

**Single phase duplicates count ways properly.** A single phase way takes **one**
slot, not three, so a 12 way single phase board is 12 slots. Ticking *Single
phase panel* in the duplicator now rebuilds the slot list in whole ways, keeping
the number of **ways** you had picked rather than the number of slots, and the
list says which rule it is using. Selecting a single phase source sets it that
way to begin with.

## 1.6.0 - Apply that applies, and renaming in bulk

**Apply was calling the wrong overload.** `GenerateInstanceFromTemplate` has a
parameterless form on some releases which rebuilds a panel schedule from the
template it is *already on*. The reflection that went looking for "an overload
we can fill" could land on that one: Revit did real work, raised nothing, and
the panel stayed exactly where it was. Apply then reported success, the table
was re-read, and every change was still waiting - "47 changes waiting" after a
run that said it had applied 47 changes.

Three things changed:

- **The overload is now picked by its parameter type**, not by matching argument
  names, so only `GenerateInstanceFromTemplate(ElementId)` can ever be called.
- **The document is regenerated and the template read back off the view.** A
  panel that did not move is reported as not moved, by name.
- **The view is looked up inside the transaction** from its id, rather than an
  `Element` handle captured when the window was opened - which by then may be an
  hour old.

**And if Revit still will not swap a template in place, that panel's schedule is
rebuilt on the wanted template** (`CreateInstanceView` chooses the template at
creation, so it cannot be ignored). A schedule already placed on a sheet is
never rebuilt - it is reported instead, because rebuilding it would take it off
its sheet. There is a switch for this in Settings, on by default.

**Apply now checks its own work against the re-read model.** Not "how many calls
did Revit accept" but "how many panels are actually on the new template", and it
names the ones that are not.

**"Master" comes out of a duplicate's name.** A copy of
`BGL_Schedule One Column Master (R2)` is now `BGL_Schedule One Column (R2) 12
Ways`. Only the whole word, so `Mastermind` keeps its name, and because an
underscore is a word character to a regular expression, `BGL_Master_One Column`
is handled explicitly - `\b` would never have fired there.

**Rename, in the Template Duplicator.** Select any number of templates and press
Rename: find and replace (with or without case matching), a prefix, a suffix,
and the same "take Master out" tick. Every row shows what it would become before
anything is written, and a rename that would clash with another name or empty a
name says so on that row instead of failing halfway through the batch. The
renaming itself runs in two passes through a parked name, so swapping two names
round - or shuffling a set along by one - does not fail on a clash with itself.

**Search boxes are readable.** The text box style was 30px tall with 6px of
padding top and bottom, which left 16px for a line of type that needs about 17 -
so every box clipped its own descenders. Padding is down to 3, the minimum
height up to 32, and every fixed-height box in every layout moved from 28 to 32.
The column headers grew to suit.

## 1.5.0 - find out which step destroys it

Every step reported success and the template still did not survive the commit.
Revit can accept a call, leave the element looking perfectly fine, and then drop
it at commit because something about it is not valid - which from the outside is
"it says it created them but they are not there" with nothing to go on.

So the tool no longer trusts any of it. **After every step it looks to see
whether the element is still in the document**: after Create, after the layout
copy, after the slot count, after regeneration. Whichever step loses it is named
in the message.

**And if the layout copy is what destroys it, the whole thing is built again
without the layout.** A template of the right type, configuration, size and name
is far more use than none, and the note says the layout could not be carried
over rather than pretending otherwise.

Two other things that could have made this worse:

- **The trailing `SetTableData` after setting the slot count is gone.**
  `GetTableData` is documented as returning "the writable table data object", so
  the update applies in place; handing a table back afterwards was one more
  thing that could invalidate the element for no benefit.
- **The check that says "none of them are in the model" now looks by name as
  well as by id.** If a template turns up under its name but not the id that was
  captured, the check itself is what is wrong - and it now says so instead of
  sending anyone hunting for a template that is sitting right there.
  `eid_value` also casts to a plain `int`, so a captured `Int64` cannot miss a
  re-read one as a dictionary key.

## 1.4.1 - two functions I deleted by accident

**Not a naming issue - my mistake.** `global name 'schedule_type_of' is not
defined` was exactly that: rewriting `set_slot_count` in 1.4.0 replaced a block
of source that also contained `schedule_type_of` and `is_template`, and both
went with it. Everything still imported cleanly, so nothing caught it until the
line ran. Both are restored.

**The bench check now catches this class of mistake.** Using `symtable`, every
global name a function reaches for is checked against what the module actually
defines - the gap an import test can never see, because the module imports
perfectly and only falls over when the line is reached. Verified by deleting
each of those two functions again and confirming it is caught. It cannot see a
typo in an *attribute* (`core.ways_from_slot`), which stays a real gap.

Naming was already doing what was asked, and is unchanged: one template per slot
count picked, each named `<source> <n> Ways` -

```
  9 slots ->  3 ways -> BGL_Schedule One Column Master (R2) 3 Ways
 18 slots ->  6 ways -> BGL_Schedule One Column Master (R2) 6 Ways
 36 slots -> 12 ways -> BGL_Schedule One Column Master (R2) 12 Ways
```

## 1.4.0 - the circuit table, and a ways suffix

**This is why nothing survived.** `Create` was working by 1.3.1 - the template
was being made - but the call that builds its circuit table was being refused
every time, so Revit was handed a template it could not finish and dropped it at
commit. The declaration:

```csharp
public void UpdateCircuitTableForTemplate(
    PanelSchedulePhaseLoadType newType,
    int nNumSlots,
    bool bPhasesAsCurrents)
```

Three arguments, and **`PanelConfiguration` is not one of them** - the
configuration is fixed when the template is created, which is why `Create` takes
it. Every shape tried before passed a `PanelConfiguration` first, and Revit said
so plainly: *"expected PanelSchedulePhaseLoadType, got PanelConfiguration"*.

Worse, the reflection that was supposed to prevent exactly this could not fill a
`PanelSchedulePhaseLoadType` parameter - nothing in the values it was given had
one - so it skipped the only real overload and fell through to the guesses.

Now: the phase load type and the currents flag are read off the template's own
data, the matcher can fill that type, and the positional fallback is the
documented order. `Document.Regenerate()` runs after each template is built, so
anything Revit objects to surfaces at once rather than being dropped silently.

**Names get the ways as a suffix.** Replacing the largest number in the name was
wrong for a source called "BGL_Schedule One Column Master (R2)" - the biggest
number there is the revision marker, so a 3 way copy came out as "(R3)". Copies
are now named `<source> <n> Ways`, e.g. **"BGL_Schedule One Column Master (R2)
3 Ways"**. An existing ways suffix is replaced rather than stacked, so
duplicating a duplicate does not accumulate them, and a clash still gets "New".

## 1.3.1 - the real Create signature

I stopped inferring and read the declaration. It is the same on 2024 and 2026:

```csharp
public static PanelScheduleTemplate Create(
    Document document,
    PanelScheduleType type,
    PanelConfiguration config,
    string strName)
```

Four arguments - and **not in the order the class summary implies**. Two things
were wrong against it:

- **The positional fallback had the arguments in the wrong order**
  (`doc, name, type, config`). Reflection fills the call by parameter name and
  gets it right, but the moment reflection could not read parameter names the
  fallback was guaranteed to fail. It is now the documented order.
- **`config` was allowed to be `None`**, which makes the four argument overload
  unfillable and drops the call to that broken fallback for no reason. The
  configuration now comes from the source's table data, then from the
  configuration picked in the duplicate panel, then from `OneColumn`.

**The layout is poured with `SetTableData` first, not `CopyFrom`.**
`Element.CopyFrom` copies *all* values from the other element - **including its
name**. A copy that then could not be renamed sat in the model under the
source's own name, which is exactly what "it says it created them but they are
not there" looks like from the outside. `CopyFrom` is now only a fallback, and
the rename afterwards is reported either way.

## 1.3.0 - Auto Assign matches on slots, and Create proves itself

**Auto Assign was comparing the wrong two numbers.** It worked out the slot
count from ways x phases, then looked for that number *in the template's name* -
but since 1.1.0 a template name carries **ways**, not slots. So a 36 slot panel
went looking for a template with 36 in its name, when the template it wanted is
called "12 Ways" and is 36 slots.

It now matches the calculated slot count against the template's **real slot
count**, read from its table data, and takes the **first template that fits**.
The name number is only a fallback for a template whose table data will not
report a count. Where more than one fits, the schedule type and the panel
configuration on screen break the tie, and the note says how many others would
have done.

**Assigning to a multi selection.** Pick several panels, open the template
dropdown on any one of them, and the template goes onto **all of them**. The
status line says how many were set. Picking a dropdown on a row that is not part
of the selection still changes only that row.

**Create now proves it worked.** The ids of everything created are handed back,
looked up again after the model is re-read, and the answer is said out loud:
nothing found means Revit took the call and kept nothing; found-but-hidden turns
the filters off and says so; either way the new templates are **selected and
scrolled to** in the list.

Two things behind "it says complete but nothing appeared" are fixed outright:

- **A rename Revit refused was being recorded and then dropped.**
  `Element.CopyFrom` copies the source's *name* across with everything else, so
  a copy that could not then be renamed sat there under the source's own name,
  invisible. The rename is now reported, and a refused name falls back to
  "&lt;name&gt; Copy" rather than being left alone.
- **The Template Duplicator was not applying the configuration filter**, so what
  it showed and what the Panel Assignment tab showed disagreed.

**The Duplicator now honours the type and configuration filters**, with a
**Use the type and configuration filters** tick box to turn them off and a label
saying which are in force. Creating something the filters would hide turns them
off automatically.

## 1.2.1 - moved to the Electrical panel

**The tool now lives on the Electrical panel**, not Management.

That also clears the install error 1.2.0 could throw:

```
Failed to create push button 'Panel Schedule Template Manager'.
Exception: The name already exists:Panel Schedule Template Manager
```

pyRevit names a ribbon item after its folder, and 1.2.0 collapsed the old
`Panel Schedule Template Manager.pulldown` into a `.pushbutton` of the same
name. With the old folder still on disk, both resolved to the same item name in
the same panel and pyRevit refused the second one. On a different panel they
cannot collide - but **the old folder still needs deleting**, or the tool
appears twice and the stale copy will not run:

```
%APPDATA%\pyRevit\Extensions\RevoBIM PY.extension\RevoBIM PY.tab\
    Management.panel\Panel Schedule Template Manager.pulldown
```

This package does not contain a `Management.panel` at all, so unzipping it
leaves Drawing Register exactly where it is.

## 1.2.0 - one button, a green +, and Create actually creates

**Create works.** The v1.1.0 diagnostics did their job and named the real cause:

```
Duplicate: 'PanelScheduleTemplate' object has no attribute 'Duplicate';
CopyElement: Copying one or more elements failed.;
Create: Create() takes exactly 4 arguments (3 given)
```

So the templates are `PanelScheduleTemplate` elements - Revit will not copy
them and they have no `Duplicate` - and `PanelScheduleTemplate.Create` takes a
**fourth** argument the documentation does not mention. Rather than guess which,
the method's own parameter list is now read by reflection and filled by name and
type, so the panel configuration (or whatever the fourth argument turns out to
be on a given release) is passed correctly. The source's layout is then poured in
with `CopyFrom`, falling back to `SetTableData`.

If a release still refuses, **Copy the layout from the source** can be unticked
in the duplicate panel to get correctly sized blank templates instead, and the
message names every route with Revit's own words.

**One ribbon button.** The separate Settings button has gone; settings live
behind a **gear chip** in the tool's own header, which now reads as a button -
bordered, filled, and it lifts on hover. The gear is drawn as a path, not set in
a symbol font.

**The first two parameter columns follow Settings.** Saving Settings points
column one at the ways parameter and column two at the phases parameter.

**A green + at the end of the headings adds another parameter column** - as many
as you want. A column's own picker has `(none)` to clear it and
`(remove this column)` to take it away again. The set is remembered.

**A progress bar across the top** while anything is running, with the
percentage on the right and what it is working on underneath.

**Merge asks in its own window.** Pick two or more templates, press Merge, and a
window lists exactly what you picked and asks "Which template to merge to?".

**Duplicate Selected goes green** the moment one template is picked, and picking
more than five slot counts asks first: *"WARNING, this process takes some time
if you selected a lot, I advise you SYNC the model before running and make a cup
of tea."*

**Everything is taller again** - 30px fields, 34px rows, 78px headings, and the
prompt window's text no longer clips its own last line.

### Fixed on the way through

- **The window is deaf while a job is running.** Pumping the dispatcher to move
  the progress bar also pumps Win32 input, so a click could re-enter the tool
  mid-transaction - closing the window during a 40 template Create tore the
  completion callback away and the run finished silently. The window is made
  hit-test-invisible for the duration and every handler that could still be
  reached by the keyboard checks first.
- A `Raise()` that Revit refuses now clears the progress band and re-enables
  Apply instead of leaving both stuck.
- An external event that finds no job now reports back, rather than leaving
  Apply greyed out for the life of the window.
- **Column filters survive adding or removing a column.** They are remembered
  against the parameter, not the column position, so shifting indices cannot
  hand one column's filter to another. A sort on a parameter column is dropped
  when the columns move, since it no longer means anything.
- Repointing a column at a different parameter clears the old search text.
- **Every table flag read off the source template is carried onto the copy.**
  `IsThirdPhaseHidden` was being read but never passed, so it silently reset.
- Argument matching picks the **longest** matching key, with the name as a tie
  break, so two keys of equal length cannot swap places between runs and bind
  the wrong value.

## 1.1.0 - duplication, parameters, and the ways rule

**Create said "skipped" and would not duplicate anything.** Both routes it had
were wrong for the templates in this project, and the message it gave back —
"Revit would not duplicate X" — said nothing about why. There are now four
routes, tried in order, and **each one reports its own actual exception**:

1. `View.Duplicate` — the right answer when a template is a `PanelScheduleView`
   flagged as a template, which is the case this was missing.
2. `ElementTransformUtils.CopyElement`
3. `ElementTransformUtils.CopyElements`
4. `PanelScheduleTemplate.Create` + `SetTableData`, with the schedule type read
   from `GetPanelScheduleType()`, the table data, or the `IsBranchPanelSchedule`
   flags — whichever the element answers to.

If every route still fails, the message now names each one and what Revit said,
which is something that can actually be acted on. The copy is also checked to be
a template afterwards, so it cannot be created and then quietly missing from the
list.

**The duplicate's name carries ways, not slots.** The number in the source name
is replaced with slots ÷ 3, so duplicating "BGL_Schedule One Column 24 Ways
(Update)" at 36 slots gives "BGL_Schedule One Column **12** Ways (Update)". A
name that already exists gets **"New"** on the end, then "New 2" and so on.

**Slot picking is a list, not chips.** Click, shift click for a run, ctrl click
to add or remove — the standard Windows behaviour. Each row shows both numbers,
"36 slots - 12 ways", so there is no arithmetic to do in your head. All / None /
Common (4-16 ways) still work.

**Every parameter on the category is now visible.** The picker used to list only
what the sampled panels happened to report, which missed parameters bound to
Electrical Equipment that a given panel does not surface, and type parameters
that never appear on an instance at all. It now reads the document's parameter
bindings directly and unions that with the elements' own parameters and their
types — so `BGL_Elec_Panel_NoOfWays` and anything like it will be there, in both
Settings and the column pickers.

**Templates filter by schedule type, defaulting to Branch Panel.** The type
combo sits above the configuration combo and drives the template list, the swap
dropdowns and the Duplicator tab. The three type names are normalised to one
spelling however the template reports them — through `IsBranchPanelSchedule`,
through `GetPanelScheduleType()`, or only through its table data — and if
nothing in the project reports the selected type, the filter drops back to all
types and says so rather than showing an empty list.

**Auto Assign runs on a selection or on everything.** Two buttons: *Auto Assign
Selected*, greyed out until rows are picked, and *Auto Assign All*.

**The + rule is no longer a choice.** Ways are added up first, then multiplied
by the phases: `8+8` on 3 phase is `(8 + 8) x 3 = 48`. The option has gone from
Settings.

**Fields are taller and the text is readable** — text boxes and dropdowns are
27px with more padding, table rows 31px, column headings roomier, and the
settings dialog's fields grew to match.

## 1.0.3 - stretch, full screen, readable columns

**The window can be stretched.** It could not before, and the reason is worth
writing down: a `WindowStyle="None"` + `AllowsTransparency="True"` window gets no
hit testing on its transparent frame, so WPF's own resize border never fires
however `ResizeMode` is set. The window now carries eight invisible `Thumb`
strips of its own, 5px around the edge, with the right cursor on each. The grid
holding them has no background, so everything underneath stays clickable.

**A proper full screen button**, sitting beside the close button where the eye
looks for it rather than as a word further along the header. Its glyph — one
square to go full screen, two to come back — is drawn from `Border` elements
rather than set in a symbol font, so it cannot come out as an empty box on a
machine without that font. F11 and a double click on the header still work, and
all three now agree with each other.

**The value columns are readable.** They were pinned to fixed pixel widths, so
stretching the window did nothing for them and anything past the right hand edge
needed a horizontal scroll. Every column is now star sized with its own minimum,
so they share the width and grow with the window:

| Column | Share | Minimum |
| --- | --- | --- |
| Panel | 1.15 | 120 |
| Panel template used | 2.3 | 195 |
| the four parameter columns | 1.25 each | 120 |
| Auto Assign | 1.75 | 150 |

That is 945px of minimums, so nothing scrolls sideways from about a 1200px wide
window upwards. Below that the columns sit at their minimums and a horizontal
scrollbar appears, which is the honest answer at that size.

Also:

- **A splitter between the template list and the table** on both tabs, so the
  balance can be set by hand. Both columns either side are star sized: with one
  of them absolute, the splitter wrote pixels into it and `Grid` never shrinks an
  absolute column, so widening the panel and then shrinking the window pushed the
  table off the right hand edge with no scrollbar to get it back.
- Rows are a little taller (29px) and the table font a half point larger.
- Column headings are roomier, and the parameter picker carries a tooltip with
  the full parameter name, which is usually longer than the column.
- **Every search box now shows what it searches** while it is empty — the theme's
  `TextBox` template gained a placeholder driven by `Tag`.
- Default size is 1440x880, and the minimum is down to 900x560 so it still fits a
  small laptop.
- Dragging a full screen window by its header, or by an edge, now counts as
  leaving full screen. It used to keep the state, so the button lied and the next
  F11 teleported the window back to bounds from before it was ever maximised.

## 1.0.2 - the layout would not parse

**Fixed: the main window died with "An XML comment cannot contain '--'".**

Two of the comment banners in `PanelScheduleTemplateManager.xaml` were drawn
with runs of hyphens:

```xml
<!-- ---------------------- panel assignment -------------- -->
```

XML forbids `--` inside a comment, so `XamlReader.Load` threw and the window
never got built. The banners elsewhere in the file are drawn with `=`, which is
why only those two were wrong, and `PstmSettings.xaml` had none - which is why
the Settings button kept working. This was there in 1.0.0 too; the assembly bug
fixed in 1.0.1 was killing the script one step earlier, so it never got as far
as parsing the layout.

The staged loading added in 1.0.1 is what turned it from a blank window into a
message naming the file, the line and the column.

- Both banners now use `=`.
- **The bench check now parses every `.xaml` as XML**, so a layout that
  `XamlReader` would refuse fails here instead. Verified by putting the exact
  comment back, and by an unclosed tag and a bare `&`.
- It also now checks that a `Style="{DynamicResource K}"` is put on the element
  type `K` actually targets - WPF raises that when the style is applied rather
  than when the layout is parsed, so it surfaces as a dead window too.

## 1.0.1 - the blank white window

**Fixed: the main button opened a blank white pyRevit window.**

`pstm_grid.py` and `pstm_window.py` reached into `System.Windows` without ever
referencing the assembly it lives in, and `pstm_window.py` did it on line 15 -
before any other import had a chance to. pyRevit does not preload WPF into every
engine, so `from System.Windows import FontWeights` threw `ImportError` at module
load, which takes the whole script down before a line of it runs and leaves an
empty output window with no traceback in it.

The Settings button worked only by accident of import order: its chain runs
through `pstm_ui.py`, which happened to reference the assemblies before touching
`System.Windows`.

- New `pstm_clr.py` does every `clr.AddReference` in one place - WPF, Windows
  Forms and the Revit API, each inside its own try/except - and **every module
  now imports it as its first import**, ahead of any `System.*` or `Autodesk.*`
  line.
- **The bench check now enforces that**, which is the part that matters: a
  module that reaches into `System.*` or `Autodesk.*` without importing
  `pstm_clr` first, or that imports it too late in the file, is now a failure.
  Verified by putting the exact bug back and confirming the check catches it.
- Both pushbuttons now **load in stages and say which stage failed** rather than
  leaving a blank window: assemblies, then modules, then reading the project,
  then showing the window. Any failure raises a Revit dialog with the traceback
  and which assemblies could and could not be referenced, and writes the same
  text to `%APPDATA%\RevoBIM\pstm_last_error.txt`.

## 1.0.0 - first release

**Panel Assignment tab**

- Every Electrical Equipment instance in the project in one table, with the
  panel schedule template its panel schedule is using.
- The template list on the left opens on **One Column** and can be pointed at
  any panel configuration, or at all of them.  The list drives what the swap
  dropdown in each row offers.
- Swap a template from the dropdown in the row.  Four more columns can be
  pointed at any parameter the panels carry, instance or type, from the picker
  in the column heading.
- Every heading has its own keyword search box, and every heading except the
  Auto Assign note has an Excel style tick filter behind the caret - everything
  ticked means no filter, unticking narrows.  A search box above the table
  searches across all of them at once.
- **Auto Assign Template** reads the number of ways parameter and the number of
  phases parameter (both chosen in Settings), works out the slot count and
  marries it to the number in a template name.  `12 ways x 3 phase` is a 36 slot
  panel; a ways value with a plus in it, `8+8`, is read as `8 + 8 x 3 = 32`,
  with `(8 + 8) x 3` available as an alternative rule.
- A panel whose calculated size has no template is **highlighted red** for
  review by hand.  A change waiting to be written is **highlighted orange**, a
  panel already on the right template green, and a size with more than one
  candidate template is flagged so the pick gets a look.
- **Nothing is written to the model until Apply.**  Apply shows exactly what it
  is about to do first, then does the lot in one transaction.

**Template Duplicator tab**

- Every template with its schedule type, configuration, slot count and how many
  panels use it, with a tick box to isolate the ones nothing uses.
- Delete templates, or merge several into one - every panel using the merged
  templates moves onto the target and the emptied templates are then deleted.
  The merge asks "Are you sure you know what you are doing you crazy person!"
  before it goes anywhere near the model.
- Duplicate a template into as many fixed slot counts as you tick, offered in
  multiples of three.  The name, panel configuration and single phase setting
  can all be tweaked on the way through, and the slot number is written into the
  name of each copy.  The **Create** button stays grey until at least one slot
  count is ticked, then goes green.

**Throughout**

- Modeless and owned by Revit's main window, so Revit stays fully navigable and
  editable while the manager is open, and the window floats above Revit rather
  than slipping behind it.
- Every write goes out through an `ExternalEvent`, which is what makes a
  modeless window able to change the model at all, and each button's work is one
  transaction so a failure rolls back cleanly.
- Dark and light palettes, switched from the header chip and remembered.
- Settings saved as plain `key=value` text under `%APPDATA%\RevoBIM\`.
- F5 refreshes, F11 or a double click on the header goes full screen, Escape
  leaves full screen.
- `import_check.py` ships beside the tool and every rule in it was verified by
  deliberately breaking it: f-strings, print statements, bare `.IntegerValue`,
  a `System.Uri` import, a `StaticResource` in a layout, a `DynamicResource`
  key `Theme.xaml` does not define, a `FindName` with no matching `x:Name`, a
  mis-namespaced import, a palette key with no brush, a
  `SetResourceReference` to an unknown key, and a missing layout file.

### Decisions worth remembering

- **`Loaded` is a Direct routed event, so it does not bubble.** The swap
  dropdown in each row is populated in its own `Loaded` handler, and the handler
  has to be attached to the `DataTemplate` factory - a handler registered on the
  `DataGrid` is never called for a cell's ComboBox, and the whole column would
  render as empty dropdowns. `SelectionChanged` does bubble, but it is attached
  the same way so the row combos never cross wires with the parameter pickers in
  the column headings.
- **`DialogBoxShowing` is hooked once and toggled with a flag.** Unsubscribing an
  IronPython bound method from a .NET event is not reliable - each attribute
  access makes a fresh delegate - so unhooking per run risked either leaking
  handlers or leaving every Revit dialog answered for the rest of the session.
- **Auto Assign never paints a row red that Apply would still write.** A panel
  the user has already picked a template for keeps that pick and stays orange,
  with the reason appended to the note. Only untouched rows go red.
- **A job on the Duplicator tab keeps the assignments waiting on the other tab.**
  Deleting an unused template used to re-read the model and silently drop them.

### Known limits

- The slot count on a duplicate is pushed through `UpdateCircuitTableForTemplate`,
  whose signature Autodesk has not documented consistently across releases.  The
  arguments are matched to the method's own parameter names at run time rather
  than hardcoded, with straight positional calls as a fallback.  If a release
  ever refuses it, the duplicate is still created and the status bar says the
  slot count could not be set.
- Duplication copies the source element first, which keeps every bit of its
  layout and appearance, and only rebuilds it with `Create` + `SetTableData` if
  Revit refuses the copy.
- A panel with no panel schedule yet gets one created when a template is applied
  to it.
- Merge cannot be undone from inside the tool, only with Revit's own undo.
- Panels in linked models are not listed.
