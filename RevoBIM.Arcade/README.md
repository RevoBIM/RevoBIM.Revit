# RevoBIM Arcade

A standalone Windows arcade for the RevoBIM PY extension. Revit only launches it; the games
run in their own process, so they keep going while a tool is busy and after Revit closes.
No Revit or pyRevit references: **one exe serves Revit 2023, 2024, 2025, 2026 and 2027.**

```
RevoBIM.Arcade\
  RevoBIM.Arcade.sln
  RevoBIM.Arcade\            the app
    Core\                    IArcadeGame, GameHost, GameRegistry, LaunchOptions, SlowClickCounter
    Services\                loop, input, storage, theme, drawer, single instance, screen helper
    UI\                      ShellWindow (header, picker, board, footer)
    Themes\                  Common, Dark, Light (brush keys only)
    Games\Hello\             the placeholder game
    Version.cs               the one place the version lives
  tools\                     publish.ps1, selftest.ps1, launch-check.ps1
  integration\               what goes into the extension (the egg_hook fragment, button bundle)
  dist\egg-bin\              publish output, ready to copy to lib\revobim\egg\bin\
```

## Add a game

1. Create `RevoBIM.Arcade\Games\<Name>\<Name>Game.cs` implementing `IArcadeGame`:

   ```csharp
   public sealed class SnakeGame : IArcadeGame
   {
       public string Key => "snake";          // lower-case letters, digits, '-'
       public string DisplayName => "Snake";
       public string Hints => "Arrows steer   P pause   R restart   Esc menu";

       public void Start(GameHost host) { /* draw on host.Surface, tick on host.Loop */ }
       public void Stop() { /* unsubscribe, save the score with host.Scores.Record(n) */ }
   }
   ```

2. Add one line to `GameRegistry.Build()`:

   ```csharp
   yield return () => new SnakeGame();
   ```

Nothing else changes. Use what `GameHost` gives you rather than your own copies:

| You need | Use |
| --- | --- |
| a drawing board | `host.Surface` (a `Canvas`), `host.SetBoardSize(w, h)`; the shell scales it |
| a timer | `host.Loop.Tick += dt => ...` (seconds since the last frame, clamped) |
| keys | `host.Input.Pressed`, `host.Input.IsDown(Key.X)`, `.Left/.Right/.Up/.Down` |
| colours | `host.Fill(shape, "HeroBrush")`, `host.Stroke`, `host.Text` (theme brush keys) |
| scores | `host.Scores.Record(n)`, `.Best()`, `.Ranked(10)` |
| the footer line | `host.SetStatus("Score 120")` |

The shell owns **P** (pause), **R** (restart: it rebuilds the game) and **Esc** (back to the menu),
so a game never sees them. Inside a game class `Key` is the string property, so alias the key enum:
`using WKey = System.Windows.Input.Key;`.

To make the Revit side use the new game, add its key to `ARCADE_KEYS` in the pasted `egg_hook`
fragment (see `integration\egg_hook.launch.fragment.py`). No caller changes.

## Build

Needs the .NET 8 SDK or newer (the project targets `net8.0-windows`).

```powershell
dotnet build RevoBIM.Arcade.sln -c Release          # day to day
powershell -File tools\publish.ps1                  # single-file self-contained exe -> dist\egg-bin\
powershell -File tools\publish.ps1 -EggBin "<extension>\lib\revobim\egg\bin"   # straight into the extension
```

The publish is `dotnet publish -r win-x64 --self-contained -p:PublishSingleFile=true`.

## Test without Revit

```powershell
powershell -File tools\selftest.ps1              # everything: logic, repo and launch checks
powershell -File tools\selftest.ps1 -SkipLaunch  # logic and repo checks only (no windows)
RevoBIM.Arcade.exe --selftest                    # just the exe's own logic checks
```

By hand:

```powershell
RevoBIM.Arcade.exe                               # the picker
RevoBIM.Arcade.exe --game hello --theme light
RevoBIM.Arcade.exe --game hello --theme dark --owner-x 100 --owner-y 100 --owner-w 1000 --owner-h 700
```

The launch checks use a scratch settings folder (`REVOBIM_ARCADE_DIR`), so a test run never
touches your real scores.

## Launch contract

```
RevoBIM.Arcade.exe --game <key> --theme <light|dark> [--owner-x <int> --owner-y <int> --owner-w <int> --owner-h <int>]
```

* No arguments, or an unknown key: the picker lists the registered games.
* `--theme` is `light` or `dark`; anything else is ignored and dark is used.
* The owner rectangle is in screen pixels. With all four numbers (w and h above zero) the window is
  centred over it; otherwise it is centred on the screen.
* Single instance: a second launch brings the running window forward, switches it to the
  requested game and exits.
* Bad arguments never stop it opening.

## Storage

`%APPDATA%\RevoBIM\arcade\` holds `settings.json` and one `scores.<game>.json` per game. The old
`easter_egg*.txt` files are not read.
