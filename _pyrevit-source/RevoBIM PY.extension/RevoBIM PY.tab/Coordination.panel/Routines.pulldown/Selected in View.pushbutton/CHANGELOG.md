# Selected in View - changelog

## 1.1.0 - 2026-10-09
- All tags now sit under one Tags heading at the top of the list.
- Under it, one row per tag FAMILY (e.g. BGL_Pipe Tag), expanding into that
  family's types. Ticking the family ticks every type; the Tags heading
  ticks every tag family. A family used across several tag categories is one
  row; its tooltip lists the categories.
- Filter follows the family: an unseen type follows its family, an unseen
  tag family is kept unless every tag is off (and Refresh turns orange).

## 1.0.0 - 2026-10-09
- New tool in Coordination > Routines.
- Modeless window owned by Revit: stays in front, Revit stays usable.
- Lists every selectable category in the active view, grouped Model /
  Annotation / Tags, coloured by discipline, with element counts.
- No Apply: while open, `UIApplication.SelectionChanged` takes unticked
  categories straight back out of each selection (click, window, Tab, Ctrl).
- All / None at the top, default all on. Section ticks for each group.
- Linked models and Pinned elements buttons: green pickable, red filtered.
  Linked covers Revit links, linked CAD and point clouds.
- Tags split into their family types; ticking the tag category ticks all,
  part-ticked shows a dash.
- Changing view re-reads the list (ViewActivated); ticks carry across views.
  Refresh turns orange when a pick meets a category the list has not seen.
- Search box, Auto / Dark / Light theme chip following the Revit canvas,
  version top right, full screen, resize grips, debug log + Copy debug.
