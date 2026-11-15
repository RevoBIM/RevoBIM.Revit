# Level Manager - changelog

## 1.2.0 - 2026-10-23

- **Shrink to taskbar** on every window the tool opens: the main window,
  Assign Level, Delete Level, Parameter Columns, Results and the
  are-you-sure prompt. The button sits top right, before full screen and
  close. Pressing it (or Ctrl+Shift+H) slides the window down to the bottom
  of its screen like a drawer closing - Top eased over 0.28s with the height
  held, then cut to the bar on landing - leaving only the header bar floating
  8px above the taskbar. The
  button turns into a green up arrow; that, a double-click on the bar, Esc,
  Enter or F11 opens it again. The bar can be dragged, and opens upward from
  wherever it was left, kept on that screen.
- Bars stack 4px apart instead of landing on each other. A dialog takes the
  main window down with it, and the main window takes an open Results window
  with it; opening or closing either brings the other back.
- While parked: resize grips are parked too, full screen and resizing are
  refused, the progress bar and parameter-column row cannot appear inside the
  bar, and closing saves the real window size, not the bar's.
- A dialog that opens while the main window is parked opens the main window
  first, so it does not centre itself on a bar at the bottom of the screen.
- The prompt sizes itself to its text; its real laid-out height is what is
  saved and restored, never the NaN WPF reports for Height.
- Results is now modeless: Revit stays usable while it is open, and Select in
  Revit works without closing it.
- Modal dialogs (Assign Level, Delete Level, Parameter Columns, the prompt)
  still hold Revit while they are open: shrinking one shows the model, but
  Revit can only be used again once the dialog is answered.
- The prompt gains a close button and the shared chrome.

## 1.1.1 - 2026-10-16

- Pacman only opens on three slow clicks (each 250ms to 2s apart) of the
  RevoBIM logo, top left. The shared egg_hook.attach is no longer called -
  it armed the whole window, so clicks elsewhere counted. A click anywhere
  else in the window, or a gap outside the window, starts the count again.

## 1.1.0 - 2026-10-16

- **Delete Level** (footer, red): highlight one level row and press it. Revit
  is asked first what goes with the level (doc.Delete in a transaction that is
  rolled back), and a dialog shows it: the level to move every element to,
  how many elements move, which elements cannot change level and would be
  deleted with it, the views deleted, sheets deleted (always 0 - Revit does
  not delete sheets with a level) and the sheets that lose a view. A second
  "are you sure" prompt repeats the counts. The move and the delete run in one
  TransactionGroup: if any element refuses to move, or Revit would still take
  a moved element with the level, nothing changes. Blocked while the active
  view is one of the views the level takes with it.
- **Isolate in 3D in Revit** (footer): opens the default 3D view ({3D - user}
  then {3D}; made if missing), fits the section box round the chosen elements
  with a 300mm margin, and temporarily isolates the elements together with the
  levels and the section box. Reset is its own committed transaction before
  the isolate, the section box element is kept in the isolate list, and the
  Levels category is switched on in that view if it was hidden.
- Footer laid out in two rows: actions above, Debug and the status line below.

## 1.0.0 - 2026-10-16

First release. Management panel, single pushbutton, modeless.

- Table of every level in elevation order, collapsible to categories and then
  to elements (indented), with Count, Element ID, Family, Type, Workset,
  Elevation and Above level columns.
- Add any project parameter as a column (instance, falling back to type);
  removable chips, remembered between runs.
- Every column: keyword filter box and an Excel style value list; a global
  search; click a heading to sort, Shift+click for further levels.
- Tick a level, a category or an element; ticking a highlighted row ticks
  every highlighted row. Click, Shift+click and Ctrl+click highlight.
- Assign Level lights up when anything is chosen and opens a dialog listing
  the levels by elevation with a preview of what will change.
- Assigning keeps every element still: change the level, regenerate, measure;
  put the offset back by the measured shift; move back if still out; roll the
  batch back if anything (or anything joined to it) is still out. A final
  measurement of the whole run rolls everything back if one element moved.
- Elements in groups, with read-only levels, owned by others or refused by
  Revit are named in a results window.
- Opens on whatever is selected in Revit (ticked, levels opened); From Revit
  selection does the same later; Select in Revit and double-click go back.
- Theme chip top right (Auto follows the Revit canvas, Dark, Light), version
  top right, full screen, resize grips, Debug tick bottom left (off by
  default) with Copy debug.
- Revit 2024 - 2027 from one copy.
