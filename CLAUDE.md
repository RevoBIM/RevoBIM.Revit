# RevoBIM.Revit

C# Revit add-in ("RevoBIM Tools") for Revit 2024, 2025, 2026 and 2027, being converted tool-by-tool from the pyRevit extension "RevoBIM PY". Owner: A² Services LTD (building services BIM).

## Build and deploy
- One project (`RevoBIM.Revit\RevoBIM.Revit.csproj`, assembly `RevoBIM.Revit.dll`), one build per Revit version, chosen by configuration:
  `Debug R24`/`Release R24` = Revit 2024, net48; `R25` and `R26` = net8.0-windows; `R27` = net10.0-windows. Plain `Debug`/`Release` = Revit 2024.
  The symbol `REVIT2024` / `REVIT2025` / `REVIT2026` / `REVIT2027` is defined for the build, for the rare `#if` where the API differs.
- The Revit API comes from the Nice3point NuGet packages (`Nice3point.Revit.Api.RevitAPI` / `RevitAPIUI`), the version matching the build (set in the csproj). Do not reference DLLs from `C:\Program Files\Autodesk\Revit 20xx`. Never copy Revit DLLs into the output; check `bin\` after changing references.
- Build one version: `dotnet build RevoBIM.Revit.sln -c "Debug R24"` (or MSBuild). Fix compile errors yourself and rebuild. Code must compile for all four versions: build each configuration before committing.
- A post-build target deploys per-user, no admin rights: DLL to `%AppData%\RevoBIM\<year>\`, manifest `RevoBIM.addin` to `%AppData%\Autodesk\Revit\Addins\<year>\`.
- Installer: `installer\build-installer.ps1` builds all four Release configurations and `dist\RevoBIM-Setup-<version>.exe` (Inno Setup, `installer\RevoBIM.iss`), which installs every version.
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
- Use API that exists in all of Revit 2024-2027. Where it does not (e.g. members removed in 2026), use `#if REVIT2024 ... #else ... #endif` and note it. Revit 2025+ runs on .NET 8/10: no .NET Framework-only APIs (BinaryFormatter, AppDomain tricks, code page encodings other than UTF-8/Latin-1, Process.Start on a document without UseShellExecute = true).

## pyRevit source (read-only)
- `_pyrevit-source\` holds copies of the original pyRevit tools. Never edit or delete anything in it. Read it to understand what a tool does.
- The user names a tool by its folder name (e.g. "Level Manager"). If two tools match, ask which one.

## Workflow
- Convert one tool per session. Do not start the next tool unprompted.
- Track progress in `CONVERSION.md`: update a tool's status when you convert it (Not started, Converted, Tested). The user sets Tested after trying it in Revit.
- Commit to git after each tool builds, with a message naming the tool. Initialise the repo if there isn't one (`bin/` and `obj/` are already ignored).
- When the user corrects a repeated mistake, offer to add a rule to this file.
