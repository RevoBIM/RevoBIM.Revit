# Space Creator — Changelog

## 3.1.0

### The window stretches
It carries **eight resize grips** of its own — four edges, four corners,
with the right cursor on each. WPF gives an `AllowsTransparency` window no
hit-testable frame, so its own resize border never fires however
`ResizeMode` is set, and the window was stuck at its start size. The grip
overlay has **no Background**, so everything under it stays clickable.

Dragging a left or top edge moves `Left`/`Top` as well as the size, and
every change is clamped at `MinWidth`/`MinHeight` — without the clamp a
fast drag past the minimum inverts the window.

Stretching now actually gains something, which needed two layout changes:

- **The body was a StackPanel**, which gives every child its natural
  height, so the tabs stayed their start size however far the window was
  pulled. It is a Grid with a star row now, and the TabControl takes the
  slack.
- **The Manage tab is a Grid** on the same principle, so the space list
  grows with the window instead of staying 300px with the toolbar pinned
  under it.

Starts at 860x720, minimum 620x420.

### Scrollbars are dark
A stock WPF `ScrollBar` **ignores `Background`** and renders in the system
light theme, which is why every scrollable panel had pale grey bars
against a near-black window. They are **retemplated**, not recoloured:

- a rounded thumb in `#4A4A50`, lightening on hover and turning **blue**
  while dragged;
- the line and page buttons are made invisible but kept — removing them
  from the template breaks `ScrollBar`'s own layout;
- 11px, transparent track, so the bar sits on the panel rather than in a
  grey gutter.

The style carries **no `x:Key`**, so it applies implicitly to every
ScrollBar in the window — including the ones WPF creates inside a ListBox
or ScrollViewer that a layout never names. It is injected into all five
windows from one definition, so they cannot drift apart.

### Bench
- The XAML rule now **wraps shared fragments** in a root carrying the
  namespaces, so the scrollbar and grip blocks are still parsed rather
  than skipped for not being whole documents.
- New rule: **every grip name exists in XAML**. The grips are looked up
  through a variable in a loop, so the `FindName` rule cannot see them and
  a typo would silently leave one edge unresizable. Verified by
  misspelling `GripBottomRight`.

## 3.0.0

### New tab: Manage
A third tab listing **every space in the project** — Level, Number, Name,
Base Offset, Limit Offset, Upper Limit, Height and Status.

- **Sort** by any column: click a heading, click again to reverse. Sorted
  by level (building order, then number) by default.
- **Group** by Level, Upper Limit or Status from a dropdown. Groups keep
  the sort order of their first member rather than being alphabetised, so
  a level-sorted list stays in building order when grouped by level.
- **Search** across every column, and a **Flagged only** tick to isolate
  the spaces that need a look by hand.
- **Base Offset and Limit Offset are editable** straight in the grid, in
  millimetres. An edited cell turns orange and the row is pending;
  **nothing is written until Apply.** Discard Pending throws the edits
  away; Refresh re-reads the model and refuses to run while edits are
  pending so they cannot be lost by accident.

Rows are built as WPF elements in code and the model is a list of dicts —
nothing is bound to a Python object, per the house rule.

### Push Spaces Up To Floor
Select spaces in the model (Revit's own selection, Finish when done). For
each, the tool works out how far up it can go:

- to the **underside of the nearest floor above** the space's location
  point, skipping the slab it stands on;
- but **never past the base of a space stacked above it**, so no space is
  pushed up into another.

The result is set as a pending Limit Offset, anchored to the space's own
level so the offset alone carries the height. Anything that cannot be
done — no floor above, nothing above to extend to, already at that height
— is **flagged with the reason** and left alone; Flagged only isolates
them for review. Nothing is written until Apply.

### Apply and the change report
Apply writes every pending row in **chunks of 25**, one transaction each,
with the **progress bar** running between them (never pumped inside a
transaction). Every space is **read back after the commit** and compared
with what was asked — a void `Set()` is not evidence — and one that did
not stick is flagged rather than counted. The grid is re-read afterwards
so Height, which Revit computes, shows the real value.

A **report window** then lists every space touched: level, number, name,
result, and exactly what changed, `from -> to` in millimetres. Failures
and unverified writes appear in the same list in red.

### Bench
`bench_push.py` is new: 9 checks over the push-up arithmetic — reaching the
floor above, ignoring the slab stood on, **stopping at a space stacked
above**, ignoring a space above that is elsewhere in plan, a raised base
skipping the slab it now sits inside, and the three flag cases. Verified
by removing the space-above check and confirming the space pushed through
to the floor.

The symtable rule caught four undefined names during this build before
they reached anyone.

## 2.18.0

### Levels were being read in survey coordinates
The log line added in 2.17.0 gave the answer immediately:

```
lines for T3.4: 1  room Z 17226mm, level LB1 - LEVEL BASEMENT at 84150mm
```

A room whose geometry sits at **17226mm**, and every host level reporting
**84150mm or more**. The same offset was visible earlier: a picked box at
Z **21815mm** while the view band read **104815mm** — about 83m apart,
every time.

`Level.Elevation` is reported relative to whatever the level's **Elevation
Base** parameter is set to. On this project that is the **Survey Point**,
so it returns survey elevations, while every point the geometry API
returns is in internal project coordinates. Comparing the two chose the
basement for a room on level 4, drew the separation lines down there, and
left every space unenclosed. It is also why the level band excluded
everything in earlier versions.

All elevation reads now go through a `level_elevation()` helper that
prefers **`ProjectElevation`** — the internal one — and falls back to
`Elevation` on a level that has no survey offset. That covers the level
band, the view range, the nearest-level match, the sketch plane, the
push-to-ceiling levels and the level list.

A bench rule now **bans raw `.Elevation` outside that helper**, and
`bench_rooms.py` gains 5 checks built on a level whose survey elevation is
272ft from its project elevation. Verified by restoring the direct read
and watching the check fail with 328.5 instead of 56.5 — the offset
exactly.

### Speed
- **One sketch plane per level, not one per room.** `SketchPlane.Create`
  makes a real element every time, so a run of several hundred rooms was
  creating several hundred identical planes. This was the largest single
  cost in a batch.
- **The room count now fills the cache.** It used to collect every room to
  count them and throw the result away, so the first click collected them
  all again.
- **Duplicate checking is set-based.** Adding hits rebuilt a list of every
  listed key for every hit — quadratic, and a box over a floor is hundreds
  of hits.
- **Separation lines are collected once** for a delete, not re-read per
  room.

### Delete Lines Around Listed
New button on the Manual tab. It deletes the space separation lines lying
inside every room in the list — for clearing a bad run, or the perimeter
of a room before redrawing it. Lines are matched by their **midpoint**
falling inside the room boundary, because a line shared between two rooms
sits exactly on the boundary and its ends coincide with the neighbouring
loops.

## 2.17.0

### The lines were on a different level to the spaces
The log showed the 2.16.0 ordering fix working exactly as intended — two
perimeters drawn, a regenerate, then two spaces — and both spaces still
came out unenclosed. So the order was not the problem after all.

The separation lines were drawn on a sketch plane at the **linked room's
own location point Z**, which carries the link's transform and the room's
base offset. The space was created on the **nearest host level**. Those
are two slightly different elevations, and **a separation line only bounds
a space that shares its level** — so the perimeter was visibly right there
and Revit would not use it.

The sketch plane is now built **from the level the space will be created
on** (`SketchPlane.Create(doc, level.Id)`), and the curves are flattened
to that level's elevation rather than to the room's Z. Both create paths
pass the level through.

The log now records, per room, the room's Z **and** the level's elevation
side by side, so any remaining gap between them is visible rather than
inferred. A space that still does not enclose has its own level logged too.

The status line no longer says the boundary "did not close", which was a
guess: it says the space exists and is placed but Revit is not treating
the perimeter as bounding it, and points at the log.

### Also
- `draw_lines_for_linked_room` removed. It became unreachable when line
  drawing moved into the two-pass create in 2.16.0, and a dead path that
  still looks callable is how the last regression got in.

## 2.16.1

### Two definitions were deleted by a block rewrite
2.16.0 rewrote `run_manual` by replacing a range of lines, and that range
also contained **`AddFromListHandler`** and **`run_cleanup`**. Neither is
called until the window is built, so nothing failed until the tool was
opened, and then it failed on the first one:

```
NameError: global name 'AddFromListHandler' is not defined
```

- `AddFromListHandler` is restored.
- `run_cleanup` is **not** restored, because it is genuinely dead now:
  nothing is drawn at pick time any more, so Remove and Clear have no
  lines to delete. The cleanup mode has been taken out of `RunHandler`
  rather than left as a path that can never run.

### The rule that should already have been here
`import_check.py` gains the **symtable** rule from the rest of the
extension: *every global name a function reaches for must exist in its
module*. It is the rule specifically for definitions lost to a block
rewrite, and it was missing from this tool.

Adding it immediately found a second, unreported bug: `run_automatic`
used `made_spaces` and `unenclosed` without ever initialising them, so
the **Automatic tab would have thrown `NameError` on its first run**.
That came in with the enclosure check in 2.16.0 and nothing had exercised
it yet.

Verified both ways: deleting `AddFromListHandler` again reproduces the
reported error, and removing the counter initialisation reproduces the
second. IronPython 2 builtins that the code probes deliberately
(`unicode` and friends, inside `try/except NameError`) are allowlisted
with a note, rather than the rule being loosened to let them through.

## 2.16.0

### "Space is not in a properly enclosed region"
The separation lines were drawn and the space placed **in the same
transaction with no regeneration between them**. Revit does not treat a
line drawn moments earlier as bounding until it regenerates, so every
space was placed into a region whose perimeter existed but had not been
seen yet. The boundary was right; the order was wrong.

Both tabs now work in passes:

1. every **boundary** for the batch is drawn;
2. **`doc.Regenerate()`**;
3. then the **spaces** are placed;
4. a second regenerate, and each space is checked for whether it actually
   bounded.

Doing all the lines first also means one regenerate per batch rather than
one per room, so it is faster than the naive fix as well.

### The warning no longer stops the run
"Not in a properly enclosed region" is a warning, not an error — Revit
still creates the space. Left unhandled it interrupts with a dialog per
space, which on a batch of four hundred is unusable. An
`IFailuresPreprocessor` now deletes warnings on every transaction, and the
run **reports how many spaces came out unenclosed** instead: the same
information, once, at the end.

A space that genuinely does not enclose is now named in the log and
counted in the summary, so a room whose boundary does not close in the
host model is visible rather than silent.

### Bench
New rule: **a regenerate must fall between drawing separation lines and
creating a space**. It tracks every line call, regenerate and space call
through the file and fails if a space is created after lines with no
regenerate in between (4 line calls checked). Verified by deleting one
regenerate and confirming it was caught by line number.

## 2.15.0

### Revit's own Finish button
Selection used `PickObject`, which takes one click and offers only Escape.
It now uses **`PickObjects`**, the multi-pick form — the one that puts
Revit's own **Finish** and **Cancel** buttons on the options bar. Rooms
still highlight and Tab still cycles through stacked ones; clicking keeps
adding to the selection until Finish is pressed, and the whole selection
arrives at once.

### The create path had no logging at all
Your log stopped at `session end` because **nothing in Create Spaces
wrote to it** — the entire creation path was a blind spot while selection
was fully instrumented. It is now logged end to end:

- what the run was asked to do — room count, boundary mode, name
  inheritance, ceiling push, workset, host level count, active view;
- per room: the host point and the level it resolved to, how many boundary
  loops came out of the link, how many separation lines were drawn, the
  **element id of the space created**, or the exact reason it was not;
- a full traceback if the run throws and rolls back, which previously
  produced a status line and nothing else;
- the totals.

### Spaces created but not visible
A new check runs after every creation: if **Spaces** or **Space separation
lines** are hidden in the active view, that is reported in the status line
and the log. A coordination view very often has them turned off, and a
space that exists but is hidden is indistinguishable from one that was
never created — which is a real candidate for what you are seeing, since
the run reported no error.

## 2.14.0

### Rooms are picked directly again — Tab and click, with highlighting
You were right that linked rooms can be selected with Tab+click. **They
can**, and this tool said otherwise for eleven versions.

The original 1.x picker used `PickObject` with a selection filter. When it
appeared to select nothing, the conclusion drawn was that a room in a link
is not a pickable element, and selection was rebuilt twice around that —
point resolution in 2.2.0, rectangles in 2.8.0, then level filtering to
undo the side effects. **The picking was almost certainly working the
whole time**; the room was resolved and then discarded a moment later on
`room.Name`, the `AttributeError` not found until 2.11.0. Every problem
since has been a consequence of working around a constraint that was not
real.

**Select Rooms** now uses `PickObject` with a room filter:

- rooms **highlight under the cursor**, drawn by Revit itself;
- **Tab cycles** through rooms stacked at that point, which is the correct
  answer to the level problem and needs no filtering at all;
- each click adds one room and the loop continues, Escape finishes;
- **no elevation filtering is applied to a click** — a room you pointed at
  is the room you meant. The Rooms On dropdown now only governs Box Select
  and From List.

It picks linked rooms or this model's rooms according to the Read Rooms
From choice, and needs no room collection to work, so it runs even when
the collection reports nothing.

**Box Select** keeps the 2.8.0 rectangle behaviour on its own button, for
adding many rooms at once.

### Also
- The **workset is remembered** between sessions.
- The window stays visible while picking, so the list fills in as you go.

## 2.13.0

### The level filter was measuring the wrong thing
2.12.0 filtered rooms to the view's own level, and the log showed why that
failed:

```
view level elevation: 109810mm, band +/-1219mm
hits: 0
```

The view is a **roof level** plan at 109.8m; the rooms visible in it are
several storeys below. A coordination plan routinely shows rooms far under
its own level through its view depth, so filtering to the level elevation
threw away everything on screen — the opposite failure to 2.11.0, where
nothing was filtered at all.

Selection is now bounded by the view's **view range** — the top clip,
bottom clip and view depth planes, which are what actually decide what a
plan view draws — with 300mm of slack for base offsets. The elevation
band used is written into the debug log at the start of every session.

New **Rooms on** dropdown on the Manual tab:

- **This view (what it shows)** — the view range, the default;
- **All levels** — no filtering;
- **any level by name**, listed from the chosen source with its elevation,
  for when neither of those is what you want.

Where several stacked rooms still contain the point, the **highest** one
inside the band now wins, since a plan shows the storey you are on rather
than the ones beneath it.

### Rooms appear in the list as you click them
The window is no longer hidden while picking. Revit cannot highlight a
linked room — a room is not a pickable element, which is the constraint
this whole tab has been working around — so the list filling in with each
room's **name and level** as it is clicked is the only feedback available,
and hiding the window removed even that. It is modeless, so Revit stays
fully usable underneath; drag it aside if it covers the area being picked.

### The workset is remembered
The chosen workset is saved and reselected next time the tool opens, if it
still exists in the model.

### Bench
The level checks are rewritten against the band API, with a new case for a
**deep view range** — the field situation, a roof level view whose range
reaches several storeys down — confirming both stacked rooms stay eligible
and the higher one wins the click.

## 2.12.0

### The wrong storey's room was being selected
Two clicks a few millimetres apart in the log returned rooms from two
different floors:

```
box: min=(343.47,-110.78)  ->  L00-KOP-009 - Club Shop
box: min=(342.93,-110.87)  ->  L04-KOP-001 - Hospitality Lounge
```

Fixing `IsPointInRoom` in 2.4.0 meant making the containment test purely
two dimensional, and that overcorrected: **rooms stack vertically**, so a
click in plan is inside a room on every storey of the building at once and
whichever the collector reached first won.

- Rooms are now filtered to **the level the view is associated with**,
  within a ±1.2m band that allows for base offsets. New checkbox on the
  Manual tab, **Only rooms on this view's level**, on by default; unticking
  it restores the all-levels behaviour for a 3D view.
- Where more than one room still contains the point, the one **nearest the
  view's level** wins rather than the first one found.
- Box selection is filtered the same way.
- The elevation the tool is working to is written into the debug log at
  the start of each session.

**The list now shows each room's level**, so a room from the wrong storey
is visible at a glance rather than having to be inferred from its number.

### Nothing is created until Create Spaces
Separation lines were being drawn as each room was picked. They are not
any more: **selecting rooms is now entirely read-only** — no lines, no
spaces, no transaction at all, from either Select Rooms or From List. The
list can be built up, corrected and cleared with nothing left behind in
the model.

Everything is created when **Create Spaces** is pressed, honouring the
boundary choice at that moment — so the separation-lines-or-not decision
can now be changed after the rooms are chosen.

### Bench
`bench_rooms.py` gains 6 checks over level filtering, built on two rooms
stacked directly on top of each other with identical plan boundaries — the
field case exactly. Verified by removing the level filter and confirming
three checks failed, returning "Hospitality Lounge" where "Club Shop" was
expected: the same wrong answer the log showed.

## 2.11.0

### `room.Name` was throwing, and every room was discarded on it
The debug panel named the fault on its first run:

```
hits: 1
  SKIP ? - could not build entry: Name
```

`AttributeError: Name`. **`Element.Name` is not reliably readable through
IronPython** — on some Revit and engine combinations the property simply
raises. `room.Area` worked, so 408 rooms were found and every box
resolved correctly; then every single hit was thrown away one line later
trying to read its name. Two versions of selection logic were rewritten to
fix something that was never broken.

Reading and writing names now go through helpers that try, in order: the
**built-in parameter** (`ROOM_NAME` / `ROOM_NUMBER`, the value Revit itself
shows), then the property descriptor (`Element.Name.GetValue`), then the
plain attribute, then a lookup by name. Nothing anywhere touches
`element.Name` or `element.Number` directly any more — not the picker, not
From List, not the results list, not the space naming on either tab.

The write side gets the same treatment, which also covers inheriting a
room's name onto a space.

### Dragging a box inside one big room
Several `hits: 0` lines in the log were small boxes dragged *within* a
single large room. A room was only selected if its **location point** fell
inside the rectangle, and a small box inside a big room does not contain
that point.

A rectangle now also selects **the room containing its centre**, so a box
dragged anywhere inside a room picks that room up. Rooms are de-duplicated
across the two rules.

### Bench
`bench_rooms.py` gains 5 checks using a `HostileRoom` stub that reproduces
the field failure exactly — `.Area` works, `.Name` and `.Number` raise
`AttributeError`. Verified by restoring the direct `element.Name` read and
confirming the suite fails with the same `AttributeError: Name` seen in
the log. Also checked: the plain attribute is still preferred when it
works, and an element with no name anywhere returns empty rather than
throwing.

## 2.10.0

### The log proved selection was working all along
The pick log settled it:

```
session start: source_key=all sources=3 rooms_available=450
box: min=(341.79,-109.42,71.57) max=(341.79,-109.42,71.57)
hits: 1
box: min=(340.03,-108.00,71.57) max=(350.19,-114.47,71.57)
hits: 7
```

450 rooms found, clicks resolving to one room, a dragged box resolving to
seven. **Selection was never the problem.** Every version from 2.2.0
onwards was aimed at the wrong half of the tool: the failure was
downstream, in the code that turns a hit into a list entry, and that code
was swallowing its own failures three separate ways.

`add_hits` had three faults, each of which alone produces "nothing
happens":

1. **A bare `except: continue` around building the list entry.** A room
   that could not be turned into an entry vanished with no message and no
   log line.
2. **The line-drawing transaction was never rolled back on failure.** If
   anything threw after `Start()`, the transaction stayed **open** — so
   every later transaction in the session failed too, including the one
   that restores the view's visibility settings. One bad room poisoned the
   whole session.
3. **`list_box.Items.Add(...)` was wrapped in `except: pass`.** A room
   could be sitting in the internal list and be invisible in the window,
   which is exactly "the click worked but nothing appeared".

All three are fixed: the transaction is rolled back properly, nothing is
swallowed, and every step is logged by name. `add_hits` is also wrapped at
the call site — an exception escaping it used to kill the handler outright,
which skipped the `window.Show()` and left the tool looking like it had
vanished.

Each session now ends by logging `picked_rooms=N list_items=N`. If those
two ever disagree, the window and the internal list have diverged, and the
log says so directly.

### Debug panel
A retractable **Debug log** at the bottom of the Manual tab, **collapsed by
default**. It shows the same lines the log file gets, live, as they
happen — session start, each box's coordinates, hits, per-room outcomes
(entry built, duplicate, lines drawn, added, or the exception), and the
end-of-session counts. **Select all** then Ctrl+C copies it.

The file at `%APPDATA%/RevoBIM/space_creator_pick.log` is still written, so
either route works.

### Bench
New rule: **no SyntaxWarnings**. A backslash in a XAML comment
(`%APPDATA%\RevoBIM\...`) is read by Python as an escape sequence before
XAML ever sees it — it was warning during this build. Caught, fixed, and
the rule verified by putting the backslash back.

## 2.9.0

### The button really was doing nothing
`Select Rooms` counted the rooms in the chosen source first, and **if that
count came back zero it never called `PickBox` at all** — no crosshair, no
box, no prompt in the status bar, nothing. The whole selection step was
skipped before Revit was ever asked for a selection, which is precisely
"it's not letting me pick rooms".

That refusal is gone. When no rooms are found the tool now says so
plainly and points at the new Diagnose button, instead of silently
declining to start.

### Diagnose
New button on the Manual tab. It reports, in plain language:

- the active view — name, type, whether a template is applied, its
  associated level (or that it has none, which means it is not a plan
  view);
- how many placed rooms are in **this** model;
- every Revit link instance, how many have a **loaded** document, and for
  each: how many room elements of any kind it holds, how many of those are
  actually placed, and a sample of three with their **host coordinates in
  millimetres**;
- which source is currently selected, and a summary.

It calls out the cases that look identical from inside Revit but have
completely different causes: every link unloaded, rooms that exist but are
unplaced or unenclosed (no area, so no space can be made from them), and
no rooms anywhere — which is a model question that no visibility setting
can affect.

The report is selectable text so it can be pasted.

### A log of every selection session
Every session writes to `%APPDATA%\RevoBIM\space_creator_pick.log`: the
chosen source, how many rooms were available, the coordinates of each box
dragged, how many rooms fell inside it, and any exception `PickBox` threw.
A session that quietly does nothing is otherwise impossible to explain
afterwards.

### Note
Three attempts at this have now failed for three different reasons, none
of which were visible from inside Revit. The point of this version is to
stop guessing: Diagnose and the log say what the tool can actually see, so
the next fix can be aimed at the real cause. **From List remains the route
that does not depend on selection working at all.**

## 2.8.0

### Selecting rooms by rectangle, not by clicking them
Every attempt so far has been built on clicking a room, and that was never
going to work. **A room is not a pickable element in Revit** — not in a
link, not in this model. `PickObject` will not register a click on one at
all, and `PickPoint` only ever gave a coordinate that then had to be
resolved back to a room, which is where each of the earlier bugs lived.

**Select Rooms** now uses `PickBox`:

- **Drag a rectangle** over the rooms and every room whose location point
  falls inside it is added. Pickability never comes into it — a rectangle
  is a pair of coordinates and the rooms inside it are worked out
  directly.
- **Click a single room** and it still works: a rectangle too small to be
  a real drag is treated as a click and falls back to point-in-room.
- The rectangle is normalised, so dragging right-to-left or bottom-to-top
  behaves the same as dragging the other way.
- The loop repeats until Escape, so several boxes can be dragged in one
  session, each adding to the list as it goes.

### Read Rooms From
New dropdown on the Manual tab: **All sources**, **This model**, or any
single loaded link by name. It drives the selection, the From List window
and the counts in the status messages, so a model with several links can
be narrowed to the architectural one.

An empty selection now reports how many rooms are available in the chosen
source, which distinguishes "the box missed" from "this source has no
rooms in it".

### Bench
`bench_rooms.py` gains 8 checks over rectangle selection: a box over this
model, over a link, over both, over empty space, one restricted to a
single source, a backwards drag, and the click/drag threshold either way.
32 checks in total.

Two things this caught while being written: the backwards-drag check
failed against an un-normalised rectangle (verified deliberately
afterwards), and the first run failed four checks because the stub room
had no location point — a fixture gap rather than a code fault, but the
sort of thing that would otherwise have been "written a test, it passed,
moved on".

## 2.7.0

### The picker searched links only
The manual picker only ever looked for rooms **in the loaded links**. If
the rooms are in the model you have open, no click could ever resolve one
— the room was visible, the click registered, and nothing matched, because
the model's own rooms were never in the search at all.

`find_room_at_point` now searches **this model first, then the links**. A
room in this document is placed through its own path — no transform, no
host level lookup — on the Manual tab, in the From List window, and in
Remove/Clear cleanup.

**From List** now lists this model's rooms as well, under "This model".

### PickObject reverted to PickPoint, deliberately
2.6.0 moved to `PickObject` to get the selection cursor. That was wrong: a
room is **not a pickable element**, in a link or in this model, so with
`PickObject` a click on a room does not register at all — worse than the
crosshair it was meant to fix. It is back to `PickPoint`, which accepts a
click anywhere, which is what lets every click add a room.

Snapping is now switched off, so it is a plain crosshair rather than
Revit's drawing cursor with snap markers. (`ObjectSnapTypes.None` cannot be
written as an attribute in Python — `None` is a keyword — so it is fetched
with `getattr`.)

### A miss now says why
A click that matches nothing reports how many rooms are known, split
between this model and the links, and how far away the nearest room is in
millimetres. A miss of 50mm is a coordinate problem; a miss of 40 metres is
a different link; no rooms at all is a collection problem. Guessing
between those is what the last few versions have been doing.

### Bench
`bench_rooms.py` gains 4 checks over resolution across both sources —
including that a room in this model resolves with no link, which is
exactly the case that was unreachable. Verified by restoring the
links-only search and confirming that check failed.

## 2.6.0

### The manual picker behaves like a picker
It was using `PickPoint`, which puts Revit into point-placement mode: a
snapping crosshair, no highlighting, and every visual cue saying "draw
something here" rather than "pick something".

It now uses **`PickObject(PointOnElement)`** — the normal selection cursor
that highlights whatever is under it. Only the clicked point is taken from
the result (`Reference.GlobalPoint`, already in host coordinates), and the
room is resolved from that point exactly as before, so what the cursor
happens to land on — a floor, a wall face — does not matter.

- If a view does not offer `PointOnElement`, the run **drops back to point
  picking for the rest of that run** and says so, rather than ending.
- `PickObject` needs something under the cursor to click, so a run that
  adds nothing now points at **From List**, which does not depend on
  picking at all.

### Icons on the tabs
- **Automatic** — a room outline in blue with a green space placed inside
  it, matching the tool's ribbon icon.
- **Manual** — a picker crosshair in orange, matching what the tab does.

Both are drawn from `Border` elements rather than set in a symbol font, so
they cannot render as empty boxes on a machine without that font. The tab
label still follows the selected/hover colour changes; the glyphs keep
their own colours.

## 2.5.0

### "No placed rooms found in that scope" — the rooms were in the link
The Automatic tab only ever collected rooms from the **host document**. In
an MEP model the rooms are normally not in the model at all; they are in
the architectural link, which is the whole premise the Manual tab was
built on. So an automatic run on a typical services model found nothing
and said so.

- New **Rooms From** choice on the Automatic tab: **This model + links**
  (the new default), **This model**, or **Links only**.
- Linked rooms are placed through the same path the Manual tab uses — the
  link's transform, the nearest host level, host-space separation lines —
  so the two tabs now produce identical results from the same room.
- The already-has-a-space check works across both. For linked rooms each
  space point is pushed back through the link's inverse transform before
  the plan test, because transforming one point is cheaper than
  transforming a whole boundary.
- With **Current view** and linked rooms, the rooms are narrowed to the
  level the view is associated with — the closest sensible reading of
  "this view" for an element that lives in another document.
- The empty message now names where it looked and what scope it used, and
  suggests including links if the search was host-only.

### Progress bar
A progress band appears under the header while a run is going, with a bar,
a running count and a percentage.

Making that safe drove a change to how the work is committed:

- Placement now runs in **chunks of 25 rooms, each its own transaction**
  inside the transaction group, rather than one transaction for the whole
  batch. One room Revit refuses can no longer roll back every room placed
  before it, and there is a safe point to repaint at.
- **The dispatcher is only ever pumped between chunks, never inside an
  open transaction.** Pumping inside one can leave the write with nothing
  committed. The manual tab's list is small enough to stay in a single
  transaction, so it advances its counter without pumping at all.
- **Pumping also pumps input**, so the window is made hit-test invisible
  for the duration and restored afterwards; a click mid-run can otherwise
  tear a handler away from work in progress.
- The bar only repaints when the whole percent moves.

### Bench
New rule in `import_check.py`: **no dispatcher pump inside an open
transaction**. It tracks every `Transaction` variable through its
`Start` / `Commit` / `RollBack` and fails if a repainting `progress` call
appears while one is open (5 transaction variables tracked). Verified by
moving a `progress.advance` inside a transaction and confirming it was
caught by line number.

## 2.4.0

### Picking selected nothing — the containment test was the problem
2.2.0 switched to picking a point and resolving the room from it, but
tested the point with **`IsPointInRoom`**, which tests the room's **3D
volume**. That volume is bounded by the room's base offset, upper limit
and limit offset, so a click that is plainly inside the room in plan is
rejected whenever any of those is set — and the room's own level
elevation, which the test point was rebuilt at, is *below* the room
whenever the base offset is positive. Every candidate failed, every click
counted as a miss, and nothing reached the list.

Containment is now a **2D plan test** and Z plays no part in it at all:

- The room's boundary loops are tessellated to XY polygons, so an arc wall
  is followed properly rather than treated as a straight chord.
- Point-in-polygon is **even-odd across every loop at once**, which makes
  a room with a hole in it — a core, a shaft — come out right without
  having to work out which loop is the outer one.
- The room's bounding box is still checked first as a cheap rejection, but
  it is not load-bearing.
- **`rooms_without_spaces` was changed the same way**, since it had the
  identical bug: a room with a base offset would have reported "no space"
  and been given a duplicate on the next automatic run.

### A route that does not depend on picking at all
New **From List** button on the Manual tab. It lists every room in every
loaded link — link, level, number and name — with a search box and
multi-select, and adds the chosen rooms exactly as picking would,
perimeters and all.

Picking can be defeated by things that have nothing to do with this tool:
a view template locking visibility, the link's display settings, phasing,
or being in a view type where `PickPoint` is not offered. Reading the
rooms out of the link works regardless, so there is always a route that
does not depend on a click landing.

A click that resolves no room now says so **immediately**, with a running
miss count and a pointer to From List, instead of staying silent until the
run ends.

### Bench
`bench_pick.py` and `bench_spaces.py` are replaced by **`bench_rooms.py`**,
20 checks across all three pieces of room geometry: 2D containment
(square, L-shape notch, donut hole, unreadable boundary), resolving a
click through a link transform at absurd and negative Z, and the
placed/unplaced split.

The stub `Room` **deliberately does not implement `IsPointInRoom`**, so any
regression back to the 3D test fails loudly with an `AttributeError`
rather than quietly passing. Verified by making exactly that change and
confirming the suite exits non-zero.

## 2.3.0

### Automatic placement only fills rooms that have no space
The scan now works out which rooms already have a space and places only
the rest, so running it twice does not double up.

- A room counts as already placed when a **space's location point falls
  inside it**. Spaces are bucketed by level first and the room's bounding
  box is checked before `IsPointInRoom`, because the naive form is every
  room against every space and that is unusable at a few hundred of each.
- **The check is project-wide even when placing into one view.** A room
  already given a space in another view must not be given a second one.
- The test point is rebuilt at the room's own level, for the same reason
  the linked-room pick does it — a space's own Z is not necessarily inside
  the room's volume.
- With *Clear all existing spaces and lines first* ticked, everything in
  scope is about to be deleted, so nothing counts as already placed.
- If every room in scope already has a space, the tool says so and does
  nothing rather than reporting a run of zero.

### A sortable list of what was created
A themed results window opens after an automatic run, listing every space
created with its **Level, Number and Name**. Clicking a column heading
sorts by it; clicking the same heading again reverses it, and the heading
shows `^` or `v`. Level is the default sort, with Level as the tie-break
on the other two.

Rows are built as WPF elements in code rather than bound to Python
objects, and sorting rebuilds the row list rather than going through a
CollectionView — both per the house rules, because binding to IronPython
objects is unreliable across engine versions.

### Workset dropdown
- **Sorted by name**, case-insensitively.
- **The keyword search is now in the dropdown itself.** The separate
  search box above it is gone; the combo is editable, and typing filters
  the list and opens it. `IsTextSearchEnabled` is off because WPF's
  built-in prefix jump fights with the filtering, and the typed text is
  matched back to a workset by name on read, since `SelectedItem` is null
  whenever the user has typed something that is not an exact item.

### Bench
- **`bench_spaces.py` is new**: 10 checks over the placed/unplaced split.
  Verified against two deliberate regressions — ignoring the level buckets
  (caught: a space on the floor above marked the room below as placed) and
  trusting the bounding box without `IsPointInRoom`. **The second one
  initially passed**, because every stub room was a rectangle so the
  bounding box equalled the room and the containment step was never
  exercised. An L-shaped room was added whose notch sits inside its own
  bounding box, and that now catches it.
- `import_check.py` now parses **every** XAML block rather than only the
  first — the results window's names were invisible to it otherwise, which
  it correctly reported as nine unresolved `FindName` calls.

## 2.2.0

### Picked rooms were never reaching the list — fixed by picking points
Everything up to 2.1.0 tried to click the linked room *as an element*,
with `PickObjects(ObjectType.LinkedElement, ...)` behind a selection
filter. **A room inside a link is generally not selectable in Revit no
matter how visible it is made**, so the filter rejected every candidate,
the pick returned nothing, and the list stayed empty. Making the
categories and link display settings visible in 2.1.0 was necessary to
*see* the rooms but could never make them clickable.

Picking is now point-based and loops until Escape:

- **Click inside a room** and the room containing that point is resolved
  from the link's own room list. One click per room, added to the list
  immediately, with a running count in the status bar.
- **Escape finishes**, rather than Enter — there is no multi-select
  operation to complete any more.
- The point is transformed into each link's own coordinates, and the test
  point is rebuilt **at the room's own level** plus a small lift. A point
  picked in a plan view lands on the view's plane, which is normally
  nowhere near inside the room's volume; testing the raw picked Z rejects
  every room. This is the specific thing `bench_pick.py` exists to prove.
- Each link's rooms are collected once and cached, so a second click does
  not re-read the link.
- A click that hits no linked room is counted and reported rather than
  ending the run.
- The now-unused `ISelectionFilter`, `ObjectType` and `RevitLinkInstance`
  imports were removed with the old code path.

Separation lines are still drawn per room as it is clicked, and Remove /
Clear still delete exactly the lines they drew.

### Bench
- **`bench_pick.py` is new**: 7 checks over the point-to-room resolution
  against stub links and rooms — the link transform being applied, a room
  resolving despite an unrelated pick Z, a negative pick Z, a point
  outside every room returning nothing, the owning link being returned,
  and the room cache filling. Verified by putting the old raw-Z behaviour
  back and confirming 4 of the 7 failed with rooms resolving to `None`,
  which is exactly the empty-list symptom.
- `import_check.py` now verifies 22 `core.*` calls; `bench_stitch.py`'s 11
  stitching checks still pass.

## 2.1.0

### Linked rooms are now actually exposed for picking
v2.0.0 turned on Rooms and Room Reference in the host view and that was
not enough, which is why linked rooms still could not be clicked. Three
things were wrong, and all three are fixed:

- **The link's own display settings were never touched.** A link set to
  *By Linked View* or *Custom* ignores the host view's categories
  completely, so turning Rooms on in the host did nothing to it. Every
  loaded link in the view is now temporarily set to **By Host View** for
  the duration of the pick, and put back exactly as it was afterwards.
- **Interior Fill was missing.** With only *Reference* on, a room can only
  be clicked on its crosshair lines, not anywhere inside its area.
  `OST_RoomInteriorFill` is now turned on too.
- **A hidden Revit Links category hides everything in it** regardless of
  the room settings, so `OST_RvtLinks` is included as well.

Only settings that were actually off get changed, and each is restored
individually.

### Separation lines are drawn as rooms are picked
Rather than waiting for Create Spaces, each room's stitched perimeter is
drawn immediately as it is clicked, so the boundary appears in the model
while picking. The list shows a `[n perimeter]` marker against each room
that has lines.

- The element ids of the lines drawn for each room are tracked, so
  **Remove Selected and Clear delete exactly the lines they drew** rather
  than leaving orphaned perimeters behind. That deletion is a model write,
  so it goes out through the same `ExternalEvent` as everything else.
- Create Spaces reuses the lines already on the model instead of drawing a
  second set on top. It only draws if there were none — the case where a
  room was picked in native mode and the boundary setting was changed
  afterwards.
- The boundary choice is snapshotted on the UI thread before the pick
  event is raised; the handler never reads WPF.

### Bench
- New rule: **every `core.*` call in the script resolves to something that
  exists in the core module** (20 checked). Verified by pointing a call at
  a name that does not exist and confirming the check failed. This is the
  cross-module version of the "global name a function reaches for exists"
  rule that has caught deletions elsewhere in the extension.
- All previous rules still pass, and `bench_stitch.py`'s 11 stitching
  checks still pass.

## 2.0.0

Merges the two former tools — **Place Automatic Spaces** and **Space From
Room Manual** — into one tool called **Space Creator**, moved from the
Spaces panel to the **Management** panel.

> **Upgrading:** delete the old
> `RevoBIM PY.tab\Spaces.panel` folder from the installed extension.
> pyRevit names a ribbon item after its folder, so leaving it in place
> gives you the old two buttons alongside the new one.
> Settings keep the same path (`%APPDATA%\RevoBIM\space_creator.txt`) on
> purpose — a missing settings file falls back to defaults silently, so
> renaming it would quietly throw the saved options away.

### Structure
- **Two tabs at the top of one window**: *Automatic* and *Manual*. The
  footer's green action button relabels itself per tab (Place Spaces /
  Create Spaces) and dispatches to the right routine.
- **Options that apply to both** — inherit room name, push to underside of
  floor above, and the workset dropdown with its keyword search — sit in a
  shared block below the tabs rather than being duplicated per tab.
- `TabItem` and `TabControl` carry full control templates. WPF's stock
  tabs ignore `Background` and fall back to the system theme, which would
  render as white tabs on the dark window. Styles are implicit
  (`TargetType` with no key) so nothing has to resolve by resource key.

### Behaviour changes this forced
- **The window is now modeless for both tabs**, because the Manual tab
  picks in the model while the window is open. That means the Automatic
  tab's placement — previously run straight from a modal dialog — now goes
  out through an `ExternalEvent` as well. A modeless window cannot start a
  transaction directly. `__persistentengine__ = True` is set and the
  window is parked in a module-level variable, or the persistent engine
  collects it out from under the user.
- The window is **owned by Revit's main window handle**, so it floats above
  Revit rather than slipping behind it and reading as a crash.
- The window state is snapshotted into an `Options` object on the UI
  thread *before* the event is raised; the handler never reaches back into
  WPF.
- **Push to underside of floor above now works on the Manual tab too.**
  `push_space_to_ceiling_underside_at` takes an explicit host level and
  host point, because a linked room's own `Level` belongs to the link
  document and is not among the levels being searched. The room-based call
  is now a thin wrapper over it.

### Bench checks
`import_check.py` was rewritten and every rule verified by deliberately
breaking it:

- **Banned constructs** (f-strings, bare `.IntegerValue`, `System.Uri`,
  `print`) — the first run reported false positives against its own
  docstrings, so the scanner now skips comments and triple-quoted blocks.
  `.IntegerValue` is exempt only inside `eid_value` / `workset_id_value`,
  and that exemption is confirmed to be genuinely exercised.
- **The embedded XAML parses as XML** — caught a run of hyphens inside an
  XML comment, the exact failure that has blanked a window in this
  extension before.
- **Every `FindName` has a matching `x:Name`** — this rule checked *zero*
  names on its first run, because the script aliases `find =
  window.FindName` and the rule only matched literal `FindName("X")`
  calls. It now follows aliases and checks 18 names. This is the same way
  the rule silently did nothing in Fire Damper Wall Type Push.

`bench_stitch.py` still ships alongside: 11 checks over the separation-line
stitching, all passing.

---

Earlier history of the two tools this replaces is in their own changelogs
(Place Automatic Spaces 1.0.0–1.2.0, Space From Room Manual 1.0.0–1.2.0):
the `XamlReader.Parse` fix for the blank window, the `Room` namespace fix,
the silent-`NewSpace`-failure fix, multi-pick, boundary modes, perimeter
stitching and the temporary room-visibility override.

## Open items for a future version
- Host level match on the Manual tab is nearest-by-elevation only.
- No light palette toggle yet; the window is dark only.
- The window does not resize (no thumb grips) — it is sized to content.
- A view template that locks V/G will block the temporary room visibility
  override; the pick still runs and the status line says so.
