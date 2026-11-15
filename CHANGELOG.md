# Changelog

All notable changes to RevoBIM Tools. The installer for each version is on the
[Releases page](https://github.com/RevoBIM/RevoBIM.Revit/releases).

## 0.2.0 — 15 November 2026

First public release. One installer for **Revit 2024, 2025, 2026 and 2027**.

### New tools
- **Pro Sheets Exporter** — batch export sheets and views to PDF, DWG, NWC and IFC with file names built from sheet parameters, parameter-driven folders and templates saved per project. Includes the Document Register with Excel export. Shares settings and templates with the pyRevit version.
- **Revision Manager** — add, edit, reorder, merge and delete revisions, with sheet counts, a search on every column and your own revision columns. Nothing is written until Apply.
- **RevoBIM Arcade** — under Coordination › Routines: Pacman, Tetris and Snake.

### New
- **Express Export** (Revit 2025+) — right-click selected sheets in the Project Browser: exported with the last Pro Sheets template, no prompts, a progress strip at the bottom of the screen, and the folder opens when done.
- **Print in ProSheets** (Revit 2025+) — right-click entry that opens Pro Sheets with the selected sheets ticked.
- **Modify tab** — a RevoBIM group with Pro Sheets Exporter and Revision Manager appears while a sheet or view is selected.
- **About** — on the right of the RevoBIM tab: installed build version and release date.
- **Installer** — dark-themed setup wizard: pick the Revit versions, checks Revit is closed, replaces any earlier install. No admin rights needed.

### Changed
- Opening Pro Sheets with sheets selected now ticks them and scrolls to them, with every other sheet still showing (untick *Show all* to isolate them).
- The add-in is now `RevoBIM.Revit.dll`, built separately for each Revit version.

## 0.1.0

- Legend Creator (Revit 2024 only, internal build).
