# Fire Damper Wall Type Push - changelog

Version lives in `__version__` at the top of `fdwt_core.py`. Both windows read
it from there, so bumping that one line is the only edit needed.

## 1.2.0 - 2026-08-24

- **A progress bar along the top of the window** while Find runs: a blue fill
  under the header, the percentage in the header beside the version, and the
  running count in the status line. It repaints only when the whole percent
  moves — pumping the dispatcher on every one of several thousand accessories
  costs more than the work being measured.
- **Floors are hosts too.** *Intersect with* — **Walls** and **Floors**,
  ticked how you like and remembered — decides what the search looks at, and a
  floor hands over exactly the same two values: its type name and its fire
  rating. A damper that passes through both a wall and a floor still goes to
  whichever it overlaps most, and the row says two hosts were hit.
- The table gains a **Host** column (Walls / Floors) with its own search box,
  "Wall type" becomes **Host type**, and the CSV export carries both.
- Unticking both categories is not allowed to leave the tool with nothing to
  look at — Walls comes straight back on.

## 1.1.0 - 2026-08-24

Apply found the elements and the values but wrote nothing. Four things could
each have caused that on their own, and all four are fixed:

- **The confirm dialog swallowed its own failure.** Anything that threw while
  opening the "about to write" window returned a silent *no*, which reads
  exactly like Apply doing nothing. It now falls back to Revit's own Yes/No
  dialog, and setting the child window's `Owner` — the likeliest thing to have
  thrown — is gone.
- **The dispatcher was being pumped inside the open transaction.** Letting
  Revit's message loop run between `Start` and `Commit` to repaint a progress
  line can leave the write with nothing committed. No pumping between those
  two lines now.
- **Workshared models.** On a cloud workshared model a write to an element
  that has not been borrowed writes nothing and says nothing — Revit asks in a
  dialog, and a run suppressing dialogs answers it. The elements are now
  borrowed with `WorksharingUtils.CheckoutElements` before the transaction
  starts, and anything another user holds is reported by name rather than
  silently skipped.
- **Nothing proved the value landed.** Revit does not reliably raise when a
  write does not take. Every value is now read back off the element through a
  fresh lookup, every route to the parameter is tried (`GetParameters` and
  `LookupParameter` do not always hand back the same object, and a family can
  carry two parameters of the same name), and a value that will not stick
  turns the row red saying what it read back instead.

Also in this version:

- `Transaction.Commit()`'s status is checked, and a commit that did not happen
  is reported rather than assumed.
- Every run writes to `%APPDATA%\RevoBIM\fire_damper_wall_type_push.log`: what
  was written, what failed and why, and **which Revit dialogs were suppressed**
  — a run that writes nothing because Revit quietly asked a question is
  otherwise unexplainable.
- **The window resizes.** `WindowStyle="None"` plus `AllowsTransparency` means
  the window gets no hit testing on its frame, so there was nothing to drag:
  eight invisible thumbs now sit on the edges and corners and are the frame. A
  full screen button beside the close button fills the working area, and
  double-clicking the header does the same.
- **A splitter between the family list and the preview**, so the list can be
  pulled wider or squeezed away.
- **Keyword search on all four parameter dropdowns**, isolating the parameters
  that hold every word typed. The old search only covered the two target
  dropdowns and never fired at all: it compared the sender with `is`, which
  compares Python object identity on a .NET object. A search that matches
  nothing says so and leaves the full list rather than emptying the dropdown.

## 1.0.0 - 2026-08-24

First release.

- Finds every duct accessory in the project (or the active view) that
  intersects a wall, using real solid geometry rather than bounding boxes.
- Dropdown of the loaded Revit links to run the intersection from, with
  `<Current model>` as the first entry.
- Pushes two values from the intersecting wall onto the accessory:
  - **1st** the wall type, from `Family type name` by default - the source
    parameter is a dropdown, and the target parameter on the accessory is
    chosen in the window.
  - **2nd** the wall fire rating, from `POP_PERF_FireRatingTarget` by default,
    into `BGL_Wall Fire Rating` by default. Both ends are dropdowns.
- Tickable list of the duct accessory families present, with a keyword search,
  so the run can be narrowed to the fire damper families.
- Preview table with a search box per column: orange where a value will
  change, green where it is already correct, red where it needs a look.
  Nothing is written until Apply, and Apply lists what it is about to do.
- Where an accessory sits in more than one wall the deepest overlap wins, and
  the row says how many walls were hit.
- Export list writes every row found to CSV, including rows past the 3000 the
  table draws.
- Dark and light palettes, switched from the chip in the header and
  remembered, with settings in `%APPDATA%\RevoBIM\fire_damper_wall_type_push.txt`.
- One transaction for the whole run, warnings swallowed, Revit's own dialogs
  suppressed for the duration.
- Loads in stages and names the stage that failed, in a Revit dialog and in
  `%APPDATA%\RevoBIM\fire_damper_wall_type_push.log`.
- Revit 2024 - 2027 from one copy: assemblies referenced before any namespace
  is touched, no `System.Uri`, no `ElementId.IntegerValue`, no f-strings.
