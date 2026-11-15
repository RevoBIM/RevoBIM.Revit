# RevoBIM Tag Tidy - what to check in Revit

The layout engine is proved on the bench (`bench_logic.py`), and every module
loads against a stub of the Revit API (`import_check.py`). What the bench cannot
prove is how Revit itself behaves. These are the API behaviours the tool relies
on, how it protects itself if one is wrong, and a quick test for each. Run them
once in a scratch copy of a model on each Revit version you use.

Every run that goes wrong writes its traceback to
`%APPDATA%\RevoBIM\tag_tidy_last_error.txt` as well as showing it.

## 1. Setting `TagHeadPosition` leaves a free leader end where it was

**Relied on:** moving a tag with a free-end leader does not drag the end.
**If wrong:** the tool reads every free end before writing and puts it back
with `SetLeaderEnd` if it moved, so the end stays put either way.
**Test:** tag a pipe with a free-end leader, run the tool, check the arrow still
touches the same point on the pipe.

## 2. Switching an attached end to free keeps it in the same place

**Relied on:** the tool reads attached leader ends by switching them to free
inside a transaction it rolls back, because `GetLeaderEnd` refuses attached
ends.
**If wrong:** leaders would point slightly off their elements in the layout
(the model itself is never changed by this, as it is rolled back).
**Test:** tag a duct with an attached leader, run the tool, check the 45 degree
leg ends exactly on the duct.

## 3. A tag's bounding box with its leader off is the tag alone

**Relied on:** `get_BoundingBox(view)` with `HasLeader = False` gives the tag's
own outline, which sets the stacking pitch and alignment.
**If wrong:** tags would overlap or space unevenly.
**Rotated views:** that box is aligned to the model axes, so in a view whose
crop is rotated (or a diagonal section) the box reads larger than the tag and
the column spaces out a little more. It is safe, just looser.
**Test:** stack a one-line and a three-line tag, check the gap between them is
2mm on the sheet at two different view scales.

## 4. The leader leaves the tag at its vertical middle

**Relied on:** with the elbow level with the tag's middle, Revit draws the
shoulder horizontal (the basis of v3.2.0 of the elbow tool).
**Test:** zoom in on a stacked three-line tag; the shoulder should be perfectly
level.

## 5. Annotation crop offsets are paper distances

**Relied on:** `LeftAnnotationCropOffset` and its siblings are in paper feet.
**If wrong:** the allowed area would be scaled by the view scale. With the
annotation crop off, the tool uses the model crop and this does not apply.
**Test:** turn the annotation crop on in a cropped plan, stack tags near its
edge, check none is hidden by it.

## 6. `SpatialElementTag` (room and space tags)

Room and space tags are off by default. When switched on, the tool moves them
with `TagHeadPosition` (falling back to moving the element) and sets the elbow
with `LeaderElbow` (falling back to `LeaderElbowPosition`). Whichever the
release accepts is used; if neither, the row says Revit refused the elbow.
**Test:** turn the setting on, stack three room tags with leaders.

## 7. `WorksharingUtils` status

**Relied on:** `GetCheckoutStatus` reports `OwnedByOtherUser` for a tag another
user has borrowed, and `GetModelUpdatesStatus` reports `UpdatedInCentral` for one
changed in central. Both are skipped with the reason.
**Test:** in a workshared model, have a colleague edit one tag, then stack a set
including it.

## 8. Elements visible in the view

**Relied on:** `FilteredElementCollector(doc, view.Id)` returns what the view
shows (respecting its view range, filters and hidden categories), and
`OwnedByView` returns its annotation. Linked models are read from their own
documents, which know nothing of the view's settings, so a linked element
hidden in the view still counts as an obstacle when links are switched on.

## 9. Speed

The search stops after 2 seconds per view (a setting). IronPython runs the
engine several times slower than the bench's CPython. On the bench, 20 tags
among 800 obstacles finish in about 2 seconds; collecting obstacles in a dense
view can add a few more. If a large selection feels slow, select fewer tags at
once or lower the search time.

## 10. Preview and Undo

**Relied on:** a `TransactionGroup` can be rolled back after its transaction has
committed, while a modal window is open, and `Assimilate` makes the whole run
one undo step named "RevoBIM Tag Tidy".
**Test:** run the tool, press Undo in the preview: every tag returns. Run it
again, press Keep, then Ctrl+Z once: every tag returns.

## 11. Auto theme follows Revit's canvas

**Relied on:** `UIThemeManager.CurrentCanvasTheme` (Revit 2024 and later)
reports the canvas theme; `UITheme.Dark` is 0, which the tool reads as dark,
never as a failed read.
**If wrong:** Auto paints dark, the house default.
**Test:** File > Options > Colors, set the canvas theme to Light, open Tag Tidy
Settings: the window should be light with the chip reading Auto. Set the
canvas back to Dark and reopen: dark.

## 12. Shrink to taskbar

**Relied on:** a `DispatcherTimer` ticks while a modal window is open (the
modal loop pumps the dispatcher), and a borderless window clips a body pinned
taller than itself.
**If wrong:** the drawer lands at once rather than sliding; it never leaves
the window half shut, and the bench proves that path.
**Test:** run Tag Tidy on a few tags, press the shrink button top right of the
preview: the window slides down leaving its header floating above the
taskbar, the button turns into a green up arrow, and the layout is visible in
the view behind it. Press the arrow (or Ctrl+Shift+H, Escape, Enter, F11, or
double click the bar): it opens where it was. Drag the parked bar up the
screen first and it opens upward from there. Then drag an edge of the window:
it must still resize. Repeat on a second monitor, including one above the
primary if you have one.

The preview is modal, because Keep and Undo hold a transaction group open, so
shrinking it shows the model but Revit stays locked until Keep, Undo or Try
the other side.

## 13. Debug report

**Test:** run the tool once, open `%APPDATA%\RevoBIM\tag_tidy_debug.txt`: it
should name the version, each view with its tag and obstacle counts, every
row of the preview and the settings. Untick the setting and run again: the
file is not rewritten.
