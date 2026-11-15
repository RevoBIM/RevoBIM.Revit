# Schematic Marriage - changelog

## 1.8.0 - 2026-11-11

Revit's own dark theme
- Dark now uses the house Revit-dark values (sampled from Revit's dark
  Project Browser): body #3C4454, fields #2D3441, title / footer bars
  #222933, table headings and chips #323C48, hover #444E5E, selection
  Revit's active blue #3A7392, edge #515C6B, text #EEF0F4. Muted grey and
  blue are lifted (#A4AAB1, #5AAEEB) so they still read on the lighter body.
  Light theme unchanged.
- Coloured and muted text turns white on a selected table row or list item
  (it was under 2.5:1 on the selection blue).
- New bench rule: palette = Revit values, Theme.xaml defaults = palette, and
  text contrast on every dark surface.

Shrink to taskbar - every window (main, Parameter Push Templates, prompts)
- New button top right, beside full screen. The window drops like a drawer:
  the bar travels down to the bottom of the screen, just above the taskbar,
  and the body slides out of sight beneath it, leaving only the bar floating
  so Revit can be seen. The button becomes a green up arrow.
- Reopen with the arrow, a double-click on the bar, Escape, Enter, F11 or
  Ctrl+Shift+H (which also shrinks). It opens upwards from wherever the bar
  has been dragged, never above the top of the screen (a monitor above the
  primary included).
- Shrinking a prompt takes its owner window down too, parked beneath it, and
  brings it back when the prompt reopens or closes. A prompt or the
  templates window opening while its owner is parked centres on the screen.
- Stays live while a job runs (the rest of the window is deaf); the bar is
  not draggable mid-job.
- Smooth: snapshot + transforms, frame-synced, 0.38s, nothing left holding
  the window's size afterwards.

## 1.7.2 - 2026-10-19

- Animation timing now uses each frame's own presentation time instead of a
  Python clock (whose ~15ms resolution on Windows made steps uneven), skips
  duplicate frames, and caps a slow frame (Revit busy) at 34ms so it can never
  show as a jump.
- The end of the genie is softer: the fade starts earlier and runs longer,
  and strips never squash below ~1.4px, which is what shimmered as everything
  piled into the footer.
- Opening hands over cleanly: the real window is shown first and the
  animation removed only after that frame is drawn - no flash at the end.
- The X on Parameter Push Templates now closes with the same animation as
  "Close back to Marriages" (a double click cannot start it twice).

## 1.7.1 - 2026-10-19

Smoother animations (open, close, editor slide)
- Frames now come from WPF's own per-frame callback (CompositionTarget
  .Rendering), in step with the screen, instead of a 15ms timer that drifted
  against the refresh and stuttered.
- The genie strips are laid out once; each frame only moves a transform, so
  there is no layout work per frame (before: 36 strips resized and
  re-positioned every tick).
- 56 strips instead of 36 and smootherstep easing with the narrowing led on
  a curve - the funnel edge is curved rather than stepped, with no visible
  start or stop.
- The clock starts on the first painted frame (no opening jump), and the real
  window only hides once the animation has drawn, so there is no blink.
- Slightly longer (0.6s) and a softer fade at the end.

## 1.7.0 - 2026-10-19

- Parameter Push Templates now opens the Mac way: it pours out of the middle
  of the main window's footer - the same spot "Close back to Marriages"
  shrinks into - bottom strips last, like restoring from the dock (~0.5s).
  Categories start reading once it has landed. If the main window is not on
  screen it simply appears.

## 1.6.2 - 2026-10-19

- A new template you have not touched is no longer "unsaved": putting it
  away (empty space, Cancel, picking another template, closing) does not ask
  to discard it. "Changed" now means different from how it was opened, for
  new and existing templates alike.
- Main window: hover a cell that is cut short (ending in ...) and its full
  description appears underneath it - for source and target cells the full
  family : type, category, element ID and the view it is drawn in. Cells
  that fit show nothing.

## 1.6.1 - 2026-10-19

- Reading categories is much quicker: only Mechanical, Plumbing and
  Electrical categories plus Detail Items and Generic Annotations are counted
  (about 50 quick counts instead of one per category in the model, 400+).
  Names are looked up per release, so ones a release lacks are skipped.
- Categories are read once per session - reopening the templates window is
  instant.
- The category drop-down groups them Mechanical / Plumbing / Electrical /
  Schematic and shows the group beside each; typing the group name
  ("electrical") filters to it.
- A template using a category outside the list still shows and edits it.

## 1.6.0 - 2026-10-19

- Parameter Push Templates: a progress band above the footer while the model
  is read - "Reading categories - 45% - 210 of 460 left" on opening, and
  "Reading Pipes parameters - ..." when a template's categories are read.
  Updated between reads only (no transaction is ever open).
- The window always opens with the editor closed and no template selected,
  pinned or not; the pin takes over once a template is opened. The toolbar
  button no longer pre-fills a new template from the selected marriage (the
  template cell's "New template for these categories..." still does).

## 1.5.0 - 2026-10-19

Parameter Push Templates window
- One click on a template slides the editor out already in edit mode (no
  separate Edit step; Edit and double-click still work).
- Clicking the empty space under the template list puts the editor away when
  nothing has been changed (unpinned only; with unsaved edits it stays).
- "Close back to Marriages" minimises into the bottom of the main window like
  a Mac window to the dock: the window is snapshotted into strips that funnel
  down, bottom first, and fade into the main window's footer (~0.5s).

## 1.4.0 - 2026-10-19

Parameter Push Templates window
- Opens contracted - just the template list. Clicking a template or creating
  one slides the editor out and the window grows with it (ease-out, ~0.26s);
  Save, Cancel, the "Editor" chip or Escape slide it back. The window moves
  left if growing would run off the screen.
- **Pin** chip: pinned, the editor stays out and greys when not editing;
  unpinned, it slides. Remembered, as are the list and editor widths.

Update Data (from the first live debug report)
- An empty source is no longer counted as "needs a look": it is left alone
  by design and reported separately ("left alone (source empty)"), with a
  pointer to the template's clear-target option. Row status reads e.g.
  "1 written, 1 source empty".
- Nothing to change -> no TransactionGroup, so no empty "Update Data" step in
  Revit's undo list.
- Source element looked up once per marriage, not per value; the source
  parameter only re-read for element references.
- Debug report: per marriage the template name, source and target labels
  and every push as "was -> now" (or "already" / "source empty"), plus a
  timing line (plan / borrow / write / total ms, transactions). Plurals fixed
  ("1 value").

## 1.3.0 - 2026-10-19

- Template assignments are now staged: choosing a template (cell menu or Set
  Template) changes the table only. Staged cells turn orange and read
  "not applied"; nothing reaches the model until **Apply Changes** (footer,
  with count, Ctrl+S).
- **Undo / Redo** buttons (icons, top left of the table) and Ctrl+Z / Ctrl+Y
  (Ctrl+Shift+Z) step back and forward through template assignments. Undo
  after applying stages the reverse change, ready to apply.
- Template editor gets its own **Undo / Redo** (icons in its heading,
  Ctrl+Z / Ctrl+Y while editing, Ctrl+S saves): name (typing folds into one
  step), categories, clear-empty option, adding and removing pushes. Undoing
  back to the saved version clears "unsaved changes".
- In a search or filter box Ctrl+Z / Ctrl+Y stay the text box's own.
- Update Data with staged changes asks first: **Apply and continue**,
  **Continue without** (runs on what the model holds, leaves the staged
  changes staged) or Cancel. It also says if the template editor has unsaved
  edits. Closing the window asks the same.
- A model reload (another user's sync, Revit undo) keeps staged changes.

## 1.2.0 - 2026-10-19

Main window
- Steps across the top: STEP 1 Source | STEP 2 Target | STEP 3 Marry them
  (template + Add Marriage on the right).
- Template cells with a template are a raised blue button (tinted face, blue
  edge, shadow); unassigned ones stay plain; a deleted template shows red.
- Multi-select: Ctrl / Shift work on the template cell too. Choosing a
  template on any selected row sets every selected marriage. New "Set
  Template (n)" button top left does the same.
- Remove Selected moved top left, red, smaller, only lit with a selection.
- Debug ticked: after Update Data (and on a failed Highlight / Isolate) a
  report opens with a Copy button to paste to Claude.

Every coloured button
- Soft drop shadow that lifts on hover, presses in on click (face drops 1px)
  and goes flat when greyed out.

Parameter Push Templates
- Green "+ New template" row under the last template.
- Editor is greyed out until New or Edit (button, or double-click a
  template). Clicking a template only shows it.
- Save Template and Cancel / Discard moved into the editor. After saving the
  editor greys out again and the saved template is selected and shown green.
- "Close back to Marriages" bottom right.

## 1.1.0 - 2026-10-19

- Table text readable again: the cell colour converters returned "unset" for
  ordinary cells, which drops WPF to its default brush instead of the theme's
  text colour. They now always return a theme brush (new bench rule).
- Template categories: one box. Type and the drop-down underneath narrows to
  the categories matching every word; Up / Down, Enter or click picks, Escape
  puts the current one back.
- Picking a source or target paints it magenta in the view it was picked in
  (projection, cut and solid surface fill). The element's own overrides are
  recorded first and put back when the pick is replaced or cleared, the
  marriage is added, Clear Highlights is pressed or the window closes.
- Highlight in View: multi-select marriages, paint their elements magenta in
  the current view; the status line says how many are actually in the view.
- Isolate in Default 3D: opens {3D - user} / {3D} (or makes "Schematic
  Marriage 3D"), resets any old isolate, fits the section box round the
  model elements and isolates them with the section box kept visible.
  Detail items are left out (they only exist in their own view).
- Clear Highlights (with count) in the footer; both actions also on the row
  right-click menu.
- Theme chip glyph redrawn (half-filled circle) - the crescent was clipped.

## 1.0.0 - 2026-10-19

First release. Schematic panel, RevoBIM PY tab. Revit 2024 - 2027.

- Pick Source (model element) and Pick Target (model element or detail item);
  one element already selected in Revit counts as the pick.
- Add Marriage stores the pair in the model (Extensible Storage, one
  DataStorage element per record, keyed by UniqueId) with an optional
  template chosen from those matching the two categories.
- Marriage table: per-column keyword filters, global search, natural sort,
  double-click a source or target cell to show it in Revit (a detail item
  opens its own view), right-click menu, Remove Selected.
- Parameter Push Template column: click to choose from compatible templates
  only; applies to every selected row with the same categories.
- Parameter Push Templates window: source / target category, searchable
  parameter lists, pushes with conversion notes, name and save; template list
  with Pushes and Used counts; New, Duplicate, Merge (choose the master,
  conflicts listed), Delete (warns when in use), Import / Export library file
  for sharing between projects (e.g. on ACC).
- Update Data lights up once any marriage has a template: plans every write,
  skips values already equal (nothing borrowed for them), borrows the rest,
  writes in chunks inside one TransactionGroup (one undo), reads every write
  back, flags type-parameter clashes, reports anything that needs a look.
- Theme chip top right: Auto follows Revit's canvas theme, or Dark / Light;
  remembered. Version top right. Full screen, resizable, modeless.
- Debug tick writes %APPDATA%\RevoBIM\schematic_marriage_debug.txt.
