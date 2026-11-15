# Unhide in View - changelog

## 1.1.0 - 2026-10-23

- **Shrink to taskbar.** A new button top right, before full screen and
  close. It slides the window down to the bottom of the screen like a drawer
  closing, leaving only the header bar floating just above the taskbar so the
  model can be seen and worked in. The button turns into a green up arrow:
  press it to slide the window back up exactly where it was.
  - Also Ctrl+Shift+H either way; while shrunk Enter, Escape, F11, the full
    screen button or a double-click on the bar bring it back.
  - The bar can be dragged; if it has been moved, the window opens upward
    from where the bar now sits, kept on that screen.
  - Ticks, filters, the scan and everything staged carry on while shrunk.
    A confirm prompt (e.g. closing with ticks) opens the window first.
  - Closing while shrunk remembers the real window size, not the bar.
- New shared helpers in `uiv_ui`: `WindowDrawer` and `work_area` (full screen
  now uses the same screen lookup).

## 1.0.0 - 2026-10-09

First release.

- Left: the elements hidden in the view being looked at (the view open in
  Revit when the tool starts), with Element ID, Category, Family : Type, Level
  and a note when the element's category is hidden there as well. A keyword
  box under every heading. Tick rows, or just select them, and press Unhide.
- Right: every view and sheet in the project with a keyword search, a Hidden
  count per view filled in by a background scan, and a "Show views with
  hidden elements" toggle. Click a view to show its hidden elements on the
  left; double-click to open it in Revit. Tick views and press "Unhide all in
  ticked views".
- Bottom left: the categories hidden in the ticked views (or the view being
  looked at), with how many of those views hide each one. Tick and Unhide.
  Categories a view template controls are named with the template and only
  changed on the template when "Also change view templates" is ticked.
- One undo step per Unhide; views borrowed first on workshared models; every
  result read back after the run - anything still hidden turns red with why.
- The scan runs in slices of at most 120ms inside an ExternalEvent, so Revit
  stays usable while hundreds of views are counted.
- House theme, dark and light: the chip top right cycles Auto (follows the
  Revit canvas) / Dark / Light. Version top right, full screen, resize grips,
  easter egg on the logo.
- Revit 2024, 2025, 2026 and 2027 from one copy.
