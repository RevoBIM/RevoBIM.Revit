#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"   ; overridden by build-installer.ps1 from the .csproj <Version>
#endif

#define MyAppName      "RevoBIM Tools"
#define MyAppPublisher "A² Services LTD"
; One Release build per Revit version, made by build-installer.ps1
#define Bin            "..\RevoBIM.Revit\bin"
#define Build2024      Bin + "\Release R24\net48"
#define Build2025      Bin + "\Release R25\net8.0-windows"
#define Build2026      Bin + "\Release R26\net8.0-windows"
#define Build2027      Bin + "\Release R27\net10.0-windows"

[Setup]
; Fixed for the life of the product. Upgrades work because every version shares this AppId.
AppId={{6F1D3A92-4B7E-4C1A-9E8D-2A5B7C0F3E11}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
; Each Revit version gets its own subfolder: {app}\2024, {app}\2025, ...
DefaultDirName={userappdata}\RevoBIM
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=RevoBIM-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
Uninstallable=yes

[Files]
; Never ship RevitAPI*.dll - the Nice3point packages are reference only.
Source: "{#Build2024}\RevoBIM.Revit.dll"; DestDir: "{app}\2024"; Flags: ignoreversion
Source: "{#Build2024}\RevoBIM.Revit.pdb"; DestDir: "{app}\2024"; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#Build2025}\RevoBIM.Revit.dll"; DestDir: "{app}\2025"; Flags: ignoreversion
Source: "{#Build2025}\RevoBIM.Revit.pdb"; DestDir: "{app}\2025"; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#Build2026}\RevoBIM.Revit.dll"; DestDir: "{app}\2026"; Flags: ignoreversion
Source: "{#Build2026}\RevoBIM.Revit.pdb"; DestDir: "{app}\2026"; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#Build2027}\RevoBIM.Revit.dll"; DestDir: "{app}\2027"; Flags: ignoreversion
Source: "{#Build2027}\RevoBIM.Revit.pdb"; DestDir: "{app}\2027"; Flags: ignoreversion skipifsourcedoesntexist

[InstallDelete]
; Remove the previous version's files before copying the new ones,
; including the DLL's name before the project was renamed (RevoBIM.Revit2024.dll).
Type: files; Name: "{app}\2024\*.dll"
Type: files; Name: "{app}\2024\*.pdb"
Type: files; Name: "{app}\2025\*.dll"
Type: files; Name: "{app}\2025\*.pdb"
Type: files; Name: "{app}\2026\*.dll"
Type: files; Name: "{app}\2026\*.pdb"
Type: files; Name: "{app}\2027\*.dll"
Type: files; Name: "{app}\2027\*.pdb"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\2024"
Type: filesandordirs; Name: "{app}\2025"
Type: filesandordirs; Name: "{app}\2026"
Type: filesandordirs; Name: "{app}\2027"
Type: files; Name: "{userappdata}\Autodesk\Revit\Addins\2024\RevoBIM.addin"
Type: files; Name: "{userappdata}\Autodesk\Revit\Addins\2025\RevoBIM.addin"
Type: files; Name: "{userappdata}\Autodesk\Revit\Addins\2026\RevoBIM.addin"
Type: files; Name: "{userappdata}\Autodesk\Revit\Addins\2027\RevoBIM.addin"

[Code]
const
  AddinGuid = '4C8B2E71-5A93-4F0D-B6E2-9D1A7C3E8F54';

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

function InitializeSetup(): Boolean;
begin
  Result := True;
  if RevitRunning() then
  begin
    MsgBox('Revit is running. Close every Revit window completely, then run this installer again.',
           mbError, MB_OK);
    Result := False;
  end;
end;

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
  Lines[7]  := '    <VendorId>A2SV</VendorId>';
  Lines[8]  := '    <VendorDescription>A2 Services LTD</VendorDescription>';
  Lines[9]  := '  </AddIn>';
  Lines[10] := '</RevitAddIns>';

  SaveStringsToFile(ManifestPath, Lines, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    WriteManifest('2024');
    WriteManifest('2025');
    WriteManifest('2026');
    WriteManifest('2027');
  end;
end;
