#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"   ; overridden by build-installer.ps1 from the .csproj <Version>
#endif

#define MyAppName      "RevoBIM Tools"
#define MyAppPublisher "A² Services LTD"
#define BuildDir       "..\RevoBIM.Revit2024\bin\Release\net48"

[Setup]
; Fixed for the life of the product. Upgrades work because every version shares this AppId.
AppId={{6F1D3A92-4B7E-4C1A-9E8D-2A5B7C0F3E11}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
DefaultDirName={userappdata}\RevoBIM\2024
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=RevoBIM-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
Uninstallable=yes

[Files]
Source: "{#BuildDir}\RevoBIM.Revit2024.dll"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildDir}\RevoBIM.Revit2024.pdb"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
; Add any non-Revit third-party DLLs that bin\Release\net48 gets. Never ship RevitAPI*.dll.

[InstallDelete]
; Remove the previous version's files before copying the new ones.
Type: files; Name: "{app}\*.dll"
Type: files; Name: "{app}\*.pdb"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
Type: files; Name: "{userappdata}\Autodesk\Revit\Addins\2024\RevoBIM.addin"

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
    MsgBox('Revit is running. Close Revit completely, then run this installer again.',
           mbError, MB_OK);
    Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Lines: TArrayOfString;
  AddinDir, ManifestPath, AsmPath: String;
begin
  if CurStep = ssPostInstall then
  begin
    AddinDir     := ExpandConstant('{userappdata}\Autodesk\Revit\Addins\2024');
    ManifestPath := AddinDir + '\RevoBIM.addin';
    AsmPath      := ExpandConstant('{app}\RevoBIM.Revit2024.dll');

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
end;
