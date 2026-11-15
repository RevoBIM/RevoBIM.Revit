# RevoBIM Sheet Name Push - Changelog

## 2.2.2
- Moved into the existing **Coordination** panel **Routines** pulldown -
  the one QFR Remover and Fire Damper Wall Type Push already sit in:
  `RevoBIM PY.tab\Coordination.panel\Routines.pulldown\Sheet Name Push.pushbutton`.
  That also removes the duplicate-`Routines.pulldown` clash the Management
  copy would have caused.
- Everything the tool needs sits **inside its own pushbutton folder**, the
  same arrangement Fire Damper Wall Type Push uses, because the pulldown
  is shared. Nothing is written to `lib\revobim`.
- The shipped `Routines.pulldown\bundle.yaml` and `icon.png` can be
  deleted if that pulldown already has its own.

## 2.2.1
- Packaged to merge straight into the existing extension: the zip's root
  folder is now `RevoBIM PY.extension\`, so it drops onto the installed
  one rather than arriving as a separate extension with its own copy of
  the RevoBIM PY tab.
- Dropped the shipped `Management.panel\bundle.yaml` - that panel already
  exists (Drawing Register sits on it) and shipping one would overwrite
  its title and ordering.

## 2.2.0
- Renamed from **Sheet Management** back to **Sheet Name Push**, and moved
  into a **Routines** pulldown on the Management panel:
  `RevoBIM PY.tab\Management.panel\Routines.pulldown\Sheet Name Push.pushbutton`.
  pyRevit names a ribbon item after its folder, so the old
  `Sheet Management.pushbutton` folder must be deleted or both buttons
  will appear.
- Pulldown ships its own `bundle.yaml` and icon; both can be deleted if a
  Routines pulldown already exists on this panel.
- **The settings path is deliberately unchanged**
  (`%APPDATA%\RevoBIM\sheet_management.txt`). A missing settings file
  falls back to the defaults silently, so renaming it would quietly throw
  away every saved target parameter and format choice.

## 2.1.0
- **Ctrl-click adds to the selection**, and ctrl-clicking an already
  highlighted row removes it again. Ctrl+Shift adds a whole range to what
  is already highlighted; a plain click still replaces the selection.
- **The text format is remembered between runs.** The choice is written to
  `%APPDATA%\RevoBIM\sheet_management.txt` as soon as it is changed (not
  only on push) and restored the next time the window opens. An unknown or
  damaged value falls back to UPPERCASE. `settings_version` bumped to 3;
  older files load fine and simply pick up the default.

## 2.0.0
Renamed from **Sheet Name Push** to **Sheet Management**; moved from the
Sheet Tools panel to **Management**.

- **Resizable windows.** Switched from `AllowsTransparency` to
  `WindowChrome` (CaptionHeight 0, ResizeBorderThickness 8) so every
  window resizes from any edge or corner while keeping the custom dark
  header. Applies to the main, results, settings and tool dialogs.
- **Click the text, not just the tick box.** Clicking anywhere on a row
  highlights it; **shift-click** extends the highlight as a range. Ticking
  any row inside a highlight applies that tick state to the whole
  highlight.
- **Settings** behind a gear icon, top right of the header. Chooses the
  target parameter for each of the three name segments from the writable
  text parameters found on sheets, defaulting to `BGL_Sheet Title 1/2/3`.
  Persisted as plain key=value in
  `%APPDATA%\RevoBIM\sheet_management.txt` with a `settings_version` stamp.
- **Inline editing.** Double-click a sheet number or name to edit it.
  Nothing is written to Revit until **Apply Edits**; staged values show in
  orange with the original in the tooltip, and the button turns from
  outlined orange to solid green while edits are pending. Enter commits,
  Escape cancels, and **Revert Edits** discards the lot.
- **Duplicate sheet numbers** are flagged red (counting staged edits, not
  just what is in the model), with an "Isolate sheet numbers already in
  use" filter. Apply Edits refuses to run while a staged number clashes.
- **Find & Replace** and **Prefix / Suffix** tools with themed icons, each
  with a live preview pane, name/number/both targeting, match-case (find)
  and a remove mode (affix). Both stage into the same edit buffer rather
  than writing directly, so they can be reviewed and reverted.
- Both tools act on the ticked sheets, or on everything currently shown
  when nothing is ticked.
- New icon set drawn in the house blue/orange palette at 8x supersampling.
- `import_check.py` extended: now also verifies every `self.<control>` the
  script touches exists as an `x:Name` in one of the five XAML files, that
  every XAML event handler has a matching method, and that all icons ship.

## 1.4.0
- Re-themed to the RevoBIM PY house style; header icon, version top right.
- Two columns (Sheet Number / Sheet Name) with tick boxes.
- Project Browser selection isolates in the list, with a show-all toggle.
- Search matches either sheet number or sheet name.

## 1.3.0
- Revit 2021-2027 via the `eid_value()` helper.
- Themed completion window replacing the pyRevit output console.

## 1.2.0
- Custom dark title bar replacing the native white caption bar.

## 1.1.0
- Project Browser selection pre-checked.

## 1.0.0
- Initial release.
