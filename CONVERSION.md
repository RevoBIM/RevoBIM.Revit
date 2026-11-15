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
| Bulk Rename | Coordination | Not started | In Routines pulldown. |
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
| RevoBIM Arcade | Coordination | Converted | In Routines pulldown (the C# Routines dropdown holds only this so far). Not a port of the Python code: Revit launches the standalone `RevoBIM.Arcade.exe` (own solution, `RevoBIM.Arcade\`). Shift-click diagnostic report not ported. |
| RevoBIM Tag Elbow Settings | Coordination | Not started | In Routines pulldown. |
| RevoBIM Tag Leader Elbow | Coordination | Not started | In Routines pulldown. |
| Selected in View | Coordination | Not started | In Routines pulldown. |
| Sheet Name Push | Coordination | Not started | In Routines pulldown. |
| Space Data Push | Coordination | Not started | In Routines pulldown. |
| Space Name To Element | Coordination | Not started | In Routines pulldown. |
| VlookUp | Coordination | Not started | In Routines pulldown. |
| Service Spacing | Coordination | Not started | In Service Spacing pulldown. |
| Settings | Coordination | Not started | In Service Spacing pulldown. |
| Nudge Down | Coordination | Not started | In stack3 stack. |
| Nudge Settings | Coordination | Not started | In stack3 stack. |
| Nudge Up | Coordination | Not started | In stack3 stack. |
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
| Excel for Revit | Management | Not started |  |
| Family Editor Tools | Management | Not started |  |
| Family Find Replace | Management | Not started |  |
| Family Management Placer | Management | Not started |  |
| Family Viewer | Management | Not started |  |
| Filter Manager | Management | Not started |  |
| Level Manager | Management | Not started |  |
| MEP System Manager | Management | Not started |  |
| Model Cleanup | Management | Not started |  |
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
| Legend Creator | Project | Converted | Logo easter egg armed (icon and RevoBIM word). v3.0.0 port. Code in `Tools\LegendCreator\`, windows in `UI\LegendCreator\`. Shares `%APPDATA%\RevoBIM\legend_creator.txt` with the pyRevit version. pyRevit progress bar replaced by a themed progress window. Debug report drops the pyRevit/IronPython lines and API-by-name probes. |
| DWG Block Replace | Schematic | Not started |  |
| Schematic Builder | Schematic | Not started |  |
| Schematic Marriage | Schematic | Not started |  |
| Auto RevCloud | Sheet Tools | Not started |  |
| Callout to 3D | Sheet Tools | Not started |  |
| Pro Sheets Exporter | Sheet Tools | Tested | v1.56.1 port. Code in `Tools\ProSheets\`, windows in `UI\ProSheets\` (pyRevit XAML embedded verbatim in `UI\ProSheets\Layouts\`, loaded at runtime). Shares settings, profiles, templates and register files under `%APPDATA%\RevoBIM\` with the pyRevit version. Not ported: Express print from Project Browser Pro (PBP not converted), "Print in ProSheets" right-click entry (Revit 2025+ only). Logo easter egg: armed on the main window (and on Revision Manager when opened from its own button), opens the RevoBIM Arcade. |
| Revision Manager | Sheet Tools | Tested | Shares Pro Sheets Exporter's code (`UI\ProSheets\PsRevWin*.cs`, `Tools\ProSheets\PsRevisions*.cs`, `PsRevData.cs`). Revision data in Extensible Storage uses the same schema as the pyRevit version. |
| Sheet Manager | Sheet Tools | Not started |  |
