<#
.SYNOPSIS
  The arcade's bench. Runs without Revit.

  1. the exe's own logic checks (--selftest): registry keys unique and valid, the launch
     parser on bad input, theme validation, the logo click rule, drawer arithmetic, storage
  2. repo checks: Version.cs agrees with CHANGELOG.md, the egg_hook fragment is intact and
     only names keys that exist in Games\
  3. launch checks: the real exe, both themes, no arguments, a bad key, owner centring and the
     single-instance hand-over (skip with -SkipLaunch)

  Exit code 0 = everything passed.
#>
param(
    [string]$Exe,
    [switch]$SkipLaunch,
    [string]$Shots
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$failed = 0
function Check($name, $ok, $detail = '') {
    if ($ok) { Write-Host "PASS  $name" } else { Write-Host "FAIL  $name  -> $detail"; $script:failed++ }
}

if (-not $Exe) {
    $Exe = @((Join-Path $root 'publish\RevoBIM.Arcade.exe'),
             (Join-Path $root 'RevoBIM.Arcade\bin\Release\net8.0-windows\win-x64\RevoBIM.Arcade.exe')) |
        Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Exe) { throw 'No exe found. Run tools\publish.ps1 (or dotnet build -c Release) first.' }
Write-Host "Testing $Exe`n"

# ---- 1. the exe's own checks
Write-Host '== logic checks (exe --selftest)'
# The exe is a GUI-subsystem program, so `& exe` would not wait for it or set the exit code.
$report = Join-Path ([IO.Path]::GetTempPath()) ('arcade-selftest-' + [guid]::NewGuid().ToString('N') + '.txt')
$proc = Start-Process -FilePath $Exe -ArgumentList '--selftest' -Wait -PassThru -RedirectStandardOutput $report
$code = $proc.ExitCode
Get-Content $report | ForEach-Object { Write-Host $_ }
Remove-Item $report -Force -ErrorAction SilentlyContinue
Check 'exe --selftest exits 0' ($code -eq 0) "exit code $code"

# ---- 2. repo checks
Write-Host "`n== repo checks"
$version = (Select-String -Path (Join-Path $root 'RevoBIM.Arcade\Version.cs') -Pattern 'Current = "([^"]+)"').Matches[0].Groups[1].Value
$changelog = Get-Content (Join-Path $root 'CHANGELOG.md') -Raw
$top = [regex]::Match($changelog, '(?m)^## (\d+\.\d+\.\d+)').Groups[1].Value
Check "Version.cs ($version) matches the top of CHANGELOG.md ($top)" ($version -eq $top)

$frag = Get-Content (Join-Path $root 'integration\egg_hook.launch.fragment.py') -Raw
Check 'fragment has both band markers' (($frag -match '>>> RevoBIM\.Arcade BEGIN') -and ($frag -match '<<< RevoBIM\.Arcade END'))
Check 'fragment keeps the launch signature' ($frag -match 'def launch\(host_window=None, theme=None, game_key=None\):')
Check 'fragment does not touch the anchors' (-not ($frag -match '(?m)^\s*(def attach|def attach_to_window|egg_auto\.install)'))

$registered = @(Get-ChildItem (Join-Path $root 'RevoBIM.Arcade\Games') -Recurse -Filter *.cs |
    ForEach-Object { [regex]::Matches((Get-Content $_.FullName -Raw), 'Key\s*=>\s*"([a-z0-9-]+)"') } |
    ForEach-Object { $_.Groups[1].Value })
Check 'game keys in Games\ are unique' (($registered | Sort-Object -Unique).Count -eq $registered.Count) ($registered -join ',')
$arcadeKeys = @([regex]::Match($frag, 'ARCADE_KEYS\s*=\s*\(([^)]*)\)').Groups[1].Value -split ',' |
    ForEach-Object { $_.Trim().Trim('"').Trim("'") } | Where-Object { $_ })
$unknown = @($arcadeKeys | Where-Object { $registered -notcontains $_ })
Check 'every ARCADE_KEYS entry is a game that exists in the exe' ($unknown.Count -eq 0) ("missing: " + ($unknown -join ','))

# ---- 3. launch checks
if (-not $SkipLaunch) {
    Write-Host "`n== launch checks (real exe)"
    $args2 = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'launch-check.ps1'), '-Exe', $Exe)
    if ($Shots) { $args2 += @('-Shots', $Shots) }
    & powershell @args2
    Check 'launch checks passed' ($LASTEXITCODE -eq 0)
}

Write-Host ''
if ($failed) { Write-Host "$failed check(s) FAILED"; exit 1 }
Write-Host 'Everything passed'
