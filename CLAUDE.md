# RevoBIM.Revit2024

C# Revit add-in ("RevoBIM Tools") for Revit 2024, being converted tool-by-tool from the pyRevit extension "RevoBIM PY". Owner: A² Services LTD (building services BIM).

## Build and deploy
- Target: .NET Framework 4.8 (net48), Revit 2024 API only. Revit API DLLs are referenced from `C:\Program Files\Autodesk\Revit 2024` with Copy Local = false. Never copy Revit DLLs into the output.
- Build: `dotnet build RevoBIM.Revit2024.sln` (or MSBuild). Fix compile errors yourself and rebuild.
- A post-build target deploys per-user, no admin rights: DLL to `%AppData%\RevoBIM\2024\`, manifest `RevoBIM.addin` to `%AppData%\Autodesk\Revit\Addins\2024\`.
- Revit locks the DLL while running. If the copy step fails, ask the user to close Revit, then rebuild. The user must restart Revit to load a new build.
- You cannot run Revit. After a build, tell the user exactly what to click and what to report back.

## Structure and conventions
- `App.cs` (`RevoBIM.App`, IExternalApplication) builds the ribbon: tab "RevoBIM", panels mirror the pyRevit tab/panel layout.
- One command class per tool in `Commands\`, namespace `RevoBIM.Commands`, following `Commands\LegendCreatorCommand.cs`. Add the tool's button to `App.cs`.
- Wrap every model change in a `Transaction` (or `TransactionGroup`) with a clear name; use `using` and roll back on failure. Commands use `[Transaction(TransactionMode.Manual)]`.
- A tool's own non-UI code (logic, model reading, building) goes in `Tools\<Tool>\`, namespace `RevoBIM.Tools.<Tool>` (e.g. `Tools\LegendCreator\`). Keep the command class in `Commands\` thin: it runs the flow and calls into `Tools\<Tool>\`.
- Shared helpers go in `Helpers\` once two or more tools need them. Convert a helper once and reuse it.
- WPF windows (pyRevit XAML forms) go in `UI\<Tool>\`, namespace `RevoBIM.UI.<Tool>`. Convert these after the simpler tools.
- Keep behaviour identical to the pyRevit original unless the user asks otherwise. Preserve tooltips and icons (icons go in `Resources\<Tool>\`, embedded resources named `RevoBIM.Resources.<Tool>.icon.png` / `icon.dark.png`).
- Revit 2024 API only for now. Do not use APIs removed or changed in later versions without noting it.

## pyRevit source (read-only)
- `_pyrevit-source\` holds copies of the original pyRevit tools. Never edit or delete anything in it. Read it to understand what a tool does.
- The user names a tool by its folder name (e.g. "Level Manager"). If two tools match, ask which one.

## Workflow
- Convert one tool per session. Do not start the next tool unprompted.
- Track progress in `CONVERSION.md`: update a tool's status when you convert it (Not started, Converted, Tested). The user sets Tested after trying it in Revit.
- Commit to git after each tool builds, with a message naming the tool. Initialise the repo if there isn't one (`bin/` and `obj/` are already ignored).
- When the user corrects a repeated mistake, offer to add a rule to this file.
