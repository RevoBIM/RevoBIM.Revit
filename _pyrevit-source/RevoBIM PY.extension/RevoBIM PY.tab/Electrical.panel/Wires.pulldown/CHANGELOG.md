# Wires — changelog

Version lives at the top of `wires_core.py`; every button and window reads it
from there and shows it in the top right corner.

## 3.7.0 — shrink to taskbar, light and dark, one theme

Wire behaviour is unchanged from 3.6.0. This release is the windows, and a
tidy-up of what 3.6.0 left behind.

**Shrink to taskbar, on every window** — Results, Settings, Auto Wire's
shuffle prompt and the yes/no prompt. The new control in the top right slides
the window down to the bottom of the screen like a drawer closing, leaving
only its header bar floating clear of the taskbar. The control turns into a
**green up arrow**; press it, double-click the bar, or press Enter, Escape or
F11 to bring the window back. Ctrl+Shift+H toggles it from the keyboard.

- The bar stays draggable while shrunk. Carried somewhere else, the window
  opens upward from where the bar now sits rather than jumping back.
- It parks on whichever screen the window is on, including a monitor set
  above the main one.
- While shrunk, Enter and Escape belong to the drawer, so they cannot press a
  Keep, Apply or Cancel button you cannot see.
- The shuffle prompt is modeless, so with it shrunk Revit is fully usable.
  The other three are modal: shrunk, the model is visible but Revit stays
  locked until the window is closed, as before.

**Light and dark, following Revit.** Every header has a theme chip: **Auto**
(follows Revit's canvas theme - `UIThemeManager.CurrentCanvasTheme`, falling
back to the UI theme on 2024+), **Dark** or **Light**. One click cycles them;
the choice is saved and every open Wires window repaints at once, with
nothing lost. Saved as `theme=follow|dark|light` in `wires.txt`.

**One theme file.** Every brush and template now lives in `Theme.xaml`; the
four layouts reference it with `DynamicResource` only, and lost their own
copies of the styles - which had drifted (a disabled button greyed out in two
windows and not the other two). Elements built in code take their colours
through `ui.paint()`, a resource reference, so they follow a swap too.

Smaller things:

- The header now follows the house order: icon, RevoBIM, tool name, theme
  chip, version, shrink, close. The shuffle prompt gained a close button
  (it cancels, exactly as Cancel does).
- Escape now means Cancel on the yes/no prompt and in Settings - the prompt
  always said it did.
- Tooltips are themed; they were the system's own pale box.
- The checkbox tick is dark navy on the dark theme's pale blue, white on the
  light theme's deeper blue; one colour was weak against one of them.
- Removed two settings that did nothing: **Route as one continuous snake**
  (routing is always a snake) and **Home run points back to the panel**
  (power has no home run yet). A tick box that changes nothing is a lie.
- Removed two settings reads whose results were thrown away, and an unused
  import.

Bench:

- `import_check.py` now fails on: any `StaticResource` in a layout, or
  outside a `BasedOn` in `Theme.xaml`; a `DynamicResource` key `Theme.xaml`
  does not define; a `Style` given to an element its `TargetType` does not
  match; a colour by value in a layout or window module; palettes with
  different keys, or a brush in no palette; a `paint()` key in no palette; a
  window missing any header part; a window loaded and never dressed; a
  drawer not built, not handed its parts, or its button not wired; the chip
  not wired; the drawer not releasing its animations, or releasing them in
  the same `try` as the final numbers; no fallback when the slide cannot
  start; `MinHeight`/`SizeToContent` not relaxed or not restored; a setting
  on a tab that nothing reads.
- `bench_logic.py`: theme resolution (including `UITheme.Dark` being 0),
  the chip cycle, palette contrast in both themes, and the parking and
  reopening arithmetic - including a second monitor above the primary.
  316 checks.
- New `selftest.py` breaks each of those 34 things on a scratch copy and
  confirms the bench notices. Run it after changing a rule.

## 3.6.0 — no destination at all

Three releases computed where a wire end should go, and got it wrong three
different ways:

| | what I computed | what happened |
| --- | --- | --- |
| 3.2.1 | trim from the bounding box | ends collapsed to stubs |
| 3.4.0 | the connector node | ends buried in the middle of the symbol |
| 3.5.0 | the node less the symbol radius | ends left ~400mm short |

The common factor is not any of the three formulas. It is that **this tool was
calculating a destination at all**, when Revit works it out correctly the
moment a wire is re-docked onto its connector.

So on `auto` there is now **no target**:

- every **joined** end is re-docked - off the connector, clear, back on,
  reconnected - and Revit places it;
- the result is kept **only if the end finished nearer the node than it
  started**;
- an end already in the right place is re-placed in the same spot, is
  therefore not nearer, and **rolls back untouched**.

Nothing is measured against a computed point, including the decision about
which ends need attention. That removes the whole class of mistake rather than
correcting the third instance of it.

The re-dock now tries a small shove before a large one - 300mm then 1500mm -
and resolves the end afresh on each, since a rolled-back sub-transaction
invalidates what came before it.

`move`, `nudge` and `jiggle` still aim at `align_target` and are still there
for when a particular answer is wanted; they are no longer part of the default
path.

### Bench

**272 checks.** The new ones assert that the `auto` path never mentions
`wire_end_targets`, `arrival_point`, `align_target` or a tolerance, and never
falls through to an aimed route - proved by putting each of those back and
watching it fail.

## 3.5.0 — let Revit place the end

The nudge got the wires moving, and moved them to the wrong place: the
connector node is the fitting's **centre**, so the wires ran into their
symbols. The 149mm offsets in the earlier traces were the symbol radius - the
ends had been at the edge all along.

The fix is in the other half of the report: *"drag away and back to the
connector and it re-aligns and **trims it to the edge**"*. Revit computes the
arrival point itself. Four rounds have gone into calculating a point that Revit
already knows.

### Re-dock, and take Revit's answer

A new route, and the **first** one tried: disconnect the end, drag the vertex
well clear so Revit has to recompute, drop it on the connector, reconnect. The
hand action, in the API.

Its test is not *"did it land on my target"* - it is **"did it end up nearer
the node than it started"**, because the exact spot is Revit's to choose and
Revit is the authority on it. Anything else rolls back.

### And where the computed fallback aims

`align_target` gains **`edge`**, now the default: the node stepped back by the
fitting's symbol radius, taken as the **smaller** half of its bounding box.
A plan symbol is usually square or round about its insertion point, so the
smaller half is the better estimate of its edge - and under-stating leaves the
wire a touch short rather than running it through the symbol. `centre` is still
there, and is what 3.4.0 was doing.

The order is now re-dock, move, nudge, re-seat, and rebuild only on request.

Bench at **261 checks**, including that the re-dock drags clear before dropping
back, that it judges by getting nearer rather than by hitting a target, and
that the default target is not the centre.

## 3.4.0 — the nudge

Two facts finally line up. There is a **visible gap** between the wire end and
the node, and dragging the node a little closes it. And Revit's refusal is
specifically *"there is already a vertex at this position **within
tolerance**"*.

So the end is not where it belongs, and the only thing stopping it going there
is that Revit will not accept a vertex landing on one it already holds. A new
**nudge** route, built from exactly that:

1. **Shove the vertex somewhere free and put it straight back** - what dragging
   the node by hand does - in case that is enough for Revit to re-seat the end
   itself. Tried at 50mm and 200mm.
2. **Walk the end in towards the node** - 0, 2, 5, 10, 15, 25 then 40mm back
   from it - and take the first distance Revit accepts. Landing 10mm short of
   the node is a fifth of a millimetre on a 1:50 sheet.

`align_max_gap_mm`, 25 by default, is how close counts as arrived. Every step
is its own sub-transaction and is read back, so a step that is refused or that
lands too far away costs nothing and says so in the trace.

The order is now move, nudge, re-seat, and - only if asked for - rebuild.

### Bench

**248 checks.** One of the new ones passed on a deliberately broken build: it
looked for `close_enough` by name, and the name was still there after the test
using it had been replaced by `if True`. It checks the comparison now. That is
the fifth check this build that has had to be tightened after being written,
and all five failed the same way - **testing that a thing is mentioned rather
than that it is done**.

## 3.3.2 — stop guessing, start measuring

The 3.3.1 trace settled two things and raised a better question.

**Settled:** the reference fix worked - 29 wires rebuilt cleanly and their tags
followed. And **the rebuild changed nothing visible**. `Wire.Create` was handed
the corrected point list *and* the connectors, and Revit kept its own end
positions. So Revit, not the caller, decides where a connected wire end sits.

**The question that raises:** `SetVertex` refuses the connector position with
*"there is already a vertex at this position"*, at a point 149mm from any
vertex `GetVertex` reports. Both facts point the same way - the wire already
has a vertex at the connector that is not in the vertex list, and the drawn
wire is `connector -> vertex0 -> ... -> vertexN -> connector`. Which would mean
the ends being moved are the vertices *inside* the arrival, not the arrival
itself.

That is a hypothesis, and three rounds have now been spent inferring what a
wire is made of from the way it refuses instructions. So:

### The rebuild is out of the default

`align_method: auto` is now move, then re-seat, and stop. **29 new element ids
for no visible change is worse than doing nothing**, and until the rebuild is
known to help it should not run because a default was left alone.
`auto+rebuild` asks for it explicitly.

### A geometry dump

`debug_geometry`, under Running, writes the whole of what Revit will say about
each wire touched: every vertex, both wire connectors with their origins and
elevations, the partner connector, the fitting behind it, its location point,
its bounding box, and every electrical connector it carries. Off by default -
it is long and slow, and it is the thing to turn on when a wire will not do
what it is told.

Bench at **234 checks**, including that the default cannot rebuild.

## 3.3.1 — a connector reference does not survive a sub-transaction

The trace from 3.3.0 said the same four things for every wire, and three of
them were my fault.

**"The referenced object is not valid"** on every *second* end, and on every
rebuild. The connectors were resolved once at the top of the wire and then
reused. A sub-transaction invalidates references taken before it - **whether it
commits or rolls back** - so by the time the second end was reached, its
connector was a reference into a document that had moved on. It read like Revit
refusing the work; it was the tool handing Revit a dead reference.

Every end is now resolved **immediately before each attempt** and never held
across one. That is what makes the second end and the rebuild reachable at all.

**"Revit returned no wire"** on the rebuild was the same cause: `Wire.Create`
was being handed those dead connectors.

**A rebuild changes the element id**, and a wire tag is hosted on the wire - so
rebuilding 57 wires would have taken their tags with them. Tags on a wire are
now snapshotted before the rebuild and re-pointed at the replacement.

### What the trace also showed, which is Revit and not me

`SetVertex` refuses the connector position with *"there is already a vertex at
this position"*, and a disconnect/reconnect re-seats the end by a few
millimetres but not onto the connector. So neither of the cheap routes can do
this, and **the rebuild is the one that can** - it is the only route that hands
Revit a fresh point list rather than editing one Revit is holding. With the
dead references fixed it should now be reached, and reported, on every wire it
is used for.

The targets themselves check out: two different wires meeting at the same
fitting resolved to the same point, which is the connector origin - the blue
node.

### Bench

**226 checks.** New ones assert that no route holds a connector across a
sub-transaction, that each resolves afresh, and that a rebuild carries the
wire's tags over. Both proved by breaking them.

## 3.3.0 — aligning an end that is not the vertex's to move

**Align Wire Ends ran and nothing moved.** It only ever tried `SetVertex`, and
on a *connected* end Revit appears to own that vertex: the call returns, the
read-back shows nothing changed, and the tool honestly reported a refusal
nobody could act on.

Dragging the node by hand works, which says the operation exists - it just is
not a vertex move. So there are now **three routes, tried in order**:

1. **Move** the vertex, as before.
2. **Re-seat** the end: disconnect the connector from its partner and
   reconnect it, which is what the manual drag appears to do. Revit puts the
   wire end on the connector on reconnect.
3. **Rebuild** the wire with its ends where they belong - the only route that
   changes the element id, which is why it is last and why it is reported.

Each route runs in its own sub-transaction and is **read back**, so one that
does nothing costs nothing and rolls back. The re-seat in particular rolls back
rather than leave a wire disconnected if the reconnect will not take.
`align_method` picks a single route if one of them turns out to be the right
one everywhere.

### A trace in the debug report

The report now carries a **trace**: per wire and per end, where it was, where
it should go, which routes were tried and exactly what each one did. It never
appears in the results window - it is the thing that explains a failure, which
is the thing nobody wants to read on a good day - and it is always in the
Debug report.

If this still does not move a wire, that trace will say which of the three
routes Revit refused and what it said.

### Bench

**220 checks.** The new ones cover the order of the routes, that each does what
it claims, that each rolls back, and that the re-seat reconnects what it
disconnected. One of them was raising instead of failing when the thing it
looked for was missing, which made a deliberate break look like a crashed
bench rather than a caught error; it checks presence before ordering now.

## 3.2.1 — the trim collapsed wires instead of tidying them

**Align Wire Ends pulled wire ends most of the way back to the next vertex**,
leaving a stub where a span should have been.

The trim is taken from the fitting's bounding box, and **a fitting's bounding
box is not its symbol** - a luminaire's box can be metres across where its plan
symbol is a 150mm circle. The only guard was "do not step back past the vertex
you came from", at 90% of the distance to it, so an oversized box did not look
slightly wrong: it dragged the end nearly the whole way and collapsed the wire.

### What changed

- **One trim rule, with two ceilings.** `trim_distance` is now the only place a
  trim is worked out, used by Align Wire Ends and by all three placers. It is
  capped at a **paper measurement** - `trim_max_paper_mm`, 6 by default - and
  at **a third of the span**, whichever is smaller, and it reports when the cap
  bit. A trim is a small tidying distance by definition; nothing about a
  bounding box should be able to make it a large one.
- **A wire now meets its fitting on the connector node by default.**
  `align_target` was `trim` and is now `centre` - the blue node itself, which
  is what was asked for and what the drawing wants. `trim` is still there for
  anyone who wants the wire to stop short of the symbol.

This also mattered for Auto Wire. The oversized trim had been there all along
and never showed, because `_retrim` was refusing to apply it - the bug fixed in
3.2.0. Had this one not surfaced first, 3.2.0 would have started collapsing
newly drawn wires too.

Settings version 14 resets `align_target`.

### Bench

**205 checks**, including a fitting with an 8m bounding box on a 2m span: the
trim must stay at the paper ceiling and the end must stay beside its fitting.
Without the cap that test produces a 1.8m trim. Every placer is also asserted
to go through the one rule rather than touching `plan_half_extent` itself.

## 3.2.0 — Align Wire Ends, and the trim that was never refused

### Align Wire Ends

A sixth button. **Moves the point where a wire meets its fitting onto where it
belongs** - the small node you would otherwise drag by hand - and changes
nothing else. No wire is retyped, retagged, reconnected or deleted, and none
changes its element id. Only end vertices move.

- **Select wires** and only those are done.
- **Select circuits** and every wire on them is done.
- **Select nothing** and it asks, naming the view, before doing every wire in
  the active plan.

Where the end sits is **the same rule Auto Wire draws with**, now factored into
one place so a redrawn circuit and a tidied one cannot disagree: short of the
symbol by the trim setting, or on the connector at the symbol centre. New
setting `align_target` on Circuits > Drawing the run, with a tolerance below
which an end is already close enough.

The step-back follows the direction the wire actually arrives from, and is
clamped so it can never reach back past the vertex before it. Each move is read
back - `SetVertex` can return without having moved anything. An end joined to
nothing is left alone: there is no fitting to align it to.

### The trim was never refused

That report full of *"trim was refused, ends sit on the connectors"* was my
bug, not Revit's. `_retrim` compared the vertex list Revit came back with
against the one it was given and, where the **counts** differed, gave up
without trying anything - then reported a refusal. The node being draggable by
hand is the proof it was never refused.

It now sets the two ends by index whatever the count came back as, since the
ends are what the trim is about, and only a refusal from Revit itself counts as
one. Auto Wire's wires should now sit short of their symbols as they were
always meant to.

### Bench

**192 checks.** Four new ones proved by breaking what they guard.

One of the older ones was wrong and had been passing for the wrong reason: the
source checks sliced from `def foo(` to the end of the file, so a rule about
what `foo` may call started failing because of what a *later* function does.
They now take a function's real boundaries from the syntax tree.

## 3.1.1 — three things Apply Wire Types got wrong in its report

The work was right; the account of it was not.

- **The summary said "3 wire(s) and tag(s) drawn".** It draws nothing. The
  count was being carried on the same field Auto Wire uses, so the summary
  contradicted the one promise this tool makes. It has its own count now and
  says **retyped**.
- **It opened the results window over something the run had nothing to do
  with.** Two wires elsewhere in the view belonged to no circuit, which is
  worth saying when sweeping the whole view and is none of the run's business
  when the person has selected a circuit. Skipped now when circuits were
  selected - which makes a clean selected run silent, as it should have been.
- **It said the same thing twice on a single circuit** - the per-circuit line
  and then a total across one circuit. The total only appears where there is
  more than one.

## 3.1.0 — Apply Wire Types

A fifth button. **Sets the wire type on wires that are already drawn, and
changes nothing else** - nothing is moved, redrawn, retagged or deleted.

- **Select a circuit** - or a wire or a fitting on one - and only those
  circuits are done. Several at once is fine.
- **Select nothing** and it asks, naming the view, before doing every circuit
  with wires in the active plan.

The type is decided by **the same three questions Auto Wire draws with, in the
same order**: an emergency circuit is emergency throughout, a wire bridging two
legs (two spaces, or two switch systems) is permanent live, everything else
takes the lighting or power type. The bench asserts the two agree rather than
trusting that they do, because two copies of a rule drift.

A wire already carrying the right type is counted and left alone. Each change
is read back before it is counted. Wires belonging to no circuit are reported
and pointed at Reconnect Wires.

Wires are grouped by circuit in **one pass** over the view. Asking each circuit
for its wires in turn resolves every wire once per circuit, which on a plan
with sixty circuits is sixty times the work for the same answer.

### Also

- **A themed yes/no window**, `WiresConfirm.xaml`, for the active-view prompt.
  A TaskDialog would have been the one window in the extension coming up in
  Revit's own colours.
- **`make_icons.py` now ships with the tool.** It has been lost twice to a
  reset working folder, and an icon set redrawn from memory never quite
  matches. Same reason `bench_logic.py` ships.
- Bench is at **163 checks**. Three of the new ones were proved by breaking
  what they guard; a fourth passed on a deliberately broken build and had to
  be tightened - it looked for the read-back anywhere in the function, and the
  "already the right type" test above it satisfied the search. It now requires
  the read-back to come *after* the change.

## 3.0.1 — `_LIVE` was never defined

**Re-Route Wires and Auto Wire both failed the moment the floating prompt
opened**, with `NameError: global name '_LIVE' is not defined`.

The list that holds a floating window referenced was used but never declared.
A text replacement meant to insert it, together with the module's new
docstring, matched nothing and did nothing - while the replacements either side
of it in the same batch applied. The module imported fine, because the name is
only read inside a function, and Python does not find that until the line runs,
which here is after the user has pressed the button.

Fixed, and the rest of that batch audited line by line - everything else had
landed.

### Two new bench rules, because every existing one passed

- **`check_undefined_names`** - any name a file reads but never binds anywhere
  in that file is now an error. It catches this exact bug, proved by deleting
  the declaration again.
- **A half-applied-edit check** on the floating path in `bench_logic.py`: the
  markers that edit was supposed to leave behind, `_LIVE` at module level among
  them, and that `show` still returns `None` on the floating path and the kept
  flag on the modal one. The return check counts only `show`'s own returns -
  the first version walked into the nested handlers, where any bare `return`
  satisfied it, and a deliberate break slipped past.

Bench is at **131 checks**.

## 3.0.0 — the Shuffle prompt floats, and chamfer looks like chamfer

Major, because the drawing commands now run a modeless window and set
`__persistentengine__`.

### Revit stays usable while you judge a route

The Shuffle prompt floats by default: the view can be panned and zoomed, other
tools used, and the route looked at properly before Keep or Cancel.

That changes how it works underneath. A modal window shown from inside a
command is still in the command's API context and can open transactions
directly. A floating one is not - the command has returned and Revit is back at
idle - so every redraw now goes through an **ExternalEvent** (`wire_events.py`)
and both drawing commands set `__persistentengine__`, without which pyRevit
tears the engine down on return and takes the window's handlers with it.

**The transaction group does not stay open.** One left open across a floating
session would sit there while you work, and anything else you did in Revit would
nest inside it - so Cancel would roll back your work as well as the tool's.
Instead each redraw commits on its own, and Cancel deletes what was drawn and
**restores what was removed from snapshots** taken before the originals were
deleted. Restored wires and tags come back with new element ids; everything else
about them is the same.

Closing the prompt with the X counts as Cancel. `modeless_shuffle: no` restores
the modal dialog, which needs none of the above and is the one to fall back to
if the floating window misbehaves.

### Chamfered wires are drawn as chamfers

A chamfered wire was being given the same arc-sampled vertices as an arc one,
so Revit faceted between them and it came out as a many-sided polygon. It is
now **an angle off the fitting, a straight run across, and an angle back in** -
the convention. `chamfer_angle_deg` sets the angle of the two cranks, 45 by
default; the straight between them takes the rest. A vertex count above 2 adds
points along that straight rather than changing the shape.

### That repeated "trim was refused" prompt

Seventeen identical lines in one report. Two things were wrong: the message was
fired per span rather than counted, and it was classed as something to act on
when it is a fact about Revit - it seats a connected wire end on its connector,
so the trim cannot hold there.

**Repeated per-span outcomes are now collected and said once with a count**, and
routine ones are informational, so they no longer open the window. On the report
in question that leaves two lines: no switch found, and five spans crossing a
fitting - both of which are worth seeing.

### Debug report

A **Debug report** button on the results window writes the release, the
settings in force with the changed ones flagged, what every lookup resolved to,
and every line of the report including the informational ones, to
`%APPDATA%\RevoBIM\wires_debug.txt` - and copies it to the clipboard so it can
be pasted straight into a message. On by default, switchable off under Running.

### Bench

`bench_logic.py` is up to **116 checks**, covering the chamfer crank, note
aggregation, the modeless plumbing and the debug report. Each new one was
proved by breaking what it guards.

Settings version 12.

## 2.9.0 — arc or chamfer, and never fewer than one vertex

### Arc or chamfered wires

The Shuffle prompt - used by both Auto Wire and Re-Route Wires - has an
**Arc / Chamfer** pair. Pressing either redraws the circuit as that kind of
wire at the same route and vertex count, so the two can be compared on the
drawing. The default is a setting, `wiring_type`, on Circuits > Drawing the
run.

The vertices are placed on the same circular arc either way, so an arc wire
sweeps through them and a chamfered wire facets round the curve - the more
vertices, the closer the chamfer gets to the arc.

### At least one vertex

The vertex count now has a floor of **1**, in the setting, on the Shuffle
stepper and in the length-shared mode. A wire with no middle vertex has nothing
to bend round: an arc wire falls back to whatever sweep Revit chooses and a
chamfered one is a straight line. The stepper's down arrow greys out at 1 and
its up arrow at 8.

### The tests ship with the tool

`bench_logic.py` sits beside `import_check.py` and runs the rules themselves -
the arc, the vertex floor, arc and chamfer, routing, clash ranking, wire types,
the Session the Shuffle prompt drives, and silent-on-success reporting. 72
checks. The earlier tests lived in a scratch folder and were lost with it, so
these now travel with the code they test. Each new check was proved by
breaking the thing it guards.

Settings version 10 - a saved vertex count of 0 is read as 1.

## 2.8.0 — silent when it goes to plan, and emergency means emergency

### A run that goes to plan finishes without a dialog

The diagnostics added at 2.1.0 to make failures explicable had the side effect
of making every success interrupt you: which wire type was resolved, which
switch was found, how many fittings were selected — all of it counted as
"something needs a look".

Report lines now come in three kinds. **INFO** is said for the record and never
opens the window. **NOTE** is worth a look. **SKIP** is something left alone.
Only the last two open the window, so a clean run is silent and the record is
still there under **Show results: always**.

Eleven lines moved to INFO — the wire type and tag resolved, the switch and how
it was found, the fittings selected, circuits already wired, spans flipped to
clear a fitting, panel home runs removed, an all-emergency circuit, and
Cancel. Everything that reports something not happening as intended still
opens the window.

### Any emergency fitting makes the circuit an emergency circuit

At 2.4.1 the rule was **every** fitting on the circuit. One fitting with the
parameter unset was enough to put permanent live spans back into a run that is
emergency in every other respect — the wrong way to be wrong. **Any** fitting
reading as emergency now draws the whole circuit in the emergency wire type,
with no permanent live anywhere on it.

A part-marked circuit is reported, with the count and the parameter name, since
that is a data problem to fix rather than something to draw around.

## 2.7.0 — one vertex means one vertex, and clash avoidance on the prompt

### The vertex count is per wire again

At 2.4.0 I read "evenly spaced based on the overall length of the circuit" as
sharing the vertices out across the circuit by span length. That meant a
setting of 1 gave one vertex to a span of average length, none at all to a
short hop and several to a long one — so most wires had no middle vertex and
did not read as a single curve.

**1 now puts one vertex at the middle of every wire**, offset from the straight
line between its two ends, whatever that wire spans. Raising the number adds
more, spaced evenly along the same arc. The old behaviour is kept as
`vertex_mode: length` for anyone who wants it.

### Route clear of other circuits, on the Shuffle prompt

A **checkbox** on the prompt turns clash avoidance on and off and **redraws
immediately**, so the difference it makes to the route can be seen rather than
taken on trust. Under it, a line saying whether this route crosses anything,
how many spans still do, or that avoidance is off and the shortest route is
winning whatever it crosses.

The prompt's own `CheckBox` needed a control template — the stock one renders
from the system theme and would have shown through as a white box.

Settings version 9.

## 2.6.0 — routing clear of other people's fittings

**A route that runs a wire across a fitting on another circuit is now ranked
below one that does not.** Every fitting drawn in the view that is not a member
of the circuit being wired becomes an obstacle, with a plan radius taken from
its own bounding box plus a clearance (150mm by default).

Three things use that:

- **The route is scored on clashes first, length second.** Not a weighting - a
  clash-free route beats a clashing one however much longer it is, because a
  wire drawn over somebody else's light is a drawing error and a metre of extra
  wire is not.
- **A span is flipped to arc the other way** where that clears a fitting the
  first side would have crossed. Reported, with the count.
- **What still cannot be cleared is reported** rather than quietly drawn
  through, with the note that Shuffle may find a route that does clear it.

A fitting sitting on the straight line at mid-span is usually **not** a clash,
because the arc bows around it - which is the wire being an arc earning its
keep. One close to an end of a span cannot be avoided by any route or side,
because the arc converges on its endpoints, and that is what gets reported.

Obstacles are collected once per run and coarse-rejected per span before the
arc is sampled, so the cost of this is small even on a plan full of fittings.

Switchable off, with the clearance as a setting. Settings version 8.

## 2.5.0 — a true arc, and 1900 lines of duplicate code removed

### The wire is now a real circular arc

The curve was a quadratic Bezier. It is now a **circle through the two ends
with the depth asked for**, and that fixes both halves of what was wrong:

- **The depth is exactly what the setting says.** On a Bezier the number was a
  control-point offset and the curve reached about half of it, so the slider
  never quite meant what it said.
- **Extra vertices land evenly spaced along the curve.** Equal steps of angle
  on a circle are equal steps of arc length; equal steps of a Bezier's own
  parameter bunch toward the ends. Two, five or eight vertices now sit at
  identical intervals on the same arc, and the arc's depth does not change
  with the count.

At one vertex it is beginning, middle, end, with the middle at the deepest
point — which is what the reference drawing shows.

### Arc depth is a share of the span by default

**18% of the distance being spanned**, so every wire on the sheet sweeps by the
same proportion. A fixed size cannot do that: it makes a 600mm hop between two
downlights bulge hard and a six metre run look flat. The old fixed paper
measurement is still there as `arc_sag_mode: paper`.

The Shuffle slider drives whichever mode is active and is labelled in its
units — 0–45% or 0–20mm on paper.

### wires_core.py carried four copies of the same 300-line block

A third of the file. Python silently uses the last definition, so everything
worked, every check passed, and nothing caught it: the module imported, the
syntax was valid, the cross-module calls resolved. 2861 lines down to 1909.

**`check_no_duplicate_defs`** now fails any module that defines a top-level
name twice, proved by pasting one back in and confirming it fires.

Settings version 7 migrates the arc keys.

## 2.4.1 — an emergency circuit is emergency throughout

**Where every fitting on a circuit reads as emergency, every span takes the
emergency wire type — crossings included — and no span is drawn as permanent
live.** The home run follows it too. Permanent live has nothing to say on a
circuit that is emergency end to end, and mixing the two reads as though part
of the run were something else.

A **part-emergency circuit** keeps the per-span rule, and is now called out in
the report with the count and the parameter name, because some fittings marked
and some not is usually a parameter that has not been filled in rather than a
design intent.

## 2.4.0 — even spacing, live route controls, switch lines, spaces

### Vertices are spaced across the whole circuit

`mid_vertices` now means **the count on a span of average length**, and the
spacing that implies is applied to every span. A hop twice as long gets twice
as many, so the vertices sit evenly along the run instead of one per hop
however long the hop. On a run of three 1m hops and one 6m hop at a setting of
1, the gaps come out 1000/1000/1000/1200mm rather than 500/500/500/3000.
Still clamped to 8 a span.

### The Shuffle prompt drives the route live

- **Number of vertices**, with up and down buttons. Each press redraws the
  current circuit at the same route with the new count.
- **Vertices offset**, a slider. Sliding it moves the vertices further off the
  straight line between the fittings, or closer to it — the arc's depth,
  in paper millimetres.
- Both redraw on release rather than on every tick, and every live control is
  re-entrancy guarded: a repeat button auto-repeats faster than a transaction
  commits.

### Auto Wire on a selection redraws it

Running Auto Wire with something selected now **removes the existing wires and
tags on those circuits first**, then draws and tags fresh. With nothing
selected it still leaves already-wired circuits alone, because "wire what is
not wired" is what the sweep is for.

### A detail line from the light to its switch

Where a circuit's switch is found, a **straight detail line** is drawn from the
light fitting to the lighting device, trimmed off both symbols the same way the
wires are. **The line style is yours to choose** from a new dropdown listing the
line styles in the model; blank leaves it on the view default. Switchable off.

### Permanent live between spaces, not just switch systems

Lights are now chained **by space** as well as by switch system: the run
completes the lights in one space before moving on, and the span that bridges
two spaces takes the **permanent live** wire type — which is what says "same
circuit, different switch system" when the difference is which room. A fitting
in no space is its own leg. Both groupings switch off independently; with both
off the route ignores boundaries entirely and no span is permanent live.

Settings version 6 migrates the changed keys.

## 2.3.0 — Electrical panel, wire type by parameter, Tidy removed

**Moved to the Electrical panel**, alongside Panel Schedule Template Manager.
No `Electrical.panel\bundle.yaml` is shipped, so whatever that panel is already
set to is left alone. **The old `MEP.panel\Wires.pulldown` folder has to be
deleted by hand** — see `DELETE THESE OLD FOLDERS.txt`.

**Renamed.** Auto Wire In View → **Auto Wire**. Re-jig Circuit → **Re-Route
Wires**.

**Removed: Tidy Wires**, and with it the end snapping, vertex merging, kink
straightening and arc sag normalising, the whole Tidy settings tab, and the
`tidy_after_reconnect` option on Reconnect. Reconnect still pulls an end onto
its connector as it joins.

### Wire types are now chosen per span, from the fitting

| Setting | Used where |
| --- | --- |
| Lighting wire | the default for a lighting span |
| Lighting wire, emergency | either fitting on the span reads as emergency |
| Lighting wire, permanent live | the span crosses from one switch system to the next |
| Power wire | a power circuit |

**A new parameter dropdown picks what marks an emergency fitting**, defaulting
to **`BGL_Elec_IsEmergency`**. It is read off the fitting, instance first then
type, and yes / true / 1 all count — a shared yes/no parameter reads back as an
integer and a text parameter as a word, and which a family uses is not this
tool's choice. The dropdown lists parameters actually carried by lighting
fittings in the model, and always offers the saved name even where nothing
carries it yet.

Permanent live wins over emergency on a crossing span, because that span's job
is to say "same circuit, different switch" and it is the only span that can say
it.

### Auto Wire

**With something selected, only those circuits are wired.** With nothing
selected, every circuit in the view that has no wires yet is wired. A selected
circuit that already has wires is named and left alone rather than having a
second set drawn over the first — Re-Route Wires is the button for those.

### The home run

Now **10mm on paper times the view scale** rather than a fixed 500mm in the
model, so it is the same length on every sheet. **Always drawn with one middle
vertex** whatever `mid_vertices` is set to, so it arcs toward the switch — it is
far too short for more than one to read. Still clamped so it can never reach the
switch it points at.

### Shuffle

**A Previous button** steps back through the route options, wrapping to the last
one at the start. It is disabled when there is only one route.

Settings version 5 migrates the changed keys.

## 2.2.1 — regression fix: the command layer was missing

**Auto Wire In View and Re-jig Circuit both failed with
`AttributeError: 'module' object has no attribute 'run_wire_circuits'`.** The
2.2.0 edit that rewrote `attach_switch` sliced `circuit_core.py` from that
function to the end of the file and replaced it — and `attach_switch` was not
the last function. `Session`, `prepare`, `run_wire_circuits`, `run_rejig`,
`_finish`, `_report_lookups` and `_pick_circuit` all went with it. Restored,
with every 2.1 and 2.2 change intact.

**The bench check reported clean while the tool was gutted**, which is the more
serious half of this. Imports were valid, syntax was valid, settings keys were
valid, and no test happened to call the deleted functions — only the ribbon
did. Two things now close that gap:

- **`check_cross_module_calls`** — every name a file reaches for on a sibling
  module must exist in that module. It catches this exact deletion, and was
  proved by re-cutting the file and confirming it fires.
- **A smoke test that calls the command entry points the way the buttons do**,
  rather than exercising the routing and geometry helpers directly. Every other
  test went in through a side door, which is why they all passed.

### Housekeeping

Delete the old **`Wire Circuits.pushbutton`** folder from the installed
extension. Extracting the zip merges rather than replaces, so the folder
renamed at 2.1.0 is still there and still on the ribbon — the traceback that
reported this bug came from it.

## 2.2.0 — vertices, tag leader, and the switch by connectivity

**Vertices are now a count, not a yes/no.** `three_vertices` becomes
**`mid_vertices`, default 1** — counted *between* the ends, so 1 gives the
three-vertex wire (start, middle, end) and 0 gives just the two ends and lets
Revit decide the sweep. More than one spaces them along the **same** arc, so
raising the count refines the curve rather than deepening it. Clamped to 0–8.

**Tags now carry a leader and sit 250mm off the wire.** The offset moved from
paper millimetres to **model millimetres**, because 250 is a real distance in
the model. `tag_offset_is_paper` switches it back for anyone who wants the tag
to hold its position on the sheet instead. `tag_leader` now defaults on.

**The switch is found by connectivity first.** The tool now walks each light's
own connectors, and one hop further through any wire hanging off them, looking
for a switch that is genuinely wired to it — a switch is almost never connected
to a fitting directly, it is connected through the wire between them. Only if
that finds nothing does it fall back to matching Switch ID parameters. A switch
that is actually wired to a light is a fact; a matching Switch ID is a claim,
and in an edited model the fact has to win. The report says which route
answered.

The switch test is category first, then the family name, so a switch modelled
outside Lighting Devices is still found rather than silently sending the home
run back to the panel.

**The home run leaves the light the switch is wired to**, not merely the
nearest one, and is now an **arrow by default**: a short wire (500mm) leaving
that light in the direction of the switch and stopping short of it, connected
at the light end only. That is the condition Revit itself draws a home run
arrowhead for, so the arrow is Revit's own rather than something invented here.
`home_run_style` set to `full` restores the wire that runs all the way into the
switch — which is a switch leg rather than a home run. The arrow is clamped so
it can never overshoot the switch it points at.

Settings version 4 migrates the changed keys.

## 2.1.0 — the lookups, and why nothing drew

**Wire types were never found, and that stopped everything.** `wire_types()`
wrapped its whole collector in one try/except and returned an empty list on any
failure, so a model full of wire types reported "No wire types in this model".
`find_wire_type()` then returned `None`, and `wire_one_circuit()` refuses to
draw a circuit without a wire type — so Auto Wire In View and Re-jig Circuit
both appeared to do nothing. One root cause, three symptoms.

- Wire types are now found by **four routes in order**, and the tool says which
  one answered: `OfClass(WireType)`, then the `OST_Wire` element types, then the
  types already in use on wires in the model, then the document's own default.
- Wire tags likewise: the wire tag category by either of its names, then every
  family symbol whose category reads as a wire tag.
- **Neither lookup swallows a failure any more.** The reason a list came back
  empty is shown in the settings window's status line and in the run report.
- `find_wire_type` falls back to the first available type rather than returning
  `None`, so a stale name in settings no longer stops the run.

**Two bugs were hiding the first one.**

- `_finish` **wiped the report on Cancel**. A run that drew nothing still opened
  the Shuffle prompt, and pressing Cancel — the only sensible thing to do with
  an empty result — threw away the notes saying why. The prompt is now skipped
  when nothing was placed, and Cancel keeps the notes.
- **The results window failed silently.** If the themed window would not build,
  `show()` returned `False` and the tool looked like it had done nothing. It now
  falls back to a plain Revit dialog.

**New: a lookup line at the head of every run report**, naming the wire type,
the permanent live type and the wire tag actually resolved, so "nothing
happened" is answerable without opening the code.

### The wire tag is now one setting, not two

Lighting and power are not independent here — the tag reads the circuit off the
wire. `lighting_tag_family` and `power_tag_family` are gone, replaced by
**`wire_tag_family` and `wire_tag_type` on the Circuits tab**, as two linked
dropdowns: pick the family and the type list follows it. Settings version 3
migrates the change.

Wire *types* stay per domain: lighting, permanent live and power.

### Renamed

**Wire Circuits is now Auto Wire In View**, on the button, in the ribbon, in the
transaction name and in the Shuffle prompt.

### Bench check

- The stub types now report their own names, so a failure reads
  `Autodesk.Revit.DB.BuiltInCategory.OST_Wire` rather than an object address.
- `ElementTypeGroup` added to the stub — the check caught its absence.

## 2.0.0 — Auto Wire In View, Re-jig Circuit, and the rename

**Renamed from Wire Fix to Wires.** Settings moved from
`%APPDATA%\RevoBIM\wire_fix.txt` to `wires.txt`; the old file is read once if
the new one does not exist.

- **Auto Wire In View** — draws the wires for every circuited lighting fitting
  in the active floor or ceiling plan. Arc wires between fitting centres, three
  vertices, sag and trim as paper measurements, one continuous snake per
  circuit, each switch system chained as its own leg, permanent live wire type
  on the span that crosses between legs, home run to the switch, panel home runs
  removed once replaced, one tag per circuit, and Shuffle to re-route before
  keeping.
- **Re-jig Circuit** — takes one circuit's wires and tags out and redraws them
  to the same rules, with Shuffle.
- **Tidy Wires** — new arc sag normaliser, off by default.
- **Settings** — rebuilt as a tabbed, schema-driven window: Circuits, Lighting,
  Power, Reconnect, Tidy, Running. Power present but off by default.

## 1.0.0 — first release, as Wire Fix

Reconnect Wires and Tidy Wires.

### To do at the next release

- Remove `highlight: new` from `bundle.yaml` once the buttons are familiar.
