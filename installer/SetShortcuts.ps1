# Sets the RevoBIM keyboard shortcuts in Revit's KeyboardShortcuts.xml, once per Revit version.
# Run by the installer after the files are in (Revit is closed then: it rewrites this file when it
# exits, so editing it while Revit runs would be lost). Also fine to run by hand:
#   powershell -ExecutionPolicy Bypass -File installer\SetShortcuts.ps1 -Years 2024,2026 -DryRun
#
# The shortcuts come from shortcuts.txt beside this script. For each Revit version:
#   - a version with no KeyboardShortcuts.xml yet is skipped: that file only exists once Revit has
#     been run and shortcuts customised, and a made-up partial file could reset Revit's own defaults;
#   - the command's line gets the shortcut (added, other shortcuts it already had are kept);
#   - any OTHER command holding the same shortcut loses just that shortcut, because two commands on one
#     shortcut make Revit ask which was meant;
#   - the file is edited as text, line by line, so everything else in it stays byte for byte as it was;
#   - the edited text is checked to be well-formed XML before it is written, and the old file is kept
#     beside it as KeyboardShortcuts.xml.revobim-backup-<time> (the last five are kept);
#   - nothing is written when the shortcuts are already as wanted.
# What it did goes to %APPDATA%\RevoBIM\logs\keyboard_shortcuts.txt. It never fails the install.
param(
    [string]$Years = '2024,2025,2026,2027',
    [string]$Map = (Join-Path $PSScriptRoot 'shortcuts.txt'),
    [string]$AppData = $env:APPDATA,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$logFile = Join-Path $AppData 'RevoBIM\logs\keyboard_shortcuts.txt'

function Log([string]$text) {
    Write-Host $text
    try {
        $dir = Split-Path -Parent $logFile
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
        [System.IO.File]::AppendAllText($logFile, ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + '  ' + $text + "`r`n"),
            (New-Object System.Text.UTF8Encoding($false)))
    } catch { }
}

# One attribute value as Revit writes it: & < > " escaped, line breaks as &#xA;
function Xml-Attr([string]$s) {
    $s.Replace('&', '&amp;').Replace('<', '&lt;').Replace('>', '&gt;').Replace('"', '&quot;').Replace("`n", '&#xA;')
}

try {
    $wanted = @()
    foreach ($line in [System.IO.File]::ReadAllLines($Map, [System.Text.Encoding]::UTF8)) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        $p = $t.Split('|')
        if ($p.Count -lt 4) { throw "shortcuts.txt: expected Keys|Panel|Button|Name, got: $t" }
        $panel = $p[1].Trim(); $button = $p[2].Trim()
        $wanted += [pscustomobject]@{
            Keys  = $p[0].Trim().ToUpperInvariant()
            Panel = $panel
            Id    = "CustomCtrl_%CustomCtrl_%RevoBIM%$panel%$button"
            Name  = ($p[3..($p.Count - 1)] -join '|').Trim().Replace('\n', "`n")
            Path  = "RevoBIM>$panel"
        }
    }
    $ourIds = @($wanted | ForEach-Object { $_.Id })
    Log ("--- keyboard shortcuts for Revit " + $Years + ($(if ($DryRun) { ' (dry run)' } else { '' })))

    foreach ($year in ($Years -split '[,; ]+' | Where-Object { $_ })) {
        try {
            $path = Join-Path $AppData "Autodesk\Revit\Autodesk Revit $year\KeyboardShortcuts.xml"
            if (-not (Test-Path $path)) {
                Log "Revit ${year}: no KeyboardShortcuts.xml yet, skipped. Start Revit once, change any shortcut (or open Keyboard Shortcuts and click OK), close Revit, then run the installer again."
                continue
            }
            $bytes = [System.IO.File]::ReadAllBytes($path)
            $bom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
            $enc = New-Object System.Text.UTF8Encoding($bom)
            $text = $enc.GetString($bytes)
            if ($bom) { $text = $text.TrimStart([char]0xFEFF) }
            $eol = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
            $lines = New-Object 'System.Collections.Generic.List[string]'
            foreach ($l in ($text -split "`r?`n")) { $lines.Add($l) }
            $changes = New-Object 'System.Collections.Generic.List[string]'

            foreach ($w in $wanted) {
                $key = $w.Keys
                $mine = -1
                for ($i = 0; $i -lt $lines.Count; $i++) {
                    if ($lines[$i].Contains('CommandId="' + $w.Id + '"')) { $mine = $i; break }
                }

                # Take the shortcut off any other command that has it.
                for ($i = 0; $i -lt $lines.Count; $i++) {
                    if ($i -eq $mine) { continue }
                    $m = [regex]::Match($lines[$i], ' Shortcuts="([^"]*)"')
                    if (-not $m.Success) { continue }
                    $idHere = [regex]::Match($lines[$i], 'CommandId="([^"]*)"').Groups[1].Value
                    if ($ourIds -contains $idHere) { continue }
                    $tokens = @($m.Groups[1].Value -split '#' | Where-Object { $_ -ne '' })
                    if (-not ($tokens | Where-Object { $_ -ieq $key })) { continue }
                    $left = @($tokens | Where-Object { $_ -ine $key })
                    $name = ([regex]::Match($lines[$i], 'CommandName="([^"]*)"').Groups[1].Value) -replace '&#xA;', ' '
                    $lines[$i] = $lines[$i].Remove($m.Index, $m.Length)
                    if ($left.Count -gt 0) {
                        $lines[$i] = $lines[$i].Insert($m.Index, ' Shortcuts="' + ($left -join '#') + '"')
                    }
                    $changes.Add("took $key off ""$name"" ($idHere)")
                }

                if ($mine -ge 0) {
                    $m = [regex]::Match($lines[$mine], ' Shortcuts="([^"]*)"')
                    $have = if ($m.Success) { @($m.Groups[1].Value -split '#' | Where-Object { $_ -ne '' }) } else { @() }
                    if ($have | Where-Object { $_ -ieq $key }) { continue }   # already as wanted
                    $joined = (@($key) + $have) -join '#'
                    if ($m.Success) {
                        $lines[$mine] = $lines[$mine].Remove($m.Index, $m.Length).Insert($m.Index, ' Shortcuts="' + $joined + '"')
                    } elseif ($lines[$mine].Contains(' Paths="')) {
                        $at = $lines[$mine].IndexOf(' Paths="')
                        $lines[$mine] = $lines[$mine].Insert($at, ' Shortcuts="' + $joined + '"')
                    } else {
                        $at = $lines[$mine].LastIndexOf('/>')
                        $lines[$mine] = $lines[$mine].Insert($at, ' Shortcuts="' + $joined + '" ')
                    }
                    $changes.Add("set $key on ""$($w.Name -replace "`n", ' ')""")
                } else {
                    # Revit has not written this command yet (it lists add-in buttons after it has run with
                    # them): add the line, in the form Revit writes.
                    $end = -1
                    for ($i = $lines.Count - 1; $i -ge 0; $i--) { if ($lines[$i].Trim() -eq '</Shortcuts>') { $end = $i; break } }
                    if ($end -lt 0) { throw 'no </Shortcuts> in the file' }
                    $lines.Insert($end, '  <ShortcutItem CommandName="' + (Xml-Attr $w.Name) + '" CommandId="' + (Xml-Attr $w.Id) +
                        '" Shortcuts="' + $key + '" Paths="' + (Xml-Attr $w.Path) + '" />')
                    $changes.Add("added $key for ""$($w.Name -replace "`n", ' ')"" (Revit had no line for it yet)")
                }
            }

            if ($changes.Count -eq 0) { Log "Revit ${year}: already set, nothing to change."; continue }
            $new = $lines -join $eol
            try { $check = New-Object System.Xml.XmlDocument; $check.LoadXml($new) }
            catch { throw "the edited file would not be well-formed XML ($($_.Exception.Message)); left alone" }

            foreach ($c in $changes) { Log "Revit ${year}: $c" }
            if ($DryRun) { Log "Revit ${year}: dry run, file not written."; continue }

            $stamp = (Get-Date).ToString('yyyyMMdd-HHmmss')
            Copy-Item $path "$path.revobim-backup-$stamp"
            [System.IO.File]::WriteAllBytes($path, $(if ($bom) { $enc.GetPreamble() } else { @() }) + $enc.GetBytes($new))
            Get-ChildItem (Split-Path -Parent $path) -Filter 'KeyboardShortcuts.xml.revobim-backup-*' |
                Sort-Object Name -Descending | Select-Object -Skip 5 | Remove-Item -Force -ErrorAction SilentlyContinue
            Log "Revit ${year}: written ($($changes.Count) change(s)); the old file is kept as KeyboardShortcuts.xml.revobim-backup-$stamp"
        } catch {
            Log "Revit ${year}: could not set the shortcuts: $($_.Exception.Message)"
        }
    }
} catch {
    Log "keyboard shortcuts: $($_.Exception.Message)"
}
exit 0
