#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"   ; overridden by build-installer.ps1 from the .csproj <Version>
#endif

#define MyAppName      "RevoBIM Tools"
#define MyAppPublisher "RevoBIM LTD"
; One Release build per Revit version, made by build-installer.ps1
#define Bin            "..\RevoBIM.Revit\bin"
#define Build2024      Bin + "\Release R24\net48"
#define Build2025      Bin + "\Release R25\net8.0-windows"
#define Build2026      Bin + "\Release R26\net8.0-windows"
#define Build2027      Bin + "\Release R27\net10.0-windows"
#define Res            "..\RevoBIM.Revit\Resources"
; The RevoBIM Arcade: one self-contained exe for every Revit version, published by build-installer.ps1
#define ArcadeExe      "..\RevoBIM.Arcade\publish\RevoBIM.Arcade.exe"
; The keyboard shortcut list ("XS Pro Sheets Exporter, ..."), written from shortcuts.txt by make-assets.ps1
#include "assets\shortcuts.inc"

[Setup]
; Fixed for the life of the product. Upgrades work because every version shares this AppId.
AppId={{6F1D3A92-4B7E-4C1A-9E8D-2A5B7C0F3E11}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppCopyright=Copyright (C) {#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoProductName={#MyAppName}
VersionInfoDescription={#MyAppName} Setup
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\revobim.ico
SetupIconFile=assets\revobim.ico
; Each Revit version gets its own subfolder: {app}\2024, {app}\2025, ...
DefaultDirName={userappdata}\RevoBIM
DisableWelcomePage=no
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
SetupMutex=RevoBIMToolsSetupMutex
OutputDir=..\dist
OutputBaseFilename=RevoBIM_Tools-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
Uninstallable=yes
; Look: dark modern wizard, larger window, RevoBIM artwork (made by make-assets.ps1)
WizardStyle=modern dark
WizardImageBackColor=#151517
WizardSizePercent=115
WizardImageFile=assets\wizard-large.bmp,assets\wizard-large-200.bmp
WizardSmallImageFile=assets\wizard-small.bmp,assets\wizard-small-200.bmp

[Messages]
WelcomeLabel1=Welcome to RevoBIM Tools
WelcomeLabel2=This wizard installs [name/ver] for Autodesk Revit.%n%nIt installs for your Windows user only, so no administrator rights are needed, and it replaces any earlier RevoBIM Tools install in one step.
SelectComponentsLabel2=Choose the Revit versions to install for. Versions found on this PC are already ticked.
FinishedHeadingLabel=RevoBIM Tools is installed
FinishedLabelNoIcons=Start Revit and look for the RevoBIM tab on the ribbon.%n%nOn first launch Revit may show a "Security - Unsigned Add-In" prompt. Choose "Always Load" so the tools stay available.
FinishedLabel=Start Revit and look for the RevoBIM tab on the ribbon.%n%nOn first launch Revit may show a "Security - Unsigned Add-In" prompt. Choose "Always Load" so the tools stay available.

[Types]
Name: "full";   Description: "All Revit versions"
Name: "custom"; Description: "Custom"; Flags: iscustom

[Components]
Name: "r2024"; Description: "Revit 2024"; Types: full custom
Name: "r2025"; Description: "Revit 2025"; Types: full custom
Name: "r2026"; Description: "Revit 2026"; Types: full custom
Name: "r2027"; Description: "Revit 2027"; Types: full custom

[Tasks]
; Ticked by default. A silent install can leave it off with /TASKS="!shortcuts".
Name: "shortcuts"; Description: "Set the RevoBIM keyboard shortcuts in Revit:  {#ShortcutList}"; GroupDescription: "Keyboard shortcuts"

[Files]
; Never ship RevitAPI*.dll - the Nice3point packages are reference only.
Source: "assets\revobim.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Build2024}\RevoBIM.Revit.dll"; DestDir: "{app}\2024"; Flags: ignoreversion; Components: r2024
Source: "{#Build2024}\RevoBIM.Revit.pdb"; DestDir: "{app}\2024"; Flags: ignoreversion skipifsourcedoesntexist; Components: r2024
Source: "{#Build2025}\RevoBIM.Revit.dll"; DestDir: "{app}\2025"; Flags: ignoreversion; Components: r2025
Source: "{#Build2025}\RevoBIM.Revit.pdb"; DestDir: "{app}\2025"; Flags: ignoreversion skipifsourcedoesntexist; Components: r2025
Source: "{#Build2026}\RevoBIM.Revit.dll"; DestDir: "{app}\2026"; Flags: ignoreversion; Components: r2026
Source: "{#Build2026}\RevoBIM.Revit.pdb"; DestDir: "{app}\2026"; Flags: ignoreversion skipifsourcedoesntexist; Components: r2026
Source: "{#Build2027}\RevoBIM.Revit.dll"; DestDir: "{app}\2027"; Flags: ignoreversion; Components: r2027
Source: "{#Build2027}\RevoBIM.Revit.pdb"; DestDir: "{app}\2027"; Flags: ignoreversion skipifsourcedoesntexist; Components: r2027
; The RevoBIM Arcade goes in silently: no component, no page, no card. Revit starts it (Routines
; dropdown, or three slow clicks on a tool's logo). Its scores and settings live in
; %AppData%\RevoBIM\arcade\ and are never touched by an install or uninstall.
Source: "{#ArcadeExe}"; DestDir: "{app}\ArcadeApp"; Flags: ignoreversion
; Tool icons for the "What is included" page (wizard only, not installed). The list is generated from
; installer\tools.txt by make-assets.ps1.
#include "assets\tools_files.inc"
; The keyboard shortcut script and its list: run once from the temp folder after the files are in, not installed.
Source: "SetShortcuts.ps1"; Flags: dontcopy
Source: "shortcuts.txt"; Flags: dontcopy

[InstallDelete]
; Remove the previous version's files before copying the new ones,
; including the DLL's name before the project was renamed (RevoBIM.Revit2024.dll).
Type: files; Name: "{app}\2024\*.dll"; Components: r2024
Type: files; Name: "{app}\2024\*.pdb"; Components: r2024
Type: files; Name: "{app}\2025\*.dll"; Components: r2025
Type: files; Name: "{app}\2025\*.pdb"; Components: r2025
Type: files; Name: "{app}\2026\*.dll"; Components: r2026
Type: files; Name: "{app}\2026\*.pdb"; Components: r2026
Type: files; Name: "{app}\2027\*.dll"; Components: r2027
Type: files; Name: "{app}\2027\*.pdb"; Components: r2027

[UninstallDelete]
Type: filesandordirs; Name: "{app}\2024"
Type: filesandordirs; Name: "{app}\2025"
Type: filesandordirs; Name: "{app}\2026"
Type: filesandordirs; Name: "{app}\2027"
Type: filesandordirs; Name: "{app}\ArcadeApp"
Type: files; Name: "{userappdata}\Autodesk\Revit\Addins\2024\RevoBIM.addin"
Type: files; Name: "{userappdata}\Autodesk\Revit\Addins\2025\RevoBIM.addin"
Type: files; Name: "{userappdata}\Autodesk\Revit\Addins\2026\RevoBIM.addin"
Type: files; Name: "{userappdata}\Autodesk\Revit\Addins\2027\RevoBIM.addin"

[Code]
const
  AddinGuid    = '4C8B2E71-5A93-4F0D-B6E2-9D1A7C3E8F54';
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6F1D3A92-4B7E-4C1A-9E8D-2A5B7C0F3E11}_is1';
  // Colours as $00BBGGRR (the RevoBIM palette)
  ColBlue   = $00E3A34F;
  ColOrange = $002D91E8;
  ColGreen  = $005AA73F;
  ColRed    = $006B6BFF;
  ColMuted  = $00A3A39A;

var
  RevitPage: TWizardPage;
  RevitStatus: TNewStaticText;

// ---------------------------------------------------------------- helpers

// True when Revit.exe is running. find exits 0 when it finds a match.
function RevitRunning(): Boolean;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{cmd}'),
       '/C tasklist /FI "IMAGENAME eq Revit.exe" | find /I "Revit.exe" >nul',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := (ResultCode = 0);
end;

function RevitFolderFound(Year: String): Boolean;
begin
  Result := DirExists(ExpandConstant('{commonpf64}\Autodesk\Revit ') + Year);
end;

// A word-wrapped text label placed at pixel position (all values already scaled).
// Color = -1 keeps the theme's text colour.
function AddText(Parent: TWinControl; const Text: String; L, T, W, H, Pt: Integer;
  Bold: Boolean; Color: Integer): TNewStaticText;
begin
  Result := TNewStaticText.Create(WizardForm);
  Result.Parent := Parent;
  Result.AutoSize := False;
  Result.WordWrap := True;
  Result.SetBounds(L, T, W, H);
  Result.Caption := Text;
  Result.Font.Size := Pt;
  if Bold then Result.Font.Style := [fsBold];
  if Color <> -1 then Result.Font.Color := Color;
end;

procedure RefreshRevitStatus();
begin
  if RevitRunning() then
  begin
    RevitStatus.Caption := #$25CF + '  Revit is running. Save your work and close every Revit window, then click Re-check.';
    RevitStatus.Font.Color := ColRed;
  end
  else
  begin
    RevitStatus.Caption := #$25CF + '  Revit is closed. You are ready to install.';
    RevitStatus.Font.Color := ColGreen;
  end;
end;

procedure RecheckClick(Sender: TObject);
begin
  RefreshRevitStatus();
end;

// ----------------------------------------------------------------- pages

procedure CreateRevitPage();
var
  Btn: TNewButton;
  W: Integer;
begin
  RevitPage := CreateCustomPage(wpWelcome, 'Before you install',
    'Close Autodesk Revit so the add-in files can be replaced.');
  W := RevitPage.SurfaceWidth;

  AddText(RevitPage.Surface, 'Close Revit first', 0, 0, W, ScaleY(26), 13, True, ColOrange);
  AddText(RevitPage.Surface,
    'Revit locks add-in files while it is open, and it only loads an add-in when it starts. ' +
    'To install or upgrade safely:' + #13#10#13#10 +
    '   1.  Save your work in any open project.' + #13#10 +
    '   2.  Close every Revit window (check the taskbar and system tray).' + #13#10 +
    '   3.  Click Re-check below, then Next.' + #13#10#13#10 +
    'If you are upgrading, the previous version is removed and replaced with this one. ' +
    'Your tool settings are kept.',
    0, ScaleY(32), W, ScaleY(150), 9, False, -1);

  RevitStatus := AddText(RevitPage.Surface, '', 0, ScaleY(196), W, ScaleY(40), 10, True, -1);

  Btn := TNewButton.Create(WizardForm);
  Btn.Parent := RevitPage.Surface;
  Btn.Caption := 'Re-check';
  Btn.SetBounds(0, ScaleY(244), ScaleX(110), ScaleY(28));
  Btn.OnClick := @RecheckClick;
end;

procedure CreateIncludedPage();
var
  Page: TWizardPage;
  Rich: TRichEditViewer;
  Rtf: AnsiString;
  W: Integer;
begin
  Page := CreateCustomPage(RevitPage.ID, 'What is included',
    'Every tool on the RevoBIM ribbon tab, by ribbon panel.');
  W := Page.SurfaceWidth;

  // The list scrolls, so it can grow as tools are added. It is one RTF document built from
  // installer\tools.txt by make-assets.ps1 (a heading per ribbon panel, then icon + name +
  // description per tool); nothing to edit here for a new tool.
  Rich := TRichEditViewer.Create(WizardForm);
  Rich.Parent := Page.Surface;
  Rich.SetBounds(0, 0, W, Page.SurfaceHeight - ScaleY(36));
  Rich.BorderStyle := bsNone;
  Rich.ScrollBars := ssVertical;
  Rich.ReadOnly := True;
  Rich.UseRichEdit := True;
  Rich.Color := $2B2B2B;
  ExtractTemporaryFile('tools.rtf');
  if LoadStringFromFile(ExpandConstant('{tmp}\tools.rtf'), Rtf) then
    Rich.RTFText := Rtf;

  AddText(Page.Surface,
    'Works with Revit 2024, 2025, 2026 and 2027. More tools arrive as they are converted.',
    0, Page.SurfaceHeight - ScaleY(32), W, ScaleY(32), 9, False, ColMuted);
end;
procedure InitializeWizard();
var
  PrevVersion: String;
  Years: array[0..3] of String;
  I: Integer;
  AnyFound: Boolean;
begin
  CreateRevitPage();
  CreateIncludedPage();
  RefreshRevitStatus();

  // Tell the user when this is an upgrade.
  if RegQueryStringValue(HKCU, UninstallKey, 'DisplayVersion', PrevVersion) then
  begin
    if PrevVersion = '{#MyAppVersion}' then
      WizardForm.WelcomeLabel2.Caption := WizardForm.WelcomeLabel2.Caption + #13#10#13#10 +
        'Version ' + PrevVersion + ' is already installed. Setup will reinstall it.'
    else
      WizardForm.WelcomeLabel2.Caption := WizardForm.WelcomeLabel2.Caption + #13#10#13#10 +
        'Version ' + PrevVersion + ' is installed. Setup will replace it with version {#MyAppVersion}.';
  end;

  // Components page: no setup-type combo, tick the Revit versions found on this PC.
  WizardForm.ComponentsList.Height := WizardForm.ComponentsList.Height +
    (WizardForm.ComponentsList.Top - WizardForm.TypesCombo.Top);
  WizardForm.ComponentsList.Top := WizardForm.TypesCombo.Top;
  WizardForm.TypesCombo.Visible := False;
  WizardForm.ComponentsDiskSpaceLabel.Visible := False;

  Years[0] := '2024'; Years[1] := '2025'; Years[2] := '2026'; Years[3] := '2027';
  AnyFound := False;
  for I := 0 to 3 do
    if RevitFolderFound(Years[I]) then AnyFound := True;
  if AnyFound then
    for I := 0 to 3 do
    begin
      WizardForm.ComponentsList.Checked[I] := RevitFolderFound(Years[I]);
      if RevitFolderFound(Years[I]) then
        WizardForm.ComponentsList.ItemCaption[I] := 'Revit ' + Years[I] + '   (found on this PC)';
    end;
end;

// "Ready to install" summary: the chosen Revit versions and where files go
// (the default one also prints a confusing "Setup type" line).
function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoComponentsInfo + NewLine + NewLine +
    'Install location:' + NewLine + Space + ExpandConstant('{app}') + NewLine + NewLine +
    'Any existing RevoBIM files for these Revit versions will be replaced.';
  if WizardIsTaskSelected('shortcuts') then
    Result := Result + NewLine + NewLine + 'Keyboard shortcuts to set:' + NewLine + Space + '{#ShortcutList}' +
      NewLine + Space + '(a shortcut already on another command is moved to the RevoBIM one; your old file is kept as a backup)';
end;

// Keep Enter / Next as the default action: stop Re-check grabbing focus on its page.
procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = RevitPage.ID then
  begin
    RefreshRevitStatus();
    WizardForm.ActiveControl := WizardForm.NextButton;
  end;
end;

// ------------------------------------------------------------- flow checks

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = RevitPage.ID then
  begin
    RefreshRevitStatus();
    if RevitRunning() then
    begin
      MsgBox('Revit is still running. Close every Revit window, then click Next again.', mbError, MB_OK);
      Result := False;
    end;
  end
  else if CurPageID = wpSelectComponents then
  begin
    if WizardSelectedComponents(False) = '' then
    begin
      MsgBox('Tick at least one Revit version to install for.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

// Last line of defence (also covers silent installs): never write over a loaded DLL.
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if RevitRunning() then
    Result := 'Revit is running. Close every Revit window, then run Setup again.';
end;

// ------------------------------------------------------------- manifests

// The .addin manifest for one Revit version, pointing at that version's DLL.
procedure WriteManifest(Year: String);
var
  Lines: TArrayOfString;
  AddinDir, ManifestPath, AsmPath: String;
begin
  AddinDir     := ExpandConstant('{userappdata}\Autodesk\Revit\Addins\') + Year;
  ManifestPath := AddinDir + '\RevoBIM.addin';
  AsmPath      := ExpandConstant('{app}\') + Year + '\RevoBIM.Revit.dll';

  ForceDirectories(AddinDir);

  SetArrayLength(Lines, 11);
  Lines[0]  := '<?xml version="1.0" encoding="utf-8"?>';
  Lines[1]  := '<RevitAddIns>';
  Lines[2]  := '  <AddIn Type="Application">';
  Lines[3]  := '    <Name>RevoBIM Tools</Name>';
  Lines[4]  := '    <Assembly>' + AsmPath + '</Assembly>';
  Lines[5]  := '    <AddInId>' + AddinGuid + '</AddInId>';
  Lines[6]  := '    <FullClassName>RevoBIM.App</FullClassName>';
  Lines[7]  := '    <VendorId>RevoBIM</VendorId>';
  Lines[8]  := '    <VendorDescription>RevoBIM LTD</VendorDescription>';
  Lines[9]  := '  </AddIn>';
  Lines[10] := '</RevitAddIns>';

  SaveStringsToFile(ManifestPath, Lines, False);
end;

// ------------------------------------------------------------- shortcuts

// Set the keyboard shortcuts for the chosen Revit versions. SetShortcuts.ps1 edits each version's
// KeyboardShortcuts.xml (Revit is closed, or it would rewrite the file on exit), keeps a backup, and
// logs to %AppData%\RevoBIM\logs\keyboard_shortcuts.txt. It never fails the install.
procedure SetKeyboardShortcuts();
var
  Years: String;
  ResultCode: Integer;
begin
  Years := '';
  if WizardIsComponentSelected('r2024') then Years := Years + ',2024';
  if WizardIsComponentSelected('r2025') then Years := Years + ',2025';
  if WizardIsComponentSelected('r2026') then Years := Years + ',2026';
  if WizardIsComponentSelected('r2027') then Years := Years + ',2027';
  if Years = '' then Exit;
  Delete(Years, 1, 1);
  try
    ExtractTemporaryFile('SetShortcuts.ps1');
    ExtractTemporaryFile('shortcuts.txt');
    Exec('powershell.exe',
         '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\SetShortcuts.ps1') + '" -Years ' + Years,
         ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, ResultCode);
  except
    // Shortcuts are a convenience: whatever goes wrong here must not undo an install.
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsComponentSelected('r2024') then WriteManifest('2024');
    if WizardIsComponentSelected('r2025') then WriteManifest('2025');
    if WizardIsComponentSelected('r2026') then WriteManifest('2026');
    if WizardIsComponentSelected('r2027') then WriteManifest('2027');
    if WizardIsTaskSelected('shortcuts') then SetKeyboardShortcuts();
  end;
end;
