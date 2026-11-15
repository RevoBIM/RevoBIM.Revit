# Circuit Manager - changelog

## 1.0.1 - 2026-11-02

- Path Offset (and every editable parameter column) can now be typed into:
  click a cell and type, or F2, or double-click. 1.0.0 bound those columns
  OneWay, and WPF's DataGrid quietly forces a OneWay column to read only.
  They now bind TwoWay with an Explicit trigger, so the typed text is
  validated and staged (green) rather than written straight into the table.
- The in-cell editor is themed (blue edge, palette colours) instead of a
  white system text box in dark mode.
- New bench rule `editable_columns` so a OneWay binding cannot come back.

## 1.0.0 - 2026-11-02

First release. RevoBIM PY tab, Electrical panel, single pushbutton.

- Modeless table of every electrical circuit in the project: Panel, Circuit
  Number, Load Name, System Type, Path Mode, Path Offset (mm), Length (mm),
  Elements.
- Every column heading has a keyword filter box and an Excel-style tick list
  (Select all / Untick all, search, count). A column's list offers what the
  other filters allow; a filtered column's caret turns orange. Reset filters
  in the toolbar.
- Add parameter column: tick any parameter electrical circuits carry; the
  chosen columns are remembered. Right-click a heading to sort, clear its
  filter or remove the column. Writable parameters are editable too.
- Path Mode: select circuits with Ctrl / Shift (cells, or rows from the row
  header), click the Path Mode of any selected circuit and pick Farthest
  Device / All Devices / Custom from the dropdown - staged on all of them.
  Custom is only offered to circuits that have a custom path stored, as
  Revit refuses it otherwise.
- Path Offset: type into a cell, or Ctrl+C / Ctrl+V like Excel - one copied
  value fills every selected cell, a block pastes from the top-left. Accepts
  2750, 2,750.0, 2750mm, 2.75m.
- Staged cells green, copied cells amber until pasted or Esc, cells Revit
  refused red with the reason listed. Nothing is written until Apply, which
  lists what it is about to do. Ctrl+Z undoes a whole paste or dropdown
  change. Ctrl+S applies, F5 re-sorts and re-filters.
- Writes go through an ExternalEvent in one transaction with a
  sub-transaction per circuit; workshared circuits are borrowed first and
  anything owned by someone else is reported with the owner; every value is
  read back after commit.
- House chrome: dark (Revit's own dark) and light palettes, Auto follows
  Revit's canvas theme, chip top right; version top right; shrink to taskbar
  drawer with green up arrow on every window (main, parameter picker, prompts);
  full screen; resizable; Revit 2024-2027.
