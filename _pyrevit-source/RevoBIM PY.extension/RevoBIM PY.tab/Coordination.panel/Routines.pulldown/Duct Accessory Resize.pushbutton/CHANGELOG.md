# Duct Accessory Resize - changelog

## 1.3.0

- **The dark palette is Revit's own slate**, not a near-black: `#3B4453`
  body, `#333B49` cards, `#2C3440` fields, `#222933` bars, `#414B5A` hover,
  `#515C6B` edges, `#F5F5F5` text, `#9DA5B0` muted, `#2D5B80` selection,
  with the row washes re-tinted onto the lighter card. Sampled from Revit
  2024 and shared with the rest of the RevoBIM suite. The light palette is
  unchanged.
- **Shrink to taskbar**, top right beside full screen and close. The window
  slides down like a drawer closing, leaving only its header bar floating
  clear of the taskbar so Revit can be worked in; the control becomes a
  green up arrow that opens it again. `Ctrl+Shift+H` does the same.
  - Parked, Escape, Enter and F11 open it again rather than answering a
    prompt nobody can see, and a double click on the bar reopens rather
    than maximising.
  - The bar stays draggable, and one carried somewhere else opens upward
    from where it now sits.
  - The shrink button stays live while a resize runs - it is the one
    control that should work at the moment somebody wants to watch Revit.
  - Closing while parked settles the window first.
- New bench rules: every layout's shrink button is wired and never disabled
  with the rest, the slide is eased by hand rather than animated, MinHeight
  is put back, the body is unpinned and the grips unparked on every way
  out, and the tick handler carries its own fallback. No layout may paint a
  literal colour.

## 1.2.0

- **Air terminals resize too.** They are picked and selected alongside ducts
  and duct accessories, and resized in the same run.
- Air terminals get their own Width / Height / Diameter parameter dropdowns,
  separate from the duct accessory ones, because a diffuser rarely names its
  sizes the way a damper does. Defaults look for the neck names first
  (`Neck Width`, `Neck Diameter`), then the duct ones.
- "Resize the air terminals" tick beside the duct accessory one; each family
  kind has its own same-parameter-twice warning.
- Air terminals are detached and reconnected round the resize exactly as
  accessories are, so a diffuser on the end of a run does not refuse the
  ducts with "connected in a network".
- The parameter panel scrolls, now there are two sets of parameters.

## 1.1.0

Fixes from the first live run (Revit 2024, workshared), where nothing resized.

- **The parameter search box no longer changes the parameter.** In 1.0.0 a
  search that filtered out the current parameter selected the first match,
  so the setting changed on every keystroke. That is how Height ended up on
  `BGL_Duct Width`, and 625 then 450 were written into one parameter. Search
  now only filters; the chosen parameter stays at the top of the list and
  only changes when a name is picked.
- **The same parameter on two dimensions is refused.** It shows in red under
  the parameters, the accessory rows go red, and Resize stays off.
- **In-line accessories are detached round the resize.** Resizing a duct that
  is connected to a damper made Revit push the size through the connector
  into the damper, and it was refused with "connected in a network and can
  no longer keep the connectivity". Every connection between the elements
  being resized and a duct accessory is now disconnected, the sizes written,
  the model regenerated, and each connection put back by position and
  proved. A connection that will not go back rolls that batch back rather
  than leaving the system broken.
- Debug now lists each element's parameters and what it is connected to, and
  repeated Revit messages are logged once.

## 1.0.0

First release, in Coordination > Routines.

- Rectangular or circular, chosen in the window and remembered.
- Width / height or diameter parameters of the duct accessory family picked
  from dropdowns (with keyword search) listing every length parameter the
  model's duct accessories carry, instance or type.
- Modeless: Select Elements for Change picks ducts and duct accessories while
  Revit stays usable; Use Revit selection takes what is already selected.
- The current size of the selection is summarised and listed row by row;
  typing a new size previews every change (orange will change, green already
  that size, red cannot be done and why).
- Resize writes ducts and accessories together in one undo step, halving the
  batch where Revit refuses so only the element at fault is lost, and reads
  every size back after the job to prove it landed.
- Type-sized accessories switch to a type of the new size, duplicating one
  when none exists (or edit the type, as a setting).
- Debug tick bottom left, Copy debug puts the log on the clipboard.
- Dark / light / Auto theme chip top right; Auto follows Revit's canvas.
- Easter egg on three slow clicks of the RevoBIM logo.
