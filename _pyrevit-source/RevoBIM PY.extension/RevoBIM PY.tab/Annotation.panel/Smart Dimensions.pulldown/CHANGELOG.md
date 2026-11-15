# Smart Dimensions — changelog

Version numbering is short semantic, shown in the top right corner of every
window. `__version__` lives at the top of `smart_dimensions_core.py`; both
buttons read it from there rather than hardcoding it in XAML, so bumping that
one line is the only edit needed.

## 1.4.0 — the stack is set out from the services, in model millimetres

The displaced text now follows an explicit set of positioning rules.

- **The datum is the outermost edge of the selected services on the side the
  text is going**, measured square to the dimension string — not the dimension
  line, and not anything that varies per segment.
- **The first displaced value sits 200mm beyond that edge**; every one after
  it a further **50mm** out. Three values land at +200, +250, +300, exactly as
  specified.
- **Every position comes off that one datum.** A leader never lengthens with
  the value it carries or with the spacing of the pipes it sits between.
- **Model millimetres, not paper.** 200 and 50 are real distances and come out
  the same at 1:50, 1:100 and everything else. The three boxes in Settings are
  relabelled **model mm** and a **Set out from** choice is added — the
  outermost service edge (default) or the dimension line.
- Because the whole stack starts beyond the outermost service edge, **text and
  leaders cannot land on a pipe, duct, tray or conduit**. It is one straight
  column at a single position along the string, never alternating sides, and
  the same logic applies whichever way the string runs — the offset is always
  square to it in the active view.
- The outermost edge is read from the solids' own edge endpoints, which is
  exact: the extreme along any horizontal direction sits on a flat end face
  and every point of that face's edges is captured. Where there are no solids
  — a Coarse view, a line-only symbol — the location curve ends and the
  bounding box stand in, and a box can only over-state the extent, so the
  failure direction pushes text further clear rather than closer.
- The segments stay **native Revit dimension segments**, moved by their own
  `TextPosition` with `HasLeader` on, so the leaders terminate exactly as they
  would if the text had been dragged by hand.
- **Settings written by an earlier version are migrated** — the three distance
  keys changed meaning from paper to model millimetres, and a saved 6 would
  otherwise have been read as 6mm rather than 200mm.

## 1.3.1 — stack spacing tightened to 150mm at 1:50

- The gap between stacked numbers was **9 paper mm**, a value chosen when they
  sat beside each other and needed room for a whole number between them. In a
  stack it is line spacing, and 9mm came out as **450mm at 1:50** — far too
  airy. It is now **3 paper mm: 150mm at 1:50**, 300mm at 1:100, 60mm at 1:20,
  scaling with the view so it reads the same on every sheet.
- **A settings file written by an earlier version is migrated**, so the old
  9mm does not survive the update. A value changed since is left alone —
  migration only fires when the file's `settings_version` is behind.
- **Fixed: the stack was blocking itself.** Numbers this run places were being
  added to the "keep clear of" list, which is checked at the clearance radius
  (6 paper mm) — wider than the new 3mm spacing, so every second slot would
  have been skipped and the spacing silently doubled. Only text already in the
  view is an obstacle now; what the run places is on the slot grid by
  construction and cannot collide with itself. The wider radius still does its
  real job: a neighbouring annotation pushes the whole column genuinely clear
  rather than interleaving with it.
- The Settings window now shows what the paper millimetres come out as **in
  the model**, for the active view's scale plus 1:50 and 1:100, updating as
  the boxes are typed in.

## 1.3.0 — leadered numbers stacked, not spread

- **Pulled-out numbers now stack one above the other** in a single column at
  the outer edge of the first element, each a gap further out from the
  dimension line than the last, instead of running along the string beside
  each other. The annotation no longer spreads sideways and pulls the whole
  thing off centre from where the line was clicked.
- A slot already taken is stepped over **further out** rather than further
  along, so the column stays a column.
- Nearest-the-string-first ordering still holds, so the leaders fan out from
  the column without crossing.
- **In a row beside each other** is kept as a setting for anyone who wants the
  1.1 behaviour back.
- The dimension line itself is unchanged and was never moved by any of this:
  the click sets its offset from the services and nothing else, and along its
  own direction it is built from the outermost references with the same
  overrun each end, so it stays centred on what it is dimensioning.

## 1.2.0 — no Finish mid-run, and generic models

- **The linked wall / column pick is now a single click.** `PickObject` returns
  on the click itself, so there is no Finish or Enter in the middle of a run.
  With the services pre-selected the whole tool is now: keys, click the wall,
  click where the line goes. **Several, Enter to finish** is still there as a
  setting for when a string needs more than one.
- **Generic Models added to the categories**, handled like ducts: flat-sided
  ones get **both edges**, curved ones fall to the family's own **centre
  reference plane**, which stands in for a centreline a generic model does not
  have. `Center (Left/Right)` or `Center (Front/Back)` is chosen from the
  instance transform, whichever is square-on to the string. Overridable to
  centre-only or edges-only in Settings.
- Generic models are **not** direction-checked against the rest of the
  selection — they are usually placed as a point rather than a run, so there is
  no location curve to test and they are taken as picked.
- The run direction is decided by elements that actually have a location curve;
  a selection of nothing but point-placed families falls back to their instance
  axes rather than refusing.

## 1.1.0 — small dimensions leadered out

- A segment measuring **under the threshold for the view's scale** has its text
  **leadered out of the string**: moved to a row that starts at the outer edge
  of the first element and runs on across, evenly spaced, with `HasLeader`
  turned on so Revit draws the leader back to the segment.
- **Threshold is a table of view scale → mm**, seeded with **1:50 = 200mm** and
  **1:100 = 250mm**. Any scale not in the table falls back to
  **base + the scale**, base 150mm — which reproduces the table's own numbers
  (150 + 50 = 200, 150 + 100 = 250) rather than inventing a different rule, and
  gives 170mm at 1:20 and 350mm at 1:200.
- The row is laid out on a slot grid measured in **paper millimetres** and
  scaled to the view, so it looks the same at every scale: 6mm out beyond the
  dimension line, 9mm between texts, 6mm clear of anything else. A slot already
  taken — by text this run has placed, or by **leadered text already in the
  view** — is stepped over rather than landed on.
- Texts are assigned nearest-the-string-first so the leaders fan out without
  crossing each other.
- The row can start from the **last** element instead of the first.
- All of it is in the Settings window, which is now two columns so it still
  fits without scrolling.
- A segment Revit will not let move is reported with the threshold that caught
  it, rather than skipped quietly.

## 1.0.0 — first release

- **RevoBIM PY tab, new Annotation panel**, `Smart Dimensions` pulldown holding
  **RevoBIM Smart Dimensions** (the command) and **RevoBIM Smart Dimension
  Settings**.
- One continuous dimension string across a bank of services, in plan views.
- Works from a pre-selection, or picks the services itself when nothing is
  selected.
- Categories and what each is dimensioned to, out of the box:
  pipes, conduits and round/oval ducts → **centreline**; cable trays and
  rectangular ducts → **both outer edges**. All five are settings.
- After the services, an optional pick of **linked walls and columns**, added
  to the same string at the face **nearest the service beside them**. Enter
  completes, Escape skips.
- One click sets where the dimension line sits; the string is spanned to the
  outermost references with a settable overrun each end.
- The command **opens no window**, so Revit's Keyboard Shortcuts dialog can
  bind keys to it. The ribbon name is deliberately unique — plain names clash
  with other addins and cannot be found in that list.
- Revit's own warning dialogs are swallowed for the duration of the run, and
  everything is placed in a single transaction so a failure rolls back clean.
- Results are reported in a themed RevoBIM window, by default only when
  something needs a look.
- `import_check.py` ships alongside: run it with any CPython to load the
  modules against a stub Revit API and catch a mis-namespaced import on the
  bench rather than as a blank white pyRevit window in Revit.
