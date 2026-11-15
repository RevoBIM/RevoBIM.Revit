# Family Find & Replace — v1.7.0

A single pushbutton on the **RevoBIM PY** tab, **Management** panel. Swaps one
loadable family for another across the model, keeping the insertion point, the
instance parameters you choose, and the electrical circuits.

## Problem it solves

The usual job is turning a face-based family into one that is not — a light or
a socket modelled against a ceiling or wall face that now has to be a plain
level-based or work-plane-based family. Revit has no swap for this: the two
families have different placement types, so the type selector will not offer
one for the other, and Revit's own *Load as Group / Replace* does not apply.

Done by hand it is: note where the element is, note which way round it reads,
note its comments and its mark and its half-dozen project parameters, note
which circuit it sits on, delete it, place the new one, type all of it back in,
and rewire the circuit. Per element. The circuit is the part that bites — delete
the last element on a circuit and Revit takes the circuit with it, and the panel
schedule row goes with that.

The rule underneath is mechanical, which is why it is worth automating: same
point, same way round, named parameters copied across, and the replacement joins
the circuit *before* the original leaves it.

## Choosing the two families

Both sides work the same way and neither is a mode. **Find** on the left,
**Replace with** on the right, and each carries two routes to the same answer:

- **The lists** — category, then family, then type, with a keyword search that
  filters across all three. Every type shows its placement type and how many
  instances are in the model, so a face-based original and a work-plane-based
  replacement are both obvious before anything runs.
- **Select family in the model** — one click on an element sets that side to
  its family and type. A single `PickObject`, so the click completes it; there
  is no Finish and no Enter. Escape leaves without changing anything.

Use either route on either side, in either order. Picking sets the *family and
type*, not that one element.

**Scope** sits at the top of the window and decides how many get replaced:

| Scope | What gets replaced |
| --- | --- |
| **Active view** (default) | every instance visible in the view you are in |
| Entire project | every instance of the source type in the model |
| Current selection | those already selected in Revit when Replace is pressed |

Active view is the default deliberately. Replacing across a whole project is
the wider blast radius of the two, so it is the one you have to ask for.

## Drafting views: import symbols to detail items

When the **active view is a drafting view**, the tool changes job. Find lists
**import symbols** - AutoCAD blocks brought in as imports - and Replace with
lists **detail items**. An orange chip in the scope bar says so, and the two
pick buttons read *Select import symbol in the view* and *Select detail item in
the view*. The window follows the active view by itself: switching between a
drafting view and anything else re-reads both lists and clears both picks,
because a type chosen in one mode means nothing in the other.

Only imports that are drawn *in a view* are listed. A detail item belongs to a
view, so an import placed as a model element has nowhere for its replacement to
go, and is left out rather than offered and then refused. Imports are listed by
their import category, then by block name; the block name is the whole label.

For the symbols to be listed one by one they have to be separate import
elements - after a **partial explode**, each block becomes one. A DWG imported
and left whole is one import, listed by its file name, and would be replaced as
one.

**Insertion point to insertion point - the default from 1.6.2.** The detail
item is placed the way a family-for-family swap places one: its insertion point
on the block's insertion point (the AutoCAD base point), turned to the block's
rotation. Build the detail item family with its origin where the block's base
point is, and it lands exactly where the symbol was, whatever its size and
shape.

The insertion point and rotation come from **the block's own placement
transform** - the transform its linework is drawn by, read from the import's
geometry. Where the import wraps the block in an outer instance holding nothing
else, the two placements are combined; a block that holds lines as well as
another block keeps its own insertion. An import that is not exactly one block
- a whole DWG left unexploded - has no single insertion point and falls back to
the import's total transform, then its instance transform. Every one of those
routes is written to the debug log for every symbol, with its origin and angle,
so if the first is ever the wrong one the log shows which was right.

That order is the fix. Up to 1.6.1 the import's `GetTransform()` was asked
first, and for an import symbol it can come back with no rotation - so the angle
read as 0 for a symbol that was turned. With the angle wrong, every placement
rule built on it was wrong too, the centre measurement included. A detail item
of identical geometry still looked right, because middle to middle with
identical shapes does not depend on the angle; anything else did not.

After placing, the detail item's own placement is read back. If its insertion
point is more than 0.5 mm from the block's, or its X more than 0.01 degrees from
the block's, it is moved or turned by exactly what is left, and the report says
*All N checked after placing: each sits within 0.5mm of its symbol's insertion
point, at its rotation*, or names the ones that do not.

**Line up centres instead of insertion points** is still there as an option,
off by default, for detail items whose origin does not match the block's base
point. It now takes its angle from the same block placement.

**Centre to centre (the option).** An AutoCAD block's
base point is wherever it was set, very often a corner, so the middle of each
symbol has to be measured - and measured **in the symbol's own axes**. The box
around a rotated symbol in world axes is centred somewhere else for anything not
symmetric about its own middle: 52 mm off for the bench's L-shaped block at 30
degrees, and right at 0 and 90, which is why it looks fine in a first test.

How it is measured, from 1.6.1: the symbol is **turned square to the view for a
moment**, inside a sub-transaction that is always rolled back, and Revit's own
bounding box read. Square, that box *is* the symbol's extents in its own axes,
so its middle - turned back through the symbol's angle - is the true middle at
any rotation, mirrored or not. It needs nothing from the geometry API, and it is
the box Revit draws when you select the element.

Where that cannot be done, the symbol's linework is read and measured in its
own axes instead; failing that, the box as it stands; failing that, the base
point. The report says how every centre was found and warns about any that fell
back to the base point.

**Rotation.** The symbol's own X axis, flattened into the view, gives its angle
from the view's right. The detail item is placed on the centre and turned to
that angle about the view's normal through the centre.

**The detail item's middle goes on the symbol's middle - whatever its size and
shape.** This is the part that failed in 1.6.0 for detail items unlike the
symbol, and it now runs in four steps:

1. The detail item is placed on the symbol's centre, **still square to the
   view**, and Revit's bounding box read. Square, that box is the item's own
   extents, so this gives exactly where the item's middle sits from its
   insertion point - true for any size, any shape, any origin.
2. It is turned to the symbol's angle, and mirrored if the block was, about its
   insertion point.
3. Where its middle now sits is **worked out** - that offset turned and mirrored
   the same way - and the item moved so its middle lands on the symbol's. The
   move is calculated, not read back off the turned element.
4. It is **measured again** the square-box way. More than 0.5 mm off and it is
   moved by what is left, once, and measured again. If it still will not land,
   it is named in the report with how far off it is.

In 1.6.0 this was a single read of the turned item's geometry and a single move,
never checked. When that read did not come back as expected, the move did
nothing: a detail item whose origin happened to sit where the block's base point
was looked right, and any other shape stayed off. The report now ends with
*All N checked after placing: each sits within 0.5mm of its symbol's centre*, or
names the ones that do not.

**Debug log.** Every drafting run writes one line per symbol to
`%APPDATA%\RevoBIM\FamilyFindReplace_debug.txt`: the symbol's centre and how it
was measured, its angle and handedness, the detail item's offset from its
origin, the move made, how the result was checked and how far off it ended.
The report gives the path.

**Mirrored blocks.** *Mirror to match blocks mirrored in AutoCAD*, on by default.
A mirrored block's axes run the other way round to the view's. The detail item
is turned to the block's angle and then mirrored across the line its own X runs
along - which keeps X and flips the other axis, reproducing the block's
handedness exactly. Handedness is judged in the view plane rather than from the
transform's determinant, so a block flipped through the sheet, which looks the
same on paper, is not treated as mirrored.

**What changes in the window.** The electrical card greys out as a whole, chip
reading *Circuits retained? : n/a*: import symbols and detail items carry no
circuits or wires, and a live-looking control would suggest otherwise.
*Associate with the nearest level below* is hidden - a drafting view has no
levels - and *Mirror to match* takes its place. *Replace inside groups* is
disabled; a symbol inside a detail group is reported and left alone. Tags and
parameter values carry across as in a model view.

**The adjust window** turns each detail item about its insertion point - or
about its own centre when centres were lined up - so it stays exactly on its
symbol, and hides the Z offset, which a drafting view has no depth for. Use it where the detail item family is drawn
the other way up to the block: the run matches the block's rotation, and the
family's own convention is the one thing it cannot know.

**Scope** works as elsewhere: Active view by default, Entire project to replace
the symbol in every view it is drawn in - each detail item going into the view
its own symbol was in - or Current selection.

## What travels with the swap

The **Parameters to retain** list is built from the original's own writable
instance parameters. Each row shows the parameter, its value on a sample
original, and whether the replacement family carries the same parameter — read
by placing one temporary instance of the replacement inside a transaction that
is always rolled back, so the answer is the real one rather than a guess from
the type.

**Nothing is ticked by default.** Retention is a deliberate choice per run: a
value carried across silently is the sort of thing that is only noticed three
drawings later. **All**, **None** and **Shared only** are there to tick a set
quickly. Built-in geometry and host parameters are kept out of the list
entirely — level, elevation, host, offset, family and type. Those are the ones
the tool is setting itself, and letting them be copied would fight it.

The list spans the full height of the window, alongside both family columns and
the report, because it is the part of this tool you actually read.

Workset and pinned state always carry across, ticked or not. A replacement lands
on the workset its own original sat on, not on one workset for the whole run.

Where a parameter exists on both sides but the storage types differ, or it is
read-only on the replacement, it is reported as left alone rather than skipped
silently.

## Groups

**Off by default.** With it off, an element inside a group is reported and left
alone, because elements in groups cannot be modified in place.

With it ticked, there is a thing to understand first: **a group type is one
definition shared by every instance of it.** Changing what is inside it changes
every instance, project wide, whatever the scope says. The tool states this in
Preview and again in the confirmation rather than quietly doing it.

There is no edit-group-in-place in the API, so the routine takes **one**
instance of each affected type apart, changes it, puts it back as a new type,
and moves every other instance onto that type. The swap therefore runs **once
per group type rather than once per instance** — on a type placed forty times,
forty times less work.

**The risk in that is checked rather than assumed.** Regrouping computes a fresh
group origin from the members it is handed, and moving an instance to a type
whose origin sits somewhere else can shift its contents. So a witness point —
where one of the family sits inside each instance — is taken *before* anything
is touched, and the first reassignment is compared against it. If it moved, the
whole group type is rolled back and rebuilt the careful way instead: every
instance taken apart, changed and regrouped exactly where it already was, so
identical inputs give identical origins and nothing can move. That route is
several times the work, which is what the confirmation means by "this could take
some time", and the report says when it was needed and why.

Each group type sits in **its own transaction**. Taking a group apart and
putting it back is one move, and half of it done is worse than none of it, so a
type that fails rolls back whole and is named in the report — and the gap
between two of them is somewhere safe to move the progress bar.

**Above five group instances the run asks first**, naming how many instances and
how many types. Afterwards a completion prompt says how many group instances
were updated, how many elements were replaced in total, and names anything left
alone. A run with no groups in it reports in the window as usual, with nothing
to dismiss.

What does not survive: **attached detail groups**, which do not come back when a
model group is re-formed — reported per group type when any are found. **Nested
groups** are left alone rather than half handled, and reported. **Excluded
members** in individual instances are not preserved.

## Tags and wires

Two things that hang off an element and are quietly lost when it is deleted.
Both are on by default, and both are transferred **before the original is
deleted** — that ordering is the whole thing, because Revit removes a tag whose
only referenced element has gone and leaves a wire end dangling. Afterwards is
too late for either.

**Tags** are re-pointed rather than recreated wherever the API allows it: the
replacement is added as a reference and the original removed, which keeps the
head position, the leader and any elbow that was dragged by hand. Where that is
not available, an equivalent tag is made in the same view, at the same head
position, with the same leader state and orientation, and the old one deleted —
that keeps the position but not the elbow. Tags are found from one collector
over the document, indexed by tagged element and cached for the run, rather
than a collector per element.

**Wires are a separate problem from circuits**, and this is worth being clear
about: putting the replacement on the circuit says nothing about the `Wire`
elements drawn on the plan. Those hold their own connections to the original's
connector, and stay pointing at it. Each wire end is now disconnected from the
original, connected to the replacement's matching connector — same electrical
system type where the replacement offers more than one — and the wire's own end
vertex dragged onto the new connector, so the wire is drawn to where the device
actually is rather than reaching for where the old one was.

## Insertion point and which way round

The replacement is placed at the original's `LocationPoint`, then nudged onto it
exactly — Revit snaps a level-based family to its level elevation on placement,
so the point it lands on is not the point it was asked for until it is moved
there.

**The level comes from the point, not from the original.** A face-based family
hosted to a face frequently carries no usable level at all, and where it does,
the level often belongs to the *host* rather than to the element — a light
hosted to Level 1's ceiling reports Level 2, because that is the level the
ceiling was drawn on. So each replacement is associated with the nearest level
**at or below** its own insertion point. A level within 1mm counts as being at
the point rather than above it, so an element sitting exactly on its own level
is not pushed down to the one beneath by floating point noise, and a point below
every level in the model falls back to the lowest.

Untick **Associate with the nearest level below** on the Placement card to keep
whatever level the original is associated with instead. That suits a family
deliberately dimensioned down from the level above on a negative offset, where
the level above is the right answer and the level below is not.

The level is written to *every* writable level parameter the family carries, not
just the one the placement overload took. A family with both Level and Schedule
Level was otherwise left with the second pointing somewhere else — invisible in
the view and wrong in every schedule. Because setting a level parameter moves
the element, the level goes on first and the insertion point is corrected
afterwards.

Which way round it reads is the interesting part, and it is why a face-based
original needs care:

- A **wall-hosted** original faces out of the wall, so its **facing direction**
  is the one worth keeping.
- A **ceiling-hosted** original faces straight down. It has no plan facing at
  all, so its **hand direction** stands in.
- Anything else falls back to the instance transform's X axis.

The first of those three that has a real direction in plan is the one used, and
the replacement is turned about the vertical through its insertion point until
it matches.

**Placement routes are chosen from the replacement's own placement type**, and
the rule that matters is: *a host element is only ever offered to a family whose
placement type actually takes one*. Handing the original's ceiling to a level
based family is what produces Revit's "Can't use this type of host", and it is
the single reason a face based to non-face based swap fails.

| Replacement's placement type | Routes tried, in order |
| --- | --- |
| `OneLevelBasedHosted` | host + level, host, host face, level, point |
| `WorkPlaneBased` | work plane, host face, level, point |
| `OneLevelBased`, `TwoLevelsBased`, anything else | level, point, work plane |

Only the first row ever sees a host element.

**Work plane based needs a plane, not a level.** Most families authored as "not
face based" are in fact `WorkPlaneBased`, and neither the level overload nor the
bare point overload gives them a plane to sit on — so they fail even once the
host is out of the way. A horizontal `SketchPlane` is created at the insertion
point for those, cached by elevation so a run over three hundred fittings leaves
three or four planes behind rather than three hundred.

**Each route sits in its own sub-transaction.** A route can return an element
and only then have Revit post an error at regeneration; without the isolation
that failure lands on the whole run rather than the attempt, and the cascade
never reaches the route that would have worked. Regenerating inside the attempt
is what forces the error to surface where it can be rolled back.

The route that worked is reported. When none does, every route tried is listed
rather than only the last — which routes were even attempted tells you what
placement type the family reported, and that is usually the answer.

## The adjust window

Where the two families are drawn to different conventions, matching the original
still leaves the whole set ninety degrees out. So the run opens a second small
window against the replacements it has just made, with them selected:

**0 / 90 / 180 / 270**, or a custom angle, and a **Z offset** in millimetres.

Both apply to the whole set at once, about each element's own insertion point,
and the numbers read as absolutes — set 90, look at it, set 180 instead, and the
tool applies the difference rather than stacking. **Reset** puts the set back to
as-placed. Each apply is its own transaction, so Ctrl+Z steps back through them.

A pinned replacement has its pin taken off for the move and put straight back.

## Electrical

**The chip is a toggle, not a verdict.** It reads **Circuits retained? : On**
in solid green, or **: Off** in solid red, and clicking it switches between the
two. On is the default.

Off is filled red rather than merely greyed because it is the destructive
setting: with it off, circuited originals are deleted and their circuits go
with them, and no undo of the model brings a panel schedule row back once the
file has been synchronised. The count of circuits on the selection sits beside
the chip, and anything dropped is reported as a failure line after the run.

Whether the two families actually *agree* electrically reads in the line
beneath the chip rather than changing the chip itself — the chip reports the
setting, the line reports the model. On but mismatched turns that line red,
names which of system type, poles or voltage disagrees with both values, and
says circuited elements will be left alone rather than swapped. No circuit is
destroyed either way, which is why there is no longer an acknowledgement tick
gating the run.

The connector is read from a placed instance of the replacement where there is
one, and from a temporary rolled-back instance where there is not. Type
parameters are the last resort, because a family's type voltage and its
connector's voltage are allowed to disagree.

**The transfer itself is add-before-delete.** Each replacement joins every
circuit its original sat on, and only then is the original deleted. That
ordering is the whole trick: a circuit with one element on it, emptied by the
delete, is destroyed by Revit along with its panel schedule row. Joined first,
it never empties, and the panel schedule keeps its row and its circuit number.

**Every add is verified, and a failure is refused rather than pushed through.**
`AddToCircuit` is tried through all four signatures it has carried across
releases — `ICollection<ElementId>`, `ElementSet`, the element, the element id
— because a release that exposes only one of them will throw on the others, and
a swallowed exception looks exactly like a circuit that quietly vanished. After
each attempt the document is regenerated and the circuit's own member list read
back, because a call that does not throw has still not necessarily done
anything.

If any circuit will not take the replacement, **that element is rolled back and
the original left exactly as it was**, with the panel and circuit number in the
report. Deleting the original at that point would destroy the circuit, and a
destroyed circuit is the one failure of this tool that costs real work to find
again.

**Phasing carries across always**, like the workset, and is set before the
circuit is touched. A replacement takes the phase of the view it was created in
rather than the original's, and circuits are phase-aware — so a phase left
alone makes `AddToCircuit` refuse for a reason that reads as nothing to do with
phasing.

## Window

Modeless, owned by Revit's main window so it floats above rather than slipping
behind. Revit stays fully navigable and selectable with it open — orbit, select,
change the view, all of it. **Resizable** by any edge or corner, minimum
960 x 660; the family lists and the parameter box take the extra height.

Layout: scope across the top, then the **Find** side (blue tick) and the
**Replace with** side (orange tick) as category / family / type columns with a
model-pick button each, the report beneath them, and **Parameter values to
retain** down the full height of the right-hand column with the compact
electrical chip and placement options under it. Footer carries the status line
on the left and **Preview** and **Replace** on the right, with the adjust
window's button beside them once a run has happened.

Themed per the RevoBIM theme reference, version top right.

### Shrink to taskbar

Every window the tool opens - the main window, the adjust window and the
confirm / completion prompt - has a **shrink button** in the top right, beside
close. Pressing it slides the window down to the bottom of its screen like a
drawer closing, leaving only its header bar floating 8px clear of the taskbar,
so Revit can be seen and worked in without closing anything. The button turns
into a **green up arrow**; press it, double-click the bar, or press Enter or
Esc, and the window slides back up to where it was. **Ctrl+Shift+H** does the
same both ways. It follows the house standard in the RevoBIM theme reference,
and matches Pro Sheets, Filter Manager and View Manager.

- **The bar stays draggable.** Carried somewhere else, the window opens upward
  from where the bar now sits, kept on that screen, rather than jumping back.
- **Windows go down together.** A dialog shrinking takes the main window down
  first, so it is not left standing over Revit, and parks its own bar above it.
  The main window shrinking takes an open adjust window down with it. Bringing
  either back brings both; closing a parked dialog brings the main window back.
- **Several bars stack** 4px apart rather than on top of one another.
- **Held during a run.** While Replace or Preview is working the window does
  not slide, from the button or the shortcut.
- **The prompt is modal.** Shrinking it gets it out of the way so the model can
  be seen, but Revit stays locked until it is answered - that is what modal
  means, and the drawer does not change it.

How it is built, in `ffr_drawer.py`: one `Drawer` per window, given the window,
its header bar, the layout root and the button. Top and Height are eased
together - cubic ease out, 280 ms, on a 15 ms `DispatcherTimer`, since a
Storyboard on a borderless window's Top and Height fights the layout pass. The
five things the standard says break a drawer are each handled and each proved:

1. **The animation is released** on Top and Height, each in its own try, both
   before the slide and when it finishes - a held animation outranks every
   later assignment and would freeze the window for good, silently.
2. **MinHeight and SizeToContent are relaxed** for the slide and put back when
   it reopens; either one vetoes a Height change and leaves a window half shut.
   The adjust window and the prompt size to their content, so this matters on
   both.
3. **The body is pinned** at its full height during the slide, so the window is
   drawn away rather than squashed, and unpinned once it reopens.
4. **The resize grips are parked** with the body, so the bar is not lined with
   invisible drag handles that swallow the click on the green arrow. The body
   is hidden only once the bar lands, and every part is put back exactly as it
   was - the progress band that was hidden stays hidden.
5. **Parked, Enter and Esc reopen the window** rather than answering a prompt
   nobody can see, and a double click on the bar reopens it.

The parking and reopening arithmetic is plain functions, proved by the logic
bench including a **second monitor above the primary one**, where the working
area's top is negative and clamping to zero would send the window to the wrong
screen. The screen comes from `Screen.FromHandle`, scaled by the window's DPI,
falling back to the primary screen's working area.

**Preview** reports exactly what the run will do — how many elements, which
parameters will carry and which will not, how many circuits are involved, and
which elements will be left alone and why — without touching the model.

## Progress

A 26px band across the top of the window under the header, for both Preview and
Replace. The label on it reads
`62%  -  45 of 120 left  -  75 of 120 elements` — **what is left rather than
what is done**, because on a long run that is the useful question. The plain
percentage also sits in the header, and the running count on the status line.

The label is white over the bar so it reads on both the filled blue and the
empty track behind it, and it is centred so it stays legible whatever the fill
has reached.

Getting this wrong is easy and expensive, so the shape of the run changed to
carry it. **The dispatcher must never be pumped between a transaction's Start
and its Commit** — doing it to repaint a progress line can leave the write with
nothing committed. So the run is chunked: twenty-five elements per transaction,
one transaction per group type, all inside the same transaction group, and
progress is reported only in the gaps between them with nothing open. Undo still
sees one step.

The bar **repaints only when the whole percent moves**. At five thousand
elements that is about a hundred repaints across two hundred transactions rather
than one per element; pumping on every element costs more than the work being
measured, and the bar cannot show a fraction of a percent anyway.

The fill is drawn as two star-sized grid columns rather than a width in pixels,
so it is a ratio and is right at any window width without measuring anything.

The whole-percent guard starts at -1 rather than 0, so the first call still
paints and the band appears empty as the run starts rather than appearing only
once some of the work is already done.

Because the run now spans several transactions, elements are held as **ids and
re-fetched at the point of use** rather than as handles captured before the
first transaction opened.

## Decisions worth remembering

- **Add to the circuit before deleting the original.** Everything else about
  the electrical handling is detail; this is the part that keeps panel
  schedules intact. Reversed, it silently destroys single-element circuits.
- **A ceiling-hosted family has no plan facing direction.** `FacingOrientation`
  points straight down and flattens to nothing, which is why the hand direction
  has to stand in and why reading rotation off `LocationPoint.Rotation` alone
  gets face-based families wrong.
- **Read the replacement family by placing one and rolling back.** A family
  symbol has no connectors and no instance parameters until an instance exists.
  A transaction that is always rolled back gets the real answer without a
  placed instance and without leaving anything behind.
- **Never offer a host to a family that cannot take one.** Revit's message for
  it — "Can't use this type of host" — names the host rather than the family
  that refused it, which sends you looking at the ceiling instead of at the
  replacement's placement type.
- **"Not face based" usually means `WorkPlaneBased`, not `OneLevelBased`.**
  The two need completely different placement calls, and the family browser
  does not distinguish them.
- **The placed point is not the asked-for point.** Revit snaps a level-based
  family to its level; the element has to be moved onto the original's point
  after placement rather than trusted to land there.
- **Nearest level means nearest level *below*, not nearest by distance.**
  Choosing by absolute distance puts a ceiling light at 2700mm onto the level at
  3600 rather than the one at 0, because 900 is less than 2700. It is wrong for
  every high-level element in the model, and it is wrong quietly.
- **Never read a face-based element's level off its host.** The ceiling belongs
  to the level above the space it encloses, so the host's level is a storey out
  for exactly the elements that need the level set for them.
- **Elements inside groups are reported, not replaced.** They cannot be
  modified in place, and ungrouping the model underneath the user is not the
  tool's decision to make.
- **Chunked transactions, per-element sub-transactions, one transaction group.**
  A single awkward element cannot take the run down, one undo still puts the
  whole run back, and there are gaps between transactions to repaint from.
- **The dispatcher must never be pumped between a transaction's Start and its
  Commit.** Letting Revit's message loop run there, purely to move a progress
  bar, can leave the write with nothing committed. That single constraint is
  why the run is chunked at all — the progress bar did not just get added to
  the existing shape, the shape changed to make it safe.
- **Pumping the dispatcher also pumps input.** It dispatches real mouse and key
  messages, so the window can be clicked or closed part way through a run. It
  is made hit-test-invisible for the duration, and the handler releases it in a
  `finally` so a job that throws cannot leave the tool looking frozen.
- **`Theme.xaml` is merged after `XamlReader` has parsed the layouts**, so the
  layouts may only use `DynamicResource`. A `StaticResource` fails at load and
  shows up as the blank white pyRevit window. The bench check enforces it.
- **A release that only takes `ElementSet` looks identical to a circuit that
  refuses.** Both surface as a swallowed exception and a missing circuit. Trying
  every signature and then verifying against the member list is the only way to
  tell the two apart, and the difference matters: one is a bug in the tool, the
  other is a fact about the model.
- **Phase before circuit.** A circuit is phase-aware, so a replacement left on
  the view's phase is refused for a reason that names neither phase nor view.
- **A window with `WindowStyle=None` and `AllowsTransparency` gets no usable
  resize border from WPF** — a couple of transparent pixels and no cursor.
  Eight explicit thumbs over the edges are the reliable answer, and dragging a
  west or north edge has to move the window as well as size it, clamped so it
  cannot drift once it hits its minimum.
- **A toggle should report the setting, not the diagnosis.** Making the chip
  green-for-compatible and red-for-incompatible meant it could not also be the
  On/Off control without one meaning overwriting the other. The chip now says
  what will happen; the line under it says what the model looks like.
- **Default nothing on rather than something on.** A pre-ticked parameter that
  happens to be wrong for this swap is invisible at the moment it matters.
- **A tag is deleted with the thing it tags.** So is a wire's connection. Both
  have to be moved while the original is still there, which puts them in the
  same bracket as the circuit transfer and for the same reason.
- **Being on a circuit is not the same as being wired.** `ElectricalSystem` is
  the logical circuit; `Wire` is the line on the drawing. Carrying one across
  does nothing for the other, and only the circuit was being carried until
  1.3.0.
- **A group type is one definition, so scope does not apply to it.** Any tool
  that edits inside a group is editing every instance, and saying so plainly is
  the only honest option.
- **Match group members against the type being replaced *from*.** Handing the
  routine the replacement type id makes it search a group for elements that
  have already been swapped: it finds none and reports, accurately and
  uselessly, that there is nothing there to replace. That was the 1.4.0 group
  bug, and the message it produced was true and completely misleading.
- **Take the fast route, but check it.** Reassigning instances to a type built
  from one of them is far quicker than rebuilding each, and it can shift their
  contents if the new origin differs. A witness point taken before the move
  turns "probably fine" into something the tool can actually tell, with the
  careful route as an automatic fallback.
- **A bench check with a hardcoded file list has a hole in it by construction.**
  The layout list is now read off disk; the prompt layout shipped in 1.4.0 was
  checked by nothing until that was fixed.
- **Measure a block's centre in the block's own axes.** The box around a
  rotated block in world axes is centred somewhere else for anything lop-sided,
  and the error grows with the angle - zero at 0 and 90 degrees, which is
  exactly why it looks right in the first test and wrong in the drawing.
- **Step a drawer by hand and always let go of the animation.** Easing Top and
  Height on a timer avoids a Storyboard fighting the layout pass; releasing
  both properties anyway costs nothing and is the difference between a window
  that can be moved again and one that cannot.
- **Bench the drawer against a window that fails like WPF.** The stand-in vetoes
  a height below MinHeight or under SizeToContent, ignores assignments while an
  animation holds them, and only ticks its timer when pumped, as a dispatcher
  does - otherwise an exception thrown in a frame comes out of the code that
  started the timer and is caught there, and the check passes for the wrong
  reason. The selftest breaks the frame handling to prove it does not.
- **Read the block's placement from the geometry it is drawn by.** An import
  symbol's `GetTransform()` can come back with no rotation; the transform on
  its GeometryInstance is the one the linework actually uses. Asking the
  instance first is what broke 1.6.0 and 1.6.1, and the logic bench now puts
  that order back on purpose to prove the check catches it.
- **Do what a family swap does.** Insertion point to insertion point, at the
  same rotation, is the rule that already lands correctly elsewhere in this
  tool; drafting views now follow it by default.
- **Place, then check - never place and trust.** One unchecked read and one
  move failed silently in 1.6.0 and only showed with a detail item unlike the
  symbol, because a look-alike family's origin happened to fall in the right
  place without any help. Every placement is now measured again afterwards.
- **Measure square, not turned.** Turned square to the view, an element's
  bounding box is its own extents, so the middle is exact. It needs a
  transaction to turn the element in, always rolled back - which is why the
  drafting preview opens and rolls back one per symbol, closed again before
  the progress bar repaints.
- **Work out the move rather than read it back.** The item's offset from its
  origin is read once while square, then turned and mirrored mathematically in
  the same order the item was - turn first, mirror second.
- **A BoundingBoxXYZ has its own Transform.** Min and Max are in that frame.
  It is usually the identity, which is why ignoring it looks fine.
- **An AutoCAD base point is not a centre.** It is wherever the block's author
  put it. Placing on it is the obvious route and the wrong one.
- **Mirror across the X line, not about X.** The plane to mirror across holds
  the block's X axis and the view normal. Using X as the plane's normal mirrors
  across the other axis and leaves the symbol pointing backwards; the logic
  bench breaks it exactly that way to prove the check catches it.
- **A drafting view and a model view do not share a list.** The window follows
  the active view through `ViewActivated` and re-reads both sides on a switch,
  keeping the handler as one object so the same one comes off again on close.
- **The pin goes on inside the run**, not left to the adjust window the user may
  never open, and `adjust_elements` releases and restores it around each move.

## Folder layout

```
Management.panel\
  Family Find Replace.pushbutton\
    script.py                     launcher, blanket try/except
    ffr_core.py                   everything that touches the document
    ffr_ui.py                     the window, the ExternalEvent, the wiring
    ffr_drawer.py                 shrink to taskbar, one Drawer per window
    Theme.xaml                    every brush and control template
    FamilyFindReplace.xaml        the main window layout
    FamilyFindReplaceAdjust.xaml  the post-run adjust window
    FamilyFindReplacePrompt.xaml  themed confirm / completion prompt
    import_check.py               bench check against a stub Revit API,
                                  with --selftest
    bench_logic.py                logic bench under CPython, with --selftest
    make_icon.py                  regenerates icon.png
    bundle.yaml  icon.png  CHANGELOG.md
```

All of it self-contained in the pushbutton folder with `sys.path`
self-injection — nothing added to `lib\revobim`, so no other tool is disturbed.

## Refusals

Preview lists the levels the replacements will land on and how many go to each,
so a wrong level rule is visible before anything is written; the run report
lists the same afterwards.

Reported rather than attempted: a group that will not ungroup or re-form, a
nested group, an element still inside a group after being ungrouped, a tag that
will not move to the replacement, a
wire end that will not reconnect or has no matching connector to reconnect to,
an element inside a group, a line-based rather
than point-based original, an original whose replacement will not place by any
of the placement routes, a parameter that is read-only or a different storage
type on the replacement, a circuit that will not take the replacement, and a run
over 5000 elements.

## Open items for a future version

- **No settings file.** Scope, the match-orientation tick and the adjust
  increments are chosen fresh each run rather than persisting under
  `%APPDATA%\RevoBIM\`. Everything else in the extension persists; this one
  does not, because its main state — which family to swap — is transient.
- Line-based and curve-driven families are not handled at all, only
  point-placed ones.
- A replacement is placed at the original's point regardless of whether that
  point is sensible for an unhosted family. A face-based light on a sloping
  soffit lands at the soffit's Z, not at a level offset, and the Z offset in
  the adjust window is the fix rather than anything automatic.
- Circuits are carried but not **re-ordered**: the replacement joins at the end
  of the circuit rather than at the original's position in it, so a panel
  schedule that was in a deliberate order may need a look.
- Nothing is done about the **load** the circuit sees. Where the replacement
  draws a different apparent load, the circuit is kept but the panel schedule
  totals move, and the tool does not warn about it — only about system type,
  poles and voltage.
- Type parameters are not offered, only instance parameters. Copying a type
  parameter would write to every instance of the replacement type, which is
  almost never what is wanted, but there is no way to ask for it deliberately.
- No batch mode: one family swapped for one other family per run.
- Drafting views: blocks nested inside a DWG that was imported and left whole
  are not reached - partial explode first, so each block is its own import.
- Drafting views: detail groups are not handled, and imports inside one are
  left alone.
- Drafting views: only detail items are offered as replacements, not generic
  annotations or other view based families.
- The drafting-view centring has been proved at the desk for detail items of a
  different size and shape to the symbol, with origins at a corner, centred and
  well outside the drawing. A symbol whose block includes text or attributes
  far from its linework will be measured to include them, since Revit's box
  does; the debug log shows it if so.
- Nested groups are not recursed into; the routine would have to run again one
  level down and it does not.
- Attached detail groups are lost when a model group is re-formed. Reported,
  not prevented.
- Members excluded in individual group instances are not preserved.
- The group routine has not been run against a group containing a circuited
  family across many instances. The pieces are each covered, but that
  combination is the one to try on a copy of the model first.
- Tags in *other* documents — a tag in a linked model pointing at an element in
  this one — are not touched.
- A wire whose two ends both land on the same replacement is reconnected end by
  end without checking that the result still makes electrical sense.
- Recreated tags lose a hand-dragged leader elbow; re-pointed ones keep it, and
  which route a release takes is not something the tool chooses.
- The parameter ticks are not remembered between runs, so a swap repeated
  across several types means ticking the same set again each time.
- Hosted-to-hosted swaps re-host onto the original's host where the placement
  type asks for it, but a replacement whose host category differs from the
  original's is not detected in advance and simply fails to place.
- Going the other way — a non-hosted original to a face based replacement —
  only works where the original has a host to borrow a face from. With no host
  anywhere near, there is no surface to place on and the element is reported
  rather than placed; finding one by ray-casting from the insertion point is
  the obvious next step.
- The sketch planes created for work plane based replacements are left in the
  model. They are what those instances are hosted to, so they have to stay, but
  nothing prunes them if the replacements are later deleted.
