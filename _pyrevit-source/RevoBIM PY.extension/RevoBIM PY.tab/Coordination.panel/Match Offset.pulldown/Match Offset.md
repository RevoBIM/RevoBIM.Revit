# Match Offset — v1.18.0

A pulldown on the **RevoBIM PY** tab, **Coordination** panel, holding five
buttons: **RevoBIM Match Offset Bottom**, **RevoBIM Match Offset Middle**,
**RevoBIM Match Offset Top**, **RevoBIM Match Offset Slope** and **RevoBIM
Match Offset Settings**. Click the button, click the element whose offset is
right, then click every element that should share it.

## Problem it solves

Setting out a bank is a lot of typing into the properties palette. Read the
offset off the service that is already where it should be, work out what that
means for the next one — which is a different size, so a different centreline
for the same soffit — type it in, repeat. The arithmetic is the bit that goes
wrong: matching soffits on a 100 and a 600 means two centrelines 250mm apart,
and the number that gets typed is usually the one that was just read.

The rule underneath is mechanical. One of the three edges is the datum; every
element after it moves in Z until its own version of that edge is on the
datum. Nothing else about it changes.

## The buttons

**Bottom**, **Middle** and **Top** open **no window at all**. They read the
saved settings and go straight to the picks, and keep going until Escape. Each
is a single command button with a deliberately unique ribbon name, so Revit's
own **Keyboard Shortcuts** dialog can bind keys to it — plain names clash with
other addins and cannot be found in that list. With a shortcut assigned the
whole tool is: keys, click, click.

**Settings** is standalone and modal, two columns so it fits without
scrolling. Set them, press Apply, and they are written to
`%APPDATA%\RevoBIM\match_offset.txt`; every later run uses them. A missing or
damaged file falls back to the defaults key by key, and keys from an older
version are ignored rather than breaking the load.

## The picks

**Click 1 — the element the offset comes from.** Its bottom, middle or top,
depending on which button was pressed, becomes the datum. It is not moved
unless rounding is on, in which case it goes onto the rounded value with
everything else.

**Every click after it** puts that element's own bottom, middle or top on the
datum. It moves in Z and in nothing else.

**Escape finishes.** Escape on the first pick leaves without a word.

The status prompt along the bottom of the Revit window is the only thing the
tool says while it runs: it carries the captured value and, when rounding
moved it, what it rounded to. That is deliberate — a pick-driven tool that
opens a dialog to tell you it worked is a tool you turn off.

## Rounding

`Round the offset to the nearest` is 0 by default, which is no rounding at
all. Above 0, **the first click rounds that element's own offset** and every
element after it is matched to the rounded value, not to the element's real
one. So clicking a pipe sitting at 2437 with a 25mm step sets the datum to
2450, and the whole bank lands on 2450.

**The first element goes onto the rounded value too.** It is rounded on
whichever edge the button asked for - bottom, middle or top - and moved onto
it before anything else is clicked, so the element the number came off sits
on the same value as everything that follows it. Leaving it behind was the
v1.0.0 behaviour and it put a bank one element out. There is a tick for it,
on by default, and it does nothing at all when rounding is off, because then
there is nothing to move it to. A source that cannot move - in a group, owned
by somebody else - is reported, and the datum still stands for everything
after it.

Three choices go with it:

| Setting | What it means |
| --- | --- |
| Round | up to the next (default), to the nearest, or down to the last |
| Round against | the offset from its level (default), or the project elevation |
| Move the first element onto the rounded value too | on |

**"Up" means towards plus infinity**, so an element below its level rounds
towards the level rather than away from it.

**The datum choice matters and is not cosmetic.** Revit's Offset is measured
from the element's own level, which is the number in the properties palette,
so that is what "round to 25" should act on. The project elevation option is
for a bank crossing two levels that has to land on one absolute grid.

## What is measured

| Element | Bottom and top come from |
| --- | --- |
| Pipes, ducts, trays, conduits | the centreline, plus half the size parameter |
| Fabrication ductwork, pipework, containment | their own **Top and Bottom of Part** |
| Fabrication hangers | the **face they bear on** — all three anchors |
| Equipment, fixtures, terminals, devices | their real **solid faces**; Middle is the offset from level |
| Anything else | its bounding box |

Size parameters rather than the bounding box, because the box takes in
insulation, lining and anything the family draws past the duct, and a
setting-out offset means the bare service. Insulation can be counted back in
from a tick. Where a category has no size parameter the box stands in, and the
run says which route it took.

**Equipment, fixtures and terminals are measured from their real solid
faces.** A bounding box takes in connectors, symbolic lines, insulation and
anything else Revit calls geometry — an air terminal's reaches out to its neck
and its flange, a piece of plant's to its base and its pipe stubs — so a
"bottom" off a box matches nothing in the properties palette. The solids are
the thing itself. **Middle stays the family's own offset from level**, read off
its insertion point rather than out of a parameter, because which parameter
holds it depends on how the family is hosted and the point is the same thing
either way.

So the three buttons give three answers: the real bottom face, the real top
face, and the datum the family was placed at. **Equipment, fixtures and
terminals measured from** in Settings offers *their offset from level* instead,
which makes all three that one number, or the raw bounding box.

Fittings, accessories, insulation, generic models and the structural categories
are deliberately not in that set: a fitting travels with its run and a generic
model is usually a hole, and for both the extent is what matters.

**MEP ancillary framing** - support strut, channel and trapeze bars - is under
*Fabrication and supports*, ticked by default, and measured like a hanger: one
height, the **top face the service sits on**, so Match Offset Bottom from a
duct puts the strut flush under it. Strut is drawn along a line at its centre,
so it is measured before anything that reads a centreline. A setting offers
its real faces or its box instead. It is a Revit 2024+ category; on an older Revit its row
is not offered.

**Fabrication parts are measured from their own Top and Bottom of Part** — the
numbers the shop and the installer work to. Those are measured from the part's
*level*, not from the project base, so both readings are compared against the
part's own solids and the one that agrees within 50mm wins; where neither does,
the solids answer and the report says so.

**A fabrication hanger is one height: the face it bears on.** Match a duct's
bottom onto a hanger and the bearer lands under the duct, which is the whole
reason anybody aligns a hanger to anything, so all three anchors are that face.
The top of a hanger's geometry is the top of its *rods*, up at the soffit,
where nothing sits.

Finding the bearer: the hanger is taken **one solid at a time**. A piece taller
than it is wide is a rod, a drop or a clamp; a piece wider than it is tall is a
bearer. The rods are thrown away, what is left at the **foot of the rods** is
the bearer — anything up at the structure is an anchor — and the face the
services sit on is the **highest real face** of it. A channel's *biggest*
upward face is the inside of its back, a good 40mm below the flanges the duct
actually rests on, which is why the biggest face is not the answer. Where a
family is drawn as one lump with nothing to tell apart, the largest upward face
is the fallback, as it was before.

So **Match Offset Bottom, click the duct, click the hanger** puts the top of
the hanger's bearer at the duct's bottom, which is the move. The same for a
pipe, a tray or a piece of plant.

**Across levels.** Everything is worked in project elevations, so a fan coil
on Level 01 matched to a duct on Level 02 lands with its bottom on the duct's
bottom, whatever the two levels are. The family is then written through its
own parameter rather than moved: **Elevation from Level** for a family on a
level, worked out against its own level; **Offset from Host** for a family on
a face or work plane, which Revit will not move off its host - written one way,
checked, and turned round if the host faces down, as a ceiling does. Only
where neither will take it is the family moved by hand. When the two ends are
on different levels the run notes what the family's offset came out at
against its own level.

**The rods are re-cut to suit.** A hanger hangs from the soffit: the top stays
and the bottom goes with the hanger, so dropping it 150mm makes its rods 150mm
longer. Rods Revit is hosting it re-solves itself and the run says so; rods set
to manual are re-cut here. A hanger raised further than its own rods are long
has nothing left to hang from — that rod is left alone and reported, rather
than written a zero or a negative length nobody would see. **Re-cut hanger rods
so their tops stay put** in Settings turns it off.

The whole tool works in **absolute project elevation** internally and converts
back at the write, so matching a pipe on Level 2 to one on Level 1 does the
right thing rather than copying a number that means something different on
each.

## How the write is done

Two routes, in this order:

1. **The offset parameter**, given the *delta* rather than the value. It is
   measured from the element's own level, so adding a delta needs no level
   elevation to be known and keeps every connection intact.
2. **`ElementTransformUtils.MoveElement`** in Z, for anything with no offset
   parameter — a fitting, a piece of equipment, a light.

Then the element is **measured again and the answer checked**. A void API call
is not evidence and Revit does not reliably raise when a write does not take.

Elements are borrowed with `WorksharingUtils.CheckoutElements` before the
transaction starts. Pinned elements are unpinned for the move and pinned again
after.

## Keyboard shortcuts

The settings window carries the three key sequences and a button that writes
them.

| Command | Suggested |
| --- | --- |
| RevoBIM Match Offset Bottom | **AB** |
| RevoBIM Match Offset Middle | **AQ** |
| RevoBIM Match Offset Top | **AT** |
| RevoBIM Match Offset Slope | **AS** |

All four are editable. **Apply these shortcuts** reads Revit's own file,
lists anything already holding one of the keys, and asks before taking it
away — *Remap to Match Offset* / *Leave them alone* / *Cancel*. The old file
is copied to `%APPDATA%\RevoBIM\` first.

Three things about that file decide the design, and all three are said in the
window rather than hoped about:

- **There is no Revit API for keyboard shortcuts.** The only route is
  `%APPDATA%\Autodesk\Revit\Autodesk Revit <year>\KeyboardShortcuts.xml`.
- **Revit reads it at startup**, so a shortcut written now takes effect next
  session.
- **Revit rewrites the whole file from memory when its own Keyboard Shortcuts
  dialog is OK'd.** Opening that dialog and pressing OK after this tool has
  written, but before restarting, throws the change away.

Where Revit has no entry for one of our buttons yet — it only lists an addin
command once it has enumerated the ribbon — one is written from the ribbon
path and flagged as unverified, with the reliable fix named: open Revit's own
dialog once, press OK, and apply again.

## Settings

| Setting | Default |
| --- | --- |
| Round the offset to the nearest | 0 mm (off) |
| Round | up to the next |
| Round against | the offset from its level |
| Move the first element onto the rounded value too | on |
| Top and bottom come from | the size parameters |
| Equipment, fixtures and terminals measured from | their real faces |
| Fabrication parts measured from | top and bottom of part |
| Fabrication hangers measured from | the face they bear on |
| Re-cut hanger rods so their tops stay put | on |
| Count insulation as part of the size | off |
| Sloping runs | are reported and left alone |
| Counts as level up to | 0.5 degrees |
| Connected fittings | are left for their pipes to move |
| Apply to anything already selected | off |
| Remember the datum between runs | off |
| Show results | only if something needs a look |
| What can be picked | every standard MEP category; structure and architecture off |
| Theme | Auto (follows Revit's canvas) |
| Show a debug report after every run | on |
| Suppress every message | off |
| Shortcuts | AB / AQ / AT / AS |

## Refusals

## What can be picked

Forty-six categories under six headings — Pipework, Ductwork, Electrical, Fire
and safety, Equipment and fixtures, Structure and architecture. Everything in
the first five is ticked to begin with; **structure and architecture is not**.
A services bank is often set out against a beam or a column, but a tool that
moves one because somebody clicked it is worse than a tool that needs a box
ticked first.

The keyword box searches the group names as well as the category names, and a
heading whose whole group has been filtered away is hidden with it. A category
a release does not have is skipped rather than taking the tool down, which is
what lets one list cover Revit 2024 through 2027 — Fire Protection, Audio
Visual Devices and Plumbing Equipment all arrived at different releases.

Match Offset Slope works on pipes only, whatever is ticked here.

## Refusals

Reported rather than attempted: an element in a Revit **group**, an element
owned by another user (both locks are asked about — a clean checkout status
still means nothing on a workset somebody else owns), a **connected fitting**
(move the pipes and the fitting follows), an element with no geometry to
measure, a **sloping run**, and a write that will not read back.

An element already on the datum is a note, not a problem, so it does not open
the window.

## Decisions worth remembering

- **One transaction per element, not one for the run.** The picks sit between
  the writes, a transaction cannot be held open across a pick, and a
  `TransactionGroup` held open across Revit's message loop is a hard crash.
  The cost is that each element is its own undo step, which the results window
  says rather than leaving to be discovered.
- **The offset parameter is given a delta, not a value.** It is relative to
  the element's own level, so a delta needs no level elevation and works
  across levels for free. The bench proves this specifically: a breakage that
  writes the value instead of the delta fails nine checks.
- **Absolute project elevation internally.** Two elements on different levels
  with the same Offset are not at the same height, and a tool that copies the
  number rather than the height gets that wrong quietly.
- **`ProjectElevation`, never `Level.Elevation`.** On a survey-point-based
  project the latter reports shared coordinates and comes back tens of metres
  out.
- **Moving a hanger is not finished when the hanger has moved.** It hangs from
  the soffit, so its rods have to change length to suit or their tops come away
  from the structure — and the result looks correct in plan and in a section
  until somebody looks at the rods.
- **A hanger has one useful height, and it is not the top of it.** The top of
  its geometry is the top of its rods, up at the soffit, where nothing ever
  sits. What services sit on is the top face of its bearer, and the way to find
  that without knowing the family is the largest horizontal face pointing up —
  a rod end is a few hundred square millimetres against tens of thousands.
- **Top and Bottom of Part are measured from the part's level, not from the
  project base** — but not on every release and not for every service template.
  A level offset read as a project elevation is out by the height of the level
  and still looks like a perfectly good number, so both readings are checked
  against the part's own solids and the one that agrees wins. Measure, do not
  reason.
- **Solids, not the bounding box.** A box takes in connectors, symbolic lines,
  insulation and anything else Revit calls geometry. And a solid's bounding box
  comes back in the solid's own frame with a transform beside it: taking Min.Z
  and Max.Z straight off it is right only when that transform happens to be the
  identity, which is exactly the sort of thing that is true in the test model
  and false on site.
- **A family's position is one number, not three.** What a terminal or a piece
  of plant sits at is its offset from level, so Bottom, Middle and Top all mean
  the same thing for it — and the bounding box, which is what "bottom" would
  otherwise mean, takes in flanges, bases and stubs and corresponds to nothing
  visible. Read it off the insertion point rather than out of a parameter:
  which parameter holds it depends on how the family is hosted, and the point
  is the same thing whichever one that is.
- **The size parameters, not the bounding box.** The box takes in insulation
  and anything the family draws beyond the service. The box is the fallback,
  and the route taken is reported.
- **The status prompt is the whole user interface during a run.** It carries
  the captured value and says when rounding moved it, which is what makes a
  windowless tool honest about what it is about to do.
- **Rounding happens once, at capture.** Rounding each target as it is picked
  would put a bank on several different values, which is the opposite of what
  the tool is for. The corollary, learned the obvious way: if the datum is
  rounded, the element it was read off has to move onto it as well, or the
  bank is one element out and the odd one out is the one that looked right.
- **The settings are resolved once, before the first pick.** Every value in
  the settings file is a string; parsing them again per click produces the
  same answer it did the click before. `RunConfig` is built once and the per
  element functions only read attributes off it. A bench rule fails if
  anything that runs per element calls `parse_number` or `is_on`.
- **`AllowElement` is the hot path in the whole tool**, not the writing. It
  runs on every element the cursor crosses, so it is one attribute chain
  against a `frozenset` of ints - no name lookups, no set building, no
  formatting. `eid_value` works out once whether this release has `.Value` or
  `.IntegerValue` and then it is a single attribute read.
- **Late enum lookup is not the same as repeated enum lookup.**
  `BuiltInParameter` members are still resolved by name inside a function, so
  a member a release lacks cannot kill the module at import - but they are
  resolved on first use and kept, rather than looked up five or six times per
  element.
- **The log is buffered and written in a `finally`.** Opening, writing and
  closing the file per element is more work than the matching. Buffering is
  only safe because the flush is in a `finally`, which is its own bench rule.
- **Worksharing is only asked about on a workshared model**, and a
  pre-selection is borrowed in one call rather than one per element -
  `CheckoutElements` is a round trip to central.
- **Sloping runs belong to Drainage Elevation Match.** Match Offset works to
  one elevation; a falling run has no single offset to match. It is refused by
  name and the other tool is pointed at, rather than being half-handled.
- **A connected fitting is not moved on its own** by default. Moving the pipes
  drags the fitting; moving the fitting on its own stretches or breaks the
  joint.
- **The category id map is built once.** `ISelectionFilter.AllowElement` runs
  on every element the cursor crosses, so it must not be doing name lookups.
- **No modeless window means no `__persistentengine__`**, and none of the
  engine-teardown problems that come with it.
- **Nothing to do with the easter egg is shipped.** `startup.py`, the hooks
  and `lib\revobim\egg` are the extension's, shared and singular; the tool
  only asks the egg that is already installed to watch its logo, inside a
  try/except. `import_check.py` fails if the delivery contains one of those
  files.
- **`<ShortcutItem ... />` cannot be matched with `[^>]*?`.** Revit writes the
  ribbon path as `Paths="a&gt;b"`, but a raw `>` inside an attribute ends the
  match early and the entry silently does not exist as far as the parser is
  concerned — which is exactly what it did until the bench caught it.

## Folder layout

```
Coordination.panel\
  Match Offset.pulldown\
    bundle.yaml  icon.png  logo.png  CHANGELOG.md
    mo_clr.py             every clr.AddReference, imported first by everything
    mo_core.py            version, settings, logging, all the pure maths
    mo_model.py           the selection filter, measuring and writing
    mo_run.py             the pick loop and its transactions
    mo_shortcuts.py       Revit's KeyboardShortcuts.xml, read and rewritten
    mo_theme.py           the dark and light palettes
    mo_ui.py              XAML loading, chrome, resize grips, the egg hook
    mo_debug.py           the debug report, with no Revit in it
    mo_launch.py          staged loading, reporting which stage failed
    mos_geom.py           the slope geometry, with no Revit in it
    mos_model.py          the run walk, the transforms and the fittings
    mos_run.py            the slope command
    settings_window.py    the settings dialog
    results_window.py     the themed report
    debug_window.py       the debug report window, with Copy
    Theme.xaml            every brush and control template
    MatchOffsetSettings.xaml  MatchOffsetResults.xaml
    MatchOffsetMessage.xaml   MatchOffsetDebug.xaml
    import_check.py       31 static rules, proved by --selftest
    bench_logic.py        468 logic checks, proved by --selftest
    Match Offset Bottom.pushbutton\    script.py  bundle.yaml  icon.png
    Match Offset Middle.pushbutton\    script.py  bundle.yaml  icon.png
    Match Offset Top.pushbutton\       script.py  bundle.yaml  icon.png
    Match Offset Slope.pushbutton\     script.py  bundle.yaml  icon.png
    Match Offset Settings.pushbutton\  script.py  bundle.yaml  icon.png
```

The shared modules sit **inside the pulldown folder**, not in `lib\revobim`,
and each button adds its parent folder to `sys.path` — same as Drainage
Elevation Match, Smart Dimensions and Drawing Register, and for the same
reason. **No `Coordination.panel\bundle.yaml` is shipped**, because that panel
already exists and shipping one would revert its title.

## Bench checks

Both run under plain CPython from the pulldown folder.

`import_check.py` — **31 rules**, every one proved by deliberate breakage:
every `.xaml` parses as XML; no `--` inside an XML comment; no
`StaticResource` in a layout; every `DynamicResource` and
`SetResourceReference` key exists in `Theme.xaml`; no style applied to an
element its `TargetType` rejects; every `FindName` has an `x:Name`, including
the aliased `self.find(...)` form; both palettes carry the same keys; no
f-strings, no `print`, no bare `.IntegerValue`, no `System.Uri`, no non-ASCII;
`mo_clr` imported before any `System.*` or `Autodesk.*` name; every namespace
has its assembly in `mo_clr`'s list; no `AddReference` for RevitAPI or
RevitAPIUI; every .NET name from the namespace the real API puts it in; no
duplicate top-level definitions; every global a function reaches for exists
(`symtable`); call arity; cross-module names resolve; `script.py` stays a thin
loader; ribbon names unique, prefixed and single line and matching their
folder; no shared extension file shipped; settings split on the first `=`
only; `code_only` preserves token spacing; the settings are resolved once
rather than per element; the log is flushed in a `finally`; the geometry module
has no Revit in it; no wrapped text in a horizontal StackPanel; every
module loads against a stub Revit and .NET API.

`bench_logic.py` — **820 checks** against a stub Revit API, running the real
functions: the rounding rule in every mode including negatives and float
noise, anchors and slopes, capture on both datums, the settings round trip
including a value containing `=` and a damaged file, prompts, the notes /
problems split, measuring pipes and point-placed families with and without
insulation, the two write routes, capture-then-apply end to end across three
sizes, the source landing on the rounded value on all three anchors, the
refusals `apply_to` makes and whether each is a note or a problem, the
resolved config, the buffered log, the whole of the shortcut file handling
including a real write with its backup, and the whole of the slope geometry -
the crossing in plan, the classification of both pipes, the target gradient in
every combination, the tilt against the gradient it was asked for, the stretch,
and three complete junctions worked end to end.

`--selftest` on `bench_logic.py` breaks thirty-seven things on purpose — rounding
always to nearest, the anchors swapped, half height doubled, settings split on
every `=`, conflicts never found, keys not normalised, the chip not cycling,
`shift` writing the value instead of the delta, a note opening the results
window, the source left behind when rounding, the log never flushing, the tilt
applied the wrong way round, the crossing height taken at the main's mid point,
the branch falling away from the junction, an apparent crossing ignoring a
joined main end, Revit failures deleted and forgotten, a refused junction
reporting the angle and nothing else, a debug report with no settings in it,
moving a pipe end reversing its curve, the routing rule groups asked for in the
singular, a square tee forced onto an angled junction, the bend put off the
branch centreline, only one way round the junction being tried, and the way
round chosen without reference to the direction of flow, and an in-line fall
not reversed for a run facing the other way — and confirms the checks notice
each one.

---

# Match Offset Slope

The fourth command in the pulldown, and a different job from the other three:
those put an element at a height, this puts a whole run on a **fall** and lands
it on another pipe. It is for connecting an existing drainage run into a main.

## Problem it solves

The manual version is done in a section: align the branch to the main so it
picks up the main's elevation and slope, then Trim/Extend the two together and
let Revit place the fitting. It is a handful of moves per junction, done dozens
of times a floor, and a few millimetres out shows up later as a fitting that
will not place.

The rule underneath is simple enough to automate. The branch belongs on the
main's centreline at the point the two centrelines cross **in plan**, at the
main's own fall. The rest of the horizontal run has to come with it, and the
uprights have to stay put and stretch.

## The two clicks

**Click 1 — the MAIN.** Its centreline and its gradient are the datum. It is
not moved unless the crossing falls past the end of it.

**Click 2 — the pipe to bring into it.** Click any pipe along the run.

Then it asks for a main again, so a run of separate joints is click, click,
click, click until Escape. The status prompt carries the main's fall and the
running count — `3 joined - pick the MAIN...` — which is the only feedback
there is during a run: a count that has not moved says the last pair did not go
in. It asks again whether the pair went in or not, because quietly carrying on
with a main the user has stopped thinking about is worse than asking.

**After each connection** in Settings switches this to *keep the same main*,
which is the one to use for a manifold where several branches go into the same
run.

Escape on the first pick leaves without a word. Escape later finishes.

## What moves, and what stretches

The run is walked through its connectors, and **the walk stops at any pipe
pitched more than 46 degrees** up or down. Anything past an upright is not
walked at all, so the floor above is never disturbed. Fittings are never
classed as uprights, so the bend between a run and its stack travels with the
run and the stack stretches up to meet it.

**The horizontal part moves as one rigid body**, in three steps that never
disturb a connection:

1. **Tilt** onto the target fall, about the end that meets the main.
2. **Stretch** that end pipe along its own axis to the crossing point.
3. **Raise or lower** the whole run so that end lands on the main's centreline.

**Uprights hold position and stretch.** Each boundary upright is let go before
the move, then re-cut so the end that met the run lands on its new position
while its other end stays exactly where it was, and reconnected. An upright is
never allowed to block the move; one that genuinely cannot follow is reported
and left loose, and the run still connects.

## The junction

**Inside the main** — the main is split at the crossing with
`PlumbingUtils.BreakCurve` and a **tee** from the routing preferences goes
across the three connectors.

Where Revit refuses that — and it refuses the moment the branch is not square
to the run — the junction family is **placed by hand and turned onto the three
pipes**, which is what Revit's own Trim/Extend does. Every junction family the
pipe type routes to is tried in turn; each is **sized from the three pipes
before anything else**, because a bigger fitting is a longer one; the way round
is chosen so the arm sweeps **with the flow**, and the angle tested against
that way round; only then is the family's angle parameter driven to suit; the
fitting is checked after it is turned and again after it is joined, and rolled
back and retried the other way round if it is more than a few degrees off; the fitting is registered on where its own axes cross rather
than on its insertion point, because a lateral's branch meets its run part way
along the body; and the three pipes are cut back to the fitting's own ends and
joined. All of it in a sub-transaction that rolls back unless all three ends
connect, so a family that does not suit the angle costs nothing and the next
one is tried.

Where the pipe type carries only a plain 90 degree tee — which is the usual
case — neither of those can help, and the branch is **squared in**: a square
tee goes into the main, a short stub runs square out of it, and a bend turns
the branch into the stub. The tee slides along the main by exactly enough that
the stub, taken square to the main in three dimensions, lands on the branch's
**own centreline**, so the run that was just put on the main's fall does not
have to move again. Every fitting is placed by Revit's own calls, so the
families come from the routing preferences and the pipes are trimmed the way
Revit trims them. The stub is three diameters with a 150mm floor, or whatever
is typed into Settings.

Failing all of that, a **takeoff** on the uncut main.

**At the end of the main** — the move has already brought both pipes to the
crossing, which is exactly the state Trim/Extend leaves behind before it
inserts the fitting. The connectors are freed and an **elbow** goes in. Where
the two runs turn out to be in line, a **union** goes in instead.

**On the same line as the main** — two runs meant to be one run never cross,
so there is no crossing to work to. The point is the main's **own free end**
and the fall is the main's **carried on through it**, which is not the same as
the falls-towards-the-junction rule: a run pointing back along the main takes
the opposite sign for the same physical fall. The second run is put on that
fall, brought to that elevation, extended or trimmed to the end, nudged
sideways onto the line if it is a few millimetres off, and joined with a
**union**. Beyond 50mm off the line (a setting) the two are refused as side by
side rather than joined.

**Past the end of the main** — the apparent intersection. Where that end of the
main has nothing joined to it, the main is carried out to the crossing, the
branch is raised to the height the main's own fall would reach there, and a
bend turns the two into each other. Where the end is already joined there is
nowhere to extend it to, and it is refused by name.

Two things that quietly break `NewTeeFitting` are handled: the two halves of
the split main are **explicitly disconnected** first — some releases leave them
joined after the break, and a tee will not take connectors that are already
connected — and the halves are **retried in the other order**, which is not
always interchangeable.

When Revit still refuses, the report says **why it is likely refusing**: the
angle the branch meets the main at, and the junction and elbow families the
main's pipe type actually offers, read out of its `RoutingPreferenceManager`.
Both pipes are left touching, so Trim/Extend finishes it by hand in two clicks.

The split and the tee sit in a **sub-transaction**, so a refused tee never
leaves the main cut in half, and a refused fitting never costs the move.

## Settings

| Setting | Default |
| --- | --- |
| Change the slope of the branch's horizontal run to match Pipe 1 | on |
| Take the fall from | the main's own fall (or a fixed 1 in N) |
| Fixed fall, 1 in | 80 |
| The branch falls | towards the junction |
| Extend or trim the branch into the main | on |
| Junction | tee or bend to suit (or bring the ends together only) |
| After each connection | ask for a new main |
| Join two runs that are on the same line | on |
| Counts as the same line within | 50mm |
| Place the junction family by hand if Revit refuses | on |
| Square an angled branch in with a stub and a bend | on |
| Stub length | 0 — three diameters, with a 150mm floor |
| Allow an apparent intersection past the end of the main | on |
| Carry the main out to it and turn in with a bend | on |
| Counts as an upright above | 46 degrees |
| Refuse a run longer than | 400 elements |

Clearing the slope tick is not the same as turning the tool off: the branch
keeps its own fall and only its **height** is matched, at the crossing point.

## Refusals, slope

Reported rather than attempted: the two pipes **parallel in plan and not on
the same line**, so they never cross; two runs **side by side** — nearly on the
same line but too far apart in plan to be joined end to end; a **vertical** main or branch; the branch **pointing away** from
the main, so the crossing is behind its own run; an **upright** clicked as the
branch, with its pitch and a note to click the pipe the stack comes off; a
non-straight segment; the main clicked twice; a run reaching into a Revit
**group**; a run reaching more than 400 elements; and an apparent crossing
where the main's end is already joined.

## Decisions worth remembering

- **The datum is the crossing point of the two centrelines in plan**, not the
  main's mid point or either endpoint. That is what makes it right on a
  sloping main, and a breakage that takes the height at the mid point instead
  fails eleven bench checks.
- **Centreline to centreline**, chosen over invert matching: the branch lands
  on the main's centreline and the fitting resolves the size difference. A
  Revit fitting joins centrelines, so matching inverts and then asking for a
  tee cannot both happen.
- **Rigid transforms, not curve edits.** `RotateElements` and `MoveElements`
  keep connectors joined; rewriting `LocationCurve` on one pipe of a connected
  run does not, and leaves the rest of the run behind. The only curves
  rewritten are the end pipe's free end, which is what trim and extend does
  anyway, and the uprights, which are disconnected first on purpose.
- **Tilting shortens a run in plan.** The 3D length is kept, so the far end
  creeps towards the junction by the cosine of the tilt - under two tenths of
  a millimetre at 1 in 80 over 30 feet. It is why the uprights are re-cut to
  the run's *new* joint position rather than assumed to still reach it.
- **The tilt sign is the thing to get wrong.** The axis is z cross v, where v
  is the run's plan direction towards the junction; rotating v about that axis
  by a positive angle takes it **downwards**, so the angle is
  `atan(now) - atan(target)` and not the other way round. Two of the cross
  product terms in the rotation shipped backwards during the build, which is a
  rotation by minus the angle - still a tilt, just the wrong one, and nothing
  about reading it would have found it. The bench checks the *result* against
  the gradient that was asked for.
- **There is no trim/extend API.** `PostCommand` can only launch Revit's
  command; it cannot be given the two elements. Bringing the ends together,
  freeing the connectors and inserting the routing preference fitting is the
  only way to automate it, and is what the tool does.
- **A held connector is not a connector.** Re-fetching one is not a substitute
  for regenerating, and a handle kept across `doc.Regenerate()` fails silently
  rather than raising. Every connector is stored as its owner's id and its own
  id, and found again after each regenerate.
- **And an id is not a connector either, once a curve has been rewritten.**
  Rewriting a `LocationCurve` can renumber an element's connectors, so the id
  taken before the move does not reliably name the same connector after it.
  The branch's connector is found by **where it is** - at the crossing - which
  is how the main's two halves were already being found.
- **A pipe's connectors are bound to the ends of its curve by index.**
  Writing `Line.CreateBound(the end that stays, the end that moves)` reverses
  the curve whenever the end staying put was index 1, which swaps which
  connector is which; Revit disconnects whatever was joined to it and the run
  comes apart at the fitting, with the geometry looking almost right. Every
  curve rewrite goes through `restretch`, which works out which index is
  staying and writes the new curve in that order.
- **A fitting keeps its connectors somewhere else from a pipe.** A pipe is an
  `MEPCurve` and carries `ConnectorManager` on the element; a fitting is a
  `FamilyInstance` and keeps its manager on `MEPModel`. Asking only for the
  first gives every fitting zero connectors — which reads as a family with no
  connectors when one is being placed, and, far more quietly, **stops a run
  walk dead at the first bend**. That one sat there from the first version and
  was only found because placing a family by hand needed the same call.
- **`NewTeeFitting` only ever places a square tee.** "Fitting cannot be created
  between the input connectors because the angle between them is too small or
  too large" is Revit saying the branch is not perpendicular, and it rules out
  every swept junction and every 45 degree drainage branch. Revit's own
  Trim/Extend does not use that call; it places the routing preference family
  and turns it. Anything that wants to match Trim/Extend has to do the same.
- **A junction's three connector directions do not say which way round it
  goes.** Its arm sits at some angle to one run connector and at 180 minus that
  to the other, and the junction needs the one angle going one way round the
  main and the other going the other — so both ways round satisfy every angle
  check there is. `BreakCurve` does not say which half it hands back either.
  Half the time, the way that satisfies the angles is the junction facing back
  up the flow: correctly sized, joined on all three ends, and wrong.
- **Two pipes on the same line are parallel, and that is the one kind of
  parallel worth doing something about.** They never cross, so there is no
  crossing point; the point to work to is the main's own end. And the fall to
  work to is the main's carried on through that end, not the
  falls-towards-the-junction rule — a run pointing back along the main takes
  the opposite sign for the same physical fall, and getting it wrong puts the
  two into a shallow V instead of one line.
- **A swept junction's arm leans back towards where the water comes from**, so
  the run connector making the acute angle with the arm belongs on the upstream
  half — and upstream is the higher end, because drainage falls. That is the
  question the angles cannot answer and it has to be asked separately.
- **Drive a family's angle parameter only after the way round is fixed.**
  Driving it to suit a guessed way round turns a family that fits exactly into
  a refusal, and does it only sometimes, which is worse than always.
- **`NewFamilyInstance` places a fitting at its default size and leaves it
  there.** `NewTeeFitting` sizes the fitting from the pipes it is given;
  placing the family by hand does not, so the junction comes out correct in
  every way except that it is the wrong size — which is worse than failing,
  because it looks finished. `Connector.Radius` has a setter on a family
  instance's connector and drives the family's own size parameters, so it is
  the one call that does it rather than guessing at parameter names. Size
  first: a bigger fitting is a longer one, and every position read before the
  resize is wrong afterwards.
- **A lateral's branch axis meets its run axis part way along the body**, not
  at the family's insertion point. Registering the fitting on its insertion
  point puts the junction in the wrong place by half a fitting; registering it
  on where its own two axes cross puts it exactly where the centrelines meet.
- **Placing a fitting is only half of trim and extend.** The pipes still have
  to be cut back to the fitting's own connector positions, which is what
  `NewTeeFitting` does for you and `NewFamilyInstance` does not.
- **`RoutingPreferenceRuleGroupType` spells its members in the plural** -
  `Junctions`, `Elbows`, `Crosses`. Asking for the singular throws
  `'type' object has no attribute 'Junction'`, and a read that swallows that
  reports "no junction family at all" about a pipe type that has plenty. Where
  no spelling resolves, the report now lists what the enum actually offers.
- **Do not break a pipe in half for a fitting that cannot be placed.** The
  pipe type's junction rule count is asked for before the split, not after the
  refusal - a break and a rollback costs two regenerates and makes Revit
  complain about connectivity on the way through for nothing.
- **The geometry module has no Revit in it**, which is its own bench rule. It
  is why 150 of the checks can run the actual decision - crossing, tilt,
  stretch, landing - rather than a restatement of it.
- **One transaction per branch**, for the same reason as the other three
  commands: the picks sit between the writes.

## Open items for a future version, slope

- A run that turns in plan is tilted as one body, so a leg running across the
  tilt axis picks up a small cross-fall. Straight runs are unaffected.
- An upright is stretched straight to the run's new joint position. Where the
  run also shifts in plan from the tilt, that leaves it a fraction off plumb
  rather than re-cutting it vertical.
- Invert matching as an alternative datum, for junctions where the two pipes
  are very different diameters. It cannot coexist with an automatic fitting.
- Batch mode: pre-select several runs, click the main once, match them all.
- If the tee keeps falling back to a takeoff, the next step is placing the
  routing-preference tee family by hand - `doc.Create.NewFamilyInstance` plus
  orientation and three `ConnectTo` calls - rather than relying on
  `NewTeeFitting`.
- The branch's own downstream run past the first upright is never touched, by
  design. A change of fall that should carry through two floors has to be run
  twice.

---

# The debug report

On by default, under **Settings > Picking and shortcuts > Diagnostics**. After
every run of either tool a window opens with the whole run in it and a **Copy**
button. It is also written to `%APPDATA%\RevoBIM\match_offset_debug.txt`
whether the window is opened or not.

**Suppress every message** holds all of it back, along with the results
window — a run finishes with nothing on screen whatever the other two settings
say. The report is still written to disk, because suppressing a message and
throwing the record away are different things; and a failure to *start* still
reports itself, because a tool that dies silently is indistinguishable from a
broken button.

What it carries: the version and the Revit build, the document, every setting
with the changed ones marked, and then per pick the numbers the decision was
taken from - the main's gradient, both parameters along the crossing, the
crossing point in millimetres, the case each pipe was classified as, the tilt
in radians, the plan angle and how far off the main's line it is, the landing
before the lift and the lift itself - followed by **Revit's own description of
anything it refused**.

**Hangers write their own geometry out**, for the first two in a run: one line
per solid with its height, its span and its footprint and whether it was read
as a rod or a bearer, and one line per upward face with its area and its
height. Every rule for finding a bearer is a guess about how somebody drew a
hanger; this is the evidence for the next one, so a hanger that measures wrong
can be read rather than guessed at.

## Decisions worth remembering

- **"Revit did not commit the move" is not a diagnosis.** Everything needed to
  explain it was known at the time and thrown away. A run that can be posted
  as one block is worth more than a message that reads well.
- **Deleting warnings is only half of failure handling.** An error the
  preprocessor does not resolve is still an error at commit, and Revit answers
  that by rolling the transaction back and returning `RolledBack` from
  `Commit()`. The preprocessor now resolves what it can and records
  everything, and `ProceedWithCommit` is returned only when something was
  actually resolved.
- **A sub-transaction does not protect the transaction around it.** The
  fitting sat in one and the move still went with it, because the rollback was
  Revit's and it took the outer transaction. Two real transactions in a
  `TransactionGroup` is what actually separates them.
- **A horizontal StackPanel measures its children with infinite width**, so
  text inside one never wraps however `TextWrapping` is set. The layout looks
  right until a message is long enough to matter - and the messages long
  enough to matter are the ones explaining why something failed.

---

# Match Offset - open items for a future version

- Sloped runs are refused rather than matched at the picked point. The setting
  and the code path exist; what has not been decided is whether matching a
  falling run at one point and dragging the rest with it is ever the right
  answer, or whether it always belongs to Drainage Elevation Match.
- Matching **invert** rather than the outside bottom, for drainage where the
  wall thickness matters.
- A horizontal equivalent — matching a setting-out line in plan rather than an
  elevation.
- No live preview. The move happens on the click, and the only way back is
  undo, one element at a time.
- The verification measure after each write is a second read of the element's
  geometry. It is cheap on an MEP curve and not free on a family instance, but
  a void API call is not evidence and there is no cheaper way to know.
- The remembered datum is stored as a raw internal-feet value, so a datum
  remembered in one project and used in another means nothing. It is keyed to
  the anchor but not to the document.
- Revit's shortcut file is rewritten in place. There is no way to ask Revit to
  reload it, so the restart is unavoidable until Autodesk exposes an API.
