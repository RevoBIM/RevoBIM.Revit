# Hanger Automation - code map

One line per file: what lives there. Paths are relative to `RevoBIM.Revit\`. Classes split over several files are
`partial`; a `X.Topic.cs` file holds part of class `X`. Pyrevit original: `_pyrevit-source\...\Hanger Automation.pushbutton\`.

## Entry and window
- `Commands\HangerAutomationCommand.cs` - ribbon command: `Execute` opens `FhaWindow.Show`, `Report` on failure.
- `UI\HangerAutomation\FhaWindow.cs` - `FhaWindow` (modeless window, 4 tabs): static state (`Tabs`, `JobButtons`, `Checks`, `OpenTiming`), view hook (`HookViews`, `ViewActivated`), fields, constructor, `OpenLaps` open timing, `C`, entry `Show`.
- `UI\HangerAutomation\FhaWindow.Setup.cs` - population (`FillLists`, `LoadControls`, `Gather`, `Save`, `FamTabs`), theme (`Theme`, `CycleTheme`), `Wire`, tabs (`ShowTab`, `ApplyTab`), drawer body (`BodyParts`, `ShowBody`, `ShrinkClick`), fold / fit (`ResizeForFold`, `FoldResized`, `Fit`, `ContentRendered`).
- `UI\HangerAutomation\FhaWindow.Finish.cs` - the Finish Selection card: `OnFinishRequest`, `ApplyFinish`, `SyncFinish`, `GrowForFinish`, `ShrinkForFinish`, `FinishClick`.
- `UI\HangerAutomation\FhaWindow.Events.cs` - tab clicks, `Status`, `HeaderDown`, `FullClick`, `CloseClick`, FAB job buttons (`RehostClick`, `ExtendClick`, `PlaceClick`, `RodCatsClick`, `InspectLockClick`), `Key`, `Close`, `Closed`, `CopyDebug`.
- `UI\HangerAutomation\FhaWindow.Jobs.cs` - running a job: `SetBusy`, `Start`, `JobExtra`, `Queue`, `StartJob`, `StartQuiet`, watchdog timer, `Finished` (results box + debug file).
- `UI\HangerAutomation\FhaHandler.cs` - `FhaHandler` IExternalEventHandler: `Execute` runs the queued job, `OnDialog`.
- `UI\HangerAutomation\FhaUi.cs` - `IFhaHost`, `FhaUi` helpers: XAML loading, palette / styles, icon, `AttachEgg`, parking / dialog placement, `AnimateHeight`, `FillWorksetCombo`.
- `UI\HangerAutomation\FhaUiChrome.cs` - `FhaChrome`: resize grips, header drag, DPI / work area, full-screen toggle.
- `UI\HangerAutomation\FhaUiDrawer.cs` - `FhaDrawer`: shrink to a title bar at the taskbar and expand back.
- `UI\HangerAutomation\FhaUiCollapser.cs` - `Collapser`: foldable tool sections, open/closed state.

## UI tabs and dialogs
- `UI\HangerAutomation\HfamUi.cs` - `IFamOwner`, `FamParams`, `FamRow`; `FamTab` (Family Hangers + Floor Support tabs): static control tables (`FamChecks`, `FamBoxes`, `FamButtons`, `RodControls`), fields, constructor, `C`, `K`, `Load`, `Gather`, `Wire`.
- `UI\HangerAutomation\HfamUi.Controls.cs` - `FamTab`: list grip drag (`ListDrag`, `ListDropped`), `Mirror` / `MirrorSel`, folding (`ToggleAll`, `FoldChanged`), `RulesClick`, `SetBusy`, `SetViewOk`, `DebugText`.
- `UI\HangerAutomation\HfamUi.List.cs` - `FamTab` family list: `Ent`, `Refill` (grouped by family), `BuildRow` (style symbols), `PaintRows`, `Current`, `Picked`, `CfgFor`, `ChosenChanged`, preview (`RequestPreview`, `GotPreview`, `ShowPreview`).
- `UI\HangerAutomation\HfamUi.Jobs.cs` - `FamTab`: `RefreshClick` / `GotList`, family settings (`SettingsClick`, `ParamsResult`, `OpenSettings`), `JobExtra`, `Run`, `AskSetup`, `Circular`, tool buttons (Place, Realign, Auto, Swap, RodCats, Rods, Dims).
- `UI\HangerAutomation\HfamDialogs.cs` - `RulesDialog` (grouping rules), `FamSettingsDialog` (per-family parameters / style).
- `UI\HangerAutomation\HfamRodCats.cs` - `RodCatsDialog`: categories a drop rod may run up to (`ext_extra`).
- `UI\HangerAutomation\HsvcUi.cs` - `ISvcOwner`, `SvcTab` (Service Type tab): parameter chooser (`ParamChoice`, `FillParams`, `ParamChanged`), scan, grouped list, sort, apply / show / reset.
- `UI\HangerAutomation\HviewUi.cs` - `Prompt` (button prompt), `DimViewsDialog` + `DimViewsUI` (`ChooseDimViews`, `AskBasePick`, `AskOpen`).
- `UI\HangerAutomation\Layouts\` - XAML: `HangerAutomation.xaml` (main window), `Theme.xaml`, `HangerDimViews.xaml`, `HangerFamilySettings.xaml`, `HangerPrompt.xaml`, `HangerRodCats.xaml`, `HangerRules.xaml`.

## Jobs - FAB hangers
- `Tools\HangerAutomation\FhaRevit.cs` - `FhaRevit` basics: element tests (`IsFab`, `IsHanger`, `IsDuct`...), transactions (`StartTxn`, `WarningSwallower`), selection filter, `Worksets`, formatting.
- `Tools\HangerAutomation\FhaRevit.Jobs.cs` - `JobPlace`, `JobRehost`, `JobExtend`; `PlaceSpec`, `PlaceJob`, `RehostPlan`.
- `Tools\HangerAutomation\FhaRevit.Hangers.cs` - FAB buttons (`HangerButtons`, `ButtonPicker`, `ButtonFor`), `HangerMatcher`, service comment / labels, `CreateHanger`, `PlaceOnHost`, `ReplaceHanger`, rod tops.
- `Tools\HangerAutomation\FhaRevit.Rods.cs` - FAB rod extension: `ExtendRods`, `Soffit` ray finder, `ExtraCategories`, `KeptRayView`.
- `Tools\HangerAutomation\FhaRevit.Graph.cs` - `FhaGraph` connector graph of a run: `BuildGraph`, `StraightHosts`, tap points.
- `Tools\HangerAutomation\FhaRevit.Dims.cs` - FAB dimensions: `DimTargets`, `ChainDimension`, dim view / sheet rows, `FindDimType`.
- `Tools\HangerAutomation\FhaFinish.cs` - Finish Selection automation: `FinishRequest`, `FhaFinish.PickObjects`, `Arm`, `Prewarm`, `FindFinishFast`, `PressFinish`, `FinishByButton` / `ByAutomation` / `ByMouse` / `ByReturn`, Win32 interop.

## Jobs - family hangers / floor supports
- `Tools\HangerAutomation\HfamRevit.cs` - `HfamRevit` basics: element tests (`IsRvtDuct`, `ServiceKind`, `IsUnit`...), pick filter, logging (`Describe`, `LogSection`), family list (`ListFamilyTypes`, `PreviewBytes`, `FamilyParamNames`).
- `Tools\HangerAutomation\HfamRevit.Jobs.cs` - `JobPlace`, `JobRealign`, `JobAuto`, bundles (`BundleFor`), `Verify`, `ListJob`, `PreviewJobFor`, `ParamsJobFor`.
- `Tools\HangerAutomation\HfamRevit.Place.cs` - `PlaceOne`, `RealignOne`, `FitToDuct`, `AlignRotation`, `CheckSides`.
- `Tools\HangerAutomation\HfamRevit.Section.cs` - `Section` of a service (size, insulation), levels, `SoffitFinder`, length / level parameters.
- `Tools\HangerAutomation\HfamRevit.Base.cs` - drop rods for family hangers (`JobRods`, `Underside`, `PickTarget`, temp 3D view), floor support base (`Stand`, `FloorStand`, `PickBase`).
- `Tools\HangerAutomation\HfamRevit.Swap.cs` - `JobSwap`: swap the service a hanger belongs to.
- `Tools\HangerAutomation\HfamRevit.Graph.cs` - `FamGraph` run graph for family jobs.
- `Tools\HangerAutomation\HfamRevit.Dims.cs` - family hanger dimensions: `JobDims`, `ChainDimension`, isolate.
- `Tools\HangerAutomation\HfamRevit.Inspect.cs` - Inspect lock diagnostic: `Ins*` records, `JobInspectLock`, `InsSelection`, `InspectRun`, `InsDumpHangerRefs`, `InsAllDims`.
- `Tools\HangerAutomation\HfamRevit.Inspect.Geo.cs` - Inspect formatting helpers (`InsEx`, `InsP`, `InsEl`...) and geometry walk (`InsWalk`, `InsGeoSummary`).
- `Tools\HangerAutomation\HfamRevit.Inspect.Dims.cs` - `InsDescribeDim`, `InsDescribeRef`, `InsDumpSource`.
- `Tools\HangerAutomation\HfamRevit.Inspect.Replay.cs` - `InsReplay`, `InsTry` (rolled-back re-alignments).

## Jobs - circular hangers / service type
- `Tools\HangerAutomation\HcircRevit.cs` - circular (ring) hangers: `PromptNotRound` (circular-on-rectangular prompt), ring measuring (`RingCandidates`, `MeasureRing`), `PlaceCirc`, `RealignCirc`, `VerifyCirc`, `NewLocker`.
- `Tools\HangerAutomation\HcircRevit.Jobs.cs` - `JobPlace`, `JobRealign`, `JobAuto`, `JobDims` for circular families.
- `Tools\HangerAutomation\HsvcRevit.cs` - Service Type assigner: `ScanJob`, `TextInstanceParams`, `RuleFor`, `CarriedServices`, `JobApply`, `JobShow3d`, `JobReset3d`.

## Locking (`HfamRevit.Locker`)
- `Tools\HangerAutomation\HfamRevit.Locker.cs` - static `PlanTypes`, `RefTypes`, `RefLabels`; `Locker` fields, constructor, `SectionFor`, `TellFamily`, `FamKey`, `Prefer`, `MaxTries`, `Outcome`; entry `Lock` / `LockInner`, `FlatHeights`; `LockIf`.
- `Tools\HangerAutomation\HfamRevit.Locker.Geo.cs` - `GeoItems`, `GeoLines`, `GeoWalk`, `HostKind`, `LockSectionName`, `FaceZ`, `WalkFaces`, `ElementFaces`.
- `Tools\HangerAutomation\HfamRevit.Locker.Views.cs` - `LockViews` (the tool's own lock views), `FindLockSection`, `MakeLockSection`.
- `Tools\HangerAutomation\HfamRevit.Locker.Refs.cs` - `RefItem`, `InstanceRefs`, `FamilyReferenceSummary`, `AlignHit`, `TryAlign`, `Alive`.
- `Tools\HangerAutomation\HfamRevit.Locker.Sources.cs` - centreline sources: `StableKey`, `CentrelineRefs`, `CentreSources`, `PlanShows`, `DedicatedPlan`, `LevelOf`.
- `Tools\HangerAutomation\HfamRevit.Locker.CentreRefs.cs` - hanger references vs the centreline: `MoveLimit` etc., `RefEval`, `EvalRef(s)`, `Eligible`, `Regen`, `PrepareCentre`, `AttemptCentre`, `Attempt`.
- `Tools\HangerAutomation\HfamRevit.Locker.Centre.cs` - `LockCentre` (instance-level centre lock), `LockElevationCentre`.
- `Tools\HangerAutomation\HfamRevit.Locker.Sym.cs` - symbol-level locks: `SymLinesFor`, `LockSym`, `LockElevationSym`, `CentreCheck`, `BottomCheck`, bottom lock `LockBottom`.
- `Tools\HangerAutomation\HfamRevit.Locker.Eq.cs` - face-based EQ centre lock: `CollectSides`, `PickSides`, `MakeEq`, `LockEq`.

## Pure logic (no Revit)
- `Tools\HangerAutomation\FhaCore.cs` - `FhaCore`: `Version`, `BuildInfo`, constants, ALL static initialisers (`FloorSkip`, `Defaults`/`BuildDefaults`, `Bases`, `WsOptions`, `Migrations`, `Palettes`, `ThemeModes`, view kinds, `Takeoff`, `Priority`), `FloorKey`, `Plural`.
- `Tools\HangerAutomation\FhaCore.Types.cs` - shared records: `V3`, `PartRec`, `ChainItem`, `Span`, `HostSeg`, `Condition`, `PlanConfig`, `ViewRow`, `SheetRow`, `IFhaPrompts`, `FhaSettings`, `JobResult`, `FhaJob`, `FhaDebugLog`, `WorksetItems`.
- `Tools\HangerAutomation\FhaCore.Settings.cs` - workset helpers (`WorksetItemsFor`, `WorksetTarget`), settings file (`SettingsDir`, `SettingsPath`, `DebugPath`, `LoadSettings`, `SaveSettings`), `Get` / `AsFloat` / `AsBool` / `ParseMm`, `PlanConfigFrom`, `NumText`.
- `Tools\HangerAutomation\FhaCore.Ui.cs` - theme maths (`Contrast`, `LabelWithAbbreviation`, `ServiceComment`), drawer (`ShrunkTop`, `ExpandTop`), dim-view lists (`NaturalComparer`, `FilterViewRows`, `ChosenViews`), search (`MatchWords`, `NextMode`, `ResolveTheme`), `FitHeight`.
- `Tools\HangerAutomation\FhaCore.Spans.cs` - vectors (`VSub`, `VNorm`, `ClosestOnSegment`), `NearestHost`, spans (`WalkDir`, `BuildSpans`, `OrientSpan`), stations (`PlanStations`, `Locate`, `Dedupe`, `DropNear`).
- `Tools\HangerAutomation\FhaCore.Placement.cs` - dimension lines (`ChooseNormal`, `DimLine`, `CollapseRefs`), rods (`RodTargetLength`, `RodOk`), span positions (`SpanSegments`, `StationOnRun`, `AvoidBlocks`, `PickCondition`), matching (`NameTokens`, `SignatureScore`).
- `Tools\HangerAutomation\HfamCore.cs` - `HfamCore`: ALL static initialisers (`Categories`, `FamKeys`, `FamDefaults`, `Modes`, `Styles`, axes, `Soffits`, `Dw144*`, `Centres`), parameter-name defaults, `FilterTypes`, `ItemKey`.
- `Tools\HangerAutomation\HfamCore.Types.cs` - `FamConfig` (per-family settings), `FamTypeItem`, `Section`, `BundleMember`, `GroupRules`, `HangerBundle`, `KeySeg`, `RunHanger`, `RunGroup`, `InlineConn`.
- `Tools\HangerAutomation\HfamCore.Families.cs` - family settings file (`ParseFamilies`, `DumpFamilies`, `LoadFamilies`, `SaveFamilies`, `FamConfigFor`), parameter guesses (`Guess*Param`), `FloorValues`, `FlrName`.
- `Tools\HangerAutomation\HfamCore.Placement.cs` - DW/144 spacing, `AutoConfig`, `HalfWidth`, `RodLength`, `LevelAbove/Below`, `RotationTo`, `PlanDirs`, `OnCentreline`, re-align (`LineParam`, `OnLine`, `PickSegment`).
- `Tools\HangerAutomation\HfamCore.Groups.cs` - `CanonicalDir`, `GroupRuns`, `ReferenceTypeAcross`, `ApplyInsulation`, grouped services (`WrapRules`, `GroupRulesFrom`, `Bundle`, `BundleSection`, `BundlePoint`).
- `Tools\HangerAutomation\HfamCore.Units.cs` - equipment / accessories (`UnitSection`, `InlineDirection`, `SideValues`), drop rods (`RodToTarget`, `Reaches`, `SidesMirrored`).
- `Tools\HangerAutomation\HcircCore.cs` - circular logic: `IsCirc`, `CircXDir`, `SupportHeight`, `PickRing`.
- `Tools\HangerAutomation\HsvcCore.cs` - Service Type logic: `HangerRecord`, `GroupRecords`, sorting, `HangerBox` / `PlanIndex` (what a hanger carries), colours.

## Helpers
- `Tools\HangerAutomation\HaPerf.cs` - `HaTiming` (`BeginJob`, `Time(...)` scopes, `EndJob` timing line in the debug file), `HaCache` (per-job caches, `Reset`).

## Where to change X
- **Finish Selection**: pressing Revit's Finish - `FhaFinish.cs` (`Arm`, `FindFinishFast`, `PressFinish`, fallbacks); the card in the window - `FhaWindow.Finish.cs`.
- **Centre lock**: order of attempts in `Locker.LockInner` (`HfamRevit.Locker.cs`); symbol-level - `LockSym` (`Locker.Sym.cs`); instance-level - `LockCentre` (`Locker.Centre.cs`) with refs in `Locker.CentreRefs.cs` and centreline sources in `Locker.Sources.cs`; EQ - `Locker.Eq.cs`.
- **Bottom lock**: `LockBottom`, `BottomItems`, `BottomCheck` in `HfamRevit.Locker.Sym.cs`; lock sections in `Locker.Views.cs`.
- **Elevation lock** (circular, centre elevation): `Locker.ElevationCentre`; `LockElevationSym` (`Locker.Sym.cs`), `LockElevationCentre` (`Locker.Centre.cs`); turned on from `HcircRevit.NewLocker`.
- **Rod extension**: FAB - `FhaRevit.Rods.cs` (`ExtendRods`, `Soffit`); families - `HfamRevit.Base.cs` (`JobRods`, `Underside`); maths - `FhaCore.Placement.cs` / `HfamCore.Units.cs`; categories - `HfamRodCats.cs` + `ext_extra`.
- **Family list**: `HfamUi.List.cs` (`Refill`, `BuildRow`, `PaintRows`); data from `HfamRevit.ListFamilyTypes`; filter `HfamCore.FilterTypes`.
- **Service type parameter**: chooser `HsvcUi.cs` (`ParamChoice`, `FillParams`, `ParamChanged`); reading / writing `HsvcRevit.cs` (`TextInstanceParams`, `JobApply`).
- **Debug log / timing**: `FhaDebugLog` (`FhaCore.Types.cs`), `FhaCore.DebugPath` (`FhaCore.Settings.cs`), written by `FhaHandler.Execute` (`log.Write()`), shown via `FhaWindow.Finished` (`FhaWindow.Jobs.cs`); timing `HaPerf.cs`; window open timing `FhaWindow.OpenTiming` / `OpenLaps`.
- **Settings keys**: defaults `FhaCore.BuildDefaults` (`FhaCore.cs`), per-family keys `HfamCore.FamKeys` (`HfamCore.cs`); controls in `FhaWindow.Setup.cs` (`LoadControls`, `Gather`) and `FamTab.Load` / `Gather` (`HfamUi.cs`).
- **Tool version**: bump `FhaCore.Version` (`FhaCore.cs`) and `<Version>` in `RevoBIM.Revit.csproj` on every change.
- **Static initialisers**: add new `static readonly` fields with initialisers only to the main `FhaCore.cs` / `HfamCore.cs` (order matters).
