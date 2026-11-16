# Conversion tracker

Status values: Not started, Converted (built, not yet tried in Revit), Tested (works in Revit 2024).

| Tool | pyRevit panel | Status | Notes |
|------|---------------|--------|-------|
| Number Sequencer | Annotation | Not started |  |
| Settings | Annotation | Not started | In Smart Dimensions pulldown. |
| Smart Dimensions | Annotation | Not started | In Smart Dimensions pulldown. |
| Tag Align Center | Annotation | Not started | In Tag Align stack. |
| Tag Align Left | Annotation | Not started | In Tag Align stack. |
| Tag Align Right | Annotation | Not started | In Tag Align stack. |
| Tag All | Annotation | Not started |  |
| RevoBIM Tag Tidy Settings | Annotation | Not started | In Tag Tidy pulldown. |
| RevoBIM Tag Tidy | Annotation | Not started | In Tag Tidy pulldown. |
| Tag Aligner Settings | Annotation | Not started | In Tag Untangle stack. |
| Tag Untangle Horizontal | Annotation | Not started | In Tag Untangle stack. |
| Tag Untangle Vertical | Annotation | Not started | In Tag Untangle stack. |
| BWIC ID Push | BWIC Tools | Not started |  |
| BWIC Penetration | BWIC Tools | Not started |  |
| 3D Extend Settings | Coordination | Not started | In 3D Extend Tools pulldown. |
| 3D Extend | Coordination | Not started | In 3D Extend Tools pulldown. |
| ClashAnalysis | Coordination | Not started |  |
| Find in View | Coordination | Not started |  |
| Match Offset Bottom | Coordination | Not started | In Match Offset pulldown. |
| Match Offset Middle | Coordination | Not started | In Match Offset pulldown. |
| Match Offset Settings | Coordination | Not started | In Match Offset pulldown. |
| Match Offset Slope | Coordination | Not started | In Match Offset pulldown. |
| Match Offset Top | Coordination | Not started | In Match Offset pulldown. |
| Centreline Snap | Coordination | Not started | In MEP Link pulldown. |
| Corner Link | Coordination | Not started | In MEP Link pulldown. |
| Link Settings | Coordination | Not started | In MEP Link pulldown. |
| Riser Link | Coordination | Not started | In MEP Link pulldown. |
| 3D Align | Coordination | Not started | In Routines pulldown. |
| Bulk Rename | Coordination | Tested | v1.1.0 port, in the Routines pulldown. Rules and settings in `Tools\BulkRename\BrnCore.cs`, Revit reading and the write (rename, parking for swaps, sheet-name write, `BrnRunner` ExternalEvent) in `BrnRevit.cs`; windows in `UI\BulkRename\` (pyRevit XAML verbatim in `Layouts\`; `BrnChrome.cs` = brn_chrome/brn_drawer/brn_theme, `BrnWindow.cs` = brn_main, `BrnDialogs.cs`, `BrnMain.cs` = brn_app). Shares `%APPDATA%\RevoBIM\bulk_rename.txt`, `bulk_rename_debug.txt` and `bulk_rename_last_error.txt` with the pyRevit version. Also on the right-click menu ("Run Bulk Rename", Revit 2025+) when two or more renamable items are selected (`Commands\RevoBimContextMenu.cs`, not yet tried in Revit). Logo easter egg armed on the main window's logo. Not ported: the bench scripts (`bench_logic.py`, `import_check.py`, `bench_stubs.py`) and the pyRevit-lib egg loader. Not yet tried in Revit. |
| Duct Accessory Resize | Coordination | Not started | In Routines pulldown. |
| Elevation Push | Coordination | Not started | In Routines pulldown. |
| Explode Import Symbol Multiple | Coordination | Not started | In Routines pulldown. |
| Family Param Push | Coordination | Not started | In Routines pulldown. |
| Family Parameter Changer | Coordination | Not started | In Routines pulldown. |
| Find Room | Coordination | Not started | In Routines pulldown. |
| Fire Damper Wall Type Push | Coordination | Not started | In Routines pulldown. |
| Hide Service Type | Coordination | Not started | In Routines pulldown. |
| Isolate Service Type | Coordination | Not started | In Routines pulldown. |
| Isolate Svc Settings | Coordination | Not started | In Routines pulldown. |
| Pipe Slope Assigner | Coordination | Not started | In Routines pulldown. |
| QFR Remover | Coordination | Not started | In Routines pulldown. |
| Reset Hide | Coordination | Not started | In Routines pulldown. |
| RevoBIM Arcade | Coordination | Tested | In Routines pulldown (the C# Routines dropdown holds only this so far). Not a port of the Python code: Revit launches the standalone `RevoBIM.Arcade.exe` (own solution, `RevoBIM.Arcade\`). Shift-click diagnostic report not ported. |
| RevoBIM Tag Elbow Settings | Coordination | Not started | In Routines pulldown. |
| RevoBIM Tag Leader Elbow | Coordination | Not started | In Routines pulldown. |
| Selected in View | Coordination | Not started | In Routines pulldown. |
| Sheet Name Push | Coordination | Tested | Folded into Bulk Rename as its third tab, "Parameter Push" (shown when sheets are selected): three target parameters, the split character and the text format (UPPERCASE / Camel Case / none) set on the tab, a live preview per sheet, and a results window after the push. Uses Bulk Rename's settings (`sheet_param_1..3`, `sheet_delimiter`, `sheet_format` in `bulk_rename.txt`), not `sheet_management.txt`. A name with fewer parts than parameters blanks the rest (as Bulk Rename's Write Sheet names did), and parts past the third stay in the third. Not ported: the standalone sheet browser, in-grid editing, duplicate-number filter and its own Find/Replace and Prefix/Suffix windows (Bulk Rename's Sheet Name and Sheet Number tabs cover renaming). No separate ribbon button. Not yet tried in Revit. |
| Space Data Push | Coordination | Not started | In Routines pulldown. |
| Space Name To Element | Coordination | Not started | In Routines pulldown. |
| VlookUp | Coordination | Not started | In Routines pulldown. |
| Service Spacing | Coordination | Not started | In Service Spacing pulldown. |
| Settings | Coordination | Not started | In Service Spacing pulldown. |
| Nudge Down | Coordination | Tested | Small button in the Coordination panel (stack3 stack) and a large button in an always-visible "Nudge" panel on the Modify tab (`UI\Ribbon\ModifyTabPanel.cs`). Code in `Tools\Nudge\NudgeEngine.cs`; both not yet tried in Revit. |
| Nudge Settings | Coordination | Tested | Window in `UI\Nudge\`, pyRevit XAML kept. Settings now in `%APPDATA%\RevoBIM\nudge_settings.json` (same keys; the pyRevit file in `%APPDATA%\RevoBIM PY\` is read once if the new one does not exist). Shortcuts are written to KeyboardShortcuts.xml as before, matched by button id. Logo easter egg armed. Not yet tried in Revit. No installer card yet (the What is included page has no room for a fourth). |
| Nudge Up | Coordination | Tested | See Nudge Down. |
| RevoBIM Clash Offset | Coordination | Not started | In System Offset Tools pulldown. |
| RevoBIM Click System | Coordination | Not started | In System Offset Tools pulldown. |
| RevoBIM Offset Break | Coordination | Not started | In System Offset Tools pulldown. |
| RevoBIM System Offset Settings | Coordination | Not started | In System Offset Tools pulldown. |
| RevoBIM System Offset | Coordination | Not started | In System Offset Tools pulldown. |
| Circuit Manager | Electrical | Not started |  |
| Containment System Creator | Electrical | Not started |  |
| Panel Template Mngr | Electrical | Not started |  |
| Align Wire Ends | Electrical | Not started | In Wires pulldown. |
| Apply Wire Types | Electrical | Not started | In Wires pulldown. |
| Auto Wire | Electrical | Not started | In Wires pulldown. |
| Reconnect Wires | Electrical | Not started | In Wires pulldown. |
| Re-Route Wires | Electrical | Not started | In Wires pulldown. |
| Settings | Electrical | Not started | In Wires pulldown. |
| Hanger Automation | FAB Automation | Not started |  |
| Excel for Revit | Management | Tested | v1.20.0 port, builds on R24/R25/R26/R27. Logic in `Tools\ExcelForRevit\` (`Efr*.cs`: core/palette, params, `ScheduleModel`, levels, `WorkHandler`, fill and formula engine, own xlsx writer/reader and Excel round trip), WPF in `UI\ExcelForRevit\` (`ExcelForRevitWindow*.cs` partial class, `EfrDialogs*.cs`, `EfrUi.cs` toolkit, `EfrMain.cs` entry), pyRevit XAML embedded verbatim in `UI\ExcelForRevit\Layouts\`. Shares `%APPDATA%\RevoBIM PY\excel_for_revit_settings.json` with the pyRevit version; failure log at `%APPDATA%\RevoBIM\logs\excel_for_revit_last_error.txt`. Not ported: the IronPython-engine liveness machinery (modeless proof, `check_modeless_health`, `migrate_window_settings`); the modeless/modal toggle stays. Logo easter egg armed on the logo and wordmark. Python benches (`import_check.py`, `bench_logic.py`, `xlsx_check.py`) not ported. |
| Family Editor Tools | Management | Not started |  |
| Family Find Replace | Management | Not started |  |
| Family Management Placer | Management | Not started |  |
| Family Viewer | Management | Not started |  |
| Filter Manager | Management | Converted | v3.31.0 port, builds on R24/R25/R26/R27. Logic in `Tools\FilterManager\` (`FmCore`, `FmFilters` = fm_filters.py, `FmOverrides`, `FmColour`, `FmNames`, `FmTheme`, `FmXlsx`, `FmEvents` = the ExternalEvent runner), windows in `UI\FilterManager\`: the pyRevit XAML is embedded verbatim in `Layouts\` and `FmXaml.cs` wires its 130 `on_*` handlers to `OnXxx` methods by name; `FmWindow*.cs` is one partial class split by tab (Manager, Table, Pusher), `FmDialogs.cs` holds the Done / Create / Rename / Colour / Override dialogs, `FmDrawer.cs` the shrink-to-title-bar drawer. Modeless window; a second ribbon press brings it back. Shares `%APPDATA%\RevoBIM\filter_manager_layout.txt` and `filter_manager_last_run.txt` with the pyRevit version; run logs go to `Documents\RevoBIM\Logs` (the pyRevit tool used `Documents\RevoBIM PY\Logs`). Logo easter egg armed on the logo (`EggHook`). Not ported: the bench scripts (`bench_logic.py`, `import_check.py`) and the pyRevit-lib egg loader. Not yet tried in Revit. |
| Level Manager | Management | Not started |  |
| MEP System Manager | Management | Not started |  |
| Model Cleanup | Management | Tested | v2.0.0 port, builds on R24/R25/R26/R27. Rules in `Tools\ModelCleanup\` (`McuCore.cs` = mcu_core.py, `McuModel`, `McuOps`, `McuNwc`, `McuAps`/`McuWeb` = ACC publish, `McuRunner` = the ExternalEvent queue), windows in `UI\ModelCleanup\` (pyRevit XAML verbatim in `Layouts\`, loaded at runtime). Modeless window; a second ribbon press brings it back. Shares `%APPDATA%\RevoBIM\model_cleanup*.txt` and the templates folder with the pyRevit version. ACC refresh token is DPAPI-encrypted when the runtime has it (net48 yes; on .NET 8+ it is looked up by reflection and, if missing, the sign-in lasts for the session only). Logo easter egg armed on the main window and Export Settings. Not ported: bench_logic.py / import_check.py (pyRevit test scripts). |
| ParaManager | Management | Not started |  |
| Project Browser Pro | Management | Not started |  |
| RevoBIM Addin Manager | Management | Not started |  |
| Space Creator | Management | Not started |  |
| Style Manager | Management | Not started |  |
| Unhide in View | Management | Not started |  |
| View Template Manager | Management | Not started |  |
| ViewManager | Management | Not started |  |
| Workset Management | Management | Not started |  |
| ClickToRVT | Point Cloud | Not started |  |
| Legend Creator | Project | Tested | Logo easter egg armed (icon and RevoBIM word). v3.0.0 port. Code in `Tools\LegendCreator\`, windows in `UI\LegendCreator\`. Shares `%APPDATA%\RevoBIM\legend_creator.txt` with the pyRevit version. pyRevit progress bar replaced by a themed progress window. Debug report drops the pyRevit/IronPython lines and API-by-name probes. |
| DWG Block Replace | Schematic | Not started |  |
| Schematic Builder | Schematic | Not started |  |
| Schematic Marriage | Schematic | Not started |  |
| Auto RevCloud | Sheet Tools | Not started |  |
| Callout to 3D | Sheet Tools | Not started |  |
| Pro Sheets Exporter | Sheet Tools | Tested | v1.56.1 port. Code in `Tools\ProSheets\`, windows in `UI\ProSheets\` (pyRevit XAML embedded verbatim in `UI\ProSheets\Layouts\`, loaded at runtime). Shares settings, profiles, templates and register files under `%APPDATA%\RevoBIM\` with the pyRevit version. Right-click menu (Revit 2025+, `Commands\RevoBimContextMenu.cs`, one creator for every RevoBIM entry): "Open in ProSheets" (was "Print in ProSheets"), "Express Export" and, with two or more renamable Project Browser items selected, "Run Bulk Rename". If the pyRevit RevoBIM PY extension is still loaded its own "Print in ProSheets" (from its `startup.py`) shows as a second group above these: that one is not built by this add-in. "Express Export" (selected sheets, last template, no prompts, floating progress strip, opens the folder; `UI\ProSheets\PsExpress.cs`) - added after testing, not yet tried in Revit. Also on the Modify tab ("RevoBIM" panel with Revision Manager, shown while a sheet or view is selected; `UI\Ribbon\ModifyTabPanel.cs`, via AdWindows) - not yet tried in Revit. Not ported: Express print from Project Browser Pro (PBP not converted). Logo easter egg: armed on the main window (and on Revision Manager when opened from its own button), opens the RevoBIM Arcade. |
| Revision Manager | Sheet Tools | Tested | Shares Pro Sheets Exporter's code (`UI\ProSheets\PsRevWin*.cs`, `Tools\ProSheets\PsRevisions*.cs`, `PsRevData.cs`). Revision data in Extensible Storage uses the same schema as the pyRevit version. |
| Sheet Manager | Sheet Tools | Not started |  |
