# Explode Import Symbol Multiple - changelog

## 1.0.0 - 2026-10-19

- First release. Coordination panel > Routines pulldown.
- Select any number of import symbols, run, pick **Partial Explode** or
  **Full Explode** (P / F keys, Esc to cancel); every selected import is
  exploded in turn.
- Linked CAD is skipped (Revit cannot explode it) and anything that is not an
  import symbol is left alone; the prompt says how many of each.
- Pinned imports are unpinned to explode; any that do not explode are pinned
  again.
- Drives Revit's own ribbon command one import at a time from the Idling
  event (Revit has no explode API and greys Explode out for more than one
  import). AdWindows command handler first, UI Automation as the fallback.
  An import only counts as exploded once it has gone from the model.
- Results selected when done (optional), with anything not exploded left in
  the selection. A themed report appears only when something failed.
- Revit dialogs during the run answered automatically and listed in the report.
- Dark / light theme following Revit's canvas by default, Auto / Dark / Light
  chip in the header, version top right.
- Debug log on by default: `%APPDATA%\RevoBIM\explode_import_multiple_debug.txt`.
