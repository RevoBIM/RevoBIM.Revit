# Hanger Automation changelog

## 1.15.0
- **Hangers now record what they carry in Comments.** Every hanger placed writes the family and type of the service(s) it goes round into its *Comments* parameter. This covers FAB hangers, Family Hangers, Family Floor Supports, circular hangers and supports, whether placed with Place or Auto place.
  - One service: `Pipe Types : Copper`.
  - A shared hanger: each service, separated by a comma, in the order met: `Cable Tray with Fittings : Ladder, Pipe Types : Copper`.
  - Repeats of the same family and type are counted: `2xPipe Types : Copper`.
  - FAB services are written as their service and part name, e.g. `Rect Supply : Straight`. A FAB hanger re-hosted with Rehost also gets its new host written.
  - Comments are overwritten each time. The debug log shows what was written.
- Bench: bench_revit 258 checks; bench_logic 156 checks.

## 1.14.1
- **Circular hangers now go on the service centreline.** When a hanger family is set up as *Circular System Based*, its reference goes on the centreline of the pipe, round duct or round FAB duct where it hangs, no longer at the invert.
  - Its offset is set to the service centre at that point, so on a sloping pipe each hanger follows the fall.
  - The drop rod (when ticked) runs from the centreline up to the level or structure above.
  - The diameter, X / Y turn, locks, worksets and dimensions are as before.
  - The ring check after placing now expects the family's reference level to run through the ring centre, and says how far off it is if not.
- Rectangular Hanger System hangers and both kinds of floor support are unchanged.
- Bench: a round FAB duct; bench_revit 254 checks / 122 breakages; bench_logic 153 checks.

## 1.14.0
- **Family list you can stretch.** A small grip under the family list on both family tabs drags it down to show more families, or up to show fewer (60 to 700 px). The window grows with it, like opening a tool. Each tab remembers its own height.
- **Families already set up stand out.** In the family list, every family saved in Family settings is in **bold green**: dark green in the light theme, and a lighter green in the dark theme so it can be read on the dark background. The selected row goes back to the normal text colour so it reads on the selection highlight. The list refreshes as soon as you save a family.
- **Set up only** tick next to the search box on both family tabs: lists only the families already set up. It is remembered per tab.
- **Circular hangers on the Family Hangers tab.** Family settings for hangers now has the same two tabs as floor supports: **Rectangular Hanger System** (the existing hanger settings, unchanged) and **Circular System Based**.
  - The circular tab sets the *Hanger diameter* parameter (default `BIM_DIM_Diameter`), which way the service runs along the family (X / Y), the *Drop rod length* parameter and where the rod goes up to.
  - A circular hanger is placed like a rectangular one: on the service's level with its reference at the service invert, turned to the axis chosen, and its drop rod run up to the level or structure above when ticked. The difference is that the diameter takes the pipe or round duct's diameter (insulated when ticked) in place of the two widths.
  - Place, Re-align, Auto place, locks, worksets and dimensions all work for circular hangers. Each hanger goes round one service, and rectangular ducts and trays are skipped and named in the results.
  - After placing, the ring is checked against the pipe centre. If it's off, the results say how far above or below, without moving it, so you can see whether the family's reference sits at the ring's underside.
- Rectangular Hanger System hangers and both kinds of floor support are placed exactly as in 1.13.0. The circular hangers run in the separate circular module, never through the rectangular one.
- Bench: bench_revit 253 checks / 121 breakages; bench_logic 152 checks.

## 1.13.0
- **Circular System Based supports now follow your updated family.** The family is placed at its reference level and *BIM_Hanger_Support_Height* runs up to the ring centre, so the tool now places it the same way as the rectangular supports:
  - It goes on the service's level, or on the floor / roof / equipment picked under *Supports stand on* (hosted on the level, offset up to the top surface).
  - It sits at the service centreline, turned so the service runs along the X / Y set in Family settings.
  - *BIM_Hanger_Support_Height* = from the base up to the **intersecting midpoint**: the service centre where that support stands. On a sloping pipe each support gets its own height.
  - *BIM_DIM_Diameter* = the service diameter, insulated when *Support outside insulation* is ticked.
  - This replaces 1.12's "+ half the diameter" rule and its automatic height correction.
- **The ring is still checked, never moved.** After placing, the tool finds the ring in the placed support. If it isn't on the service centre (within 1 mm), the results say how far above or below it came out, so a family change shows up straight away. The debug log gives the ring's position for every support.
- Family settings' Circular System Based note describes the new rule.
- Rectangular supports and hangers are unchanged.
- Bench: bench_revit 241 checks; bench_logic 152 checks.

## 1.12.1
- **A placement Revit throws away no longer breaks the next one.** When Revit undid a support's transaction with an error, the bottom-lock section made inside it went too. The tool still held on to it, so the next click failed with "The referenced object is not valid". A lock section that no longer exists is now made again. This bug dates from 1.5.2.
- **The log now says when Revit undoes a placement, and why.** It prints Revit's error text (for example a family that can't be built at the sizes given) instead of a silent failure. This covers every tab.
- No change to how rectangular supports, hangers or circular supports are sized or placed.
- Bench: bench_revit 241 checks / 113 breakages.

## 1.12.0
- **Rectangular supports and hangers are back to 1.10.2.** `hfam_revit.py` is the 1.10.2 file again, word for word, so placing, re-aligning, auto placing, rods, locks and dimensions for Family Hangers and Rectangular Floor Based supports work exactly as they did before the circular work. Their settings and Family settings rows are unchanged.
- **Circular System Based supports have their own path** (`hcirc_revit.py`, `hcirc_core.py`). The Family Floor Support tab only uses it when the chosen family is saved as *Circular System Based* in Family settings; any other family runs the rectangular tools as before.
- **The ring is now measured and centred on the pipe.** After placing, the tool reads the ring's own round faces in the placed support and moves *BIM_Hanger_Support_Height* until the ring centre is on the pipe centre, within 1 mm.
  - It starts from your rule: the drop from the pipe centre to the base, plus half the diameter.
  - It is right whichever end of the ring the family's height parameter actually runs to (the bottom, the middle or the top).
  - Heights still follow a sloping pipe, support by support.
  - If the ring doesn't move with the height parameter, or faces across the pipe, the results say so (check the parameter, or switch X / Y in Family settings).
  - The debug log shows the support's base point, every height tried and where the ring ended up.
- Place, Re-align, Auto place, locks, worksets, the base pick and run dimensions all work for circular supports through the new path. The Dimension placer reads a circular support by the way its pipe runs.
- *Set up the family first* (with Ignore) and the two Family settings tabs are unchanged.
- Bench: bench_revit 240 checks / 111 breakages (the ring centred with the height running to its bottom, centre or top, on a sloping run and after re-align; the tab sends circular families to their own jobs and rectangular ones to theirs); bench_logic 156 checks; import_check 30 rules, including a new one that the rectangular files never reach into the circular path.

## 1.11.1
- **Circular System Based: the ring now sits centred on the pipe.** In 1.11.0 the support height was set to the full drop from the pipe centre to the base. The family's *BIM_Hanger_Support_Height* runs to the edge of the ring, so the ring did not line up with the pipe.
  - The support height is now the drop from the service centre **at that support** down to what it stands on (the level, or the picked floor / roof / equipment top), **plus half of BIM_DIM_Diameter**.
  - The centre is taken where the support stands, so on a sloping pipe each support's height follows the fall.
  - The log shows the centre, the drop and the half diameter for every support.
  - The *Support height measured to* option is gone - the ring is always centred on the service.
- Bench: a 1:100 sloping pipe run; bench_revit 233 checks / 109 breakages.

## 1.11.0
- **Two kinds of floor support family.** On the Family Floor Support tab, Family settings now has two tabs: **Rectangular Floor Based** (the frame family, as before) and **Circular System Based** (new). The tab showing when you Save is the kind the family is saved as.
- **Circular System Based** settings:
  - *Hanger diameter* parameter (default `BIM_DIM_Diameter`, else guessed from a name with "diameter");
  - *Support height* parameter (default `BIM_Hanger_Support_Height`);
  - which family axis the service runs along (X / Y);
  - whether the height is measured to the service centre (default) or its underside.
- **What placing a circular support does:**
  - It goes at the centre of the pipe or round duct you pick, turned so the service runs along the chosen axis.
  - It stands on whatever *Supports stand on* says - the level, or the picked floor, roof or equipment (hosted on the level, offset up to it).
  - The diameter parameter takes the service's diameter, insulated when *Support outside insulation* is ticked.
  - The support height runs from the base up to the service.
  - Place, Re-align and Auto place all work this way. Align-lock, dimensions and worksets are as before.
  - Each service gets its own ring: no shared supports. Rectangular ducts, cable trays and units are skipped and named in the results.
- **Families not yet set up:** pressing a tool with a family that has never been saved in Family settings now asks *Set up the family first*. **Set up the family** opens its Family settings; **Ignore and carry on** runs with the parameters guessed from their names and is not asked again this session. The selected family's line under the list says *not set up yet* until it is. This applies to both family tabs.
- Bench: bench_revit 232 checks / 108 breakages; bench_logic 147 checks.

## 1.10.2
- **Run dimensions that did not appear.** A chain dimension is refused by Revit when it can't see one of its references in that view - a duct end outside the view range or crop, say - and the failure was silent.
  - The document is now regenerated before dimensioning, so hangers placed in the same run have geometry another view can reference.
  - If the full chain (run ends and hangers) is refused, it is tried again on the hangers alone.
  - In a plan the dimension line sits on the view's level.
  - Every reason a run gets no dimension is logged: no reference on a hanger, too few references, Revit's refusal for each try.
  - This applies to Family Hangers, Family Floor Support and FAB Hangers.
- **Auto place has its own dimension settings:** *Distance from hangers / supports* and *Type* sit under *Dimension each run*, below a subtle divider. They are the same settings as the Dimension placer's, kept in step, and each tab has its own.
- **Dimension views window** opens on **Views**, filtered to **Floor plans**. The filter also offers All plans, Sections and elevations, and All.
- **One tool open at a time:** opening a tool folds whichever other tool is open. Expand all still opens every one.
- **The chosen family's preview shows when the tool opens,** on both family tabs. It is read straight away while the window is built, instead of being queued, where the second tab's read used to be refused and left on "No preview". A later read Revit could not start is retried when it is free.
- Bench: bench_revit 216 checks / 101 breakages.

## 1.10.1
- **Floor supports on a picked element: a prompt before the pick.** Before, after Apply in the Dimension views window (or on pressing Place / Re-align / Auto place), the tool went straight into the pick. The only hint was Revit's status bar, so it looked as if it had hung.
  - It now asks first: *Now click the floor, roof or equipment the supports stand on*, with **Pick it in Revit** / **Stand on the level** (the X stands them on the level too). It says when to click the link first.
  - Esc during the pick still stands them on the level.
- Bench: bench_revit 210 checks / 95 breakages.

## 1.10.0
- **Escape never closes the tool.** It is pressed to leave Revit picks; the window now ignores it. While the window is shrunk, Escape, Enter and F11 open it again.
- **Auto place from a 3D view with *Dimension each run* ticked** (Family Hangers, Family Floor Support and FAB Hangers):
  - First you are asked where the run dimensions go: **No - skip dimension placement**, or **Choose views...**.
  - **Choose views** opens a *Dimension views* window with **Sheets** and **Views** tabs:
    - the house search (every word, any order) on each;
    - a plans / sections filter on Views;
    - tick boxes, with highlight-and-tick (tick one highlighted row and every highlighted row follows);
    - *Tick shown* / *Untick shown*;
    - a running count.
  - **Apply** (bottom right) closes it and the tool runs. Dimensions go in every ticked view and every plan or section on every ticked sheet.
  - **In a section** the dimension line lies in the section's plane, below the run. A section the run does not lie along is left out and logged.
  - **When done** it asks whether to open the views, or the sheets, with the dimensions, and opens them.
  - In a plan or section nothing changes: dimensions go in the active view as before.
- **The family tabs' dimensions now use their own settings:** *Distance from hangers* (fam_dim_offset) and *Type*. Before, they used the FAB tab's offset and Revit's default type.
- **Shrink to the taskbar on every window,** per the RevoBIM theme reference: the main window, Family settings, Hanger rules, the new prompts and the Dimension views window.
  - **Dialogs:** shrinking a dialog parks the main window beneath it, and both come back together, including when the dialog closes. A dialog opened while the window is parked opens centred on the screen.
  - **Keys:** Ctrl+Shift+H toggles any window.
  - **The slide:** the body is pinned during it, so it is clipped rather than squashed. MinHeight and SizeToContent are relaxed and put back. The grips park with the window. The animation is released when it lands, and the window lands at once if it can't animate. The parking arithmetic is in fha_core and benched, including a monitor above the primary.
- **Dark theme on the RevoBIM theme reference's Revit palette:**
  - body #3C4454, fields #2D3441, cards #323C48, title bar #222933;
  - selection #3A7392, hover #444E5E, edge #515C6B;
  - accents lifted so every text pairing clears 4.5:1: blue #72BAF0, orange #F2A452, muted #ABB3BF;
  - dark text on green and blue buttons.
- Bench:
  - bench_revit 207 checks / 94 breakages;
  - bench_logic 140 checks / 8 breakages;
  - import_check: every window has a drawer and a green expand arrow, the drawer releases its animation, and Escape never closes.

## 1.9.0
- **Family Floor Support: stand on a picked element.** The new *Supports stand on* row (under the workset row) offers *The service's level* (as before) or *A floor, roof or equipment I pick (here or in a link)*.
- **When you start a tool:** with the second choice, Place, Re-align and Auto place first ask you to click the floor, roof or mechanical equipment. Click a linked model and you then click the element inside it; tick *It is in a linked model* to go straight there. Esc stands them on the level.
- **Height:** each support stays hosted on the same level. Its *Elevation from Level / Offset from Host* lifts the base onto the element's top surface, found by a ray straight down from the support's centre (links included).
  - **On a slope:** it stands where the centre meets the surface. The log gives the height under each post and how far the surface falls across the frame.
  - **Centre off the surface:** it stands on the surface's edge, at the highest hit under a post.
  - **No face hit:** it uses the top of the element's box if the support is over it.
  - **Not under the support (or above the service):** that support stands on its level, and the results say so.
- **Parameters follow the base:** the *First Bar Offset* is measured from the base, so the bottom bar still meets the service invert. The *Support Height* is unchanged.
- Bench: bench_revit 174 checks / 81 breakages (fake rays down onto host and linked floors, a sloped roof, a surface edge).

## 1.8.1
- **Dark theme matches Revit's dark theme.** The greys are taken from Revit's own Project Browser:
  - window #3C4454;
  - title bar, tab bar and footer #212932;
  - fields and lists #2D3441;
  - cards #343C4A;
  - text #E8F0F8.
- Edges, hover, selection, muted and disabled text are toned to sit on those. The RevoBIM blue, orange, green and red accents are unchanged. Light theme unchanged.
- import_check: rule_theme_defaults_dark, so Theme.xaml's first-paint colours always equal the dark palette.

## 1.8.0
- **Shrink to the taskbar** (new button top right, before Full screen) so you can see Revit:
  - the window slides down like a drawer closing, to just above the taskbar, leaving only its title bar floating;
  - the button turns into a **green up arrow**; press it (or double-click the bar) to slide the window back up to where it was;
  - if you drag the bar somewhere first, the window grows up from there, kept on screen;
  - while shrunk the bar can still be dragged, the theme chip still works, and the window doesn't resize itself;
  - Full screen and F11 open it again first.
- Bench: bench_revit 165 checks / 75 breakages; import_check rule_shrink_button.

## 1.7.1
- **Place on service: one hanger round the whole selection.** Select several services, press Pick and place, then click on one of them where the hanger goes. One hanger goes round every selected service:
  - centred on the mean of their centres;
  - stretched to the outer edges either side;
  - at the lowest invert (a floor support stands there, as tall as the tallest).
- **Selection overrides the Hanger rules:** the gap and height limits no longer apply on Place; you chose the services. A selected service that isn't parallel to the clicked one, or doesn't run alongside it where you clicked, is left out and named in the results.
- Keep clicking to place more combined hangers along the same services; Esc finishes.
- Auto place and Re-align still group services by the Hanger rules.
- Bench: bench_revit 157 checks / 70 breakages.

## 1.7.0
- **Workset for placed and edited hangers** on every tab (FAB Hangers, Family Hangers, Family Floor Support): a row at the top of each tab, saved per tab.
  - **Leave as is** (default, the old behaviour): new hangers go on their service's workset; a replaced FAB hanger keeps the old one's workset; edited hangers stay where they are.
  - **Same as the service:** new and edited hangers go on the workset of the service they hang from.
  - **Active workset:** new and edited hangers go on the active workset.
  - **A named workset** from the model: new and edited hangers go there.
- **What counts as placed:** FAB Auto place, FAB rehost (replace), Family Place and Auto place, and floor supports.
- **What counts as edited:** FAB rehost (move), FAB extend to structure, Family Re-align and the Drop rod extender.
- **Problems are reported:** a hanger Revit won't move (owned by someone else) is reported in the results, and the rest of the work still happens. A saved workset name that isn't in this model is shown as "(not in this model)" and reported; new hangers then go on their service's workset.
- The setting does nothing in a model that isn't workshared.
- Bench: bench_revit 153 checks / 69 breakages (fake worksets, workset table and workset parameter); bench_logic 123 checks.

## 1.6.0
- **Family Floor Support tab built.** It is the Family Hangers tab without the Drop rod extender: family picker, Family settings, Support rules, and Place / Re-align / Auto place / Dimension placer. The tools start collapsed, with insulation and align-lock ticks on each.
- **Placement differs from hangers:**
  - The support stands on the service's level with an offset of 0. If that level is above the service, it stands on the highest level below the invert.
  - The **first bar offset** is set to the service invert above that level.
  - The **support height** is set to the service depth, plus a clearance above.
  - **Insulation:** with *Support outside insulation* ticked, the first bar drops by the thickness and the height and widths grow by twice the thickness.
  - **Widths and centring** are the same as the hangers. A shared support is centred on the mean of the service centres, stretched to the outer edges, and as tall as the span from the lowest bottom to the highest top.
  - **Align-lock** is the same as the hangers: the centre plane to the centreline, and the bottom bar's top to the service bottom face.
- **Family settings** for floor supports: first bar offset parameter (default *First Bar Offset*), support height parameter (default *BIM_Hanger_Support_Height*), and clearance above the service. Both parameters are guessed from the family's names if the defaults aren't there. The drop rod rows are hidden on this tab.
- **Settings:** the floor tab keeps its own settings (flr_*). The grouping rules are shared with Family Hangers.
- **Auto place:** existing supports standing on the floor still count as "already there" on later runs, however far below the service they stand.
- **One layout for both tabs:** the floor panel is built from the Family Hangers panel by build_floor_panel.py, so improvements to the hanger tab carry across. import_check fails if the two drift apart.
- **Fixed:** a missing width parameter was only reported for shared hangers; it is now reported for every hanger.
- Bench:
  - bench_revit 143 checks / 62 breakages; bench_logic 118 checks;
  - import_check: two new rules (floor panel in sync, every control has its floor twin).

## 1.5.3
- **Family Hangers tools start folded.** Every tool on the tab opens collapsed each time the window opens; click a tool's header to open it, or Expand all.
- **New tab: Family Floor Support** (green floor-stand icon). A placeholder while the family is developed - it shows an "in development" card only.
- Bench: bench_revit 122 checks (floor tab, folded start), import_check checks the new tab can scroll.

## 1.5.2
- **Align-lock fixed.** In the 1.5.1 test every centre lock failed with "the family has no centre reference plane along the run": BGL_HAN_Base Hangar Dynamic has no plane set to *Center (Front/Back)*.
  - Every reference plane the hanger family offers is now tried: both centre planes, Strong, Weak, then the sides. Revit only accepts a pair that already coincides, so the first one accepted is the centre plane.
  - The first lock in a run logs the family's reference planes by name.
  - If none lines up, the result says which plane to set to *Is Reference* in the family editor.
- **Round services no longer get a lock section.** A lone service among selected ones went through the shared-hanger code and lost its round flag. Every round duct then got a new section and "no flat bottom face found".
  - A service that nothing joins now keeps its own section: round flag, depth, insulation.
  - Round services lock to the centre only, logged as information rather than a problem.
- **Lock sections reused.** "Hanger Automation - bottom locks …" is looked up by name before one is made, so later runs no longer leave "(1)" copies. Copies made by 1.5.0 / 1.5.1 can be deleted, but their locks go with them.
- **Bottom lock is sturdier.**
  - The service's bottom face is read from model geometry.
  - The hanger side tries its faces at the invert, then its Bottom / Top / Center (Elevation) / Strong / Weak planes.
  - A failure lists the heights of the hanger's flat faces.
- **Auto place: hangers by a bend no longer knock out the next leg.** A hanger 600 mm from a bend was read as sitting at the start of the leg round the bend. That leg's first hanger was dropped, and a short leg lost all of them.
  - A hanger now has to sit truly on the span to count.
  - The "placed this run" memory only holds shared hangers, checked against their own services.
- **Place hanger under a unit.** Click mechanical equipment or a duct accessory:
  - the hanger goes at its bottom face, centred across it, where you clicked along it;
  - it is stretched to the unit's width across;
  - the unit runs along its in-line connectors, else along its longer side;
  - it is locked to the unit's centre plane and bottom face.
- Bench:
  - bench_revit has 122 checks and 52 breakages. Fake references now carry geometry and the fake NewAlignment refuses pairs that don't coincide. New fakes: Strong-only and no-reference families, and units.
  - bench_logic has 113 checks.

## 1.5.1
- **Shared hangers came out mirrored.** A shared hanger reaches further one way than the other. 1.5.0 guessed which of the family's two stretch parameters points which way, and for BGL_HAN_Base Hangar Dynamic the guess was backwards: the long side (828 mm) went over the pipes and the hanger stopped half way into the far cable tray.
  - The hanger is now measured after placing: its extent across the run is read from its bounding box.
  - If the long side came out on the short side, the two widths are swapped.
  - The log shows the reaches either way before and after.
  - Family settings *Swap* is now only the first guess.
- Bench: bench_revit 107 checks / 45 breakages (a fake family whose parameters point the other way), bench_logic 105 checks.

## 1.5.0
- **Shared hangers fixed and reworked.** In the 1.4.0 test the two pipes were never grouped: the clear gap limit was 100 mm. Then every planned spot was skipped as "existing" — the hangers from an earlier run — and the log did not say so.
  - The gap limit is now 500 mm by default.
  - A shared hanger is centred on the **mean of the service centres** (or midway between the outer edges, if chosen).
  - Each width parameter reaches its own side's outer edge, so the two sides differ when the services are uneven.
  - It sits at the lowest invert.
- **Hanger rules** button (under Refresh list): bottoms within (50 mm), clear gap under (500 mm), parallel within (2°), centre on (mean / edges).
- Family settings: **Swap the two width parameters**, in case a shared hanger comes out mirrored.
- **Align-lock** tick on Place, Re-align and Auto place, on by default. Shared hangers are never locked. It locks:
  - the family's centre plane along the run to the service centreline, in the plan view;
  - the hanger face at the invert to the service's bottom face (or its insulation's, when hung outside it). This is in a section named "Hanger Automation - bottom locks …", made along the service and kept, because a lock lives in the view it was made in.
  - Round pipes get the centre lock only: they have no flat bottom face.
- **Debug:** every shared-hanger decision is logged — who joined, and why each other service was left out (gap / height / not parallel / not alongside). The log also shows every planned spot dropped as existing, and what it was near. The results say how to place anyway.
- **Layout:** tools are back in one column. The window slides with each tool as it opens or folds, so its bottom stays at the lowest tool. It never grows taller than 97 % of the screen's working area — on a 24" monitor it stops short of the taskbar and the tab scrolls instead.
- Bench: bench_revit 105 checks / 44 breakages, bench_logic 102 checks, import_check 22 rules / 31 breakages.

## 1.4.0
- **Drop rod extender** (new tool, above the Dimension placer).
  - Pick one or more hangers (or select them first), then click the element to hang them from: a floor, beam, steel or service, in this model or a linked one.
  - Clicking a link goes on to a click on the element inside it; tick "Target is in a linked model" to go straight there.
  - Each hanger's drop rod runs from its reference level up to the target's underside directly above it. That is found by a ray through a clean temporary 3D view, links included.
  - Where the target is not directly above, the rod goes to its lowest point (its invert). A target below a hanger is reported, not used.
- **Pipes and cable trays** work everywhere ducts do: place, re-align and auto place.
  - Pipes are round, sized on the outside diameter, with pipe insulation handled like duct insulation.
  - Cable trays use their width and height.
  - FAB pipework works too.
  - Auto place walks pipe and cable tray fittings and accessories.
  - The DW/144 cap only applies to ductwork.
- **One hanger round services that sit together.** Services join one hanger when they are:
  - parallel;
  - within 50 mm of each other's bottom;
  - less than 100 mm apart in plan (edge to edge, chained neighbour to neighbour).

  The hanger spans from the outermost edge to the outermost edge, is centred between them, and sits at the lowest invert.
  - Place: select the services first, then click.
  - Re-align: pick several services, then the hangers.
  - Auto place: select several runs. The widest run leads and the others share its hangers instead of getting their own.
- Tool names now say "service" where they meant ducts only.
- Bench: bench_revit 98 checks / 39 breakages, bench_logic 95 checks, import_check 22 rules / 29 breakages.

## 1.3.0
- Family Hangers tools fold away. Collapsed, a tool shows only its icon and name.
  - Clicking its header slides it open or shut: height and fade run on a 260 ms ease-in-out curve and the chevron turns with it.
  - Hovering a header highlights it.
- Each tool's green button now sits at the bottom right of its own body.
- **Collapse all / Expand all** at the top left of the tools.
- Which tools are open is remembered.
- The tools sit in two independent columns, so folding one never leaves a gap beside it.
- Opening a tool grows the window if it needs the room (up to the screen height); folding leaves the window as it is.
- Bench: bench_revit 84 checks / 31 breakages, import_check 22 rules / 29 breakages.

## 1.2.1
- The window now sizes itself to show every tool:
  - when it opens and whenever you switch tab, it grows or shrinks to the open tab's content;
  - it never grows taller than the screen it is on, and moves up if it would run off the bottom;
  - only on a screen too short for everything does the tab scroll.
- Family Hangers tools are laid out two across (Place | Re-align, Auto place | Dimension placer), so the tab is about a third shorter. The window opens 1060 wide.
- Bench: bench_logic 86 checks, import_check 22 rules / 27 breakages.

## 1.2.0
- **Re-align no longer moves hangers along the run.** 1.1.0 projected every hanger onto the picked duct segment and clipped it to that segment's ends, so a hanger on the next segment was dragged back. Now:
  - the run is walked from the picked duct, and each hanger is matched to the straight it actually hangs over;
  - it slides only sideways onto that straight's centreline (the line is not clipped);
  - height, width and rod are fitted to that straight's own size.
- **Auto place button is back.** It had been pushed below the bottom of the window. Every tool button now sits in its card's title row, and both tab bodies scroll if the window is short.
- **Insulation.** Each family tool has a "Hanger outside insulation" tick, on by default.
  - Outside: the hanger wraps the insulation, so each half width grows by the thickness and the invert drops by it.
  - Unticked: the hanger fits the bare duct.
  - The thickness comes from the duct's hosted insulation (Revit ducts) or the part's own InsulationThickness (FAB).
- **Dimension placer** (new section, floor plans only; the button greys out elsewhere, following Revit's ViewActivated).
  - The view is temporarily isolated to the hanger families, with dimensions kept visible.
  - Box-select or click hangers, then Finish.
  - One centre-to-centre chained dimension is placed along each straight line of hangers, using the family centre reference square to the run (front/back or left/right from the hanger's own orientation). It sits the set distance from the hangers (default 800 mm) in an optional dimension type.
  - The view is put back afterwards.
- **Debug.** There is a Debug tick in the footer, on by default. Family jobs now log:
  - the model, view, levels, chosen family / placement type / family settings and tab settings;
  - each click, duct and section (with insulation), level, invert and offset written, rotation applied, each width and rod written (flagging any not set);
  - for re-align, every move and the segment used;
  - for auto place, every part of the run and every span (ends, size, spacing, planned stations, takeoffs, placed points);
  - for the dimension placer, the groups and reference types.
  - Copy debug adds the chosen family, its parameters and the family settings file.
- Bench: bench_revit 77 checks / 29 breakages, bench_logic 82 checks, import_check 21 rules / 25 breakages.

## 1.1.0
- Renamed from Fab Hangar Automation to **Hanger Automation**: folder `Hanger Automation.pushbutton`, ribbon title "Hanger Automation". Settings carry over from `fab_hangar_automation.txt` on first run.
- Two tabs with icons under the header: **FAB Hangers** (unchanged) and **Family Hangers**. The results box and footer are shared.
- **Family Hangers.** Choose the hanger family and type:
  - filter by Generic Models, MEP Ancillary Framing or Duct Accessories, or search;
  - the type's preview image shows on the left.
- **Family settings** (button right of the list), saved per family in `hanger_automation_families.txt`:
  - the two width stretch parameters (guessed from Left / Right names);
  - the drop rod parameter (default BGL_DIM_Drop Rod Length);
  - which way the width runs (family X or Y);
  - clearance each side;
  - where the rod stops (base of the level above, or underside of structure above).
- **Place hanger on duct.** Click on Revit ducts or FAB ducts, one after another (Esc to finish). Each hanger is:
  - centred where you clicked, with its reference level at the duct invert;
  - on the duct's level and the duct's workset;
  - turned square to the duct, with both stretch parameters set to half the duct width plus clearance.
  - The drop rod is optionally extended to the soffit.
- **Re-align hangers to duct.** Pick a duct, then hangers. Each is moved onto the centreline (keeping its place along the duct), onto the duct's level, invert and width refitted, rod optionally re-extended.
- **Auto place along a selected duct run.** Works on Revit or FAB ducts.
  - Horizontal straights only.
  - First hanger after each bend, then spacing up to your maximum, capped by DW/144 for the duct size: 3000 mm, or 2500 mm over a 1500 mm longer side.
  - A hanger before the next bend, set down or (optionally) in-line damper / accessory, with the spacing shrunk to fit.
  - Nothing on takeoff stubs; hangers moved clear of taps and kept off joints / flanges by the flange clearance.
  - Skips where a hanger already is; optional chained dimension.
- New icon: the hanger with a cog.
- Bench: bench_revit 58 checks / 22 breakages (fake Revit ducts, levels and family instances), bench_logic 72 checks, import_check 20 rules / 23 breakages.

## 1.0.2
- Auto Rehost and size now **replaces** each hanger with a new one placed on its nearest duct, exactly as a fresh placement: same kind of hanger, with the condition, width and depth Revit gives a new hanger on that duct. 1.0.1 only moved the hanger (PlaceOnHost keeps the old size) and copied dimensions by name, which did not resize it.
  - The kind of hanger is found by trying each hanger button in the old hanger's service inside a rolled-back sub-transaction and comparing item id, product name and size-free name words with the old hanger. Cached per kind.
  - Kept from the old hanger: workset, Comments, Mark, every writable shared parameter, and rod top levels (before any extend).
  - The new hangers are left selected. If a hanger cannot be re-created it is moved instead, and the results say so.
  - Untick "Replace with a new hanger..." to only move hangers.
- Easter egg: PacMan now starts only on a few slow clicks of the RevoBIM logo top left. 1.0.1 handed the shared `attach(logo, host_window=...)` the window as its logo, which armed the whole window. Arguments are now matched to the real signature by name; the theme goes over as a callable. Clicking the logo never drags the window.
- Bench: bench_revit 30 checks / 13 breakages, import_check 20 rules / 23 breakages, bench_logic 48 checks.

## 1.0.1
- Fixed: the window would not open ("'Window' object has no attribute '_full'"). Full screen and resize state now live on Python objects; nothing is ever attached to the WPF window.
- Fixed: hangers are now hosted from the duct's Connector object, as CreateHanger and PlaceOnHost require (1.0.0 passed a connector number, which Revit refuses).
- Fixed: rods are set to manual before SetRodLength (Revit refuses to set the length of an auto-hosted hanger). If no soffit is found by ray, Revit's own Attach to structure is used.
- Fixed: the result callback reached for a Dispatcher on the wrong object.
- Rods are cast from under the hanger through a temporary clean 3D view, so hidden floors, section boxes and templates in your own 3D views can't hide the slab. The view is removed at the end of the run.
- Taps cut into a straight are found (side connectors and hosted tap parts) and hangers move 400 mm clear of them. Branches starting at a tap are treated as takeoffs.
- Hanger button: prefers the duct's own service, picks the tightest condition covering the duct width or diameter, falls back to an unrestricted condition.
- Existing hangers are matched by their position along the run, not just straight-line distance.
- New hangers go on the workset of the duct they hang from. Every count is read back after the transaction group closes.
- ExternalEvent.Raise() status is checked, and a watchdog frees the window if Revit never starts the job. The window is parked so a second click brings it forward.
- Canvas theme read from UIThemeManager.CurrentCanvasTheme, compared by name.
- Linear dimension types only in the dimension list; element names read safely.
- New "Push the rods up to structure" setting is remembered (settings version 2).
- Bench: bench_stubs.py (a stub .NET that refuses new attributes the way IronPython does), bench_revit.py (fake Revit: 21 checks, 8 breakages incl. the 1.0.0 crash), import_check.py (19 rules, 20 breakages).

## 1.0.0
- First release.
- Auto Rehost and size selected, Extend hanger to structure, Auto place hangers with chained dimensions.
- Dark / light / auto theme chip and version top right.
