# RevoBIM Tag Tidy - changelog

## 1.1.0

- **Hook for other tools.** New `tidy_hook.py`: another RevoBIM tool can run
  Tag Tidy on tags it has just placed, with no window and no pick, inside its
  own run and its own undo step. `tidy_hook.tidy_tags(doc, tag_ids,
  overrides)` returns a summary, counts and the same rows the preview shows,
  and never raises. `HOOK_VERSION = 1`. Tag All 1.10.0 is the first caller.
  - The saved Tag Tidy settings are used (side, leader angle, gap, reach,
    obstacles, search time). A caller may override a short list
    (`OVERRIDABLE`); the preview is always off and "Where I click" is treated
    as "Whichever side is clearer", since nobody is there to click.
  - The debug report notes the run came from another tool.
- `tidy_ops.build_jobs` now builds each view's job for both the command and
  the hook, so the two cannot drift apart.
- Bench: import_check 22 rules (new: the hook runs headless inside its
  caller's run - no TransactionGroup, window or pick in `tidy_headless`, and
  the preview forced off), selftest 22 of 22.

## 1.0.0

First RevoBIM PY release, built from **Sam BIM Tag Stack 1.1.0**. The layout
engine is unchanged: same columns, same 45 degree leaders, same clash search,
same 30mm reach rule, and the same 128 engine checks pass on the bench.

What changed to make it a RevoBIM PY tool:

- **Ribbon**: a **Tag Tidy** pulldown on the **Annotation** panel of the
  **RevoBIM PY** tab, holding **RevoBIM Tag Tidy** (the command) and
  **RevoBIM Tag Tidy Settings**. Both names are unique and prefixed RevoBIM so
  they can be found in Revit's Keyboard Shortcuts list. The shared modules live
  in the pulldown folder; no bundle.yaml on the panel or the pulldown, so the
  existing Annotation panel configuration is not touched.
- **Theme**: dark is now Revit's own dark theme (`#222933` bars, `#3C4454`
  body, `#2D3441` fields, `#3A7392` selection) with muted text and blue lifted
  so they read on it. A theme chip top right of every window shows **Auto**,
  **Dark** or **Light**; Auto (the default) follows Revit's canvas through
  `UIThemeManager` on Revit 2024 and later, dark before that. A click goes
  Dark, Light, then back to Auto, and is remembered.
- **Shrink to taskbar** on both windows, top right beside full screen and
  close: the window slides down to the bottom of its screen like a drawer,
  leaving only its header floating, and the button turns into a green up arrow
  to bring it back. Ctrl+Shift+H does the same; while parked, Escape, Enter,
  F11 and a double click on the bar open it again. On the preview this is how
  to see the layout in the model before pressing Keep.
- The settings window can now be resized and filled to the screen like the
  preview.
- **Debug report**: every run writes `%APPDATA%\RevoBIM\tag_tidy_debug.txt`
  (summary, each view's tag and obstacle counts, every row, the settings). On
  by default; a tick in the settings turns it off.
- Settings in `%APPDATA%\RevoBIM\tag_tidy.txt`, errors in
  `%APPDATA%\RevoBIM\tag_tidy_last_error.txt`. Undo steps are named
  "RevoBIM Tag Tidy".
- `tidy_clr.py` references `mscorlib`, `System` and
  `System.Diagnostics.Process` by name as well, and no longer references
  RevitAPI / RevitAPIUI (pyRevit supplies them).
- Bench: `import_check.py` keeps the 14 Tag Stack rules and adds 7 RevoBIM
  rules (assemblies referenced, a drawer on every window, the shrink button
  wired, animations released, changelog version, Revit dark palette and
  contrast, ribbon names), each proved by `--selftest`. `bench_logic.py` (was
  `bench_stack.py`) adds theme resolution, the drawer's parking arithmetic
  (including a monitor above the primary) and the drawer driven through a fake
  timer, and has its own `--selftest`.
