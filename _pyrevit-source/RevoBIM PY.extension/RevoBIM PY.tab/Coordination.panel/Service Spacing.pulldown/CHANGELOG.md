# Service Spacing — changelog

## 1.2.0

- **Trunking has its own clear gap, 70mm**, applied against anything else it
  sits beside. A cable tray counts as trunking when its **family name**
  carries the token `Trunking` — the token, the gap and whether it beats the
  cable tray gap are all settings. Family name, type name and the type's own
  family name are all read, and `Trunking` / `TrunkingTray` / `Trunking Tray`
  all resolve to the same token.
- **Rows.** Where part of the selection sits at a different level — more than
  **60mm** clear, top edge to bottom edge — it is treated as its own row and
  spaced on its own string rather than against the row below. Rows are
  reported and numbered in the results.
- Optional **vertical spacing between rows** (off by default): rows are
  cleared bottom row held, on the widest gap any pair across the two rows is
  entitled to.
- Results table gains Row and Lift columns and names which gap governed each
  pair.
- Bench check now rejects a `FindName` with no matching `x:Name` and a layout
  that is not well-formed XML.

## 1.1.0

- **Service clear gap now defaults to 75mm edge to edge**, up from 25mm. The
  cable tray gap is unchanged at 50mm.
- `settings_version` bumped to 2 with a migration that resets `gap_services`,
  so a file saved at 25mm picks the new default up rather than quietly
  carrying on at the old figure.
- Note that with "a service beside a cable tray" left at its default — the
  larger of the two gaps — a pipe next to a tray now takes the 75mm service
  gap rather than the 50mm tray gap.

## 1.0.0

First release.

- Pulldown on the **RevoBIM PY** tab, **Coordination** panel, holding
  **RevoBIM Service Spacing** (the command) and **RevoBIM Service Spacing
  Settings**.
- Centre-to-centre spacing on the minimum clearance rule:
  `(w1 / 2) + (w2 / 2) + clear gap + insulation`, rounded up to the nearest
  5mm. Defaults: 25mm clear between services, 50mm where a cable tray is
  involved, so trays come out 50mm edge to edge on the same calculation.
- Runs off the current selection with no window and no prompts. With nothing
  selected it asks for the services with `PickObjects` and Return finishes the
  pick.
- Widths are measured from the solids' own edge endpoints projected onto the
  spacing axis, so a rotated tray or an angled run is measured correctly
  rather than inflated by an axis-aligned bounding box. Parameters and then
  the bounding box stand in where there is no geometry.
- Insulation and lining are read as separate elements via
  `InsulationLiningBase.GetInsulationIds` and added to the half extent.
- The spacing axis is square to the dominant run direction in plan; vertical
  (stacked bank) is a setting.
- Connected fittings and inline segments travel with each service; the walk
  stops at anything that turns off the run.
- One transaction with a failure preprocessor, plus a `DialogBoxShowing`
  handler, so a refusal rolls back clean and Revit's own dialogs stay out of
  the way.
- Results reported in a themed window, by default only when something needs a
  look.
- `import_check.py` ships with the tool.
