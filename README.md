# RevoBIM Tools

Revit add-in by RevoBIM LTD for building services BIM, for **Revit 2024, 2025, 2026 and 2027**.

## Download

[![Download RevoBIM Tools 0.3.0](https://img.shields.io/badge/Download-RevoBIM%20Tools%200.3.0-2EA44F?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/RevoBIM/RevoBIM.Revit/releases/download/v0.3.0/RevoBIM_Tools-0.3.0.exe)

**Build 0.3.0** · released 16 November 2026 · [all releases](https://github.com/RevoBIM/RevoBIM.Revit/releases)

## Install

1. Close every Revit window.
2. Run `RevoBIM_Tools-0.3.0.exe` and pick the Revit versions to install for. No admin rights are needed.
3. Start Revit. The tools are on the **RevoBIM** tab. **About**, on the right of the tab, shows the installed version and its release date.

Installing a newer version replaces the old one.

## Change log

### 0.3.0 — 16 November 2026

Four new tools, and a clearer installer. Install it over 0.2.x.

**New tools**
- **Excel for Revit** — under Management: opens a schedule as an editable spreadsheet grid. Instance parameters are blue, type parameters orange, read-only cells light red. Copy and paste, fill down, drag to sequence, formulas, numbering, prefixes, highlighting, find and replace, filters, sorting and grouping, undo and redo, in a dark or light theme. Export to Excel for editing or issuing, and import the edited workbook back. Nothing is written to the model until Apply, which runs every edit in one transaction.
- **Model Cleanup** — under Management: syncs the model, saves a detached copy, then removes links and unplaced views and purges the copy, ready to send. The live model is never cleaned.
- **Nudge Up / Nudge Down / Nudge Settings** — under Coordination, and in a Nudge group on the Modify tab: raise or lower elements by a set increment (default 50mm). Select elements first, or run with nothing selected and click elements one by one until Escape. Nudge Settings sets the increment and how the buttons behave.

**Changed**
- **Installer** — the "What is included" page is now a scrollable list of every tool with a small icon, grouped by ribbon panel, so it keeps working as more tools are added.
### 0.2.1 — 15 November 2026

Maintenance release. No change to how the tools work: install it over 0.2.0.

### 0.2.0 — 15 November 2026

First public release. One installer for Revit 2024, 2025, 2026 and 2027.

**New tools**
- **Pro Sheets Exporter** — batch export sheets and views to PDF, DWG, NWC and IFC with file names built from sheet parameters, parameter-driven folders and templates saved per project. Includes the Document Register with Excel export.
- **Revision Manager** — add, edit, reorder, merge and delete revisions, with sheet counts, a search on every column and your own revision columns. Nothing is written until Apply.
- **RevoBIM Arcade** — under Coordination › Routines: Pacman, Tetris and Snake.

**New**
- **Express Export** (Revit 2025+) — right-click selected sheets: exported with the last Pro Sheets template, no prompts, a progress strip at the bottom of the screen, and the folder opens when done.
- **Print in ProSheets** (Revit 2025+) — right-click entry that opens Pro Sheets with the selected sheets ticked.
- **Modify tab** — a RevoBIM group with Pro Sheets Exporter and Revision Manager while a sheet or view is selected.
- **About** — installed build version and release date.
- **Installer** — pick the Revit versions, checks Revit is closed, replaces any earlier install.

**Changed**
- Opening Pro Sheets with sheets selected ticks them and scrolls to them, with every other sheet still showing.

Earlier versions: see [CHANGELOG.md](CHANGELOG.md).

## Tools

| Tool | Where |
|------|-------|
| Excel for Revit | RevoBIM tab › Management |
| Model Cleanup | RevoBIM tab › Management |
| Nudge Up / Nudge Down / Nudge Settings | RevoBIM tab › Coordination; Modify tab › Nudge |
| Legend Creator | RevoBIM tab › Project |
| Pro Sheets Exporter | RevoBIM tab › Sheet Tools; Modify tab › RevoBIM (sheet or view selected); right-click › Print in ProSheets (2025+) |
| Express Export | Right-click on selected sheets (Revit 2025+) |
| Revision Manager | RevoBIM tab › Sheet Tools; Modify tab › RevoBIM |
| RevoBIM Arcade | RevoBIM tab › Coordination › Routines |
