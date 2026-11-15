# Containment System Creator - changelog

Version is shown in the top right corner of every window and is defined by
`__version__` at the top of `script.py`. The windows read it from the script,
so bumping `__version__` is the only edit required.

## v1.4.1 - 2026-10-23

Revit's own dark colours, sampled from its project browser.

| Part of the tool | Was | Now | Revit's equivalent |
| --- | --- | --- | --- |
| Window background, trees | `#232326` | `#3C4454` | browser body |
| Header and footer bars | `#1C1C1F` | `#212932` | title bar |
| Text boxes, dropdowns, search | `#1C1C1F` | `#2D3441` | search box |
| Cards | `#2B2B2E` | `#343C4A` | a step darker than the body |
| Edges and borders | `#3E3E42` | `#4E5665` | tree lines |
| Selected tree row | `#2B5473` | `#323C48` | selected row |
| Text | `#E4E4E4` | `#E8F0F8` | text |
| Muted text, arrows | `#9A9A9E` | `#9DA4B2` | icons |
| Hints, disabled text | `#6A6A6E` | `#7B8290` | search hint |
| Buttons, shrink hover | `#3A3A3E` | `#46505F` | toolbar tab |

- The RevoBIM blue, orange and green accents are unchanged, as is the red
  close-button hover.
- The trees now sit on the browser-body colour with Revit's darker selected
  row, as Revit's own project browser does, instead of on the text-box colour.
- The code-built tree text uses the same Revit text and grey.
- `import_check.py` gains `rule_revit_dark_palette`, which fails if a layout
  drifts off these values or any of the old neutral greys come back.

## v1.4.0 - 2026-10-23

Shrink to taskbar, on every window.

- **All four windows** - the main window, Create System, Edit System
  Parameters and the results window - have a **shrink button** in the top
  right, beside close. Pressing it slides the window down to the bottom of its
  screen like a drawer closing, leaving only its header bar floating 8px clear
  of the taskbar, so the model can be seen. The button turns into a **green up
  arrow**; press it, double-click the bar, or press Enter, Esc or F11, and the
  window slides back up to exactly where it was. **Ctrl+Shift+H** does the same
  both ways. Built once, in `csc_drawer.py`, and handed to every window, so the
  gesture is identical everywhere.
- **The bar stays draggable.** Carried somewhere else, the window opens from
  where the bar now sits, kept on that screen, rather than jumping back.
- **Windows go down together.** A dialog shrinking takes the main window down
  with it, so the main window is not left standing over Revit, and parks its
  own bar just above. Bringing the dialog back brings the main window back
  behind it; closing a parked dialog brings the main window back too. Several
  bars stack 4px apart.
- **While parked**, every other key is swallowed so nothing acts on a window
  you cannot see, and Esc reopens rather than closing.
- **The windows are modal.** Shrinking one shows the model, but Revit stays
  locked until the window is closed - that is what modal means, and the drawer
  does not change it.
- How the slide is built: `Top` only is eased by hand, cubic ease out over
  0.28s on a 15ms timer. The window keeps its full height on the way down so
  nothing re-measures mid-slide, and is cut to the bar only once it has landed.
  No Storyboard: an animation holds its end value and outranks every later
  assignment, which leaves a window that can never be moved again. MinHeight,
  SizeToContent and the main window's resize grip are relaxed for the trip and
  put back; the body is pinned for the slide; every part of the window below
  the header is collapsed while parked and restored to exactly what it was; a
  frame that throws lands the window rather than stranding it half way.
- Assembly references moved into `csc_clr.py`, imported first by every module,
  and now include `System.Windows.Forms` and `System.Drawing` for the screen
  lookup.
- Ships `import_check.py` and `bench_logic.py`, each with a `--selftest` that
  proves every rule by breaking it on purpose. The logic bench also re-proves
  the naming rules from v1.0.0-v1.2.0, since this release was rebuilt from the
  change history rather than from the installed files.

## v1.3.1 - 2026-09-01

- Moved from the **MEP** panel to the **Electrical** panel. Containment service
  types are electrical work, and the tool sits with the rest of it now.

  Nothing inside the tool changed. **Delete the old copy** at
  `RevoBIM PY.tab\MEP.panel\Containment System Creator.pushbutton` before
  reloading - pyRevit builds the ribbon from the folder tree, so leaving it
  there puts the same button on both panels.

## v1.3.0 - 2026-08-10

Runs on Revit 2024, 2025, 2026 and 2027 from one copy of the script.

- **`from System import Uri` fails on 2025+.** `System.Uri` moved assemblies
  under .NET 8, and the import threw at module load. The icon is now loaded
  from a byte stream instead of a `Uri`, and icon loading is fully guarded.
- **`ElementId.IntegerValue` was removed in 2026.** All id handling now goes
  through an `eid_value()` helper that prefers `.Value` and falls back to
  `.IntegerValue`.
- Assembly references are requested defensively and individually.
- Renaming confirms by reading the name back.
- Written to run unchanged on IronPython 2.7 and IronPython 3.

## v1.2.0 - 2026-08-10

Editing existing systems, not just creating new ones.

- Clicking any system type - or any of its fittings - in either tree lights up
  an **Edit System Parameters** button in the footer.
- The edit dialog changes the type name, BGL_Function and BGL_Type Mark across
  the system type and every fitting type in its routing preferences.
- Only the service part of the type name is editable, with a preview of the
  resulting full name and every fitting rename.
- **BGL_Type Mark** is the type mark parameter throughout, falling back to
  Revit's built-in Type Mark, with any fallback reported.
- One transaction per edit.

## v1.1.0 - 2026-08-10

- Cable tray kinds are **Cable Tray**, **Cable Ladder**, **Cable Trunking** and
  **Cable Basket**, resolved from the type name, then the system family name,
  then the fitting family names (`_TrunkingTray`, `_Cable Basket`).
- Whole-token matching, longest alias first; the generic Revit family name is
  ignored when resolving the kind.
- **Full new type name** box with an **Auto** button.
- "With fittings" decided by whether a type actually has fitting types.

## v1.0.0 - 2026-08-10

First release: tray and conduit trees, Create System dialog with preview,
dynamic fitting-slot discovery, one transaction per creation.
