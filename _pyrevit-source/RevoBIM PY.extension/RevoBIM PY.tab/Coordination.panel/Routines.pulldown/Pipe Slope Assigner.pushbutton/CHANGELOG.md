# RevoBIM Pipe Slope Assigner - changelog

## 1.2.0

Fixes the refusal on the concourse drainage (77 pipes, 85 fittings, network
scope at 1:60): "Pipe 14475518 would be 1:81, not 1:60", short pipes beside
the 45 degree junctions falling the wrong way.

- **Set ups and set downs stop the fall.** The line between horizontal and a
  set up / down / upright was 46 degrees, so a 45 degree set down was treated
  as horizontal pipe and re-sloped - that was 14475518, 14474061 and 15283736.
  It is now 15 degrees by default (5, 10, 15 or 30 in the window). The walk
  stops at a set up or down in every scope; the set up / down stretches to stay
  joined, and anything beyond it is not touched. A sloped set up / down whose
  angle changes by more than a degree is flagged to check the bends.
- **Fittings are measured where their axes meet, not at their insertion
  point.** On a 45 degree junction the branch axis meets the main a way along
  from the family's insertion point, so the fall was worked out through the
  wrong point and the short pipes beside it came out wrong - 1:7 falling
  backwards on a 48mm pipe. The meeting point of the connector axes is now
  found in 3D (least squares), so junctions, 45 degree bends, vertical bends
  and bends into stacks are all measured through the centrelines.
- **New scope: Selected pipes and fittings, as one system.** Select the pipes
  and fittings (box-select is fine), Apply, and everything horizontal in the
  selection falls together to one outlet. Selected pipes steeper than the set
  up / down line are left as they are and stretch. Pipes joined on but not
  selected stretch to stay joined and are listed with their new fall; fittings
  not selected are held. Separate groups in the selection become separate
  systems. Nothing selected: Apply asks you to pick them, then Finish.
- Short pipes are judged in millimetres as well as ratio: a 7mm pipe between
  two fittings passes if its fall is within 0.3mm.
- New refusals, so a bad plan never reaches the model: a pipe end moving more
  than 5mm sideways, a fitting turning more than 10 degrees, a fitting asked to
  fall two ways at once. Every problem is listed, not just the first.
- The largest run allowed goes from 600 to 1500 elements.
- The debug report shows where each fitting's axes meet beside where the
  family is placed.


## 1.1.0

- **Revit stays usable while the tool is open.** The window is modeless: zoom,
  pan, orbit, select a different run, edit the model - it floats above Revit
  (owned by Revit's window, so it never slips behind).
- The window stays open after Apply. Select another run and Apply again; Close
  or Esc when finished. Pressing the ribbon button again brings the open window
  forward rather than opening a second one.
- The selection panel and the preview follow Revit's selection live
  (`SelectionChanged`). The preview walks at most 20 runs, so a box-select of a
  whole floor does not stall Revit; Apply always takes everything.
- Apply queues the work through an `ExternalEvent`, clicks included. While it
  runs the window takes no input and says so; if Revit is mid-command it waits
  until you finish or Esc out.
- The results window is modeless too, and replaced by the next run's.
- The window reopens where you last left it (if that is still on a screen).
- Safety net: if pyRevit ever tears the engine down behind the window, the next
  launch notices and offers the fixed (modal) window instead. Setting
  `window=modal` in `pipe_slope_assigner.txt` forces it; `window=modeless` goes
  back.

## 1.0.0

First release, in the Routines pulldown on the Coordination panel.

- Click a horizontal pipe, press the button, choose **1:100, 1:80, 1:60 or 1:40**
  (keys 1-4), Enter to apply.
- **Apply to**: the current horizontal run (through bends, straight on through
  tees, never out of a branch), or the run and every horizontal run joined to it.
- **Direction of fall**: keep the way it falls now, or two clicks - fall FROM,
  then fall TO. A level run with nothing to say which way it drains asks for the
  two clicks by itself.
- **Hold the elevation at** the low end (default) or the high end.
- Every pipe falls at exactly 1:N along its own axis, including both legs of a
  run that turns a corner. Bends and tees turn to suit; uprights and branch
  pipes stretch, their far ends staying put.
- Every writable parameter value on the pipes and fittings is read before the
  change, compared after, and put back if the reconnect disturbed it; anything
  that will not go back is reported by name.
- Debug tick: shows the full report in the results window with Copy report, to
  paste to Claude. The report is always written to
  `%APPDATA%\RevoBIM\pipe_slope_assigner_debug.txt`.
- Dark / light / Auto (follows Revit's canvas) from the chip top right, version
  top right, RevoBIM logo carries the easter egg.
- Runs on Revit 2024 - 2027, IronPython 2.7 and 3.
- One undo step for the whole run. Workshared: elements are borrowed first; a
  run somebody else holds is left alone and named.
