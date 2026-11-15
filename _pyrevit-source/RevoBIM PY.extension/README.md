# RevoBIM PY — Place BWIC Horizontal

pyRevit tool that places `BGL_BWIC_Penetration_Horizontal_Rectangular-Dynamic`
around a set of services and aligns it to a wall picked in a linked model.

Tested against Revit 2024 / pyRevit 2.7.x (IronPython 2.7 engine).

## Install

Copy the `RevoBIM PY.extension` folder into your pyRevit extensions folder,
then **pyRevit → Reload**:

```
%APPDATA%\pyRevit\Extensions\RevoBIM PY.extension
```

The button lands on the **RevoBIM PY** tab, **BWIC Tools** panel. If that panel
already exists, copy only the `Place BWIC.pushbutton` folder into it.

## The window

Two tabs — **Wall** and **Slab** — with a settings gear at the top right beside
the version and close button.

### Slab tab

Select the services, press Return to finish the selection, then click the
floor. The opening is placed at the centre of the selection and sized in plan:

| | |
|---|---|
| Length / Width | Extent of the selection in plan + clearance each side, rounded up to 5mm |
| Position | Centre of the selection |
| Base level | The floor's own level |
| Base offset | Floor depth + your figure (50mm default) |
| Top level | The same level |
| Top offset | Base + your figure (100mm default) |

Clearance and both offsets are on the tab itself, so they can be changed per
run. The family is chosen in Settings.

**Floor based families** can only be hosted on a floor in the current model —
Revit will not host anything on a linked floor. Where the floor is linked the
opening is placed unhosted at the correct level and offsets, and the status box
says so.

### Settings

Behind the gear, split the same way:

**Wall** — family name, the three size parameters, default clearance, round up
step, and the family types used for blockwork and fire rated walls. These were
constants in the script before; the behaviour is unchanged.

**Slab** — two placement rules, shown one at a time:

*Two levels* for a family with Base Level, Top Level and offsets. *Single
level* for a non face based family: it goes on the **nearest level**, its
vertical height parameter is set to the floor thickness, and its top height
parameter is set from the floor top. Every parameter is a dropdown read off
the chosen family.

The plan sizing is yours to set — which parameter is the width, which is the
depth, the clearance each side and the round up step — independent of the wall
tool.

Also: family kind (floor based or regular, defaulting to floor based), the
generic model family and type, Length and Width parameters, the base and top
level and offset parameter names, and the default clearance. Leave the level
and offset parameter names blank to use Revit's own Base Level, Top Level and
offsets.

## The Wall tab

Pressing the ribbon button opens a modeless, frameless window headed
**RevoBIM BWIC Placement** (RevoBIM in blue), with the builders work hole icon
to the left of the heading. The palette follows Revit's own dark theme —
`#3B3B3B` shell, `#454545` panels, `#353535` canvas, `#2E2E2E` fields. There is
no system title bar — drag the heading to move the window, and close it with
the X at the top right or the Close button. It stays open while you navigate
the model, so you can keep adding penetrations without
re-running the tool.

| Control | Notes |
|---|---|
| Clearance | Added to every side of the opening. Defaults to 50mm, type any value. |
| Workset | Dropdown of every user workset in the model. Remembered between runs. |
| Also pick services from linked models | Off by default. Adds a second pick step. |
| Level parameter | Dropdown of the writable parameters the family can carry. Defaults to `BHE_Level`, or the first parameter with "Level" in its name if that is absent. Pick the top entry to skip the step. |
| Keep this window on top | On by default. |
| Log the selected services to Comments | On by default. |
| Place on the first workset named \*BWIC\* | On by default. |
| Pin the services and the placed BWIC | **Off** by default. Linked services are never pinned. |
| **Place BWIC** (red) | Hands focus to Revit and starts the placement loop. |
| **Resize existing BWIC from selection** (orange) | Re-fits an existing BWIC to a fresh selection. |

## How services are measured

Straight runs are measured from their real edges rather than their bounding
box: duct width and height, pipe and conduit outside diameter, cable tray width
and height, with insulation thickness added where present. This matters for any
run at an angle in plan — a 600×400 duct running at 45° has a bounding box
1.4× wider than the duct, and sizing off that would oversize the opening by
several hundred millimetres.

Fittings, accessories and equipment have no single cross section, so they are
measured from their **real solid geometry** instead — edge points off the
actual solids. A conduit bend or duct elbow sits at an angle by definition, so
its bounding box overstates the envelope; the solids give the true extent. Only
if the geometry cannot be read at all does it fall back to the bounding box.

### What can be selected

Pipes, flex pipe, ducts, flex duct, cable tray, conduit, and **all of their
fittings and accessories** — conduit fittings, pipe fittings, duct fittings,
tray fittings — plus air terminals, sprinklers, mechanical, electrical and
plumbing fixtures, equipment and generic models. Anything outside that list is
ignored by the picker, so a stray click on a wall or floor cannot end up
sizing the opening. The list is `SERVICE_CATEGORY_NAMES` at the top of the
script.

## Linked services

With **Also pick services from linked models** ticked, a second pick step
follows the host selection. Pick services in any loaded link, then Finish; Esc
skips the step. Their geometry is transformed into host coordinates, so they
contribute to width, height and elevation exactly as host services do, and they
appear in the Comments log. They are never pinned — you cannot modify a linked
element.

## Settings

Remembered between runs in
`%APPDATA%\RevoBIM PY\place_bwic_settings.txt`: workset, clearance, level
parameter and the linked-services option. It is a plain key=value file, safe to
hand edit. A missing or damaged file falls back to the defaults key by key.

## The placement loop

1. Press **Place BWIC**. Revit comes to the front.
2. Select the services and press Finish. (If elements were already selected
   when you pressed the button, that selection is used.)
3. Pick the wall in the linked model. Only walls in links are selectable.
4. The BWIC is placed, and the tool immediately asks for the next set of
   services — carry on in another area.
5. **Escape** at any prompt ends the loop and brings the RevoBIM window back
   to the front, with a summary in the status box.

## Resizing an existing BWIC

Press **Resize existing BWIC from selection** and the loop runs:

1. Pick the BWIC. Only instances of the BWIC family are selectable. If you had
   exactly one selected before pressing the button, this step is skipped.
2. Select the services passing through it, then press Return.
3. Pick the wall.

The instance is resized and repositioned in X, Y and Z to exactly the same
rules as a new placement, and its level, level code, workset and Comments are
re-stamped. The wall kind is re-evaluated too, so a BWIC that has ended up on a
blockwork or fire rated wall picks up the right family type. A pinned BWIC is
unpinned for the move and pinned again afterwards.

Like placing, it loops until Escape, so several openings can be corrected in
one go.

## What each placement does

| | |
|---|---|
| Alignment | The instance is rotated so its facing (Front/Back) direction matches the wall normal, i.e. `BGL_Length` runs through the wall, and it sits on the wall centre line in plan. Curved walls are handled. |
| `BGL_Length` | Wall thickness, read from the linked wall type. |
| `BGL_Width` | Extent of the selection measured along the wall, + clearance each side, rounded up to the nearest 5mm. |
| `BGL_Height` | Vertical extent of the selection, + clearance each side, rounded up to the nearest 5mm. |
| Elevation | Midway between the bottom of the lowest service and the top of the highest, so the opening encompasses the whole selection centrally. |
| Level | The level the BWIC sits on, or the nearest one beneath it. Checked against the final position and corrected if the placement left it elsewhere. |
| Level code | Two digit code for that level, written to the chosen parameter. |
| Workset | First user workset whose name contains `BWIC`, alphabetically. |
| Pinning | Every service used for the placement, and the BWIC itself. |
| Comments | Family and type of every service in the selection. |

### Level

**In a plan view the BWIC goes on that view's level**, whichever floor plan,
ceiling plan, structural plan or area plan you are working in. In a 3D view,
section or elevation there is no view level, so it falls back to the nearest
level at or below the opening.

After it is positioned the association is read back from whichever level
parameter the family exposes (`Level`, `Schedule Level`, `Reference Level` —
the set varies by Revit release) and, if it does not match, written to **every**
writable one — setting only the first that accepts it let Schedule Level take
the new level while the real Level parameter stayed put, which is what made
instances read as the lowest level in the model. Changing the level re-bases the offset, so the instance is
nudged back onto its target elevation afterwards.

If none of those parameters is writable the instance keeps the level it was
created on and the status box says so.

### Level code

| Level name | Code |
|---|---|
| `Level 00` | `00` |
| `Level 01` | `01` |
| `Level 04` | `04` |
| `Roof`, `Main Roof`, `LRF` | `RF` |
| any other name with a number | those digits, padded to two |
| a name with no number at all | position counting up from the lowest |

The keyword table is `LEVEL_CODE_RULES` at the top of the script. The code is
derived from the level the instance actually ended up associated with, not the
one picked before placement.

Because `RF` is text, the target parameter needs to be a text parameter —

an integer or number parameter will take `04` but not `RF`, and the status box
reports it if that happens.

### Family type per wall

The linked wall's **Type Name** decides which family type is placed. Rules are
tested in order and the first match wins:

| Wall | Test | Family type |
|---|---|---|
| Fire rated | Type Name contains `FR` or `FIRE`, or the wall type carries a Fire Rating value | `BWIC - Fire Rated Wall` |
| Blockwork | Type Name contains `BLK` | `BWIC - Blockwork` |
| Anything else | — | the family's default type |

Fire rated is tested first, so a wall that is both blockwork and fire rated
comes out fire rated. Swap the entries in `WALL_RULES` if your standard says
otherwise.

Keywords match as whole words, so `BLK` does not fire on `BLOCKING` and `FR`
does not fire on `FRAME`. Separators like `-` and `_` still count as word
breaks, so `WAL-BLK-140` and `BLK_215` both match.

If the rule's family type is not loaded, the default type is placed and the
status box says so rather than skipping the wall.

### Workset

Only applies to workshared models. If nothing matches `BWIC` the instance lands
on the active workset and the status box says so. Change `WORKSET_KEYWORD` in
`script.py` to match a different naming standard.

### Pinning

The services are pinned as they are consumed, and the BWIC is pinned last so
nothing else in the routine has to work around a locked element. Elements that
cannot be pinned are skipped silently and the count in the status line reflects
what actually took.

### Comments format

The elements you selected before placement are logged — not whatever happens to
sit inside the finished opening. Entries are `Family: Type`, quantified when the
same family and type appears more than once, delimited by `_`:

```
Pipe Types: Standard x3_Duct Types: Mitred Elbows / Taps x2_Cable Tray: Ladder
```

System families report their category in place of a family name, which is how
Revit names them. Loadable families report the real family name.

## Settings

Top of `script.py`:

| Constant | Default |
|---|---|
| `FAMILY_NAME` | `BGL_BWIC_Penetration_Horizontal_Rectangular-Dynamic` |
| `P_LENGTH` / `P_WIDTH` / `P_HEIGHT` | `BGL_Length` / `BGL_Width` / `BGL_Height` |
| `DEFAULT_CLEARANCE_MM` | `50.0` — the value the window opens with |
| `ELEVATION_MODE` | `'extents_centre'`, or `'highest_service'` to sit on the highest service's centre line instead |
| `ORIGIN_VERTICAL` | `'centre'`, or `'bottom'` / `'top'` if the family origin is not mid-box |
| `QTY_DELIMITER` | `'_'` |
| `ROUND_UP_MM` | `5.0` — width and height round up to this step |
| `SUPPRESS_MESSAGES` | `True` — no pyRevit console, no Revit warning dialogs |
| `WORKSET_KEYWORD` | `'BWIC'` |
| `WALL_RULES` | fire rated then blockwork — keywords, fire rating test and family type per wall |
| `LEVEL_PARAM_NAME` | `'BHE_Level'` — the dropdown default |
| `LEVEL_CODE_RULES` | `ROOF` and `RF` → `RF` |
| `LEVEL_PARAM_KEYWORD` | `'Level'` — the fallback search term |
| `DUPLICATE_TYPE_IF_TYPE_PARAMS` | `True` — duplicates the type per size if `BGL_*` are type parameters |

## Notes

* The script sets `__persistentengine__ = True`, which pyRevit needs for
  modeless windows. Reload pyRevit if you edit the script while the window is
  open.
* The run is silent: pyRevit's logger is in quiet mode, the output console is
  closed if anything opens it, and Revit's own warning dialogs are cleared by a
  failure preprocessor on the transaction. Everything worth knowing goes to the
  status box in the window instead. Set `SUPPRESS_MESSAGES = False` to get the
  messages back while debugging.
* The window will look frozen while Revit is waiting for you to pick — that is
  normal, the external event holds the UI thread during picking.
* The family is assumed to be a non-hosted point-based generic model. Face
  based or work-plane based versions need a different placement call.
