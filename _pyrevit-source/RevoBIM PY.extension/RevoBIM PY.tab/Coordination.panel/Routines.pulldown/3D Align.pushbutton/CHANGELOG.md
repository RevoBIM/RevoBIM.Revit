# 3D Align - changelog

## 1.0.0
- First release, in Coordination > Routines.
- Vertical then vertical: the second is centred on the first in X and Y.
- Vertical then horizontal: the horizontal's centreline is moved square to its
  own run until it passes through the vertical's centre at the run's height.
- Horizontal then vertical: the vertical is moved square to the run onto its
  centreline. After a horizontal, only uprights can be picked.
- 46 degrees divides vertical from horizontal, as in Drainage Elevation Match.
- Pre-selected element used as the first pick. Keeps going until Escape.
- Every move is plan only and read back afterwards; a move that does not land
  is reported, not assumed.
- Revit refusing to move an element with its connections: release them and
  move (default, reported) or leave it (reported).
- Pinned elements unpinned and re-pinned; grouped elements refused; borrowed
  before writing on workshared models, with the holder named.
- Largest-move guard, 3000mm by default.
- Results window only when something needs a look; dark and light, following
  Revit's canvas by default, with the theme chip top right.
- Shift+Click opens the settings.
- import_check.py and bench_logic.py, every rule proved with --selftest.
