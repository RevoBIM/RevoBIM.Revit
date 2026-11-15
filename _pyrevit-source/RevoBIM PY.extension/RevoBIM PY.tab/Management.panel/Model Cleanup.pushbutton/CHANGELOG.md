# Model Cleanup - changelog

## 2.0.0

Revit stays usable
- The window is modeless: Revit can be worked in while it is open. Every
  button that needs the model queues a job on one ExternalEvent and Revit
  runs it when it is free. A second press of the ribbon button brings the
  open window back instead of opening another.
- While a request waits for Revit the status line says so; after 20 s it
  explains why (an edit mode or a Revit dialog) and Esc cancels the request.
  A refused request says what to do and drops only that request.
- While a job runs, Revit is switched off for its length (the progress bar
  pumps messages, which would otherwise let a ribbon click start a command
  mid-job) and switched on again on every path out, including errors and
  closing the window.
- Export Settings opens inside a job, so everything it reads from the model
  is read in Revit's API context; Revit waits while it is open.
- Revit's Close command for a cleaned open model is posted from the window
  as it closes. A cleaned model that is not the one in front is closed
  directly.

Shrink to taskbar, on every window
- Main window, Export Settings and every prompt have a shrink button top
  right. It slides the window down to the bottom of its screen, leaving the
  header bar floating clear of the taskbar; the button turns into a green
  up arrow that slides it back. Ctrl+Shift+H both ways; Esc, Enter, F11 or a
  double click on the bar reopen it. Built to the house standard.
- The bar can be dragged; a bar carried elsewhere opens upward from where it
  sits. A dialog that shrinks takes its owner down with it and stacks its
  bar above; reopening or closing the dialog brings the owner back. A
  dialog opened while its owner is parked centres on the screen.
- The shrink button stays live while a job runs; the rest of the window
  ignores the mouse and keyboard until the job ends.

Revit dark theme
- Dark mode now uses Revit's own slate blue-grey (frame #222933, window
  #2D3440, panels #3B4453, fields #262D38) instead of neutral grey. Muted
  text and red were lifted to stay readable on the lighter panels. The
  RevoBIM accents are unchanged.

Raster images
- "Remove all raster images, placed or not" is gone; only images that are
  not placed are removed. A template that had it on gets "Delete raster
  images that are not placed" switched on instead.

Fixes from a code review
- Callout views placed on a kept sheet were deleted along with an unplaced
  parent view. Every view stage now checks what each delete actually
  removed; a delete that would take a view that stays is undone and that
  view is kept, with the reason in the log. Views kept this way are counted
  apart from real refusals.
- A refused final sync in Clean Up now falls back to a compact save, so the
  committed clean up is never thrown away when the window closes.
- Skip steps 1 and 2 on a local of a live central no longer borrows every
  workset (which locked the team out until the next sync).
- A detached copy whose Save As fails is closed instead of left open
  invisibly, and the message says it was the save that failed.
- Losing the network while watching an ACC publish stops the check instead
  of stacking an error every 10 s.
- Placeholder sheets are never chosen as the view to switch to.
- The progress bar during step 2 showed numbers as the stage text.
- Count could be pressed from the keyboard during a run.
- The debug report now records whether the window was attached to Revit's
  (the 1.8.1 note said it did; it did not).

Fixes from a second review
- The Windows file dialogs (NWC folder, Save As) shown during a job switch
  Revit off while they are up, like the themed prompts do.
- Views placed on a sheet Revit refused to delete are protected by the
  cascade guard too.
- Expanding a drawer keeps anything shown while it was parked (the progress
  bar as a job starts) instead of hiding it again.
- Reopening a dialog no longer pulls up a main window the user had parked
  themselves.

## 1.10.0

- Export Settings: Save to file and Load from file, beside the template
  dropdown, so a template can be kept outside %APPDATA% or sent to someone
  else.
  - Save to file writes the template as it stands on screen, including
    unsaved edits, with the default name "Model Cleanup Template - <name>.txt".
  - Load from file asks what to call it, offers Replace it or Keep both when
    the name is taken, then edits the loaded template straight away.
  - A file saved by an older version is migrated on load; a file that is not
    a Model Cleanup template is refused with a sentence saying so.
  - Templates copied straight out of %APPDATA%\RevoBIM\model_cleanup_templates
    load too.
  - The folder last used is remembered.

## 1.9.1

- Fixed the white list box in dark mode. The NWC view list (and the purge
  category list when purge is off) was disabled, and WPF's stock ListBox
  paints a white system background when disabled whatever the theme says.
  The ListBox template is now replaced in full, and a disabled list simply
  dims.
- The NWC view list stays usable while Export NWC is unticked, so the views
  can be picked first.
- Radio buttons and dropdowns have a disabled look (they had none, which
  showed as black Primary dots).
- The search boxes on NWC export, Views to retain and Sheets to retain get
  their own full-width row, with the buttons beneath; the NWC one was
  squeezed to "Search 3D view".

## 1.9.0

New
- NWC export, set up on a new NWC export tab in Export Settings and run first
  in Clean Up, before anything is removed, into the folder the detached copy
  is saved in (asked for when there is none, e.g. ACC).
  - Settings: Navisworks exporter defaults, or the settings on the tab
    (coordinates, parameters, faceting and eleven options).
  - Views: every 3D view in the model, with a search box, Tick shown / Clear
    shown / Ticked only, a tick per view and one Primary.
  - Names: the primary is <model>.nwc; each other view is
    <model>_<view name>.nwc.
  - Each file is checked on disk. If any are not written, Clean Up asks
    before carrying on; nothing has been removed at that point.
- Step 2 is now Save As Detached Copy, and its confirmation says the saved
  copy is the detached model everything afterwards works on.

From the second debug report
- ACC models go straight to saving the open (just synced) model as the
  detached copy. Revit refuses to detach a cloud model on open, so the old
  first attempt only ever failed.
- Save and close no longer syncs a second time when Clean Up already saved
  and relinquished and nothing has changed since.
- The CAD count before Clean Up allows for imports inside views that are
  going (it said 5194; the run asked for 53).
- Templates still carrying the old "RevoBIM Model Cleanup" sync comment get
  the current default.
- Purge groups: Other Types, Other Elements, Line and Text Styles.
- The full sheet and view table is only re-read after the run when the
  debug report is on.

## 1.8.1

- The window no longer drops behind Revit during a sync. It is now owned by
  Revit's main window (it had no owner, so when Revit's sync progress handed
  focus back to Revit the tool went underneath). An owned window always sits
  above Revit, and still goes behind other applications like any Revit
  dialog.
- After every sync, detach, save, clean up and ACC sign-in it is also
  restored, raised and focused. Topmost is only pulsed, never left on.

## 1.8.0

- Views to retain and Sheets to retain each have a Retained only button
  that isolates what is ticked, still grouped by the browser organisation.
  It turns orange and reads Show all while on, and works with the search.
  Retain shown / Clear shown act on what is showing.
- While isolated, unticking something leaves its row in place until Show
  all or a new search, so rows never jump out from under the pointer.

## 1.7.0

- New clean up stage, Delete raster images that are not placed (on by
  default). It runs straight after the sheets, views, schedules and
  legends, so an image that was only placed on a deleted sheet or view goes
  too, and before links, templates and the purge.
- "Not placed" is Revit's own purge answer for the Raster Images category,
  so an image picked in an element's Image parameter is kept even though it
  sits on no view.
- The Clean Up count for it allows for the sheets and views going first.
- The old raster stage is now labelled Remove all raster images, placed or
  not, and stays off by default.

## 1.6.1

- Export Settings: a Suffix tick beside the file name suffix. Untick it and
  the send copy keeps the model's own name (plus the date, if that is still
  ticked); the suffix box greys out but keeps its text for next time.
  Templates saved before this have the suffix on, as they did.

## 1.6.0

- Close after a clean up now asks: Cancel, close the window (leaving the
  open model open, or opening the copy as before), or Save and close.
- Save and close saves compact and relinquishes every workset, then offers
  to open the model's folder (Explorer with the file selected), and closes
  the model.
  - The saved copy, or an open model that is its own central: synced with
    Relinquish all and Compact.
  - A model that is not workshared: saved compact.
  - A model never saved: asks where, saves it compact (as its own central
    when workshared), then syncs and relinquishes.
  - A local file of another central (or any cloud model): asks. Save local
    only is the default; Sync and relinquish sends the clean up to that
    central and needs CONFIRM typed.
- The open model is closed with Revit's own Close command, posted as the
  window closes - Revit refuses to let an add-in close the active model
  directly. The background copy is closed straight away.
- Cleaning the open model: if the active view is not a retained sheet or
  view, a retained sheet is opened (a retained view if no sheet is
  retained) and the old view is closed - even if the old view would have
  stayed. With nothing retained, it only moves off a view that is going.

## 1.5.1

From the first debug report (Revit 2024, 285 sheets and 446 views removed,
nothing refused, nothing left behind):

- The Clean Up counts for unused view templates and filters now allow for
  the sheets and views that go first. The report showed 2 and 0 predicted
  against 31 and 87 removed.
- The confirmation now lists what stays that someone might expect to go:
  views whose delete stage is off (46 legends in that run), and view types
  the tool never deletes, such as panel schedules (53).
- Title block revision schedules are described as such in the report ("goes
  with its sheet") rather than "Revit keeps this one".
- A stage's protected ids and placed-view count now print under that
  stage's own heading, not the one before it.
- Revit's version no longer prints the year twice.

## 1.5.0

- Fix for "Clean Up did not remove the views and sheets that were not
  retained". Delete sheets not retained is off by default and in every
  template saved before 1.4.0; with it off no sheet goes, and every view on
  any sheet counts as placed and stays. Clean Up and Export Settings now
  catch this: when retain lists are set but the stage that would use them is
  off, they say so and offer to turn it on.
- The Clean Up confirmation lists how many sheets, views, schedules,
  legends, links, templates and filters each stage will remove, counted on
  the model being cleaned.
- Cleaning the open model: if the active view is going, a retained sheet or
  view is opened first (then the starting view, then anything that stays)
  and the old view is closed. Any other open view that is going is closed
  too.
- Debug report tick box in the footer (remembered). Writes
  %APPDATA%\RevoBIM\model_cleanup_debug_report_<date>_<time>.txt: Revit and
  engine versions, model facts, browser organisations, the template, every
  sheet and view with its retain key and the reason it goes or stays, each
  stage's asked / removed / refused with names, purge passes by category,
  what should have gone but is still there, dialogs Revit raised, and any
  error with its traceback. Written after every section, so a failed run
  still leaves it. Open debug report selects the file in Explorer. No sign-in
  token is ever written to it.

## 1.4.0

- Export Settings has three tabs: Categories to purge, Views to retain and
  Sheets to retain.
- Views and sheets are grouped exactly as the project browser shows them
  now (its current organisation, then view type), with a tick per item, a
  part-tickable tick per folder, a search box that matches names and folder
  names, Retain shown / Clear shown, and collapsible folders.
- New clean up action, Delete sheets not retained (off by default). Views,
  schedules and legends are now deleted unless retained or placed on a sheet
  that stays.
- New order: sheets, views, schedules and legends first, then links, CAD,
  point clouds, images, templates, filters, and the purge last.
- The purge runs 4 passes by default. Saved templates are migrated from 3
  to 4; a template saved with its own number after this keeps it.
- Retained views are stored by type and name, retained sheets by number, so
  a template carries across models built to the same standard.

## 1.3.0

- Skip steps 1 and 2: a red button under Clean Up, available only before
  anything else has run. Clean Up then runs on the model that is open now.
- The prompt warns, in capitals, never to do this to a central model or to
  a local that will be synced, and names the case when the open model is
  still connected to its central or is the central file itself.
- The prompt only goes through when CONFIRM is typed exactly, in capitals.
  Anything else skips nothing and says why.
- After a skip, steps 1 and 2 show Skipped in orange, the Clean Up card
  names the open model in red, and Publish stays dark (nothing was synced).
- A skipped run never saves or syncs. The log says so; Revit's Undo reverses
  the whole clean up in one step.

## 1.2.1

- Renamed from "RevoBIM Model Cleanup" to "Model Cleanup": the ribbon
  button, the window titles, Revit's dialogs, and the names written into
  Revit's undo history and sync comments. The RevoBIM logo in the header
  stays, as on every RevoBIM tool.
- The button folder was already "Model Cleanup.pushbutton", so nothing moves
  on disk and no second button appears. Settings, templates and the saved
  ACC sign-in keep their file names, so nothing is lost.
- If a keyboard shortcut was bound to the old name, it may need binding again
  under the new one.

## 1.2.0

- Publish latest to ACC, under step 1. Lights once a cloud workshared model
  is synced. Asks with links or without links (or the template can fix the
  choice), and is offered straight after a sync unless the template turns
  that off.
- Uses Autodesk's Data Management commands C4RModelPublish and
  C4RPublishWithoutLinks - Revit itself has no publish API. Checks
  C4RModelGetPublishJob first so a publish already running is not doubled,
  then watches the job every 10 s (window stays usable) until ACC reports
  done or failed, for up to 15 minutes.
- Sign-in is a browser PKCE login against your own APS app: only a Client
  ID, no secret. The refresh token is encrypted for the Windows user with
  DPAPI; Sign out in Export Settings forgets it. Escape cancels a sign-in
  wait.
- Export Settings: new Publish to ACC card (offer after sync, links choice,
  Client ID, sign-in port, callback URL, setup help, sign out). Window is
  taller to fit it without scrolling.
- Revit's own fallback dialog now keeps three-way choices three-way.
- New modules mcu_aps (rules) and mcu_json (a small JSON reader, since the
  engine's json module is not guaranteed); both bench tested.

## 1.1.0

- Thick progress bar along the bottom of the main window and Export
  Settings, replacing the thin line under the header. Percent in the bar,
  the current stage on the left, time left and time elapsed on the right.
- Blue while running, green when done, orange when done with refusals, red
  when a step fails. Stays up after a run showing how long it took.
- Clean Up progress is weighted by how long each stage usually takes (the
  purge and the views get the biggest slices), and reports after every chunk
  of 25, every element of a one-by-one replay, and every purge pass.
- Time left blends the whole-run average with a smoothed recent rate, waits
  for 2 seconds and 2% before guessing, and the percent never runs
  backwards. Repaints on every whole percent and at least every 0.15 s,
  never more often.
- Sync, Save As, counting and the settings scan show their stages too.
  While Revit itself is busy in one long call the bar says so.

## 1.0.0

- First release, on the RevoBIM PY tab, Management panel.
- Three big step buttons in order: Sync Current Model (Save for a
  non-workshared model), Save As Model, Clean Up Model. Save As lights once
  the sync is done; Clean Up lights, in green, only once both are done, and
  only once per copy.
- Save As opens the central detached (preserve or discard worksets), saves it
  where chosen, and every clean up runs on that copy. The live model is never
  cleaned. If Revit will not open the central a second time, offers to save
  the open model as the copy instead.
- Clean up actions: Revit links, CAD links and imports, point clouds, raster
  images, views / schedules / legends not on a sheet (keep words, starting
  view and primary views of kept dependents protected), unused view
  templates, unused view filters, and a multi-pass purge.
- Export Settings: named settings templates with a dropdown, a purge category
  list read from the live model with unused and used counts, and a
  "Show used / unused elements" tick that lists the elements themselves.
- Dark and light chip top right; Auto follows the Revit canvas.
- Easter egg on the RevoBIM logo (three slow clicks).
- Chunked deletes with one-at-a-time replay, so one refused element never
  costs the rest; every refusal is named in the run log.
