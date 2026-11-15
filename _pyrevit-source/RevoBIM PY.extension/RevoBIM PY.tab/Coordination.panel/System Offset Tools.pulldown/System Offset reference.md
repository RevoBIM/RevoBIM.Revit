# System Offset Tools — v5.5.0

A pulldown on the **RevoBIM PY** tab, **Coordination** panel, holding five
buttons: **RevoBIM System Offset**, **RevoBIM Offset Break**, **RevoBIM Click
System**, **RevoBIM Clash Offset**, and **RevoBIM System Offset Settings**.

**Clash Offset** is the fourth: it finds the clash along the run, decides which
way round is both sensible and cheap, and jogs the services clear. It shows
what it worked out before writing anything, and the direction can be overruled
per clash.

Give it the work either way. **Select the services and the things to avoid
together** and it sorts them out — the MEP runs move, everything else is what
they move around. Or select nothing and it asks: the services, then what is in
the way in this model, then what is in the way in a link, each pick skippable.

Both commands take the same two clicks, open the same prompt and read the same
settings. They differ in one thing:

| | What it does | Bends | Room needed |
| --- | --- | --- | --- |
| **System Offset** | out and back — the run jogs across an obstruction and rejoins its own line | 4 | `2 x offset / tan(angle)` |
| **Offset Break** | out and stop — the run is cut at the second click and steps onto a new line; what lies beyond stays put | 2 | `offset / tan(angle)` |

**Click System** is the third, and works differently: click a run, then keep
clicking in space, and the service grows to each click, with a bend at every
corner, until Escape.

Select **several parallel runs first** and the whole bank is routed at once,
staying parallel and keeping its spacing round every corner. Runs that are not
parallel are refused rather than banked.

A window sets what happens next, in two parts.

**Horizontal placement** — the bend angle (90, 45, 30, 22.5 or typed) and the
length of the next piece. Leave the length blank and the piece runs to wherever
you click; fill it in and the click only sets the corner and which way to turn.
**Place Horizontal Bends** goes back to Revit to pick.

**Height adjustment** — a run-on distance (500mm), an offset, and a rise angle
(45 degrees). **Set Up** or **Set Down** arms the next click, and the move is
three pieces with two bends, none of them in plan:

1. the run carries on for the run-on distance
2. it rises or falls by the offset, at the angle
3. it runs on straight at the new level, as far as the click reaches

A rise takes `height / tan(angle)` of run in plan — nothing at 90 degrees,
which is a plain riser. Available from the moment the tool opens; the forward
end comes from where the click lands.

**It fits the room the click gives** rather than refusing. The height is never
given up; the run on shortens first, then the angle steepens, up to a square
riser. Only a click with nowhere to turn in at all is refused, and whatever had
to give is reported.

A bank rises as one: every run gains the same height over the same plan run, so
services stacked above one another keep the height between them.

**Escape in Revit reopens the window** mid-route, and **Finish** ends the
tool.

Only the turns that head back **along** the run eat into it, so a break has
twice the room a jog does at the same angle.

**Both run on a whole selection.** Select several parallel runs first and they
are all offset together, staying parallel and keeping their spacing. The bends
come out staggered, because that is what holds the spacing on the diagonals —
see below. Runs that are not parallel are refused rather than banked.

## Problem it solves

Getting a service past something in its way is a break, a move, two more
breaks and four fittings, done by hand in a section or a plan, and the
arithmetic that decides how far the bends eat into the run is done by eye. It
is a handful of moves per clash and there are dozens per floor, and a run that
comes out a few millimetres off shows up later as a fitting that will not
place.

The rule underneath is mechanical: the middle of the run belongs on a line
parallel to itself at a set distance, each bend eats `offset / tan(angle)` of
run along the axis, and everything the run was connected to at either end has
to stay connected.

## The buttons

**RevoBIM System Offset** opens **no window at all**. It reads the saved
settings and goes straight to the two clicks, and keeps going until Escape. It
is a single command button with a deliberately unique ribbon name, so Revit's
own **Keyboard Shortcuts** dialog can bind keys to it (View > User Interface >
Keyboard Shortcuts, search "RevoBIM System Offset"). Plain names clash with
other addins and cannot be found in that list. With a shortcut assigned the
whole tool is: keys, click, click.

**Settings** is standalone and modal, two columns so it fits without
scrolling. Set them, press Apply, and they are written to
`%APPDATA%\RevoBIM\system_offset.txt`; every later run uses them. A missing or
damaged file falls back to the defaults key by key, and keys from an older
version are ignored rather than breaking the load. The window also carries a
button that posts Revit's Keyboard Shortcuts dialog.

## The two clicks and the prompt

**Click 1 — the START of the offset.** **Click 2 — the END**, on the same run.
Both are `PickObject(PointOnElement)` filtered to the four categories, so
nothing else in the model can be picked by accident.

**Then the prompt opens**, carrying:

- the **calculated distance** in an editable box — the multiplier times the
  service's own width, rounded up onto the 5mm grid;
- what that number came from, and **how much room the two clicks leave** at the
  set angle;
- **four direction buttons**: Up, Down, Left, Right.

Press one and the offset runs, the prompt closes, and the loop goes straight
back to waiting for the next first click. **Escape at the prompt** cancels that
one offset and leaves the tool running. **Escape on the first click** finishes.

Up and down are elevation. Left and right take their sign from the view's own
right direction, so "left" on the prompt is left on the screen. A vertical run
has no up or down and those two buttons are greyed out rather than refused
after the fact.

A distance the two clicks will not leave room for is **refused in the prompt**,
with the largest that does fit, rather than after the picks are spent.

## What gets built

Along the run, `u` is the axis and `v` the offset direction square to it. With
an offset `d` at angle `a`, each bend eats `r = d / tan(a)` of run — `d` at 45
degrees, nothing at 90.

```
lead ....... c1
                \  first leg
                  c1 + r*u + d*v ....... c2 - r*u + d*v      the middle
                                                       \  second leg
                                                         c2 ....... tail
```

- **lead** and **tail** are the original element and the far half of it. They
  do not move, so whatever the run was connected to at either end stays
  connected.
- **the middle** is the original middle, re-cut onto the offset line.
- **the two legs** are copied from the middle, so they carry its size, type,
  insulation and lining without any of it having to be read and re-applied.
- **four elbows** from the element's own routing preferences.

At 90 degrees `r` is zero and the legs are square, which is the same code path
with a different number in it rather than a second case.

## Refusals

The tool works on **pipes, ducts, cable tray and conduit**, matched on
`BuiltInCategory` id rather than on words in the category name — name matching
swept in Flex Ducts and Flex Pipes, neither of which has a straight centreline
to offset.

Reported rather than attempted: anything outside those four; an arc or a run with no straight centreline; and a run too short overall to
cut an offset into.

**A click at or past an end of the run is clamped inward**, not refused, and
the clamp is reported. v3 refused it, which — combined with a second click that
sat on the view's work plane rather than on the run — refused nearly every
offset anybody tried.

An elbow the routing preferences will not take **joins the two pieces directly
and says so**, rather than leaving the run in bits.

## Settings

Two, and the theme chip.

| Setting | Default |
| --- | --- |
| How far to offset | **1 x** the width of the service |
| Angle of offset | **45 degrees** (22.5 / 30 / 45 / 60 / 90) |
| Theme | follow Revit — the header chip, not a row in the window |

Everything else is a constant in `so_core.py`: the 5mm rounding, the 25mm
floor, the 10mm shortest piece, fittings on, the service type copied, and
results shown only when something needs a look. A setting nobody changes is
only another way to get it wrong.

## Folder layout

```
Coordination.panel\
  System Offset.pulldown\
    bundle.yaml  icon.png  CHANGELOG.md
    so_clr.py             every clr.AddReference, imported first by everything
    so_core.py            version, settings, units, the offset arithmetic
    so_model.py           geometry, breaking, moving, fittings, transactions
    so_run.py             the pick loop for the two offset tools
    so_click.py           the click by click routing loop and the bank
    angle_prompt.py       the bend angle window
    so_clash.py           reading a clash and working out the way round it
    so_clash_run.py       the Clash Offset picks
    clash_window.py       the Clash Offset preview
    offset_prompt.py      the distance and direction prompt
    so_ui.py              XAML loading, theming, chrome, the easter egg
    so_command_host.py    the live UIApplication
    settings_window.py    the settings dialog
    results_window.py     the themed report
    theme.py              the dark and light palettes
    Theme.xaml            every brush and control template
    SystemOffsetSettings.xaml
    SystemOffsetResults.xaml
    OffsetPrompt.xaml
    AnglePrompt.xaml
    ClashOffset.xaml
    import_check.py       16 rules, all 16 proved by --selftest
    bench_logic.py        76 checks under plain CPython
    RevoBIM System Offset.pushbutton\           script.py  bundle.yaml  icon.png
    RevoBIM Offset Break.pushbutton\            script.py  bundle.yaml  icon.png
    RevoBIM Click System.pushbutton\            script.py  bundle.yaml  icon.png
    RevoBIM System Offset Settings.pushbutton\  script.py  bundle.yaml  icon.png
```

The shared modules sit **inside the pulldown folder**, not in
`lib\revobim`, and each button adds its parent folder to `sys.path` — same as
Drainage Elevation Match, Smart Dimensions and Drawing Register, and for the
same reason: it keeps the tool self-contained and avoids touching the
`lib\revobim` package other tools rely on.

The pulldown folder is deliberately **`System Offset Tools.pulldown`** rather
than `System Offset.pulldown`, with the ribbon label set by `title:` in its
`bundle.yaml`. pyRevit names a ribbon item after its folder, and a folder that
clashes with one already installed in the same panel fails the load with "The
name already exists" — at which point pyRevit **abandons the rest of that
panel**, so half the extension's buttons disappear. v3.0.0 shipped as
`System Offset.pulldown` and did exactly that.

The old `System Offset.pushbutton` should still be deleted, but nothing breaks
if it is not: you get two entries in the panel until it goes.

## Version control

`__version__` at the top of `so_core.py`. Both windows read it from there and
show it in the top right, so bumping that line is the only edit.

## Revit 2024 – 2027

- `so_clr.py` references every assembly before any `System.*` or `Autodesk.*`
  name is touched, and every other module imports it first.
- No `System.Uri` — the logo loads from bytes through a `MemoryStream`.
- No bare `ElementId.IntegerValue` — everything goes through `eid_value`.
- `BuiltInCategory` members are looked up late, inside a function.
- `PlumbingUtils.BreakCurve` and `MechanicalUtils.BreakCurve` are each tried
  inside their own try/except and fall through to the manual split, so a
  release that moves or drops one does not take the tool down.
- No f-strings, no `print`, `.format()` throughout, `u''` literals.

## Dark and light

Every brush and control template lives in one `Theme.xaml`, referenced from the
layouts with `DynamicResource` only. `theme.apply` writes the chosen palette
straight onto `window.Resources`, which sits in front of a merged dictionary in
WPF's lookup order, so the palette swaps on an open window with no reload.

The default is **follow Revit**: `UIThemeManager.CurrentCanvasTheme`, then
`CurrentTheme`, then dark. The chip in the header cycles Auto, Dark, Light and
the settings window has it as a dropdown that applies on pick.

The light palette is not the dark one inverted — the accents are darkened
(`#4FA3E3` → `#1B72BE`, `#E8912D` → `#B96A12`, `#3FA75A` → `#2E8546`).

## Decisions worth remembering

- **A `PickPoint` is not a point on the element.** v3 made the second click a
  `PickPoint` so the direction could be read out of which side it landed. The
  point sits on the **view's work plane**, not on the run, so projecting it
  back onto the centreline landed past the end of the element often enough to
  refuse nearly every offset. Clever, and wrong. Asking for the direction in a
  prompt costs one keypress and cannot misread anything.
- **Clamp, do not refuse.** A guard that turns a run down because a click was
  4mm from its end is a guard that turns down the run. Move the cut in and say
  so.
- **The prompt and the routine share one arithmetic.** `max_offset_mm` decides
  what the prompt will accept and `plan_offset` decides what the routine will
  build; the bench asserts they agree at every angle, because a prompt that
  offers a number the routine then refuses is worse than no prompt.
- **A record needs two lists, not one.** What happened and what went wrong are
  different things, and a successful offset produces plenty of the first. The
  report opened after every single run until they were separated, and the
  remarks it was opening for were all perfectly correct — which is what made it
  read like the tool complaining about its own work.
- **A click in space is not where Revit says it is.** `PickPoint` returns a
  point on the view's work plane, which in a plan is the level rather than the
  height the service is at. Projecting each click onto the plane through the
  current end, parallel to the view, keeps a plan route at its elevation and a
  section route at its depth with one rule. This is the same trap that made
  System Offset v3 refuse nearly every offset, met a second time from a
  different direction.
- **A preference is not a rule.** A column is gone round and a beam is gone
  under, but a preferred way out that costs four metres against three hundred
  for the alternative is not the right answer. Clash Offset prices all four
  ways, takes the preferred one if it is within a third of the cheapest, and
  says when it did not.
- **The cuts have to sit back by a bend's worth.** A jog's offset middle does
  not start at the cut, it starts `offset / tan(angle)` further in, so cutting
  at the edge of an obstruction plus a clearance still lets the sloping legs
  clip it.
- **One pick cannot cover both the model and a link.**
  `ObjectType.LinkedElement` picks the beam inside a link but nothing in the
  host model at all; `ObjectType.Element` hovers a link as one whole building
  rather than the beam inside it. Asking with LinkedElement alone made model
  elements unreachable. Two picks, either skippable, is the only honest answer.
- **Measure the service the way it is about to move.** A 600 x 300 duct is
  300 out to the side and 150 up. Using the larger dimension both ways
  over-clears the narrow way by 150mm — safe, but it moves services further
  than they need to go, and the real number is there to be read.
- **Insulation is a separate element.** A geometry read that does not ask for
  it offsets the service by its core size and leaves its lagging fouling the
  thing it was meant to clear.
- **A bounding box is not the obstruction.** It is axis aligned, so a beam at
  an angle reads far bigger than it is and the service gets pushed much further
  than it needs. Edge points are exact; the box is a fallback, and it only ever
  overstates.
- **Adapt rather than refuse, but know what must not be traded.** A level
  change has a height, a run on and an angle, and only the height is the point
  of it. Shortening the run on and then steepening the angle fits almost any
  click; refusing because the first arrangement did not fit made the tool feel
  broken when it was only being literal.
- **A click in a plan lands on a level plane, so a routed pipe comes out
  level.** The fall has to be put back deliberately: set the corners out in
  plan, then drop each onto the run's own gradient. Doing it that way also puts
  the first corner exactly on the sloped run's centreline, which is what the
  split there needs.
- **A jog cannot hold its gradient and rejoin the run it left.** It is longer
  in plan than the straight it replaces, and at a fixed gradient extra length
  is extra fall, so a true-gradient jog arrives low by
  `2 x offset x tan(half the bend)` — 4mm for 300mm at 45 degrees on 1:60.
  The ends and the long middle hold the fall; the two short bend legs carry the
  difference, and the report says by how much. A break has no such constraint
  and holds the fall on every piece.
- **Measuring a turning route corner to corner reads steeper than its
  gradient**, because the fall follows the path and the path is longer than the
  straight line. A correct route looks wrong if checked that way.
- **A bank is a parallel offset of the route, not a copy of it.** Same in both
  tools, met twice from different directions. Putting every run's bend at the
  same station pulls the diagonals to `cos(angle)` of the spacing — 300mm
  becomes 212mm at 45 degrees and 0mm at 90. Each leg is shifted square to
  itself and each corner is where the shifted legs cross, which staggers each
  bend along its own run by `spacing x tan(half the turn)`. Two pipes
  side by side running east, translated 300mm north, are 300mm apart on the leg
  that runs east and exactly on top of each other on the leg that turns north.
  Spacing is measured square to each leg, so every leg is shifted sideways and
  the corner is where the shifted legs cross — the outer strand turning later
  than the inner one is the whole point. Spacing straight through the routing
  plane is the exception and is a plain shift.
- **A bend of less than a right angle starts before the click**, by
  `sideways / tan(angle)`. This is the same arithmetic as the offset tools'
  run-back, arrived at from the other end; anywhere a turn has to arrive at a
  given point, it is there.
- **The first leg is the run, not a piece bolted onto it.** That is what lets
  "split at the point of the bend" mean something, and it is what makes every
  click in Click System the same operation rather than the first one being a
  special case.
- **Two tools, one routine.** Offset Break is not a second implementation. It
  shares `analyse`, the prompt, the pick loop, the fit test, the transaction
  group and the rollback path; only which pieces get built differs. The cost of
  that is that the two loaders are near identical files, so the bench carries a
  rule that fails if they call `so_run.run` the same way — a copied loader
  that forgot to change the mode would give two buttons doing the same thing
  and looking entirely correct.
- **Re-fetching a connector is not a substitute for regenerating.** Revit
  shortens the two pieces either side of a bend to make room for the fitting,
  so the next bend measures a piece that has changed. Reading the connector
  live still reads it from a model that has not caught up, and Revit answers
  with "the angle between them is too small or too large". Two of four bends
  took a fitting and two did not, every time, until the regenerate went back.
- **A run's own axis points whichever way it was drawn**, so left and right
  cannot be taken from it. They come from the way the run reads on screen
  instead. The first attempt tested the side vector against the view's right
  direction, which is exactly zero for a run lying across the view — a guard
  that looked right and did nothing.
- **Regenerating is what this tool costs.** Not the geometry, not the picks,
  not the window — `doc.Regenerate()`, called a dozen times per offset on a
  model where each call is a fraction of a second. Batching the curve edits and
  trusting a live connector re-fetch between the bends took it to four. Before
  optimising anything else here, count the regenerates.
- **The selection filter is the hottest code in the tool.**
  `ISelectionFilter.AllowElement` runs for every element the cursor passes
  over, so anything in it that is not a dict lookup is felt as lag on the pick
  rather than as time in the routine.
- **A modal dialog raised from inside the command is safe; an `ExternalEvent`
  would not be.** The command is still running, so the prompt can block for an
  answer. Waiting on an `ExternalEvent` from the window that raised it
  deadlocks, which is why this tool has neither.
- **`PickObject` for one, `PickObjects` for many — and the difference is a
  keystroke.** Neither click here uses `PickObjects`, so nothing in the default
  path needs Enter or Finish.
- **`tan(45 degrees)` is 0.9999999999999999.** A run with exactly enough room
  came out 3e-14 mm short and was refused. Any "does it fit" comparison built
  on a trig call needs a tolerance.
- **Cable tray and conduit have no `BreakCurve`.** Only Plumbing and Mechanical
  ship one. Everything else is split by copying the element and re-cutting both
  halves, which is what the utility does internally anyway.
- **`BreakCurve` does not say which half it hands back.** It returns "the new
  element", and that is not reliably the far side of the cut. Assuming it was
  left the original run at full length with the offset built over the top of
  it, and every following cut landed on the wrong piece. The tell was that
  cable tray and conduit — the two categories with no `BreakCurve`, going
  through this tool's own copy-and-re-cut — were the only things working.
  **Measure which half is which; never assume.** `split_at` returns both, in
  order along the run.
- **Re-fetch every connector after `doc.Regenerate()`.** A `Connector` handle
  held across a regenerate goes stale, and connecting through a stale handle
  produces two pieces that look joined and behave as loose parts. `place_elbow`
  takes elements and a point, never connectors, for exactly this reason.
- **The legs are copied from the middle, not rebuilt.** Size, type, insulation,
  lining and every instance parameter come along for free; rebuilding them
  means reading and re-applying all of it and getting one wrong.
- **Rigid re-cutting, not moves.** The middle's `LocationCurve` is rewritten
  once it has been disconnected at both ends, rather than being moved with the
  connections live.
- **The split and the fittings are separate transactions inside one
  `TransactionGroup`**, so a refused fitting never leaves the run cut in half,
  and Revit's undo still sees one step.
- **A refused elbow joins the pieces directly and says why.** Leaving a run in
  five loose parts because one routing preference was missing is worse than a
  bend with no fitting in it.
- **`GetParameters`, not `LookupParameter`**, for the service type push — a
  family can carry two parameters of the same name and the two calls do not
  always hand back the same object.
- **Height Adjust does not belong here.** It was in this tool first, was
  extracted to `lib\revobim\height_adjust.py` so Nudge and MEP Link could share
  it, and having it in two places was a way to have two behaviours.
- **A blank white pyRevit window means the script died before any of it ran.**
  Both `script.py` files are thin loaders that name the stage that failed —
  assemblies, modules, reading the model, the picks, reporting — into a Revit
  dialog and into `%APPDATA%\RevoBIM\system_offset_last_error.txt`.
- **A failed text edit is silent, and the result still compiles.** A block
  replacement whose anchor does not match leaves the code that uses a name
  while the code that defines it never lands. Nothing complains until the line
  runs in Revit. The bench rule for it — every global a function reaches for
  exists, walked with `symtable` — is cheap, and is the one that would have
  caught it.
- **A rule nobody has tested is a rule that does not work.** All 16 bench rules
  are proved by `--selftest` breaking each one on purpose. Two rules were doing
  nothing when first written: the `so_clr` rule counted imports inside
  functions, which run long after module load, and the `.IntegerValue` and
  `System.Uri` rules fired on the comments explaining themselves.

## Bench checks

Both run under plain CPython from the pulldown folder.

`import_check.py` — **16 rules**: every `.xaml` parses as XML; every .NET name
comes from the namespace the real API puts it in; nothing reaches into
`System.*` or `Autodesk.*` at module level before `so_clr`; no `StaticResource`
in a layout; no `DynamicResource` key `Theme.xaml` lacks; no style applied to
an element its `TargetType` does not match; no `FindName` without an `x:Name`
(aliased calls included); no f-strings, no `print`, no bare `.IntegerValue`, no
`System.Uri`; both palettes carry every key and `Theme.xaml` has a brush for
each; nothing defined twice; every module loads against the stub API; the
ribbon name is unique, prefixed and consistent across the folder, the bundle
title and `__title__`; the easter egg is wired to the logo in both windows; and
**no shared and singular file is shipped** — no `startup.py`, no hook, no
`lib\revobim\__init__.py`.

`python import_check.py --selftest` breaks each rule on purpose. All 16 catch
their own breakage.

`bench_logic.py` — **76 checks** over the run-back arithmetic at every angle,
the minimum span and its refusal message, angle snapping and clamping, the
three distance modes with rounding and the floor, direction from the click and
both fallbacks, the settings round trip, a damaged file, a migration, a value
containing an `=`, and `eid_value` against a 2024-style and a 2026-style
`ElementId`.

## Open items for a future version

- **Four direction-specific command buttons** (Offset Up / Down / Left /
  Right), each bindable to its own key, for people who would rather not let the
  click decide.
- A run that is already sloped is offset square to its own axis, so an offset
  up on a falling pipe rises square to the fall rather than vertically. Correct
  for a services offset, arguable for drainage.
- The offset is always parallel — there is no mode that steps the run onto a
  different level and leaves it there.
- Several parallel services are offset one at a time; a bank has to be done
  one by one.
- Insulation on the two legs comes from the copy, so a run whose insulation
  varies along its length picks up the middle's.
- No preview. The offset happens on the second click, and Escape is the only
  way out before that.
- A takeoff-style branch, rather than an offset, would use most of the same
  geometry.
