# Changelog

All notable changes to RevoBIM Tools. The installer for each version is on the
[Releases page](https://github.com/RevoBIM/RevoBIM.Revit/releases).

## 0.6.5 — 23 November 2026

Keyboard shortcuts, tidier Modify tab, and Hanger Automation updates. Install it over any earlier version.

**New**
- **Keyboard shortcuts** — the installer can set them in Revit (ticked by default): **XS** Pro Sheets Exporter, **R5** Revision Manager, **H6** Hanger Automation, **NU** Nudge Up, **ND** Nudge Down. A shortcut already on another command moves to the RevoBIM one, and your old shortcuts file is kept as a backup. A Revit version that has never saved its shortcuts is skipped: start it once, change any shortcut, close it, and run the installer again.
- **Routines** dropdown has its own icon.

**Changed**
- **Modify tab** — the RevoBIM group (Pro Sheets Exporter, Revision Manager) shows only while a sheet or view is selected: in the Project Browser, a view on a sheet, or a sheet's title block picked in the sheet view. The Nudge group shows only while model elements are selected. Both stay hidden otherwise.
- **Pro Sheets Exporter** — opening it with sheets selected ticks them and shows only those sheets (tick *Show all* for the rest); right-click *Open in ProSheets* on views opens the Views list filtered to them.
- **Hanger Automation** — faster Finish Selection and window opening; family list grouped by family with style symbols; a prompt for circular hangers on rectangular services; symbol-level centre elevation lock; service type parameter chooser.

Versions 0.4.0 to 0.5.3 are described on the Releases page.

## 0.3.0 — 16 November 2026

Four new tools, and a clearer installer. Install it over 0.2.x.

**New tools**
- **Excel for Revit** — under Management: opens a schedule as an editable spreadsheet grid. Instance parameters are blue, type parameters orange, read-only cells light red. Copy and paste, fill down, drag to sequence, formulas, numbering, prefixes, highlighting, find and replace, filters, sorting and grouping, undo and redo, in a dark or light theme. Export to Excel for editing or issuing, and import the edited workbook back. Nothing is written to the model until Apply, which runs every edit in one transaction.
- **Model Cleanup** — under Management: syncs the model, saves a detached copy, then removes links and unplaced views and purges the copy, ready to send. The live model is never cleaned.
- **Nudge Up / Nudge Down / Nudge Settings** — under Coordination, and in a Nudge group on the Modify tab: raise or lower elements by a set increment (default 50mm). Select elements first, or run with nothing selected and click elements one by one until Escape. Nudge Settings sets the increment and how the buttons behave.

**Changed**
- **Installer** — the "What is included" page is now a scrollable list of every tool with a small icon, grouped by ribbon panel, so it keeps working as more tools are added.
## 0.2.1 — 15 November 2026

Maintenance release. No change to how the tools work: install it over 0.2.0.

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
