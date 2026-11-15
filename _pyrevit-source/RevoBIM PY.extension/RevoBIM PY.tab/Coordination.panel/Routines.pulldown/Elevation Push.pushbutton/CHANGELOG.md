# Elevation Push - CHANGELOG

## 1.3.0

- **Results moved out of the pyRevit output window into a themed WPF window**,
  the way the rest of the extension reports. Styling the output window was the
  wrong approach twice over: it is white by default, `add_style` is not
  reliably honoured across pyRevit releases, and it leaked the dark styling
  into other tools' output for the rest of the session.
- The window follows the house style: no system title bar, rounded border,
  blue RevoBIM wordmark with the orange tool name, version top right, section
  headings with the 4px coloured tick, matched / updated / skipped stat row,
  and a footer status line coloured green or orange by outcome. Retemplated
  ScrollBar, since a stock one renders a system-themed surface.
- The window is owned by Revit's main window through `HOST_APP.proc_window`,
  so it cannot slip behind Revit and read as a crash.
- `SHOW_RESULTS` added: `always` (default), `auto` (only when something needs
  a look) or `never`.
- If the window will not load for any reason the run still reports, in plain
  text, with the traceback -- a silent run is never acceptable.
- `import_check.py` added, with a `--selftest` that breaks each of its ten
  rules on purpose and confirms it is caught. It found two real faults before
  release: a `System.Diagnostics` import in `script.py` where no assembly had
  been referenced, and a reach for the injected `__revit__` builtin. Both are
  now routed through `HOST_APP`.

## 1.2.1

- Report fixed for dark mode. The cards were dark but the pyRevit output
  window itself is white, so the section headings and notes were light text
  on white and unreadable. `apply_dark_window()` now repaints the window
  (body, links, code blocks, scrollbars) via `output.add_style`, and every
  block also carries its own dark background so the report still reads if
  that style is refused.

## 1.2.0

- Moved into `Coordination.panel\Routines.pulldown`, alongside QFR Remover
  and Fire Damper Wall Type Push, and delivered as a merge-safe
  `RevoBIM PY.extension` tree rather than its own extension.
- Report rethemed to the RevoBIM palette: header carrying the blue wordmark,
  the orange tool name and the version top right, a filters card, a
  matched / updated / skipped stat row, and section headings with the 4px
  coloured tick.
- `eid_value()` helper added; no bare `ElementId.IntegerValue` anywhere, so
  the tool runs unchanged on Revit 2024 through 2027.
- `__version__` at the top of `script.py` is the single place the version is
  set; the report reads it from there.
- Icon redrawn in the RevoBIM blue and orange.

## 1.1.0

- Renamed to **Elevation Push**.
- Filters generalised to a `FILTER_RULES` list, matched on ANY rule and
  deduplicated by element id. Added Duct Fittings, Cable Tray Fittings and
  Pipe Fittings on family name containing QFR, beside the original Duct
  Accessories on Fire.
- Per-rule match counts reported.

## 1.0.0

- Pushes `Elevation from Level` into `BGL_Elevation from Level` for Duct
  Accessories whose family name contains Fire.
- Parameter lookup falls back from the instance to the type.
- Where a parameter is not found, the available parameter names on the first
  offending element are reported so the spelling can be checked.
