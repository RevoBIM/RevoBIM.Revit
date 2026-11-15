# BWIC ID Push - changelog

## 1.2.0
- Icon redrawn to the RevoBIM palette (blue `#4FA3E3` opening, orange
  `#E8912D` tag, `#3E3E42` wall), flat and square, generated at 8x
  supersampling and downscaled to 96x96 PNG.
- **Silent completion.** The pyRevit output window and every `forms.alert`
  are gone. `script.get_output()` is not called at all, so the blank white
  console no longer appears ahead of the picks.
- Feedback for the previous pair is carried in the status-bar prompt of the
  next pick, so nothing interrupts the run.
- Link documents cached in the selection filter. `AllowReference` fires on
  every mouse move, so resolving the link instance and its document on each
  one was the main cost of hovering over a busy view.
- Generic Model category id resolved once at module level rather than per
  hover.
- The target parameter is checked for existence and read-only status
  **before** a transaction is opened, so a skipped element costs nothing.
- Whole session wrapped in a `TransactionGroup`, assimilated into a single
  undo step; rolled back untouched when nothing was written.
- `eid_value()` helper replaces bare `.IntegerValue` for Revit 2024-2027
  compatibility (deprecated 2024, removed 2026).
- `__version__` added at the top of `script.py`.

## 1.1.1
- Reverted to the windowless two-click command.

## 1.0.0
- Initial release.
