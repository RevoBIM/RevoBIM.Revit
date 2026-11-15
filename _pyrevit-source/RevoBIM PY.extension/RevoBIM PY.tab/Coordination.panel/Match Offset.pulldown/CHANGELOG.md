# Match Offset - changelog

## 1.18.0

**MEP ancillary framing now goes flush under the duct.** Match Offset Bottom,
click the duct, click the strut: the top of the channel lands on the bottom of
the duct. In 1.17.0 it was landing half its depth proud - about 20mm on a
41mm channel - because strut is drawn along a line at its centre, and a line
is what the tool reads a duct's centreline off.

Support steel is now measured the way a hanger is: **one height, the face the
service sits on**, which is its top. Where the family has drops or rods drawn
in it, the bearer is told apart from them the same way a hanger's is. It is
read before anything that looks for a centreline, so the line it is drawn
along can no longer be mistaken for one.

New setting on the Match Offset tab, **MEP ancillary framing measured from**:
*the top face it supports on* (the default), *its real faces* (Bottom the
underside, Top the top), or *its bounding box*. The debug report writes the
strut's geometry out the same way it does a hanger's.

Settings version 7: a new key, nothing reset.

Bench: 820 logic checks, including the section that was sent over - a 200mm
duct with its bottom at 6555 and a 41mm channel under it, ending with the
channel top at 6555 and its underside at 6514. New breakage: support steel
measured along its centreline.

## 1.17.0

**MEP ancillary framing can be picked** - the strut, channel and trapeze bars
modelled as MEP supports rather than as the building's structure. It sits
under the Fabrication heading, now **Fabrication and supports**, ticked by
default, and is measured from its real solids like equipment: Bottom is the
underside of the steel, Top its top face.

The category arrived in a later Revit than the oldest this tool supports. On a
Revit without it the row is not offered in Settings, rather than being a tick
box that ticks nothing.

Settings version 6. A saved list gets the new category **added** to it rather
than being reset to the defaults, as v4 and v5 had to do - so any box unticked
on purpose stays unticked.

Bench: 803 logic checks, including a trimmed v5 list keeping its trim and
gaining the new row, and a current file with it unticked staying unticked. New
breakage: a new category resets a trimmed list.

## 1.16.0

**A family matched to something on another level now lands where it is meant
to, and says what its own offset came out at.**

Match Offset Bottom, click a duct, a fabrication duct or a piece of plant,
then click the family that goes under it. The base of the first is found the
way it always has been - a duct from its centreline less half its size, a
fabrication duct from its Bottom of Part, plant from the lowest face of its
solids - and the whole match is worked in **project elevations**, so the level
each end is on cannot put the family in the wrong place.

What changed is how the family is written:

- **A family on a level** is written through its own **Elevation from Level**,
  worked out against *its* level. Before, it was picked up and moved, which
  lands in the same place but leaves the arithmetic to Revit.
- **A family on a face or a work plane** - a grille on a ceiling, a box on a
  floor - is written through its **Offset from Host**. Revit will not move a
  hosted family off its host, so before, it stayed where it was and the run
  reported it as out by the full amount. Offset from host runs along the
  host's normal, so under a ceiling it runs *down*: the offset is written one
  way, the family is looked at, and the offset is turned round if it went the
  other way.
- Only where neither parameter will take it is the family moved by hand, as
  before.

When the family is on a different level from what it was matched to, the run
notes it: *"Air Terminals 123 on Level 01: bottom now 6555 mm above its own
level"* - the number that ends up in its properties palette, which is the one
somebody checking the job reads. It is a note, so it does not open the
results window on its own.

The debug report carries the level the datum came off.

Bench: 791 logic checks, including a fan coil on Level 01 matched to a duct
on Level 02, a ceiling grille whose offset runs down, a floor box whose offset
runs up, an offset that moves nothing being put back, and a read only
elevation stepped over. Two new breakages: families moved by hand and never
through their own offset, and an offset from host assumed to run up.

## 1.15.0

**A hanger's bearer is found by telling it from the rods, not by being the
biggest face.** Aligning a hanger's top onto a duct's bottom was landing part
way down the hanger instead of on the face the duct sits on.

"The biggest upward face" is right for a hanger drawn as a bar and two rods and
wrong for every hanger drawn in any detail. A channel's biggest upward face is
the **inside of its back**, a good 40mm below the flanges the duct actually
rests on; a hanger with a backing plate or a second tier has a big upward face
part way up it that nothing ever touches. Either way the bearer ends up low and
the duct ends up sitting in fresh air.

What is true of all of them: the services sit on the **bearer**, the bearer is
the widest piece that is not a rod, it is down at the **foot of the rods**, and
what the duct rests on is the **highest** face of it. So the hanger is now read
one solid at a time - a piece taller than it is wide is a rod, a drop or a
clamp; a piece wider than it is tall is a bearer - the rods are thrown away,
anything up at the structure is an anchor rather than a bearer, and the highest
real face of what is left is the answer. A family drawn as one lump has no
pieces to tell apart, so that still falls back to the largest upward face, as
before.

**Hangers write their own geometry into the debug report**, for the first two
in a run: one line per solid with its height, its span and its footprint and
whether it was read as a rod or a bearer, then one line per upward face with
its area and its height. Every rule for finding a bearer is a guess about how
somebody drew a hanger, and this is the evidence for the next one.

Bench: 763 logic checks, including a channel whose biggest face is inside it,
an anchor plate at the soffit that is not a bearer, a hanger drawn as one lump
falling back rather than refusing, and the old rule proved to get the channel
wrong. New breakage: a hanger taken at its biggest upward face.

## 1.14.0

**Hanger rods are re-cut after the move.** Aligning a hanger's bearing face
onto a duct's bottom was already right in 1.13.0 - click the duct, click the
hanger, the bearer lands under the duct - but the rods stayed the length they
were, so their tops came away from the soffit and the hanger was left hanging
on nothing. It looks correct in plan and in a section until somebody looks at
the rods.

A hanger hangs from the soffit, so the top stays and the bottom goes with the
hanger: drop it 150mm and its rods get 150mm longer. Rods Revit is hosting it
re-solves itself and the run says so; rods set to manual are re-cut here, the
same call the Fab Hangar Automation tool makes.

A hanger raised further than its own rods are long has nothing left to hang
from. That rod is left alone and reported, rather than being written a zero or
a negative length that no one would see.

New tick on the Match Offset tab, on by default: **Re-cut hanger rods so their
tops stay put**.

Bench: 745 logic checks, including hosted rods left to Revit, a rod with
nothing left reported rather than written, and a hanger that has not moved
left alone. New breakage: hanger rods left behind by the move.

## 1.13.0

**Fabrication parts are in**, as four categories under their own heading:
fabrication ductwork, pipework, containment and hangers. All four ticked.

**A fabrication part is measured from its own Top and Bottom of Part** - the
numbers the shop and the installer work to, and the ones in the properties
palette - rather than from anything derived. Those parameters are measured
from the part's **level**, not from the project base, so both readings are
compared against the part's own solids and the one that agrees within 50mm
wins. A level offset read as a project elevation is out by the height of the
level and still looks like a perfectly good number; where neither agrees the
solids answer and the report says so.

**A hanger is one height: the face it bears on.** Match a duct's bottom onto
a hanger and the bearer lands under the duct, which is the whole reason
anybody aligns a hanger to anything - so all three buttons are that one face.

Finding it: the top of a hanger's geometry is the top of its **rods**, up at
the soffit, where nothing sits; the top of its bounding box is the same thing.
The bearing face is the **largest horizontal face pointing up** - a rod end is
a few hundred square millimetres, a bearer's top is tens of thousands.

**Equipment, fixtures and terminals now use their real solid faces** for
Bottom and Top, with Middle still the family's own offset from level. 1.12.0
made all three the offset from level; that fixed the air terminal case and
left no way to ask what a plant item's bottom face is actually at, which is a
real question with a real answer. Now the three buttons give three answers:
the real bottom face, the real top face, and the datum the family was placed
at. *Their offset from level* is still there as a setting for anyone who wants
all three to be that one number.

**Real solids, not the bounding box.** A box takes in connectors, symbolic
lines, insulation and anything else Revit calls geometry; the solids are the
thing itself. Solid bounding boxes are read through their own transform
rather than straight off Min.Z and Max.Z, which is right only when that
transform happens to be the identity - true in the test model, false on site.

Three new settings on the Match Offset tab: **Equipment, fixtures and
terminals measured from** (real faces / offset from level / bounding box),
**Fabrication parts measured from** (top and bottom of part / real faces /
bounding box) and **Fabrication hangers measured from** (the face they bear on
/ the top of their solids / bounding box).

Settings version 5: the category list grew again and `point_measure` changed
what it defaults to, so both are migrated rather than left reading as the tool
ignoring what was asked for.

Bench: 729 logic checks, including the bearing-face rule picking the biggest
upward face rather than the highest, a parameter nine metres from the solids
not being believed, and a hanger with no solids falling back rather than
refusing. Three new breakages: a hanger taken at the top of its rods, top and
bottom of part believed whatever the solids say, and the solids read off the
bounding box.

## 1.12.0

**Equipment, fixtures and terminals are now set out on their offset from
level**, not on their bounding box.

Aligning an air terminal to a piece of mechanical equipment was going by the
extents of whatever each family draws - an air terminal's box takes in its neck
and its flange, a piece of plant's takes in its base and its pipe stubs - so
"bottom" was a number that matched nothing anybody could see in the properties
palette, and matching two of them lined up a flange with a plant base.

What one of those sits at is its **own offset from level**, and that is one
number rather than three. So for these categories all three buttons put two
elements at the same elevation, which is the point: Bottom, Middle and Top all
mean the same thing for a family whose position is a single insertion point.

The elevation is read off the element's own insertion point rather than out of
a parameter, because which parameter holds it depends on how the family is
hosted - *Elevation from Level*, *Offset from Host*, *Default Elevation* - and
the point itself is the same thing whichever of them the family happens to
carry. As everywhere else in the tool it works in absolute elevation, so two
elements on different levels still land level with each other.

**Which categories**: plumbing fixtures and equipment, air terminals,
mechanical equipment and control devices, electrical equipment and fixtures,
lighting fixtures and devices, data, communication, telephone and audio visual
devices, sprinklers, fire protection, fire alarm, security and nurse call
devices, specialty, medical and food service equipment, casework and furniture.

**Which are deliberately not**: pipes, ducts, trays, conduits and their
fittings, accessories and insulation, generic models and the structural
categories. A fitting travels with its run and a generic model is usually a
hole, and for both the extent is what matters.

New setting on the Match Offset tab, **Equipment, fixtures and terminals
measured from**: *their offset from level* (the default) or *their bounding
box*, which is the old behaviour for when the extents really are what you want.

Bench: 678 logic checks, including that every point-based key is a real
category, that a pipe and a generic model are untouched by any of it, that a
family with no insertion point falls back to its box rather than refusing, and
that all three anchors give the same answer for a terminal. New breakage:
equipment measured from its bounding box.

## 1.11.0

**Every standard MEP category is now in the list**, up from 25 to 46, under
six headings so it can actually be read.

Added: **Air terminals**, pipe insulation, duct insulation, duct lining,
plumbing equipment, mechanical control devices, telephone devices, audio
visual devices, nurse call devices, fire protection, medical equipment and
food service equipment - alongside the electrical fixtures, lighting,
data, communication, security and specialty equipment that were already
there.

Also in the list, and **off until they are ticked**: casework, furniture,
furniture systems, structural framing, structural columns, columns,
structural foundations, stairs and railings. A services bank is often set out
against them, but a tool that moves a beam because somebody clicked one is
worse than a tool that needs a box ticked first.

- The list is grouped - Pipework, Ductwork, Electrical, Fire and safety,
  Equipment and fixtures, Structure and architecture - and the keyword box
  searches the group names as well as the category names, hiding a heading
  whose whole group has been filtered away.
- A category a release does not have is skipped rather than taking the tool
  down, which is what lets one list cover Revit 2024 through 2027: Fire
  Protection, Audio Visual Devices and Plumbing Equipment all arrived at
  different releases.
- Settings version 4, with a migration that puts the new list in. Without it
  a category list saved before today names only the old keys, so air terminals
  would be silently off for anybody who had ever pressed Apply - which reads
  as the tool not seeing them rather than as a setting.

Match Offset Slope still works on pipes only, whatever is ticked.

Bench: 642 logic checks, including that no key, label or Revit category
appears twice, that every group has something in it and accounts for every
category, that every services category ships ticked and no structural one
does, and that the migration replaces an old list but leaves a current one
alone. New breakage: structural categories shipping ticked.

## 1.10.0

**Suppress every message**, a tick under Settings > Picking and shortcuts >
Diagnostics. With it on, a run finishes with nothing on screen at all: no
results window and no debug report, whatever the other two settings say.

Two things it deliberately does not do:

- **The debug report is still written** to
  `%APPDATA%\RevoBIM\match_offset_debug.txt`, so a suppressed run can still
  be looked at afterwards. Suppressing a message and throwing the record away
  are different things.
- **A failure to start still reports itself.** A tool that dies silently is
  indistinguishable from a broken button, and there is nothing the user can do
  about it if nothing says so.

Bench: 609 logic checks, including that a problem is still a problem when
messages are suppressed - the run knows, it just does not say.

## 1.9.0

**The slope tool now works in pairs.** Once a connection is made it goes
straight back to asking for a main, so a run of separate joints is click,
click, click, click until Escape.

- The status line carries the **running count** as well as the question -
  "3 joined - pick the MAIN..." - because the prompt is the only feedback
  there is during a run, and a count that has not moved says the last pair
  did not go in.
- It asks for a main again whether the pair went in or not. Quietly carrying
  on with a main the user has stopped thinking about is worse than asking
  again.
- The old behaviour is still there: **After each connection** on the Slope tab
  is *ask for a new main* (the default) or *keep the same main*, which is the
  one to use for a manifold where several branches go into the same run.

Bench: 602 logic checks, including the prompts themselves - that the first
asks for a main, the second asks for the pipe to bring into it and carries the
main's fall, that the count appears once something has gone in and not before,
and that one-main mode still asks for branches.

## 1.8.0

**Two runs on the same line are now made into one run**, rather than refused
as parallel. Click one, click the other, and the second is put on the first's
fall, brought to its elevation, extended or trimmed to its end, and joined
with a union.

Two pipes drawn on the same line never cross, so there is no crossing point to
work to. The point to work to is the **main's own free end**, and the fall to
work to is the main's **carried on through it** - which is not the same as the
"falls towards the junction" rule the branch case uses. A run pointing back
along the main takes the opposite sign for the same physical fall, and getting
that wrong puts the two into a shallow V instead of one line.

- The lateral offset is measured and reported. Within 50mm (a setting) the two
  count as the same line and the run is **nudged sideways onto it** as part of
  the move, because a union will not take two ends a few millimetres apart.
  Beyond that they are refused as side by side, with a sentence saying the
  difference between "these never meet" and "these are the same run".
- The main's end has to be free; where something is already joined to it the
  refusal says so.
- A run pointing away from the main is still refused as behind.
- The body move is now in all three directions rather than only up and down,
  which is what carries the sideways nudge. The junction case is unaffected -
  its landing is already exactly on the crossing in plan, so the sideways part
  is zero.

New ticks: **Join two runs that are on the same line**, on, and **Counts as
the same line within** (50mm).

Bench: 590 logic checks. The in-line case is checked for a run beyond either
end of the main, a run that overshoots and is trimmed back, a run a few
millimetres off the line, a run two feet off it, a main end with something
joined to it, the tick cleared, a genuinely parallel run alongside, and the
fall rule on its own both ways round. New breakage: an in-line fall not
reversed for a run facing the other way.

## 1.7.0

**The junction now faces the direction of flow.** It went in, it was the right
size, it joined on all three ends, and it swept back up the main instead of
down it.

The reason it could: **a junction's three connector directions do not say
which way round it goes.** Its arm sits at 45 degrees to one run connector and
135 to the other, and the junction needs 45 one way round the main and 135 the
other - so *both* ways round satisfy every angle the tool was checking, and
which one came out depended on which way up the family happened to be placed
and which half `BreakCurve` happened to hand back. Half the time that is the
junction facing back up the flow.

So the tool asks the question the angles cannot answer: **a swept junction's
arm leans back towards where the water comes from**, so the run connector
making the acute angle with the arm belongs on the **upstream** half of the
main - and upstream is the higher end, because drainage falls. The way round
is chosen on that, and the angle test is applied afterwards rather than
instead.

Along with it:

- The family's own angle parameter is only driven **after** the way round is
  fixed, so it can never be used to force a family onto the way round it does
  not suit - which is what made 1.5.0 refuse a family that fitted perfectly.
- The fitting is **checked after it is turned and again after it is joined**:
  all three connectors have to be pointing where they were asked to, within a
  few degrees, or the placement is rolled back and the other way round is
  tried. Every failure in this part of the tool so far has looked finished,
  so it now proves its own work.
- Where the branch arrives **against** the flow the report says so, because a
  junction facing the other way is a different fitting and a different piece of
  design, not something to place quietly.
- The debug report names which end of the main the water comes from, which way
  round each attempt was, what angle that way round needed, and how many
  degrees off the fitting ended up.

Bench: 555 logic checks. The flow rule is a plain function over an angle and a
direction, checked for a swept junction both ways round, a square tee, a main
with a hair of fall, a level main, and that at every angle **exactly one** of
the two ways round faces the flow. New breakage: the way round chosen on the
angles alone, which is what every version up to 1.6.0 did.

## 1.6.0

**The Y goes in every time now, not sometimes.** Two runs a minute apart on
identical geometry gave opposite answers: one placed
`_PFI_Tee_Socket_uPVC_DWV_F&F` and joined it, the other refused it as "its
branch sits at 135 degrees to its run and the junction needs 45". The family
is a 45 degree swept junction and fits perfectly - the question was only which
way round it goes.

A junction's branch sits at some angle to one of its run connectors and at 180
minus that to the other, so which half of the main each run connector meets is
a **choice, not a fact** - and `BreakCurve` does not say which half it hands
back, so the order cannot be relied on either. 1.5.0 picked one way round,
found it 90 degrees out, and drove the family's own angle parameter to suit
that pick - which turned a family that fitted exactly the other way round into
a refusal, and only when the fitting happened to be placed the wrong way up.
Both ways round are now tested before a family is called unsuitable, and the
angle parameter is only driven after both have been tried.

**The fitting is the right size.** `NewFamilyInstance` places a fitting at its
type's default size and leaves it there; Revit's own `NewTeeFitting` sizes the
fitting from the pipes it is given. The junction is now sized from the three
pipes - through `Connector.Radius`, which has a setter on a family instance's
connector and drives the family's own size parameters, rather than by guessing
at parameter names - and sized **before** it is turned and moved, because a
bigger fitting is a longer one and every position read before the resize is
wrong afterwards. The report says what size each end came out.

**A squared junction now opens the results window.** Bringing a drainage
branch in square when it should sweep is a change of design intent, so the
fallback says so and names the junction family angle to load instead, rather
than passing as a note nobody sees.

Bench: 537 logic checks. The way-round decision is a plain function over two
angles and is checked for a 45 degree swept junction, a 135 degree one, a
square tee against both a square and an angled junction, and - the point of it
- the same family fitting whichever order the two halves of the main are
offered in. New breakage: only one way round tried.

## 1.5.0

**A fitting is a FamilyInstance and keeps its connectors somewhere else.** A
pipe is an `MEPCurve` and carries `ConnectorManager` on the element; a fitting
does not - its manager hangs off `MEPModel`. Only the first was being asked
for, which had two consequences. The obvious one: placing a junction family by
hand reported "the family has 0 connectors, not three" and gave up. The quiet
one, which had been there since the tool was written: **the run walk stopped
dead at the first bend**, so a branch made of pipe-bend-pipe only ever had its
first pipe and that bend moved. Both are fixed, and the same fix went into the
connected-fitting check, which had been reporting every fitting as
unconnected.

**An angled branch is squared into the main.** With the connectors fixed, the
by-hand placement can now read `_PFI_Tee_Socket_uPVC_DWV_F&F` properly and say
what it finds: its branch sits at 90 degrees to its run and the junction needs
45, and it carries no angle parameter - so it cannot be turned onto a 45 degree
branch and never could have been. That is not a failure to work around, it is
the family being a plain tee.

So the tool now does what a drainage layout actually does, and what Revit's own
Trim/Extend does with a plain tee family: **a square tee goes into the main, a
short stub runs square out of it, and a bend turns the branch into the stub.**

- The tee slides along the main by exactly enough that the stub, taken square
  to the main in three dimensions, lands on the branch's **own centreline** -
  so the run that was just put on the main's fall does not have to move again.
- Every fitting is placed by Revit's own calls, so the families come from the
  pipe type's routing preferences and the pipes are trimmed the way Revit
  trims them.
- The stub is three diameters long with a 150mm floor, or whatever length is
  typed into Settings.
- If the tee would slide off the end of the main it is refused and says so.

New ticks, both on: **Square an angled branch in with a stub and a bend**, and
a **Stub length** box.

The order of attempts for a crossing inside the main is now: Revit's own tee
(which works where the pipe type carries a lateral), then the junction family
placed and turned by hand (which works where it carries a swept junction),
then the square tee with a stub and a bend, then a takeoff.

Bench: 524 logic checks. The squaring is a plain function over points -
checked for a stub exactly square to the main in 3D, a bend exactly on the
branch centreline, a sloping main and branch, and a branch in line with the
main being refused. New breakage: the bend put off the branch centreline.

## 1.4.0

**The tee goes in at an angle now.** `doc.Create.NewTeeFitting` only ever
places a *square* tee: the moment the branch is not perpendicular it answers
"Fitting cannot be created between the input connectors because the angle
between them is too small or too large", which rules out every swept junction
and every 45 degree drainage branch there is. Revit's own Trim/Extend does not
use that call - it places the routing preference family and turns it onto the
three directions. So does this, now, as the fallback when `NewTeeFitting`
refuses:

- every junction family the main's pipe type routes to is tried in turn;
- the family's own branch angle is compared against the angle the junction
  needs, and where the family carries an angle parameter it is driven to suit;
- a family whose branch cannot reach the angle is reported and the next one
  tried, rather than being forced in crooked;
- the fitting is registered on **where its own axes cross**, not on its
  insertion point, because a lateral's branch meets its run part way along the
  body;
- the three pipes are cut back to the fitting's own ends - the half of trim
  and extend that placing a family does not do - and joined;
- all of it sits in a sub-transaction that rolls back unless all three ends
  actually connect, so a family that does not suit costs nothing.

New tick, on by default: **Place the junction family by hand if Revit refuses**.

**The routing preference read was asking for names that do not exist.**
`RoutingPreferenceRuleGroupType` spells its members in the plural - `Junctions`,
`Elbows`, `Crosses` - and every one was being asked for in the singular, so
every read threw and the tool reported "no junction or elbow family at all"
about a pipe type that had plenty. Both spellings are tried now, and where none
resolves the report lists what the enum actually offers.

Two things that follow from that: the "the main's type carries no junction
family, so it was left whole" guard was firing on a bad read and is now
trustworthy, and the report lists the families by name so a missing 45 degree
lateral is visible.

The debug report carries every junction attempt and what each one said.

Bench: 510 logic checks, with the 3D turns checked against the angles they were
asked for - including that a square tee is left 45 degrees out on a 45 degree
junction, which is what stops it being forced in. Two new breakages: the rule
groups asked for in the singular, and a square tee forced onto an angled
junction.

## 1.3.1

**The branch no longer comes apart at its bend.** Moving one end of a pipe was
written as `Line.CreateBound(the end that stays, the end that moves)` whichever
end was staying. A pipe's connectors are bound to the ends of its curve **by
index**, so where the end staying put was index 1 that reversed the curve and
swapped which connector was which. Revit answered with *"The duct/pipe has been
modified to be in the opposite direction causing the connections to be
invalid"* and *"The family is connected in a network and can no longer keep the
connectivity"*, disconnected the bend, and the run came apart - with the
geometry looking almost right, which is what made it hard to see. Every place a
curve is rewritten - the end pipe, the uprights, and the main when it is
carried out to an apparent crossing - now goes through `restretch`, which works
out which index is staying and writes the new curve in that order.

**"A connector went missing after the split" is fixed.** The tee looked the
branch connector up by an id captured **before** the move. Rewriting a
LocationCurve can renumber an element's connectors, so the id no longer named
the same connector and the tee was abandoned before Revit ever saw it. The
branch connector is now found by **where it is** - at the crossing - which is
how the main's two halves were already being found.

**The main is no longer split for a tee that cannot be placed.** The pipe
type's junction rules are counted first; where there are none the main is left
whole and the report says to load a junction family, rather than breaking the
pipe in half and putting it back together again on the way to a refusal.

**The routing preference read now says why it came back empty.** "No junction
or elbow family at all" and "the read threw" looked identical in the report and
mean entirely different things. Junction, Elbow, Cross, Union and Transition
rule counts and any exception all go into the debug report.

The debug report also carries the end pipe's endpoints before and after the
stretch and which index stayed put, so this class of bug is visible in the
report rather than only in Revit.

Bench: 484 logic checks, with "moving a pipe end reverses its curve" added as a
deliberate breakage - it fails six checks.

## 1.3.0

**A refused fitting no longer costs the move.** 1.2.0 put the move and the
junction in one transaction with the fitting in a sub-transaction, which is
not the same thing: an error the failure preprocessor did not resolve is still
an error at commit time, and Revit answers that by rolling the **whole**
transaction back. That arrived as "Revit did not commit the move" with the
move gone and nothing said about what Revit objected to. The move and the
fitting are now two transactions inside a `TransactionGroup`, so a refused
fitting leaves the run where it was put and undo still sees one step. The
group is safe here where one across the picks would not be: nothing pumps the
message loop between the two.

**Revit's own words are now reported.** The failure preprocessor deleted
warnings and returned Continue, which leaves an error unresolved and the
commit doomed. It now deletes warnings, resolves errors where Revit offers a
resolution, and **writes every failure down**. A rolled-back commit says what
Revit objected to instead of that it happened.

**A refused junction says what family it needs.** "The branch meets the main
at 135.0 degrees" left the reader to work out the rest. It now says that is 45
degrees off the main's line, that an oblique or swept junction family is what
that needs, that most pipe types carry only the 90 degree tee, and - where the
pipe type has no junction family at all - where to load one.

**Long messages in the results window wrap.** They were in a horizontal
StackPanel, which measures its children with infinite width, so TextWrapping
never fired and the end of every long sentence ran off the edge. It is a Grid
now, and a bench rule fails if wrapped text is ever put in a horizontal stack
again.

**New: a debug report**, on by default, under
Settings > Picking and shortcuts > Diagnostics.

- After every run of either tool a window opens carrying the settings that
  were in force, the geometry the decision was taken from - the main's
  gradient, both parameters along the crossing, the crossing point, the case
  each pipe was classified as, the tilt in radians, the plan angle and how far
  off the main's line it is - every step taken, and Revit's own description of
  anything it refused.
- **Copy** puts the lot on the clipboard. It is also written to
  `%APPDATA%\RevoBIM\match_offset_debug.txt` whether the window is opened or
  not, so closing it does not throw the report away.
- The tick turns it off; nothing else changes when it is off.

Also: the themed TextBox can scroll and grow now - its template fixed the
scrollbars to Hidden, so a multi line box could never scroll however its own
properties were set.

Bench: 31 static rules and 468 logic checks. Three new deliberate breakages -
Revit failures deleted and forgotten, a refused junction reporting the angle
and nothing else, and a debug report with no settings in it.

## 1.2.0

**New: RevoBIM Match Offset Slope**, a fifth button in the same pulldown, for
connecting an existing drainage run into a main.

- Click the main; every click after it takes a branch run, puts its horizontal
  part on the main's fall, lands its free end on the main's centreline at the
  point the two centrelines cross **in plan**, then trims or extends it in and
  fits it.
- A crossing inside the main splits it with `PlumbingUtils.BreakCurve` and puts
  a **tee** across the three ends. A crossing at the main's end gives a
  **bend**, or a **union** where the two runs turn out to be in line.
- A crossing **past the end of the main** is an apparent intersection: where
  that end has nothing joined to it, the main is carried out to meet it, the
  branch is raised to the height the main's own fall would reach there, and a
  bend goes in. Where the end is already joined, it is refused and says so.
- The horizontal run travels as **one rigid body** - tilt about the end that
  meets the main, stretch that end to the crossing, raise the lot - so every
  joint in it stays joined. **Uprights are let go, re-cut to follow, and
  reconnected**, so a stack never blocks the move and the floor above is never
  disturbed.
- The two things that quietly break `NewTeeFitting` are handled: the halves of
  the split main are explicitly disconnected first, and they are retried in
  the other order. When Revit still refuses it falls back to a takeoff, and if
  that fails too it says the angle the branch meets the main at and what the
  pipe type's routing preferences actually offer, leaving both pipes touching
  so Trim/Extend finishes it by hand.
- Suggested shortcut **AS**, alongside AB, AQ and AT.

The settings window is now **three tabs** - Match Offset, Match Offset Slope,
Picking and shortcuts - because there are two tools' worth of settings in it
and a window has to fit a section without scrolling. Plain buttons swapping
Visibility rather than a TabControl, which would need a control template of
its own to be themed.

New slope settings: match the branch's slope on or off; take the fall from the
main or from a fixed 1 in N; fall towards, away or the way it already does;
extend and trim on or off; the junction to suit or ends-together only; allow
an apparent intersection; carry the main out to it; the upright angle; and the
run length the walk refuses past.

Settings version 3. A v1 or v2 file loads unchanged.

Bench: 30 static rules and 410 logic checks. The geometry lives in a module
with no Revit and no WPF in it - which is its own rule now - so the whole
decision, crossing to tilt to landing, runs on the bench. Four new deliberate
breakages, including the tilt applied the wrong way round and an apparent
crossing ignoring a joined main end.

Two things the bench found while it was being written: the cross-module name
check had never once looked at an aliased import, so `import mos_geom as geom`
resolved against nothing; and the Rodrigues rotation in `apply_tilt` had two
cross-product terms the wrong way round, which is a rotation by minus the
angle - still a tilt, just the wrong one, and not something reading the code
would have found.

## 1.1.0

**The first element clicked now moves onto the rounded value too.** With
rounding on, v1.0.0 rounded the datum and put every *later* element on it
while leaving the element it was read off where it was, so a bank ended up
one element out. The source is now matched to the rounded datum as well, and
the whole bank - the element the number came from included - sits on one
value. Off when rounding is off, since there is nothing to move it to, and
there is a tick in Settings for anyone who wants the old behaviour.

- New setting: **Move the first element onto the rounded value too**, on by
  default. Settings version 2, with the migration entry to go with it.
- The source is moved using the measurement taken at capture, so it is not
  measured twice.
- A source that cannot move - in a group, owned by somebody else - is
  reported, and the datum still stands for everything after it.

Speed and efficiency, everywhere it is actually spent:

- **`ISelectionFilter.AllowElement` runs on every element the cursor
  crosses.** It is now one attribute chain against a `frozenset` of ints.
- **`eid_value` resolves the release once.** `.Value` or `.IntegerValue` is
  worked out on the first call and remembered, rather than two probes and a
  swallowed exception every time.
- **Every `BuiltInParameter` member is resolved once**, on first use, and the
  name tuples with it - still late enough that a member a release lacks
  cannot kill the module at import, but no longer a `getattr` per element per
  lookup.
- **The settings are resolved once into a `RunConfig`** before the first pick,
  instead of a dozen string comparisons and two float parses per click.
- **The log is buffered and written once**, in a `finally`, rather than
  opening and closing the file per element.
- **Level elevations are read once per document per run** and searched in
  sorted order, rather than a `FilteredElementCollector` per element.
- **`Location`, `ConnectorManager` and the bounding box are each fetched once
  per measurement** rather than two or three times.
- **Worksharing is only asked about on a workshared model.** Two API calls per
  element saved on every non-workshared file, and the borrow is one call for
  a whole pre-selection rather than one per element.
- One `IFailuresPreprocessor` instance for the session rather than one per
  transaction.
- Bench: two new static rules (settings resolved once, the log flushed in a
  finally) and two new logic breakages, so none of the above can quietly come
  undone. 29 rules and 269 checks, all proved by deliberate breakage.

## 1.0.0

First release.

- Four buttons in a **Match Offset** pulldown on the **RevoBIM PY** tab,
  **Coordination** panel: Match Offset Bottom, Match Offset Middle, Match
  Offset Top and Settings.
- The three command buttons open no window. First click takes the top, middle
  or bottom offset off the element clicked; every click after it puts the next
  element's own top, middle or bottom on that same offset. Escape finishes.
- Each command carries a unique ribbon name prefixed "RevoBIM " on a single
  line, so Revit's own Keyboard Shortcuts dialog can find it and bind keys
  to it.
- Settings: round the captured offset to the nearest N mm (default 0, which
  is off), up / to nearest / down, against the element's own level offset or
  against the project elevation.
- Settings also carry the three key sequences (AB, AQ and AT by default) and
  a button that writes them into Revit's KeyboardShortcuts.xml, backing the
  file up first and asking before it takes a key off whatever holds it.
- Dark and light, following Revit's own canvas by default, with an
  Auto / Dark / Light chip in the header.
- Results are reported only when something needs a look. A clean run finishes
  with no dialog at all.
