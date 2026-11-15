# Space Name To Element - changelog

## 2.0.2

**The category list can be scrolled with the wheel.** The `TreeView` was nested
inside a `ScrollViewer`, so it grew to its full content height and its own
scroll viewer had nothing left to scroll - while still marking the wheel event
handled, so the outer one never saw it either. The tree now scrolls itself. A
bench rule fails on any self-scrolling control nested in a `ScrollViewer`,
proved by putting the bug back.

**The window no longer goes white when a run starts.** The external event was
raised the instant the confirm dialog closed, so the UI thread went to work
before WPF could repaint the area the dialog had covered, and that patch stayed
white until the first progress update. The progress band now goes up and the
window is repainted first, and the run is raised on the dispatcher afterwards.
On top of that the repaint is throttled by time as well as by percentage - a
few hundred spaces means whole seconds can pass inside one percent, and a
window that has not painted for a second goes white - and hit testing is set
once when the run starts rather than on every repaint.

## 2.0.1

**The dark theme was not being applied at all.** `Theme.xaml` named a
`RotateTransform` and retargeted it from a trigger to spin the tree's expander
arrow. WPF cannot retarget a Freezable, so the whole dictionary failed to load,
the merge was caught by a `try/except: pass`, and every control fell back to its
Windows default - which reads as an inverted dark mode rather than as a failure.
Three consequences, all one bug:

- controls, scroll bars and buttons rendered light
- the parameter box could not be typed into, because `IsEditable` was set in the
  style that never loaded
- the header buttons lost their sizing

Fixed by swapping the arrow for two `Path` elements toggled by `Visibility`. The
merge is **no longer wrapped in try/except** - a theme that will not load now
fails loudly. `IsEditable` is set on the ComboBox itself as well as in the style.
Two bench rules added, both proved by breaking them: a `Setter.TargetName` may
not name a Freezable, and every `Setter.TargetName` must exist in its own file.

Also removed: `xmlns:sys` pointing at `mscorlib`, a facade assembly on .NET 8,
and `Value="Auto"` on the scroll bar's `Width`. Each orientation now sets its own
thickness.

**Search** now filters on **category, family and type** names, and opens each
branch only as far as the level that matched - a category-name hit leaves the
category closed, a type-name hit opens the category and the family. All / None
follow the same rule.

**Header buttons** are one size (30x30), vertically centred as a pair, and both
red: the full screen glyph is drawn from `Border` elements, and both fill red
with a white glyph on hover.

**Ticking after a run works again.** The results window was opened with
`ShowDialog` from inside the external event's `Execute`, running a nested message
loop inside Revit's API context and leaving the window unable to take a click. It
is now queued onto the dispatcher and shown once `Execute` has returned. On top
of that, finishing a run explicitly restores `IsHitTestVisible`, re-enables the
tree and re-reads the tick states, rather than relying on the pump to do it.

The confirm step falls back to Revit's own dialog if the themed one throws - a
silent "no" is indistinguishable from a broken button.

## 2.0.0

Rebuilt to the house module format.

**Moved**

- Now a pushbutton inside the **Routines** pulldown on the **Coordination**
  panel, rather than its own button on the Data panel. Delete the old
  `Data.panel\Space Name To Element.pushbutton` folder, or the button appears
  twice.
- Every module the tool uses sits **inside the pushbutton folder**, because the
  Routines pulldown is shared with QFR Remover and Fire Damper Wall Type Push.
  The button adds its own folder to `sys.path`. `lib\revobim` is untouched.

**The window**

- **Modeless** - Revit stays fully navigable and editable while it is open, and
  the window is owned to Revit's main window so it floats above rather than
  slipping behind. Every write goes out through an `ExternalEvent`.
- The category list is now a **tree**: category, then family, then type, each
  with its own tick box. A category shows a partial tick when only some of its
  types are picked. Ticking a category or family sets everything below it.
  Children are built on first expand, so a large model still opens quickly.
- The search box searches **category, family and type names**, and opens the
  branches it matched. All / None act on whatever the search is showing.
- **Progress runs in the window**, with a percentage and a label saying which
  phase is running, instead of Revit's own progress bar at the top of the
  screen. Cancel stops after the current chunk and keeps what was written.
- **Refresh** (or F5) re-reads the model and keeps the categories that were
  ticked.
- Dark and light palettes, switched from the chip in the header and remembered.
- Resize grips, full screen on the header button, F11 or a double click.
- Version in the top right; results in a themed window, not the pyRevit output.

**The parameter picker**

- Typing in the box **narrows the list to matching parameters** as you type.
- The chosen parameter is **remembered between sessions**, along with the theme
  and the three options, in `%APPDATA%\RevoBIM\space_name_to_element.txt`.
- Still filtered to instance-bound text parameters only.

**Writing**

- Elements are **borrowed** with `CheckoutElements` before the write - a write
  to an unborrowed element in a workshared model writes nothing and says
  nothing, because Revit asks in a dialog and a suppressed run answers it.
- Elements another user holds, by element or by workset, are reported by name
  rather than silently missed.
- Every value is **read back** to prove it landed.
- Writes go in chunks of 200 inside a `TransactionGroup`, so undo still sees one
  step but one refused element cannot cost the whole run. The dispatcher is
  never pumped between a transaction's Start and Commit.
- Warnings deleted by an `IFailuresPreprocessor`.

**Revit 2024 - 2027**

- `snte_clr.py` references every assembly before any `System.*` or
  `Autodesk.*` name is touched, and every other module imports it first. This is
  what caused the `Cannot import name Visibility` error in 1.1.0.
- No `System.Uri` - the icon loads from bytes through a `MemoryStream`.
- No bare `ElementId.IntegerValue` - everything goes through `eid_value`.
- `BuiltInCategory` members looked up late, inside a function.
- No f-strings, no `print`, `.format()` throughout.

**Bench checks**

- `import_check.py` enforces fifteen rules; `--selftest` breaks each one on
  purpose and confirms it is caught. All fifteen catch their own breakage.
- `bench_logic.py` covers the tri-state tree, the selection maths, natural
  sorting, `eid_value` across versions and the settings round trip - 46 checks.

## 1.1.0

- Target parameter chosen from a searchable drop down rather than hardcoded,
  filtered to instance based text parameters.
- Ticked categories the parameter is not bound to are added to the project
  parameter's instance binding.

## 1.0.0

- First version. Category tick list, writes "Space Name - Space Number" into
  `BGL_Room name`, joining multiple spaces with " / ".
