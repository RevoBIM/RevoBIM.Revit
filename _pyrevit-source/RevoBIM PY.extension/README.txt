RevoBIM PY - Nudge                                                       v1.6.0
==================
Revit 2024 | pyRevit (IronPython 2.7 engine) | metric (mm)

Three small stacked buttons that raise and lower elements by a fixed amount.

  RevoBIM PY  >  Coordination  >  [ Nudge Up ]
                                 [ Nudge Down ]
                                 [ Nudge Settings ]

Three small stacked buttons directly on the Coordination panel, not inside a
pulldown.


INSTALLING
----------
This zip IS your extension folder. It merges straight into what you already
have:

  %APPDATA%\pyRevit\Extensions\RevoBIM PY.extension\

Copy "RevoBIM PY.extension" over the top of the existing one and let Windows
merge the folders. It only adds:

  RevoBIM PY.tab\Coordination.panel\stack3.stack\   the three buttons
  lib\revobim\nudge.py                              the move engine
  lib\revobim\nudge_settings.py                     the shared settings
  lib\revobim\revit_shortcuts.py                    the shortcuts writer

Nothing existing is overwritten. There is deliberately NO bundle.yaml for
Coordination.panel in this package, so your panel's own settings, ordering and
the Routines pulldown are all left exactly as they are.

MERGING lib\revobim: keep the __init__.py you already have. The one in this
zip is a placeholder for a clean install only - if yours has anything in it,
do not let it be replaced.

Then restart Revit. A pyRevit reload is enough to get the buttons on the
ribbon, but NOT enough to register them for keyboard shortcuts - see below.

UPGRADING FROM 1.2.0 OR EARLIER
-------------------------------
Earlier versions shipped as a separate "RevoBIM PY Nudge.extension" folder
with the buttons on the Modify panel. Both of those have changed, so DELETE
the old install first:

  %APPDATA%\pyRevit\Extensions\RevoBIM PY Nudge.extension\

pyRevit builds each command's ID from its folder path, so leaving the old
folder in place gives you two sets of Nudge buttons - one on Modify, one on
Coordination - both live, and both fighting over the keyboard shortcuts.

Your settings are unaffected. They live in %APPDATA%\RevoBIM PY\ rather than
in the extension, so the increment and rounding survive the move. The keyboard
shortcuts do NOT survive: the command ID changed with the folder path, so
reassign them in Nudge Settings after the first restart.


KEYBOARD SHORTCUTS
------------------
Set them from inside the tool: Nudge Settings > KEYBOARD SHORTCUTS. Type two
or three letters against each command and press Save. It writes straight into

  %APPDATA%\Autodesk\Revit\Autodesk Revit 2024\KeyboardShortcuts.xml

keeping a .bak copy alongside, and warns you if another command already uses
those keys. RESTART REVIT afterwards - Revit only reads that file at startup,
so nothing happens until you do. That is true however you assign shortcuts,
including through Revit's own dialog.

Suggested keys: something you can hit over and over with one hand, since the
whole point is repeating it. NU / ND, or a pair of adjacent letters.

Doing it the manual way instead:
  View > User Interface > Keyboard Shortcuts   (or type KS)
  Set Filter to "Add-Ins", or search for "Nudge"
  Click the Press New Keys box, type your keystroke, hit Assign, then OK.

IF THE COMMANDS DO NOT APPEAR
-----------------------------
Three causes, in the order they are worth checking:

1. YOU RELOADED RATHER THAN RESTARTED. Revit builds that command list from
   the ribbon once, at startup, and never refreshes it. A pyRevit reload puts
   the buttons on the ribbon but does NOT get them into the shortcuts dialog.
   Close Revit completely and reopen it. This is nearly always the answer the
   first time a new tool is installed.

2. THE EXTENSION IS LOADED FROM A CUSTOM EXTENSION DIRECTORY. Extensions
   loaded through pyRevit's "Custom Extension Directory" setting do not get
   registered with Revit's keyboard shortcut dialog at all. The extension must
   sit in the standard folder:

     %APPDATA%\pyRevit\Extensions\

3. THE SHORTCUTS FILE HAS NEVER BEEN CREATED. If you have never touched
   keyboard shortcuts on this machine the XML may not exist yet. Open the
   Keyboard Shortcuts dialog and press OK once to write it, then reopen
   Nudge Settings.

The button titles are single line - "Nudge Up", "Nudge Down", "Nudge
Settings" - so they read cleanly in the shortcut list. They are prefixed with
"Nudge" deliberately: a command called just "Up" is near-impossible to find in
that dialog. If you rename them, rename them in bundle.yaml AND script.py, and
update the COMMANDS list at the top of the Nudge Settings script.py so the
shortcut fields still find them.


HOW IT RUNS
-----------
Two modes, and the tool picks between them by looking at your selection.

SELECTION MODE - something is already selected
  Every selected element moves by the increment. Once. The selection is put
  back afterwards, so pressing the button again - or hitting the shortcut
  again - moves the same elements again by the same amount. Hold the shortcut
  down and they walk.

CLICK MODE - nothing is selected
  You get a prompt reading "Raise by 50 mm - click an element". Every element
  you click moves immediately, no dialog, no confirmation. It keeps asking
  until you press Escape. Click the same element five times and it moves five
  increments.

Both directions work the same way, Up and Down.

Each click in click mode is its own transaction, so Ctrl+Z steps back one
element at a time. Selection mode commits the whole selection in one
transaction, so Ctrl+Z undoes that press in one go.


SPEED
-----
Nudge Up and Nudge Down are on keyboard shortcuts and get pressed over and
over, so the delay before anything happens matters more than the move itself.
Three things were costing that delay and all three are gone in 1.4.0:

  - THE PYREVIT IMPORT. The buttons used to open with "from pyrevit import
    revit, script", which drags in a large dependency tree on every press.
    None of it was needed - the document is reached through __revit__
    directly. This was the bulk of the pause.
  - THE ENGINE. Both buttons now carry __persistentengine__, so the
    IronPython engine stays warm between presses instead of being built and
    torn down each time. Safe here because the tool holds no state, no window
    and no event handlers, so there is nothing to leak between runs. If it
    ever needs rebuilding, comment that line out at the top of the script.
  - THE SETTINGS READ. The JSON file was opened and parsed on every press. It
    is now cached and only re-read when the file actually changes on disk, so
    a press costs one stat call. Saving from the Settings window clears the
    cache, so a changed increment still takes effect immediately.

Smaller things: the fitting categories are resolved into a set once rather
than walked per element, elements are looked up before the transaction opens
so it is held for as little time as possible, and the selection is only
written back when Revit has actually dropped it rather than on every run.

The Settings window still uses pyrevit for its WPF plumbing. It opens once
and is not on the hot path, so there is nothing to gain there.


ROUNDING
--------
The resulting elevation is rounded to the nearest 5 mm by default, so an
element sitting on an untidy figure gets pulled onto the grid rather than
carrying its odd number around forever.

  2437 mm, Nudge Up 50   ->  2485    (48 mm this press, tidied onto a 5)
  2485 mm, Nudge Up 50   ->  2535    (exactly 50 from here on)

So the first press on an untidy element is slightly short or slightly long,
and every press after that is the full increment. Something already on a
round figure is unaffected.

If the increment is smaller than the rounding - say a 2 mm step against a
5 mm round - the rounding would put the element straight back where it
started and the tool would appear to do nothing. It moves a whole rounding
step instead.

On a sloped run the start elevation is the one rounded, and the end is
shifted by the same amount, so the run lands tidily without its slope
changing. On the rare element that has no elevation parameter at all and has
to be moved bodily in Z, there is no elevation to read, so the step itself is
rounded rather than the result.

Change the figure, or switch it off entirely, in Nudge Settings.


WHAT IT WRITES
--------------
Elevation goes to a parameter wherever one is writable, so the element keeps
its relationship to its level rather than being shoved through space. Tried
in this order:

  1. Middle Elevation                     the normal case for a level run
  2. Start Elevation + End Elevation      sloped runs - both shifted together
                                          so the slope is preserved
  3. Offset from host / level             fittings, accessories, equipment
  4. a plain move in Z                    last resort

Bear in mind this moves elements one at a time. Connections at the edge of
what you move will drag or drop exactly as they would if you nudged the
element by hand. Walk the whole run - fittings included - to keep a system
tidy, or select the lot first and nudge them together.


WHAT CAN BE CLICKED
-------------------
  Always          pipes, ducts, cable tray, conduit and flex, and
                  FAB ductwork, pipework and containment STRAIGHTS
  Fittings tick   their fittings and accessories, mechanical and
                  electrical equipment, fixtures, sprinklers and
                  generic models
  Fabrication     FAB fittings, FAB hangers, and MEP ancillary framing
  tick            (strut, channel, trapeze - Revit 2024+)

Everything else is filtered out and will not highlight.


FABRICATION PARTS
-----------------
FAB parts are never written through Top or Bottom of Part. Those are
measured from the part's level on some releases and service templates and
from the project base on others - Match Offset found this the hard way - so
writing them is a guess. Instead the part's centreline is measured against
its own level (ProjectElevation, never Level.Elevation, which goes tens of
metres out on a survey-based project), rounded, and the part is moved by the
difference. Pinned parts are unpinned for the move and pinned again after.

FAB hangers hang from the soffit, so after a hanger moves its rods are
re-cut to keep their tops where they were: raising it 50 mm shortens manual
rods by 50, lowering lengthens them. Rods Revit is hosting re-solve
themselves and are left alone. A rod that would come out shorter than 10 mm
is left as it was rather than written a length nobody would notice.

Select a duct AND its hanger and nudge them together: hangers go last, and
any hanger Revit has already carried up with its duct is counted as moved
rather than moved a second time. Measured, not assumed - whether Revit
carries it depends on how the hanger was hosted.


MEP ANCILLARY FRAMING
---------------------
Face- or level-hosted framing is written through Offset from Host /
Elevation from Level, the same as any family. Line-based framing has both
end level offsets shifted together, the start rounded and the end moved by
the same amount, so a level trapeze stays level and a falling one keeps its
fall. Anything with neither is measured and moved in Z.


SETTINGS
--------
  Increment                   how far each press moves things. Default 50 mm.
                              Four quick-pick chips: 10 / 25 / 50 / 100.
  Round final elevation       snap the result to a tidy figure. Default on,
                              at 5 mm. Untick to leave elevations exactly as
                              the increment lands them.
  Keep the selection          put the selection back after nudging, so the
                              next press moves the same elements. Default on.
  Keep clicking               with nothing selected, keep asking for elements
                              until Escape. Default on. Untick for one
                              element per press.
  Allow fittings              default on, as above.
  Allow fabrication           FAB fittings, FAB hangers and MEP ancillary
                              framing. Default on. FAB straights are always
                              allowed whatever this says.
  Re-cut hanger rods          keep manual rod tops at the soffit when a FAB
                              hanger moves. Default on.

Settings are shared by all three buttons and are written to:

  %APPDATA%\RevoBIM PY\nudge_settings.json

They survive a Revit restart and a pyRevit reload. Reset puts the defaults
back - it does not save until you press Save.

The presets list is not exposed in the window. Edit "presets" in the JSON if
you want different chips.


MESSAGES
--------
All three tools finish silently - no dialog, no pyRevit output window.
Anything that could not be moved goes quietly to the pyRevit debug log.


THEME
-----
Same palette as System Offset, QFR Remover and Rejoin 3D. Shell greys
#262A31 / #2F343C / #21252B, RevoBIM wordmark in blue #3D9BE9, tool name and
accents in orange #F07C10, custom chrome with a draggable header, version
stamped bottom right of the header.

Icons are one family: the same dark plate, the same grey datum rule, the same
element bar, drawn with the same heavy stroke weight so they read at 16px.
Only the colour changes with the direction - Nudge Up lifts a GREEN bar off
the rule, Nudge Down presses a RED bar down towards it, and Nudge Settings
puts the blue gear over a dimmed, colourless version of the same scene.


VERSION HISTORY
---------------
  1.6.0  FAB ductwork, pipework and containment, FAB hangers (rods re-cut),
         and MEP ancillary framing can now be nudged. Two new settings.
         Category and parameter lookups now resolved by name at call time.
         Logic bench added: Nudge Settings.pushbutton\bench_logic.py.
  1.5.1  Reverted 1.5.0. The buttons are back to a stack on the Coordination
         panel. If 1.5.0 was installed, delete the three Nudge pushbutton
         folders out of Coordination.panel\Routines.pulldown\.
  1.5.0  Buttons moved into the Routines pulldown. Reverted in 1.5.1.
  1.4.0  Much faster response on Nudge Up and Nudge Down - the pyrevit import
         dropped from both buttons, a persistent engine, and a cached
         settings read. See SPEED above.
  1.3.0  Ships as RevoBIM PY.extension and merges into the existing install.
         Buttons moved from the Modify panel to Coordination. Delete the old
         RevoBIM PY Nudge.extension folder - see UPGRADING above.
  1.2.0  Final elevation is now rounded to the nearest 5 mm by default, set
         or switched off in Settings.
  1.1.0  Keyboard shortcuts can now be set from the Settings window, written
         straight into Revit's KeyboardShortcuts.xml with a backup and a
         clash warning. Restart of Revit still required, as always.
  1.0.2  Icons redrawn bolder. Nudge Up is now green, Nudge Down red.
  1.0.1  Settings window would not open - "Cannot import name Visibility".
         PresentationCore is now referenced explicitly before the import, and
         the import is guarded so a missing enum cannot stop the window.
  1.0.0  Nudge Up, Nudge Down and Nudge Settings. Selection mode and click
         mode, shared settings store, themed settings window.
