# System Offset Tools — changelog

## v5.5.0

**Clash Offset can go round things in this model, not only in links.**

It could not before, and the reason is a Revit detail worth writing down:
`ObjectType.LinkedElement` will pick the beam *inside* a link but nothing in
the host model at all, while `ObjectType.Element` hovers a link as one whole
building rather than the beam inside it. **One pick cannot cover both.** The
tool asked with LinkedElement only, so model elements were simply unreachable.

There are two picks now, and either can be skipped with Escape: **this model
first, then links**.

**A selection can hold both.** Select the services and the things to avoid
together, press the button, and the tool sorts them out: the pipes, ducts,
cable tray and conduit are what moves, and everything else in the selection is
what they move around. No picking at all in that case.

Two things that fall out of it:

- **The services cannot be picked as their own obstruction.** They are filtered
  out of the model pick, because a run offset around its own body is an easy
  mistake to leave available.
- **A whole link instance selected by accident is ignored** rather than treated
  as an obstruction, since its geometry is the entire building. Its contents
  are what the linked pick is for.

Obstacles are de-duplicated by element and by whether they came from a link, so
picking the same beam twice does not build the jog twice.

## v5.4.0

**Clash Offset measures the service the way it is about to move.**

v5.3.0 took the service's largest dimension whichever way it went, so a
600 x 300 duct was treated as 600mm wide even when it was going straight up. It
is measured off its real geometry per direction now: **300 out to the side, 150
up**. The offset is the obstruction's reach that way, plus the service's own
half size that way, plus the clearance.

**Insulation and lining count.** They are separate elements in Revit, so a
plain geometry read misses them entirely and the service gets offset by its
core size while its lagging still fouls what it was meant to clear. 25mm of
lagging on that duct now reads as 325 sideways and 175 up.

**It cuts to the real overlap, not the whole obstruction.** Where Revit will
give a boolean intersection it is used, so a beam running nearly along a
service no longer makes the jog long enough to clear metres of beam. The whole
obstruction stays as the fallback, and the window says which it used.

**A bank is measured run by run.** Each service's own size in the chosen
direction is taken, and the offset is whatever the one needing the most room
needs — so a small pipe beside a large duct is not offset on the duct's size,
and the large duct is not left fouling on the pipe's.

A pre-selection is still all that is needed: select the services, press the
button, pick what is in the way. The window says how many are moving together.

345 logic checks — including a round pipe reading the same every way, a
rectangular duct reading differently, lagging widening both, and a worked
column where going round needs 750mm and going over needs 3200mm.

## v5.3.0

**New button: RevoBIM Clash Offset.** Pick the services, pick what they clash
with — in this model or in a link — and the tool jogs them clear of it.

**It works out where, which way and how far.**

- *Where:* the obstruction's own reach along the run. The cuts sit back from it
  by the clearance **and by a bend's worth**, because the offset middle does not
  start at the cut — it starts a bend in. Without that the sloping legs clip
  the very thing being avoided.
- *Which way:* the shape says what should be preferred — a column is gone
  round, a beam is gone under — and the numbers say whether that preference is
  affordable. Going round a column is right up until it costs four metres and
  going under costs three hundred, at which point the cheaper way wins and the
  report says why.
- *How far:* far enough that the service's near face clears the obstruction's
  far face, plus the clearance, rounded onto the 5mm grid.

**Real solids, not bounding boxes.** A box is axis aligned, so a beam running
at an angle reads as far bigger than it is and the service gets pushed much
further than it needs to go. Edge points are used instead, with the box only as
a fallback for something with no usable geometry — and a box only ever
overstates, so the fallback errs safely.

**Linked models work.** A pick inside a link gives the link instance and the
real element separately; both are unpicked and the link's own transform is
carried through, so a link that is moved, rotated or on a shared coordinate
system needs no special case.

**A bank moves as one.** Several parallel services stay parallel and evenly
spaced round the clash, using the staggered-bend geometry the offset tools
already have — and the distance is taken from the service that needs the most
room, not the one that happened to be picked first.

**Nothing is written until the button is pressed.** The window lists every
clash, what it decided and why, what each of the four ways out would cost, and
lets the direction be overruled per clash. The clearances can be changed and
everything recalculates.

Two clearances of its own, saved alongside the rest: **clear it by** 50mm, and
**start the bend** 100mm before it. They live in this tool's window rather than
the Settings one, where the number can be seen against the clash it applies to.

Known rough edge: the service's own size is taken from its largest dimension,
so a 600 x 300 duct is treated as 600 whichever way it moves. That over-clears
the narrow way by 150mm, which is the safe direction to be wrong in.

334 logic checks, 20 bench rules.

## v5.2.0

**Fixed: "the click is -143939mm along".**

On the very first action the route's direction was taken from the way the run
reads on screen, not from where the click landed, so a click behind the run
sent the whole calculation off the other way. It comes from the click now —
the same rule the horizontal path already used. The screen rule stays as the
fallback for when there is nothing else to go on.

**A level change now fits the room it is given, rather than refusing.**

The height is the point of the move and is never given up. Everything else
bends to fit, in the order that costs least:

1. use the run on as asked
2. shorten the run on, down to nothing
3. steepen the angle, up to a square riser, which takes no run in plan at all

Asking for a 1000mm rise at 45 degrees with a 3000mm run on:

| Room the click gives | What it builds |
| --- | --- |
| 4010mm | as asked |
| 3000mm | run on 1990mm, still 45 degrees |
| 1200mm | run on 190mm, still 45 degrees |
| 600mm | run on 10mm, steepened to 59.9 degrees |
| 120mm | run on 10mm, steepened to 84.3 degrees |
| 15mm | refused — there is genuinely nowhere to turn |

Whatever it does, it says so. The bench asserts the pieces always add up to the
room available, that the landing is always usable, and that the rise still
gains the full height at whatever angle it settled on — across every one of
those cases.

A click behind the run is now told that plainly instead of being handed a
negative distance.

321 logic checks.

## v5.1.0

**Set Up and Set Down work from the moment the tool opens.** They were greyed
until a horizontal piece existed, because the route had no known forward end
before the first click. It does now: the direction is taken from the way the
run reads on screen — the same rule left and right already use — so a route
can start with a level change.

**A level change is now three pieces**, which is what was asked for:

1. the run **carries on** for the run-on distance, so the turn does not sit
   right on the end of what was already there;
2. it **rises or falls** by the offset, at the angle;
3. it **runs on straight at the new level**, as far as the click reaches along
   it.

Two bends, neither of them in plan. The click sets how far piece 3 goes;
everything before it comes from the window, which is what keeps the whole move
to one press and one click.

**Run on** is a new field, defaulting to **500mm**. Set it to 0 and the turn
starts at the end of the run.

A click that does not reach past all three pieces is refused with the
arithmetic: running on 500mm and turning 500mm at 45 degrees needs 1010mm
before there is anywhere to land, and the message says how far the click
actually was.

288 logic checks.

## v5.0.0

**Fixed: Set Up and Set Down looked like they did nothing.**

They were firing. Each press placed a riser straight off the end of the last
one, so pressing up twice stacked two risers end to end — which is why the log
carried four "Taken up" notes and three refused elbows measuring **0 degrees**
(two collinear risers joined end to end) and **180 degrees** (up, then straight
back down on top of itself). The route walked into the air and nothing read as
having happened.

**Set Up and Set Down now arm the next click**, which is what was wanted:
press one, click in Revit, and the run goes **straight to the click and then
rises or falls by the offset**. Two pieces, no bend in plan.

**A rise angle**, in the same section, defaulting to **45 degrees**. The plan
run a rise takes is `height / tan(angle)` — 500mm at 45, 866mm at 30, nothing
at 90, which is a plain riser and the old behaviour.

**A stacked bank keeps its height.** Every run gains the same height over the
same plan run from its own end, so services above one another stay exactly as
far apart as they were. Worth knowing: that leaves them closer together *square
to* a sloping leg than they are vertically, by `cos(angle)` — 300mm apart
vertically is 212mm apart square to a 45 degree leg. Holding the height was
what was asked for and it is the right call, but it matters if a bank is tight.
Both numbers are in the bench.

Two smaller things from the same screenshot:

- The report said **"System Offset"** and **"0mm at 45 degrees"** on a routed
  run. It names the tool it came from now, and a routed run no longer gets an
  offset's one-line summary, because it has no single distance or direction to
  report.
- The piece leaving a sloping rise starts **at** its end rather than stretching
  it, the same as for a vertical riser.

276 logic checks.

## v4.9.0

**Click System's window is now two jobs, not one.**

**Horizontal placement** holds the angle tiles, the angle and the length, and a
green **Place Horizontal Bends** button at the foot of the section. That green
button is what goes back to Revit to pick corners — it replaces the old Apply.

**Height adjustment** is new, below it. It takes the run **straight up or
straight down** by a set offset, with no bend in plan and **no click at all**:
press **Set Up** or **Set Down** and it is placed. Both carry an arrow icon,
green for up and orange for down, drawn as `Path` geometry so they cannot come
out as empty boxes on a machine without the symbol font.

The riser is copied from the piece it leaves, so size, type, system and level
come across, and an elbow goes in where it turns. For a bank it is the same
move for every run, so the spacing is untouched.

Two things worth knowing:

- **The piece that leaves a riser starts AT the riser rather than extending
  it**, because a riser cannot be stretched sideways to reach a corner. The
  bend there is square whichever way it heads, so the chosen angle does not
  apply to that one piece.
- **Set Up and Set Down are greyed until the route has an end to take** — that
  is, until one horizontal piece has been placed. Greyed rather than hidden, so
  it is clear the section is there and why it cannot be used yet.

A riser needs no click, so pressing Set Up returns straight to the window ready
for whatever comes next, rather than back to Revit.

The window is resized to carry both sections without scrolling.

## v4.8.0

**Escape now reopens the prompt instead of ending the run**, in Click System.

Mid-route, Escape in Revit brings the window back so the angle or the length
can be changed, and **Apply goes straight back to picking** where it left off.
**Finish** in the prompt is the way out of the tool. The pick prompt says so.

**The prompt gained a length.**

| Length | What the click means |
| --- | --- |
| blank | the new piece runs **to the click**, as before |
| set | the click only puts the corner and says **which way to turn**; the piece is the length asked for |

**A tile now selects rather than commits.** Pressing 90 fills the angle in and
lights the tile up; Apply is what returns to Revit. That had to change with
this release: the window is now reached mid-route to change something, and a
tile that committed the moment it was pressed left no way to set an angle and a
length in the same visit.

The tick is now *"keep these for the rest of the run"* — it holds the length as
well as the angle.

259 logic checks, covering a set length at 90 and at shallower angles, straight
on, on either side, and a corner with nothing behind it to cut.

## v4.7.0

**Sloped runs keep their fall.**

### Click System

A click in a plan lands on a level work plane, so a route set out from those
clicks came out **dead flat** — a pipe at 1:60 turned into a level one the
moment it was extended. Now every corner and every end is worked out in plan
and then **dropped back onto the run's own gradient**, so each new length
carries the same fall as the one before it, click after click, round every
corner.

Two things fall out of that beyond the obvious. The corner now lands exactly on
the sloped run's centreline, which is what the split at the first click needs to
work at all. And a bank of sloping runs each carries **its own** fall from its
own end, rather than every strand being levelled onto the leader's.

Only in a plan. In a section or an elevation the click's own height is what you
meant, and it is used as picked.

### Offset Break

Holds the run's gradient on **every** piece — the bend leg and the stepped run
both — because a break does not come back to the line it left, so there is
nothing to compromise with. Sideways offsets only: up and down exist to change
level, and holding the fall there would defeat them.

### System Offset

Already keeps the two ends and the long middle exactly on gradient. It cannot
put the two bend legs there as well, and that is arithmetic rather than a
shortcoming: **a jog is longer in plan than the straight it replaces, and at a
fixed gradient extra length is extra fall.** A route holding the gradient on
every piece arrives *below* the pipe it has to rejoin — by
`2 x offset x tan(half the bend)`, which is 4mm for a 300mm offset at 45
degrees on a 1:60 fall, 10mm at 90 degrees — and no choice of span or angle
avoids it.

So the ends and the middle hold the fall, the two short bend legs carry the
difference, and the report now **says so with the number** rather than leaving
it to be found.

The whole of it — gradient as rise over plan run, putting a plan point back on
grade, the jog shortfall, and a break holding grade end to end — is bench
tested. 245 logic checks.

One of those tests failed first time and the code was right: measuring a
turning route corner to corner reads steeper than its gradient, because the
fall follows the path and the path is longer than the straight line. Worth
knowing before anyone checks one of these by eye.

## v4.6.0

**Fixed: pipes and ducts offset wrongly; cable tray and conduit were fine.**

That split is the whole diagnosis. Cable tray and conduit have no `BreakCurve`
utility, so they went through this tool's own copy-and-re-cut, which builds
both halves itself and knows exactly which is which. Pipes and ducts went
through `PlumbingUtils.BreakCurve` / `MechanicalUtils.BreakCurve` — and the
code **assumed the element those return is the far half of the cut**.

Revit makes no such promise. Where it handed back the near half instead, the
original run kept its full length, the second cut then landed on the wrong
piece, and the offset was built over the top of a run that had never been
shortened: the overlapping duct in the screenshot, with Revit's warnings on it.
The two bends that could not find a fitting were downstream of the same cause.

`split_at` replaces `break_at` and **measures which half is which** rather than
assuming, returning both in order along the run. Both routes now go through it,
so the native split and the copy-and-re-cut behave identically — which is what
was asked for: pipes and ducts doing what the cable trays do.

The rule itself is `so_core.halves_in_order`, bench tested including a run
drawn the other way round and one off axis. 225 logic checks.

Two smaller things fell out of it: `_on_side`, which existed only to guess
which half was which, is gone; and the "Broken by" note now reads "Split by",
naming which of the two routes was taken so the next report says which code
path ran.

## v4.5.2

Two fixes, both of them mine.

**"Fitting cannot be created ... the angle between them is too small or too
large", on two of the four bends, every time.**

v4.1.0 turned off the `doc.Regenerate()` between the four bends as a speed
optimisation, reasoning that every connector is re-fetched live so the model
did not need catching up. That reasoning was wrong. Re-fetching a connector
does not help when the model has not regenerated: Revit shortens the two pieces
either side of a bend to make room for the fitting, and the next bend was
reading the piece as it had been **before** the previous elbow shortened it. So
bends one and three took a fitting and bends two and four did not, on every
offset.

`REGEN_BETWEEN_BENDS` is back on. It costs three regenerates per offset, and I
had written "flip this to True if a bend ever comes out in the wrong place"
next to it, which is exactly what happened.

A refused bend now also reports **the angle Revit actually measured**, because
that number is the one thing that separates wrong geometry from a family that
simply does not cover the angle.

**Left and right depended on which way the run happened to be drawn.**

Right was taken from the element's own axis, which points whichever direction
the duct was drawn in, so the same run drawn the other way round offset the
opposite way. The guard meant to correct that compared the side vector against
the view's right direction — and for a run lying across the view that dot
product is exactly zero, so it never corrected anything at all.

Right is now the right hand of somebody walking the run **the way it reads on
screen**: left to right, and bottom to top where the run goes straight up the
view. Same run, same answer, whichever way it was drawn. The rule sits in
`so_core.side_of_travel`, bench tested against the exact case the old guard
missed. 221 logic checks.

## v4.5.1

**Fixed: "global name \'bank\' is not defined".** v4.5.0 could not start the
picks at all.

The block that reads the selection never landed. It was inserted by a text
replacement whose anchor did not match, so the edit did nothing and said
nothing, while the later edits that USE the selection matched perfectly well.
The result compiles, imports, passes every check the tool shipped with, and
fails on the first line that runs.

**`import_check.py` gained the rule that catches this**, and it is one the
house table reference already called for — *every global name a function
reaches for exists in its module* — which I had left out. Walked with
`symtable`, so it understands scopes, comprehensions and nested functions, with
the names IronPython injects into a pyRevit script (`__revit__`, `unicode`,
`xrange` and friends) allowed for.

Putting the missing block back out again confirms it fires on exactly what
shipped:

```
so_run.py: run reaches for "bank", which nothing defines
so_run.py: run reaches for "chooser", which nothing defines
```

20 rules now, all 20 proved by `--selftest`.

## v4.5.0

**System Offset and Offset Break now run on a whole selection.** Select several
parallel runs, press the button, take the same two clicks on any one of them,
and all of them are offset together — staying parallel and keeping their
spacing.

Runs that are not parallel are refused: *"Elements not parallel. User must
manually review them."*, with the worst pair's angle. Nothing is changed.

**The bends are staggered, and that is the whole point.** Putting every run's
bend at the same station along the run pulls the diagonals closer together than
the straight legs — by `cos(angle)`, so 300mm of spacing becomes 212mm at 45
degrees, 260mm at 30, and 0mm at 90. Each run is therefore a parallel **offset**
of the leader's route rather than a copy of it: every leg shifted square to
itself by the same distance, and each corner found where the shifted legs
cross. That moves each bend along its own run by `spacing x tan(half the turn)`,
which is exactly the staggered set of parallel diagonals you would draw by
hand.

Spacing square to the plane the offset turns in — runs stacked above one
another when offsetting left or right, or spread side by side when offsetting
up or down — needs none of that and is a plain shift. Which part is which is
worked out per run, so a bank that is both spread and stacked is handled
without a special case.

**Where a bank will not fit, the click is taken again.** Staggering moves the
outer run's bends along its own length, so a span that suits the middle of a
bank can run off the end of the outside of it. That is not a failure to report
and move on from, so the tool says **"Make second click further away"**, with
what ran out, and goes straight back to the picks.

Both bench checks grew: the staggered spacing is measured on every leg at
several angles, **against the same-station version**, so the wrong answer is
written down next to the right one. 203 logic checks.

`rule_no_duplicate_defs` was matching on indentation, so two classes each
carrying an `AllowElement` — correct and normal for two selection filters —
failed the check. It walks the syntax tree now and knows one scope from
another.

## v4.4.0

Two things for **Click System**.

### Route a whole bank at once

Select several parallel runs before pressing the button and they are all routed
together, staying parallel and keeping their spacing round every corner. No run
needs picking — the selection is the input. Runs that are not parallel are
refused: *"Elements not parallel. User must manually review them."*, with the
worst pair's angle, and nothing is changed.

**A bank is not the leader's route copied sideways, and that matters.** Two
pipes side by side running east, translated 300mm north, are 300mm apart on the
leg that runs east and **exactly on top of each other** on the leg that turns
north — they end up collinear. Spacing has to be measured square to each leg,
which makes each strand a parallel **offset** of the leader's route: every leg
shifted sideways by the same distance, and the corner found where the shifted
legs cross. The outer strand turns later than the inner one, which is what
keeps the bank square across itself the whole way round.

Spacing straight through the routing plane — services stacked one above another
in a plan route — is a plain shift and needs none of that, so an offset is
split into the two parts and each is handled the way it needs.

Both cases are bench tested by measuring the spacing on each leg, including the
translation version, so the wrong answer is written down next to the right one.

### A bend angle per corner

After the run is chosen and before the click that places the corner, a small
window offers **90, 45, 30, 22.5 or manual**, defaulting to 90. Ticking *use
this angle for the rest of the run* keeps it and the window stops appearing,
which is what makes a square route four clicks rather than eight. It is ticked
by default.

**A bend of less than a right angle has to start before the click.** At 90
degrees the corner sits square under the click; at anything shallower it must
begin `sideways / tan(angle)` earlier or the leg cannot arrive at the click at
all — the same arithmetic the offset tools use, met from a different
direction. Where there is not enough run to start that early the click is
refused, saying how much earlier it needed to begin and suggesting a squarer
angle. The turn is bench checked to be the angle asked for to 1e-9, and to land
exactly on the click.

181 logic checks, 19 bench rules, all 19 proved by `--selftest`.

## v4.3.0

**New button: RevoBIM Click System.** Route a service by clicking.

Click a run, then click where it should go: the run carries on to the corner, a
90 degree bend goes in, and a new length runs out to the click. Every click
after that does the same again from the end of the last one, until Escape.

**One operation, used every time** — extend the current length to the corner,
put a bend at the corner, run a new length out to the click. The corner is the
click projected back onto the current length's own axis, so the turn is exactly
square by construction rather than by rounding to it.

The first click is that same operation with one extra step. Where the corner
falls inside the run, the run is **cut there and whatever lies beyond is let
go**, so the new route is its own system. The first leg is not a new piece
bolted onto the run — it **is** the run, carried on to the corner, which is
what makes "split at the point of the bend" mean anything. Every click after
that extends lengths this tool made itself, which have a free end and nothing
to let go of, so nothing is ever cut again and the route stays one system.

Other decisions worth knowing:

- **A click in space is not where Revit says it is.** `PickPoint` returns a
  point on the view's work plane — in a plan, the level, not the height the
  service is at. Each click is projected onto the plane through the current end
  parallel to the view, which keeps a plan route at its own elevation and a
  section route at its own depth, with one rule for both.
- **A corner behind the current end is allowed.** It shortens the current
  length rather than being refused; the real constraint is that enough of that
  length survives to hold its own joint, not that you clicked forwards.
- **A click straight ahead adds no bend** — the length simply carries on. A
  click a few millimetres off the axis is refused rather than fudged into a
  bend nobody can see.
- **New lengths are copied from the run**, so size, type, system, insulation,
  level and workset all come across without any of it being read and reapplied.
- **One transaction per click**, so a click that will not work costs that click
  and not the route, and Escape at any point leaves everything already routed
  committed.
- Where the corner lands past the end of a run that is joined to something
  there, the click is refused rather than driving the run through its own
  neighbour.

**Bench.** The corner rule lives in `so_core.plan_corner`, duck typed on
`DotProduct` / `Multiply` / `GetLength`, so it runs against a plain vector on
the bench instead of against Revit — including that the turn is square to 1e-9
and that it holds on a run heading in any direction. 142 logic checks.

`rule_command_buttons_differ` was quietly broken by the third button: it only
fired when **all** the loaders started identically, which with two buttons is
the same test and with three is not. It fails on any two matching now, and the
selftest catches it — which is the whole reason for having one.

## v4.2.1

**A completed offset now says nothing.** The report was opening after every
single run.

The cause was that a record carried one list. A successful offset fills it with
perfectly ordinary remarks — "Broken by BreakCurve", "Copied BGL_Service Type",
and for Offset Break "the run is cut at the second click" — and the rule that
decided whether to open the window treated any entry in it as something needing
a look. The remarks were right; counting them as problems was not.

A record carries **two** lists now:

- **notes** — what happened, for the record. Never opens the window.
- **problems** — what did not go the way it should: a bend that would not take
  a fitting, fewer fittings than the mode expects, a refusal. The only thing
  worth interrupting somebody for.

The window opens on a refusal or a problem and stays shut otherwise. When it
does open it now lists **only the offsets that earned it**, so one awkward
offset in a run of twenty is not something to hunt for, and problems are picked
out in orange above the notes.

The rule moved into `so_core.needs_reporting`, out from behind WPF, so it is
bench tested rather than taken on trust — including the specific case that
broke: a clean offset carrying three notes and no problems must stay silent.
120 logic checks now.

## v4.2.0

**New button: RevoBIM Offset Break.** The same two clicks, the same prompt and
the same settings as RevoBIM System Offset — but the run does not come back
onto its own line.

- Click where the break starts, click where to cut.
- The prompt offers the distance and the four directions, as before.
- The piece between the clicks steps across on **two** bends, the run is cut at
  the second click, and **whatever lies beyond the cut stays exactly where it
  was**, disconnected. That disconnection is the gap.

It is a single command button with a unique ribbon name, so it can be bound to
its own key — search "RevoBIM Offset Break" in Revit's Keyboard Shortcuts.

**A break has twice the room a jog does.** Only the turns that head back ALONG
the run eat into it: a jog turns out and back and pays twice, a break turns out
and stops and pays once. `plan_offset` and `max_offset_mm` take a bend count
now, and the bench asserts the prompt's limit and the routine's fit test agree
in **both** modes at every angle — a prompt that offers a number the routine
then refuses is worse than no prompt.

Everything else is shared. One `analyse`, one prompt, one pick loop, one
transaction group and one rollback path; only which pieces get built differs.

**Bench:** two new rules. Ribbon names are now checked across **all** buttons
for uniqueness and consistency, and `rule_command_buttons_differ` fails if the
two command loaders call `so_run.run` the same way — they are near identical
files, so one copied without changing the mode would give two buttons that do
the same thing and look entirely correct. 19 rules, all 19 proved by
`--selftest`; 111 logic checks.

## v4.1.0

**The offset now defaults to 1x the width of the service**, rather than 3x. A
migration resets the multiplier, so a saved 3 does not come forward.

**Faster.** Three things were costing real time, in this order:

- **`doc.Regenerate()` was called about a dozen times per offset** — after each
  break, inside each copy, after every curve edit, and once before each of the
  four bends. On a real model each call is a meaningful fraction of a second
  and it is by far the dominant cost. The work is batched into **four** now:
  one after each break, one after every curve edit together, and one at the
  end. Cable tray and conduit, which have no `BreakCurve` and are split by copy
  and re-cut, drop from six to two on top of that.

  The four regenerates between the bends are the one that needed thought. Revit
  shortens the two pieces either side of a bend to make room for the fitting,
  so in principle the next bend wants the model caught up. In practice every
  connector is already re-fetched live and the ends the previous elbow touched
  are not the ends the next one measures. `REGEN_BETWEEN_BENDS` at the top of
  `so_model.py` puts them back if a bend ever comes out in the wrong place.

- **`Theme.xaml` was re-read and re-parsed for every prompt**, and the prompt
  opens once per offset. File reads are cached and the logo bitmap is built
  once and frozen. The dictionary itself is still parsed per window on purpose
  — a `ResourceDictionary` shared between two live windows is a source of very
  quiet bugs, and the read was the part worth saving.

- **`kind_of` ran an import, four `getattr` calls and four `int` conversions
  every time it was asked** — and it is asked from
  `ISelectionFilter.AllowElement`, which Revit calls for every element the
  cursor passes over. It is a cached dict lookup now, which is the difference
  between a filter that feels instant and one that does not.

**Streamlined.** `perpendicular_part`, `nearest_direction` and the unused
`as_bool` and theme imports were left behind by the v4 redesign and are gone.
`_build` reads as one sequence rather than a chain of conditionals on settings
that no longer exist.

87 logic checks, 18 bench rules, all 18 proved by `--selftest`.

## v4.0.0

**The direction is now asked for, not guessed.** Click the start, click the
end, and a prompt opens carrying the calculated distance in an editable box and
four direction buttons. Press one and the offset runs, the prompt closes, and
the tool goes straight back to waiting for the next first click. Escape at the
prompt cancels that one offset and keeps the tool running; Escape on the first
click finishes.

**Fixed: v3 refused almost every offset.** The second click was a `PickPoint`,
so the point sat on the view's work plane rather than on the run. Projected
back onto the centreline it frequently landed at or past the end of the
element, and the guard that wanted 10mm of run left at each end refused it —
"Click a little further in from the ends", however far in you clicked.

Two changes, either of which would have been enough:

- both clicks are `PickObject(PointOnElement)` again, so the point is genuinely
  on the run;
- a cut that lands at or past an end is now **clamped inward** rather than
  refused. Refusing was the wrong answer anyway. The run is only turned down
  when it is too short overall to cut an offset into, and the clamp is
  reported.

**Settings cut to two.** How far to offset (a multiple of the service width,
now defaulting to **3x**) and the angle (45 degrees). The 5mm rounding, the
25mm floor, the fittings, the service-type copy and the reporting are constants
rather than settings — a setting nobody changes is only another way to get it
wrong. The theme is the header chip and nothing else.

**Categories are now exact.** Pipes, ducts, cable tray and conduit, matched on
`BuiltInCategory` id. v3 matched on words in the category name, which swept in
Flex Ducts and Flex Pipes — neither has a straight centreline to offset.

Also:

- Left and right take their sign from the **view's own right direction**, so
  "left" on the prompt is left on the screen rather than left in world
  coordinates.
- Up and down are greyed out on a vertical run rather than refused after the
  fact.
- The prompt shows how much room the two clicks leave, and will not accept a
  distance that will not fit. `max_offset_mm` and `plan_offset` are
  bench-checked against each other at every angle, so the prompt can never
  offer a number the routine then turns down.
- Arrows are `Path` geometry, not a symbol font.
- 84 logic checks, 18 bench rules, all 18 proved by `--selftest`.

## v3.0.2

**The bundle folder can no longer collide with the old one.**

v3.0.0 and v3.0.1 shipped as `System Offset.pulldown` into a panel that
already held `System Offset.pushbutton`. pyRevit names a ribbon item after its
folder, so the two collide with "The name already exists" — and pyRevit does not
just skip the bad one, it **abandons the rest of that panel**, so half the
extension's buttons disappear and the tool shows a blank pyRevit window.

Relying on the delivery notes to have the old folder deleted was not a design.
The folder is now `System Offset Tools.pulldown`, with `title: System Offset`
in its `bundle.yaml`, so the ribbon still reads "System Offset" but nothing can
clash. If the old button is still installed you get two entries side by side —
visible and harmless — rather than a broken extension.

- `import_check.py` gained `rule_no_legacy_name_collision`, which fails if the
  bundle folder stem is one an earlier delivery used. 18 rules now, all 18
  proved by `--selftest`.

## v3.0.1

- Both loaders drop a **breadcrumb before importing anything that can fail**,
  so a death at module load leaves something to read rather than a blank
  window with no traceback. Stages are named per module, and the log records
  the engine version and the folder it ran from.
- `import_check.py` gained a **no non-ASCII outside a `u''` literal** rule.

## v3.0.0

Rebuilt as a pulldown against the house theme and structure reference.

**Structure**

- Now a **pulldown** on the Coordination panel holding **RevoBIM System
  Offset** and **RevoBIM System Offset Settings**, replacing the single
  `System Offset.pushbutton`. **The old pushbutton folder has to be deleted**
  — pyRevit names a ribbon item after its folder and a `.pulldown` and a
  `.pushbutton` of the same name in the same panel fails the load with "The
  name already exists".
- The shared modules sit inside the pulldown folder and each button adds its
  parent to `sys.path`, the same as Drainage Elevation Match and Smart
  Dimensions. `lib\revobim` is not touched.
- `__version__` at the top of `so_core.py`; both windows read it from there.

**Removed**

- **Height Adjust is gone.** It lives in `lib\revobim\height_adjust.py` and is
  reached from Nudge and MEP Link. This is an offset tool.
- The floating command window is gone with it. The command opens no window at
  all: it reads the saved settings and goes straight to the picks.

**Added**

- **Keyboard shortcuts.** The command button's ribbon name is
  "RevoBIM System Offset" — unique and prefixed, so it can be found in
  View > User Interface > Keyboard Shortcuts. A button in Settings posts that
  dialog.
- **Settings window**, standalone and modal, two columns, saved as plain
  `key=value` text at `%APPDATA%\RevoBIM\system_offset.txt` with a
  `settings_version` and a `MIGRATIONS` table.
- **The second click now carries the direction.** It is a `PickPoint`, so
  where it lands off the run decides which side the offset goes to, and
  optionally how far. A view with no work plane falls back to a second point
  on the element and the saved direction.
- **Dark and light**, following Revit's own canvas theme by default
  (`UIThemeManager.CurrentCanvasTheme`, then `CurrentTheme`). The chip in the
  header cycles Auto, Dark, Light.
- **Easter egg** on the RevoBIM logo, three slow clicks, in both windows.
- **Results window**, themed, shown only when something needs a look by
  default.
- Bend angles of 22.5, 30, 45, 60 and 90 degrees, snapped to multiples of five.
- Distance rules: a multiple of the element width, a set distance, or however
  far off the run the second click landed. Rounded up to a settable step, with
  a settable floor.
- `import_check.py` (16 rules, all 16 proved by `--selftest`) and
  `bench_logic.py` (76 checks).

**Fixed**

- Cable tray and conduit have no `BreakCurve`, so they are split by copy and
  re-cut rather than being refused.
- Connectors are re-fetched after every `doc.Regenerate()`. A handle held
  across a regenerate goes stale and joins pieces that then behave as loose
  parts.
- The split and the fittings sit in a `TransactionGroup`, so a refused fitting
  never leaves a run cut in half.
- `tan(45 degrees)` is 0.9999999999999999, so a run with exactly enough room
  came out a fraction of a micron short and was refused. Compared with a
  tolerance now.
- Elbow failures report the reason and join the pieces directly rather than
  leaving the run in bits.

## v2.x — the earlier tool (for the record)

- Modeless window with `IExternalEventHandler` / `ExternalEvent` and
  `__persistentengine__ = True`.
- Dark-mode WPF floating window, 45/90 degree radios, Up/Down/Left/Right,
  standard or specified distance, Service Type copy for tray and conduit.
- Height Adjust section, later extracted to `lib\revobim\height_adjust.py` so
  Nudge and MEP Link could share it.

## v1.0.0

- Direction prompt, click start, click end. Broke the element at both picks,
  shifted the middle by 2 × width, rebuilt with elbow fittings at four bends.
