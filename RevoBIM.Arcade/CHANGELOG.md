# RevoBIM Arcade — changelog

## 0.1.0 — 2026-11-15 — the base

A standalone Windows arcade that runs outside Revit. This release is the base only:
the shell, the game contract and the shared services, with a placeholder game. No real
game is ported yet.

- **Standalone.** C# .NET 8 WPF, one self-contained `RevoBIM.Arcade.exe` (win-x64). No Revit or
  pyRevit reference, so one build covers Revit 2023, 2024, 2025, 2026 and 2027, and it runs with
  Revit closed.
- **Game contract.** `IArcadeGame` (`Key`, `DisplayName`, `Start(GameHost)`, `Stop()`, optional
  `Hints`). A game is one folder under `Games\` and one line in `GameRegistry`.
- **Shared services.** Game loop, input, score and settings storage, theme, window shell,
  shrink-to-taskbar drawer, launch parsing, single instance.
- **Launch contract.** `--game <key> --theme <light|dark> [--owner-x --owner-y --owner-w --owner-h]`.
  No arguments or an unknown key shows the picker. Bad input is ignored, never fatal.
- **Single instance.** A named mutex. A second launch passes its game key to the running window
  and exits.
- **Themes.** Dark (#3B4453 body, #333B49 cards, #222933 bars, #F5F5F5 text, #2D5B80 selection)
  and light (the Sheet Manager light palette), as two brush dictionaries. No literal colours in
  layouts.
- **Shrink to the taskbar.** Ported from the Addin Manager drawer: slides down to a floating bar,
  the button becomes a green up arrow, Esc / Enter / F11 / Ctrl+Shift+H / double click reopen it.
- **Logo easter egg.** Three slow clicks (each 250 ms to 2000 ms after the last), the same rule as
  the Revit side. It returns to the game picker.
- **Hello** placeholder game (a bouncing square) proves the registry and launch path.
- **Storage.** `%APPDATA%\RevoBIM\arcade\settings.json` and `scores.<game>.json`. The old
  `easter_egg*.txt` files are not read; scores start fresh.
- **Bench.** `tools\selftest.ps1` (logic, repo and launch checks).
