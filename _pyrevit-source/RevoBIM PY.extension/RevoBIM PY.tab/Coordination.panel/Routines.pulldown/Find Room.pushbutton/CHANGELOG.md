# Find Room - changelog

## 1.0.0 - 2026-10-19

- New tool in Coordination > Routines.
- Rooms / Spaces switch. Rooms come from this model or any loaded linked
  model (chosen from the Model dropdown, with room counts); spaces always come
  from this model, so the dropdown greys out.
- Rooms listed under their levels in elevation order, levels collapsible
  (click the level, or Expand all / Collapse all), keyword search on number,
  name and level, natural number order. Unplaced / not enclosed rooms hidden
  unless "Unplaced" is ticked.
- Picking a room lists the floor plans on its level (linked rooms matched to
  this model's levels by height, then name, then nearest) with type, scale,
  sheet and template, "Last used" and "Open now" badges, and a red note where
  the room sits outside the view's crop.
- Clicking a plan (or Enter / Go to view): Temporary View Properties on,
  Rooms + Color Fill + Interior Fill + Reference switched on (Spaces
  equivalents for spaces), the room coloured with a temporary solid fill
  (element override in this model, a "RevoBIM Find Room" rule filter for
  linked rooms), view opened and zoomed to the room. One undo step.
- Clear highlight (and, by default, closing the window) puts back exactly what
  was changed. Going to another room on the same plan only moves the colour.
- Double-click or Enter on a room goes straight to its first plan. A room
  selected in Revit before launch is picked for you.
- Modeless, owned by Revit; ExternalEvent queue with Pending handling and a
  watchdog. Theme chip top right: Auto (follows Revit's canvas) / Dark /
  Light. Version top right, full screen, resize grips, settings panel,
  debug report.
