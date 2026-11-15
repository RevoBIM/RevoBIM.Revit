<#
.SYNOPSIS
  Launches the arcade exe the way Revit will, and checks what comes up. No Revit needed.

.PARAMETER Exe
  The exe to test. Defaults to the published one, then the Release build.

.PARAMETER Shots
  Folder to save a screenshot of each launch into (optional).
#>
param(
    [string]$Exe,
    [string]$Shots
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Exe) {
    $candidates = @(
        (Join-Path $root 'publish\RevoBIM.Arcade.exe'),
        (Join-Path $root 'RevoBIM.Arcade\bin\Release\net8.0-windows\win-x64\RevoBIM.Arcade.exe'))
    $Exe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Exe -or -not (Test-Path $Exe)) { throw "No exe found. Build or publish first." }

Add-Type -AssemblyName System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public static class ArcadeWin {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern void SwitchToThisWindow(IntPtr h, bool altTab);
}
'@
[void][ArcadeWin]::SetProcessDPIAware()

$failed = 0
function Check($name, $ok, $detail = '') {
    if ($ok) { Write-Host "PASS  $name" } else { Write-Host "FAIL  $name  -> $detail"; $script:failed++ }
}

function Wait-Window($proc, $seconds = 10) {
    $end = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $end) {
        $proc.Refresh()
        if ($proc.HasExited) { return $false }
        if ($proc.MainWindowHandle -ne 0) { return $true }
        Start-Sleep -Milliseconds 150
    }
    return $false
}

function Save-Shot($proc, $name) {
    if (-not $Shots) { return }
    New-Item -ItemType Directory -Force $Shots | Out-Null
    $r = New-Object ArcadeWin+RECT
    [void][ArcadeWin]::GetWindowRect($proc.MainWindowHandle, [ref]$r)
    $w = $r.R - $r.L; $h = $r.B - $r.T
    if ($w -le 0 -or $h -le 0) { return }
    # Bring it to the front first, or whatever sits on top of it ends up in the shot.
    [ArcadeWin]::SwitchToThisWindow($proc.MainWindowHandle, $true)
    Start-Sleep -Milliseconds 700
    [void][ArcadeWin]::GetWindowRect($proc.MainWindowHandle, [ref]$r)
    $bmp = New-Object System.Drawing.Bitmap $w, $h
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
    $bmp.Save((Join-Path $Shots "$name.png")); $g.Dispose(); $bmp.Dispose()
}

function Stop-All {
    Get-Process RevoBIM.Arcade -ErrorAction SilentlyContinue | ForEach-Object {
        [void]$_.CloseMainWindow(); if (-not $_.WaitForExit(2000)) { $_.Kill() }
    }
    Start-Sleep -Milliseconds 300
}

# A scratch settings folder so a check run never touches the user's real scores.
$env:REVOBIM_ARCADE_DIR = Join-Path ([IO.Path]::GetTempPath()) ('arcade-launch-' + [guid]::NewGuid().ToString('N'))
Stop-All

$cases = @(
    @{ Name = 'game hello, dark';  Args = @('--game','hello','--theme','dark');  Title = 'Hello' },
    @{ Name = 'game hello, light'; Args = @('--game','hello','--theme','light'); Title = 'Hello' },
    @{ Name = 'no arguments';      Args = @();                                   Title = 'RevoBIM Arcade' },
    @{ Name = 'unknown game key';  Args = @('--game','nosuchgame','--theme','dark'); Title = 'RevoBIM Arcade' },
    @{ Name = 'bad theme value';   Args = @('--game','hello','--theme','purple'); Title = 'Hello' }
)

foreach ($c in $cases) {
    # Start-Process rejects an empty ArgumentList, so the no-arguments case has to leave it off.
    if ($c.Args.Count -gt 0) { $p = Start-Process -FilePath $Exe -ArgumentList $c.Args -PassThru }
    else { $p = Start-Process -FilePath $Exe -PassThru }
    $up = Wait-Window $p
    Check "$($c.Name): a window opens" $up "process exited or no window"
    if ($up) {
        Start-Sleep -Milliseconds 700
        $p.Refresh()
        Check "$($c.Name): title is right" ($p.MainWindowTitle -like '*RevoBIM Arcade*') $p.MainWindowTitle
        Save-Shot $p ($c.Name -replace '[^a-z0-9]+','-')
    }
    Stop-All
}

# Owner rectangle: the window should be centred over it.
$p = Start-Process -FilePath $Exe -ArgumentList @('--game','hello','--theme','dark','--owner-x','100','--owner-y','100','--owner-w','1000','--owner-h','700') -PassThru
if (Wait-Window $p) {
    Start-Sleep -Milliseconds 600
    $r = New-Object ArcadeWin+RECT
    [void][ArcadeWin]::GetWindowRect($p.MainWindowHandle, [ref]$r)
    $cx = ($r.L + $r.R) / 2; $cy = ($r.T + $r.B) / 2
    Check 'owner rectangle: window centred over it' ([math]::Abs($cx - 600) -le 3 -and [math]::Abs($cy - 450) -le 3) "centre was ($cx,$cy), wanted (600,450)"
} else { Check 'owner rectangle: window opens' $false }
Stop-All

# Single instance: a second launch must not start a second window, and must hand over its key.
$first = Start-Process -FilePath $Exe -ArgumentList @('--theme','dark') -PassThru
[void](Wait-Window $first)
Start-Sleep -Milliseconds 500
$second = Start-Process -FilePath $Exe -ArgumentList @('--game','hello','--theme','dark') -PassThru
[void]$second.WaitForExit(6000)
Start-Sleep -Milliseconds 800
$first.Refresh()
Check 'single instance: second launch exits' $second.HasExited
Check 'single instance: only one arcade running' (@(Get-Process RevoBIM.Arcade -ErrorAction SilentlyContinue).Count -eq 1)
Check 'single instance: the running window switched to the requested game' ($first.MainWindowTitle -like '*Hello*') $first.MainWindowTitle
Save-Shot $first 'single-instance-handover'
Stop-All

Remove-Item $env:REVOBIM_ARCADE_DIR -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item Env:\REVOBIM_ARCADE_DIR -ErrorAction SilentlyContinue

if ($failed) { Write-Host "`n$failed launch check(s) FAILED"; exit 1 }
Write-Host "`nAll launch checks passed"
