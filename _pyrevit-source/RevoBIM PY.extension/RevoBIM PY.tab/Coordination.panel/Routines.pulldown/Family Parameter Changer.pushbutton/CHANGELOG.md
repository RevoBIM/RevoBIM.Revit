# Family Parameter Changer - Changelog

## 1.3.0
- **Bulk rebind.** An orange **Bulk rebind...** button on the Families
  heading opens a three-step dialog: which families (all, or one
  category), which parameter (a census of every parameter name in that
  scope with how many families carry it, how many are already shared and
  how many are not), and which shared parameter to rebind to. The footer
  previews exactly how many families will be queued and how many skipped
  before anything is pressed. **Queue** adds them to the same queue the
  per-row Rebind... uses, so preview, the one-family-per-Execute chain,
  progress, cancel and the report all apply unchanged.
- Bulk skips a family whose parameter is **already bound to exactly the
  chosen shared parameter** (a no-op with a family-editor cost), and
  in-place / non-editable families, and says how many of each. The skip is
  a tick in the dialog and a setting.
- **Run log** at `%APPDATA%\RevoBIM\family_parameter_changer.log`: what
  Apply was asked to do, every result, the summary - timestamped and
  appended. A log that cannot be written never costs the run. On by
  default; the report dialog is all there was before, and it was gone once
  closed.
- **Settings gear** in the header (drawn from a `Path`): light palette,
  show what Apply will do first, bulk skips already-bound, write a run log,
  with the log path shown and an **Open log folder** button.
  `confirm_before_apply` had been a setting with no UI since 1.0.0.
- **Copy report** on the results dialog puts every line on the clipboard.
- Bench: `parameter_census`, `plan_bulk`, `append_log` and
  `format_result_line` are pure and covered - **80 checks**. Two
  regressions put back on purpose (ignore the skip flag; queue blocked
  families) were each caught.

## 1.2.0
- **One family per ExternalEvent.** The handler now pops a single family
  off its queue per `Execute`, rebinds it, loads it back and returns; the
  window updates and raises the event again for the next one. This is
  what makes a progress bar possible at all - while an ExternalEvent is
  executing, Revit's thread is busy and the window cannot repaint, so a
  run that did every family inside one Execute would have shown a frozen
  bar until the very end. It also isolates faults (a family Revit refuses
  costs that family and nothing else) and gives Revit's idle loop a breath
  between family-editor sessions.
- **Progress bar** along the top of the window - two star columns
  weighted done / remaining, so no `ActualWidth` arithmetic - with the
  percentage in the header and `Family 3 of 12 . name . 2 rebound, 0
  failed . next: ...` on the status line.
- **Cancel** during a run, stopping after the family in hand - never
  mid-family. Closing the window during a run does the same and closes
  afterwards; the window is never torn out from under an open family
  editor. The body is hit-test-invisible while a run is on.
- **Load back overwrites the family in the project**, explicitly:
  `IFamilyLoadOptions.OnFamilyFound` returns true (overwrite) with
  `overwriteParameterValues = true`, and the shared-family path does the
  same from `FamilySource.Family`.
- **Every rebind is read back from the project** after the load - the
  parameter is looked up by name on the family's first type (or on a
  sample instance for an instance parameter) and checked to be shared
  with the wanted GUID. A load that raises nothing but changes nothing is
  reported as a failure, not a success.
- **Worksharing.** A family borrowed by another user, or on a workset
  another user owns, is skipped and named - both locks are asked about.
- **Warnings deleted** by an `IFailuresPreprocessor` on the family-editor
  transaction; Revit's own dialogs suppressed via `DialogBoxShowing`,
  hooked once and switched with a flag, with the count reported per
  family. `Transaction.Commit()`'s status is checked rather than assumed.
- **The active document is checked** at every step: if it has changed
  since Apply was pressed, the step is skipped rather than written into
  the wrong model.
- **In-place and non-editable families** are listed but flagged in red
  and cannot be queued - `EditFamily` cannot open them.
- **Read optimised:** type parameters are read from one symbol per family
  (every type of a family carries the same set - reading all of them
  multiplied the work by the number of types for nothing), instances are
  walked once for the whole project keyed by `GetTypeId()` rather than
  `Symbol.Family.Id`, the unused per-parameter group label lookup is gone,
  and after a run **only the families touched are re-read**.
- **UI optimised:** search boxes debounce 250ms; queuing a change repaints
  only its own row and category header rather than rebuilding the list.
- Bench: a new `symtable` rule - every global a function reaches for
  exists in its module - added because this release was a block rewrite of
  the controller, which is exactly what that rule exists to catch.
  `bench_logic.py` now installs a fake Revit and drives the **real**
  `fpc_ops.Execute` through the one-per-call chain, a refused
  `ReplaceParameter`, a refused `EditFamily`, a refused load, a missing
  family, a changed active document, a GUID not in the file, and a load
  that silently does nothing - 61 checks. Both the all-at-once regression
  and the trust-the-void-call regression were put back and confirmed
  caught.

## 1.1.0
- **Moved to the Routines pulldown** on the **Coordination** panel, beside
  QFR Remover and Fire Damper Wall Type Push. The ParamTools panel this
  tool briefly created is gone. No `Routines.pulldown\bundle.yaml` or
  `Coordination.panel\bundle.yaml` is shipped, so merging cannot overwrite
  the ones already there.
- **The family list is grouped by category**, each group a collapsible
  header carrying the family count and, where anything is queued on a
  family inside it, the queued count in orange. Expand all / Collapse all
  on the header. A live search always shows what it found, whatever is
  collapsed.
- **Theme brought in line with the rest of the extension:**
  - ScrollBar, its thumb and its page buttons are now retemplated
    *implicitly* — a ScrollViewer builds its own scroll bars and there is
    no handle to reach them by name, so left stock they rendered in the
    system light theme. This was the main thing making the tool look
    foreign next to the others.
  - Header rebuilt to house spec: the real tool icon (loaded from bytes
    via `MemoryStream`), **RevoBIM** in blue at 20px bold with the tool
    name in orange at 15px beneath it, theme chip, version, then full
    screen beside close.
  - Full screen and close glyphs are drawn from `Border` and `Path`
    elements rather than set in a symbol font.
  - Section headings carry the 4px coloured tick — blue for the family
    list, orange for the parameter table.
  - Resize grips use an explicit transparent `ControlTemplate` rather than
    `Opacity="0"`; a stock `Thumb` draws a bevel from the system theme.
  - `GridSplitter`, `ToolTip` and `TextBox` focus states themed.
  - The `BorderBrush` resource key is renamed `EdgeBrush` — a resource key
    that shadows a WPF property name is asking for trouble.
- Footer gains **Clear queued changes** (orange, greyed until something is
  queued), and the status line now says plainly that nothing is written
  until Apply. F5 refreshes.
- Two new bench rules, both proved by deliberate breakage: every
  `SetResourceReference` key exists in `Theme.xaml`, and the dark and light
  palettes each cover every brush `Theme.xaml` declares (and declare no
  brush it does not).
- `import_check.py` now blanks comments and string literals before
  scanning, so a rule cannot fire on its own explanatory comment. The
  first attempt at this rebuilt the source from tokens and dropped the
  spacing between them, which turned `from System import Uri` into one
  word and silently disarmed the `System.Uri` rule — the selftest caught
  it, which is the entire reason it exists.
- Logic bench up from 17 to 27 checks, covering the grouping and collapse
  behaviour.

## 1.0.0
- First release.
- Reads every loaded family in the project (type parameters from each
  family's types, plus instance-only parameters sampled from one instance
  per family where one exists).
- One family selected at a time. Each parameter row shows whether it is
  currently a shared parameter, and offers **Rebind...** to pick a
  replacement from the project's current shared parameter file.
- Rebinding uses `FamilyManager.ReplaceParameter`, which keeps the
  parameter's current value, formula and grouping - it swaps the
  definition, not the data. Opens the family in the family editor, applies
  every queued change for that family in one transaction, loads it back
  into the project with "overwrite parameter values" set, and closes the
  family document without prompting.
- Nothing is written until Apply, and Apply previews exactly what it is
  about to do first (toggle in Settings).
- Dark/light theme, remembered. Modeless, owned to Revit's main window.
- `FamilyManager.ReplaceParameter` is not available on every Revit release
  this tool targets (added 2022) - a family on an older API reports that
  plainly per parameter rather than failing the whole run.
