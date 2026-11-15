# Click to RVT Element - changelog

## 1.0.0 - 2026-11-12

First release, Point Cloud panel.

- One click on a linked point cloud recognises what was clicked: round run
  (pipe, conduit, round duct), rectangular run (duct, cable tray, beam,
  column), wall face, floor or ceiling.
- Runs are traced along the cloud to their ends (or click the end); walls are
  followed to their ends and top, slabs flood-filled to a traced outline.
- Size snapped to the closest the project offers: pipe ODs from routing
  preference segments, duct and tray size tables, conduit standards, wall type
  widths (thickness measured when both faces are scanned), structural types
  by width/depth parameters.
- Best match placed straight away; up to six alternatives to swap to with
  one click. Select in Revit / Delete it.
- Section preview of the points and the fitted shape.
- House chrome: Auto / Dark / Light theme chip following Revit's canvas,
  shrink-to-taskbar drawer on both windows, full screen, resize grips.
- Debug log on by default: %APPDATA%\RevoBIM\click_to_rvt_debug.txt
