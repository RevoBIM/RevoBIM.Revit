# RevoBIM easter egg — changelog

## 1.12.0 — no more white window behind the game

The blank window was pyRevit's output window, and it opened because something
reached stderr. What reached it was IronPython complaining about the wait 1.11.0
had just added:

> Calling Thread.Sleep on an STA thread doesn't pump messages. Use
> Thread.CurrentThread.Join instead.

Fair. Revit's UI thread is STA, `Thread.Sleep` on it does not pump messages, and
the warning is written to stderr - which is all it takes to put a blank white
window behind the game and make it read as a crash.

- **One `pause()` helper**, using `Thread.CurrentThread.Join(ms)`, which is the
  documented way to wait on an STA thread. It pumps, and it says nothing.
- `egg_launcher` **cannot** import Thread - it is one of the portable modules the
  desktop build shares - so its wait is **injected** by the caller instead.
  `time.sleep` is exactly right on a desktop and exactly wrong inside Revit.
- The window wait came down from 2s to 1.2s, since it only ever elapses when
  something is already wrong.
- The button **closes pyRevit's output window** after launching. Errors go to a
  TaskDialog, so there is nothing in it worth keeping, and a warning raised by
  IronPython itself is not ours to stop at source.

Rule 23 holds it: `Join` is used, `Thread.Sleep` and `time.sleep` appear nowhere
outside the one helper, and `spawn()` takes the injected pause.

Rule 22 was also caught out by its own selftest here. It checked that
`_survives(process` appeared in the source — but the broken version still
mentioned it, so the rule passed. It now checks that the call is **acted on**
(`if not _survives(`), not merely present.

## 1.11.0 — the button did nothing, and said nothing

Three faults, and every one of them was the same mistake: **starting a thing was
taken as the thing working**. That is the same lesson as proving a parameter
write by reading it back, and it is worse here, because the caller was told it
had succeeded so nothing was reported anywhere.

1. **The button had no `__persistentengine__`.** The game runs on its own thread
   and the script returns immediately afterwards, so pyRevit disposed the engine
   as the command returned and took the game thread with it. The command
   "succeeded", nothing appeared, and there was nothing to look at.
2. **`spawn()` returned True on `Popen` returning.** That only means Windows
   started something. A Python that is 2, or 3 without tkinter, starts perfectly
   and exits half a second later. It is now polled for 0.8s and reported as a
   failure if it does not survive, falling through to the thread; and its stderr
   goes to `%APPDATA%\RevoBIM\arcade_process.log` instead of into the void,
   since pythonw writes nowhere.
3. **`_launch_threaded()` returned True on `Thread.Start` returning.** It now
   waits up to two seconds for the window to actually be parked, which costs
   nothing normally - the window is up in about a tenth of a second - and only
   elapses when something is already wrong.

**`auto` now means thread, not process.** A name on PATH is not proof that the
Python behind it is 3 or has tkinter, and guessing wrong is precisely how the
button came to do nothing. The thread needs nothing installed and cannot fail
that way. A separate process is still the stronger answer and is one **Pop out**
chip, or `run_mode=process`, away.

Rule 22 holds all four points, and the selftest breaks each in turn.

**If a tool starts something that outlives its own run, it needs
`__persistentengine__ = True`.** That is a general pyRevit rule, not an egg one.

## 1.10.0 — a button for it

**RevoBIM Arcade**, a pushbutton in the **Routines** pulldown on the
**Coordination** panel — the same pulldown QFR Remover and Fire Damper Wall Type
Push sit in.

- Click it and the game opens. It uses whichever game the chip was last set to,
  which is Pacman until somebody changes it — forcing Pacman here would make the
  chip pointless.
- It goes through the same `run_mode`, so it opens in its own process where
  there is a Python and on its own thread where there is not. It does not freeze
  while a tool is working.
- **Shift-click for a diagnostic report**: whether the automatic attachment
  installed, how many windows it has seen and wired, the click timing in force,
  and the last dozen log lines. That is the thing to reach for when the logo
  clicks are not working somewhere.
- Loads in stages and names the stage that failed, into a dialog and into
  `%APPDATA%\RevoBIM\arcade_last_error.txt`, rather than leaving pyRevit's
  blank white window.

**No `Routines.pulldown\bundle.yaml` is shipped**, and no
`Coordination.panel\bundle.yaml` either. Both already exist and are shared, and
shipping one would silently revert whatever the tools already in them had set —
the exact rule written down in `claude_RevoBIM_shared_files.md`. Rule 8 now fails
the build if either turns up in the zip, and its selftest plants one to prove it.

The same rule holds the folder name and the bundle title in step, since pyRevit
names a ribbon item after its folder, and holds the title to a single short line
so it is not mangled in Revit's Keyboard Shortcuts list.

## 1.9.0 — it no longer depends on startup.py

**Yes, overwriting `startup.py` with another tool's would have killed it** — and
silently, which is the worse half. Nothing fails when a shared file is
clobbered: the feature that lived in it simply stops existing, with no error to
go looking for.

1.8.0 hung the whole automatic attachment off one shared, singular file. That
was a design fault, not bad luck: there is exactly one `startup.py` per
extension, so every tool that ships one is fighting over it and the last zip
unpacked wins.

**Four anchors now, across two different pyRevit mechanisms**, every one of them
idempotent so all of them running is fine:

1. `startup.py` at the extension root
2. `hooks\app-init.py` — a different mechanism, a different folder, untouched by
   anything that overwrites `startup.py`
3. `hooks\doc-opened.py` — because hook support has changed shape across pyRevit
   releases, and a redundant idempotent call costs nothing
4. `egg_hook.attach` arms it as a side effect, so **one hand-wired tool brings
   the whole thing back** even if all three files above have been lost

Rule 7 fails if fewer than three of the file anchors are present, because two is
one bad zip away from none. Its selftest deletes two of them and confirms it
fires; the on-disk harness had to be reshaped to copy the extension tree rather
than a bare folder, since the rule looks three levels above the egg.

Also shipped: **`claude_RevoBIM_shared_files.md`** for the project context — the
list of shared and singular files in the extension (`startup.py`, the hooks,
`lib\revobim\__init__.py`, panel and pulldown `bundle.yaml`), what happens when
a tool ships one, and the rules for shipping a banded fragment instead. This is
a general class of bug and the egg is only the first thing to have been bitten
by it.

## 1.8.0 — every tool, without editing any of them

**`startup.py` at the extension root is the whole job.** Drop it in, or paste
its banded block into the one you already have. Every RevoBIM tool window gets
the egg as it opens — the ones built before the egg existed, and the ones built
after it that nobody remembered to wire.

How: WPF lets a handler be registered against a **class** rather than an
instance, for the whole AppDomain, so a single `Window.Loaded` class handler
sees every window any addin in Revit ever opens. Windows carrying a RevoBIM logo
get the egg; nothing else is touched.

That handler is now the most dangerous code in the package — it runs inside
every window's `Loaded`, for every addin in the process — so four things are
held by rule 6, each verified by breaking it:

1. **it can never throw.** An exception there breaks window creation for other
   people's addins, which is a far worse thing than a missing easter egg.
2. **the cheap test comes first.** A dozen `FindName` lookups is nothing;
   walking the logical tree of every dialog Revit opens is not. `find_logo`
   gained a `deep=False` mode for it, and only a title carrying the brand earns
   the full walk.
3. **a window is marked once wired**, so a re-parented element raising `Loaded`
   again does not stack a second hook on it.
4. **`install()` is idempotent**, since a `startup.py` pasted together from two
   sources can easily call it twice.

`wants_egg` is a plain function of three booleans so what the handler decides to
touch is testable without a Revit. The bench spends more checks on what it
**leaves alone** — Revit's own dialogs, another addin's window, an untitled one
— than on what it takes, because a wrong positive puts an easter egg on somebody
else's software.

The egg's own window marks itself, so it does not hook its own logo.

`egg_auto.status()` reports whether it installed and how many windows it has
seen and wired, for a diagnostic dialog. There is no uninstall: WPF has no
`UnregisterClassHandler` and a class handler lives for the life of the
AppDomain, so the handler steps over anything already wired instead.

## 1.7.0 — it no longer freezes while a tool is working

The game was built on Revit's UI thread, so any pyRevit tool holding that thread
froze it solid until the tool finished. A window belongs to the thread that
created it and repaints on that thread's dispatcher; there was never any way
round that while it lived there.

**`run_mode`, defaulting to `auto`.** Three ways to run, and auto never picks
the one that freezes:

| Mode | What it is | Needs |
| --- | --- | --- |
| `process` | a separate OS process — nothing to do with Revit at all, and it keeps playing if Revit is closed | Python on the machine |
| `thread` | this process, but the game's own STA thread with its own dispatcher — immune to Revit's UI thread being held | nothing |
| `inline` | Revit's own UI thread. What every version up to 1.6.0 did | — |

`auto` takes `process` where a Python was found and `thread` where one was not,
so **the freeze goes away on every machine** whether or not anything is
installed. Each mode falls through to the next if it cannot start, and the log
says which one it used.

What the threaded mode has to get right, all of it held by rule 6:

- the window is built **inside** the thread. Building it outside and showing it
  there leaves it belonging to Revit's dispatcher and changes nothing.
- the thread is **STA**, which WPF requires, and **background**, so it cannot
  keep Revit alive after somebody has closed it.
- ownership goes through the **HWND**, not `window.Owner` — WPF will not let a
  window on one thread own a window on another, and it throws.
- the theme and the owner handle are resolved on the **caller's** thread. A
  theme callable normally reads the host tool's own state, and touching a WPF
  object from the game thread throws.
- the dispatcher is shut down when the window closes, or the thread sits in
  `Dispatcher.Run()` for the life of the session.
- the window is parked in the **AppDomain** as well as in a module list: a modal
  tool's command returns while the game thread is still running, and pyRevit can
  dispose the engine out from under it.
- changing game or theme reopens **on the same thread**, rather than going back
  through `launch()` and possibly handing the game to a whole new process
  because somebody touched the theme chip.

Also: the unused `DispatcherTimer` import finally went, three versions after the
render loop that used it.

## 1.6.0 — it runs outside Revit

**Do not use the 1.5.0 zip.** Its `__init__.py` shipped empty — a bad version
bump truncated it — so `from revobim.egg import __version__` failed and the
whole egg never imported. Rule 5 now holds it, because an empty file compiles,
imports and passes every other check, and the one line it breaks sits inside the
try/except that stops the egg breaking a tool. It was completely dead and looked
like nothing at all.

**The desktop build.** `RevoBIM Arcade` — the same games, in their own process,
with no Revit running and none of its resources used.

- `standalone\RevoBIM Arcade.bat` or `.pyw` — double click either.
- **Pop out** chip in the in-Revit window hands the running game to a detached
  process and closes the Revit one. The chip only appears where a Python was
  actually found; a button that does nothing on half the machines in the office
  is worse than no button.
- Needs Python 3 from python.org and nothing else — tkinter only, no pip, no
  packages. The .bat says so plainly if it cannot find one.

**What made it a day's work rather than a rewrite** is the surface contract. A
game draws through ten methods and knows nothing about what is underneath, so a
Tk canvas underneath instead of a WPF one is a second implementation of those
ten methods — `pacman.py` and `snake.py` are shared byte for byte.

- `egg_theme.py` dropped its `egg_clr` import, which it never used, so it too is
  shared.
- `egg_settings`, `egg_scores`, `egg_log` and `egg_registry` were already pure
  stdlib. **So the scoreboard is the same board**: a game won at your desk sits
  in the same table as one won inside Revit.
- Both surfaces now answer to both `brush()` and `colour()`, so a game cannot be
  written against one implementation by accident.

**Three rules to keep it that way**, all self-verified:

- **portable modules import no .NET.** One `from System.Windows import ...`
  added to any of them breaks the standalone app while leaving the Revit one
  working perfectly — the worst shape a regression can take, because whoever
  added it has no reason to look.
- **the Tk surface answers every call the WPF one does**, parsed rather than
  imported so it works on a bench with no tkinter.
- **`__init__.py` carries a `__version__` and the changelog agrees with it.**

13 new bench checks drive the real `TkSurface` through a stub canvas: a full
600-frame game of Pacman, Snake on the light palette, the arc angles negated
(Tk measures anticlockwise, the games are written for WPF where the y axis
points down — get it wrong and the mouth faces backwards), translucent colours
flattened onto their backdrop since Tk has no alpha, and a scale change reaching
the walls and pellets that were drawn once at the start.

## 1.5.0 — the egg was not opening in any tool

Four faults, each of which would have done it on its own, and every one of them
silent because the hook is wrapped in try/except so it can never take a tool
down.

1. **The timing was wrong.** The house behaviour, and what every tool's
   documentation says, is three **slow** clicks. The hook allowed 650ms for the
   whole run, which is a fast triple click. Clicking the way the tools describe
   never reached three. Timing is now the **gap between clicks** — 250ms to
   2000ms each — not one window for the run. `settings_version` 3, and
   `click_window_ms` is accepted and ignored.
2. **A handled tunnelling click was never heard.** Preview goes root to leaf, so
   a header that handles `PreviewMouseLeftButtonDown` for its own drag runs
   before the logo does and marks the event handled — and a plain `+=` handler
   is not called for a handled event. Registered through
   `AddHandler(..., handledEventsToo=True)` now.
3. **`FindName` returning None was a silent no-op.** A tool whose XAML calls its
   logo something else got an empty element list and nothing else.
   **`attach_to_window(window)`** now finds the logo itself: the known names
   first, then any TextBlock reading "RevoBIM" or Image named like a logo. It
   does not matter what the layout calls it.
4. **A TextBlock is only hit testable where its glyphs are.** Clicking the gap
   between letters did nothing. The target gets a transparent Background, which
   is invisible and makes the whole box take the click.

Also:

- **A log.** `%APPDATA%\RevoBIM\easter_egg.log` records every attach, every
  click with its gap, and every launch. The try/except rule is what made this
  necessary: a hook that never fires looked exactly like one nobody asked for.
- **`egg_hook.diagnose(window)`** returns a readable report — timing, whether a
  logo was found and what it was, live hooks, and the last dozen log lines.
- One physical click reaching two hooked elements is counted **once**, deduped
  on `args.Timestamp`. `is` will not do it: it compares Python identity, not
  .NET identity.
- Bench rule 14 holds all three timing faults. Its own first cut looked for the
  word "Timestamp" anywhere in the file and was satisfied by the docstring
  explaining why timestamps matter — deleting the actual call still passed. It
  now checks the source with docstrings and comments stripped.
- 18 new bench checks on the counter itself, including three clicks a second
  apart actually opening it.

## 1.4.0

- **One life.** `LIVES` at the top of `pacman.py` if it ever wants to go back.
- The death animation plays either way. Going straight to the card on the last
  life meant never seeing it — which, on one life, meant never seeing it at all.
- The footer no longer counts lives, since one is not a count. It shows pellets
  eaten instead.
- Two bench tests were watching ghosts move for several hundred ticks and
  quietly relying on the hero surviving that long. They now give themselves the
  lives they need rather than depending on the game's.

## 1.3.0

- The scoreboard shows **15** rows, up from 10.
- **"Now get back to work!"** under the table, in orange.
- Fifteen rows is taller than the body on a default sized window, so the card
  now sits in a `Viewbox` set to `DownOnly` — it shrinks to fit rather than
  being clipped, and is never blown up to fill a full screen, which would leave
  one short table in enormous text.
- `settings_version` is 2, with a migration on `scores_shown`. A changed default
  needs one: the whole set of keys is written back on every save, so an existing
  file is not missing the old value and would never fall through to the new one.
- Bench rule 13 holds both the sign-off and the 15, and fails a changed default
  that arrives without a migration.

## 1.2.0

**A scoreboard.**

- Every finished game is written to
  `%APPDATA%\RevoBIM\easter_egg_scores.txt` with the player, the date and the
  time. One record per line, `game|when|player|score`.
- The board is the shell's, not a game's, so **every game gets it and a new
  game gets it for nothing**. Nothing in the game contract changed.
- **Scores** chip in the header, or Tab, shows it. Opening it over a live game
  pauses that game. Escape now unwinds a layer at a time: board, then full
  screen, then the window.
- On a finished game the board comes up on its own after 1.4 seconds, giving
  the game over card its moment first. The row just played is picked out in
  orange, rows by the same player in full white, everyone else muted.
- The chip carries the finishing position — **Scores #1** in green, anything
  else in orange.
- The player is the Windows account, overridable with a `player` setting for a
  shared coordination machine logged in as something dull.
- The file is capped at 300 records, trimmed **by score rather than by age**:
  throwing away last year's 9,000 to keep this morning's 40 is the wrong trade.
- A tie is settled by whoever got there first, which also keeps the board from
  reshuffling every time a score repeats.

## 1.1.0

**Smoother.**

- The loop moved from a 33ms `DispatcherTimer` to `CompositionTarget.Rendering`,
  which fires once per frame the display actually draws, in step with vsync.
- Logic and drawing are now separate: `tick()` runs on a fixed step off an
  accumulator, `render(alpha)` runs every frame, and everything that moves is
  drawn between where it was and where it is. 30 logic steps a second, 60fps
  motion, and not one line of the grid arithmetic changed.
- A frame longer than 250ms — a dragged window, a stalled machine — is dropped
  rather than caught up, so nothing teleports; and no more than five logic steps
  run in one frame.
- Pacman's mouth now chews off distance travelled rather than frame count, so it
  matches the speed it is moving and holds still when it stops. Ghosts bob, and
  their pupils look the way they are going.
- Snake slides between cells instead of jumping, and its step slowed 90 → 110ms
  now that it no longer needs the rate to feel alive.

**Full screen.**

- Button beside close, F11, or a double click on the header. Escape leaves full
  screen before it closes the window; dragging the window leaves it too.
- By bounds rather than `WindowState.Maximized`, on the working area of
  whichever monitor the window is on, divided by the DPI scale — a borderless
  `AllowsTransparency` window maximised the normal way covers the task bar and
  lands on the wrong screen.
- The board sits in a `Viewbox`, so full screen is the same maze at four times
  the size with no game code involved. The window also stretches now, from eight
  resize grips.

**A game over worth losing to.**

- The hero opens right up and shrinks away rather than just vanishing.
- A card over the board: **GAME OVER**, or **NEW BEST** in green where the score
  beat the stored one; the score; level, pellets eaten and ghosts eaten; a rank
  from Setting Out Apprentice to Model Federation Overlord; a rotating sign-off
  ("The ghosts have raised an RFI"); and a prompt that breathes rather than
  blinks, because a hard blink at 60fps is a strobe and this window sits in
  front of somebody's model.
- Snake gets its own card, ranks and sign-offs.

**Bench.**

- `import_check.py` is up to 11 rules, with a new one that fails a game drawing
  inside `tick()`. Its selftest case was wrong first time — it edited the first
  matching line, which was in `start()`, where drawing is fine.
- `bench_logic.py` is up to 54 checks: interpolation at alpha 0, 0.5 and 1, the
  tunnel frame not interpolating, twenty extra frames changing no game state,
  the card and its ranks, and the pulse never going fully invisible.
- Two older tests were quietly relying on the death timing and broke when it
  changed; they now run until a ghost is actually out of the house.

## 1.0.0

First version.

- `lib\revobim\egg\` — one shared path, imported by any tool that wants it. No
  tool carries a copy of anything.
- Triple click on the RevoBIM logo in any tool's header opens the game window.
  `egg_hook.attach` is the whole public surface, three lines in a tool.
- Games are discovered by filename from `egg\games\`. `pacman.py` ships as the
  default and `snake.py` beside it, purely to prove the contract holds for a
  second game. Adding one edits nothing outside its own file.
- The game chip in the header cycles through whatever is in that folder; the
  choice is saved.
- Dark and light, cycling auto / dark / light from the header chip. `auto` is
  the default and takes the palette from the tool that launched it, falling back
  to Revit's own `UIThemeManager.CurrentTheme` where the release exposes it.
- High score per game in `%APPDATA%\RevoBIM\easter_egg.txt`, alongside the game
  and theme settings, plain `key=value` like every other RevoBIM tool.
- `import_check.py` — 10 rules, `--selftest` proving each catches its own
  deliberate breakage. Two did not on the first run and were fixed.
- `bench_logic.py` — 35 checks playing both games headless against a fake
  surface. Caught a ghost-release bug that no static rule would have.
- `egg_rule.py` — a bench rule to paste into each tool's own `import_check.py`,
  so a rebuild that forgets to wire the egg fails on the bench.
