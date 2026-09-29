$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$env:XDG_DATA_HOME = Join-Path (Get-Location) '.cache\data'
$env:XDG_CONFIG_HOME = Join-Path (Get-Location) '.cache\config'
$env:XDG_CACHE_HOME = Join-Path (Get-Location) '.cache'
$env:APPDATA = Join-Path (Get-Location) '.cache\godot-user'
if (-not $env:AKADEM_MAP) {
    $active = Join-Path (Get-Location) 'game\data\active_map'
    $env:AKADEM_MAP = if (Test-Path $active) { (Get-Content $active -Raw).Trim() } else { 'akadem' }
}
$godot = Join-Path (Get-Location) '.tools\Godot_v4.6-stable_win64_console.exe'
if (-not (Test-Path $godot)) { $godot = Join-Path (Get-Location) '.tools\Godot_v4.6-stable_win64.exe' }
if (-not (Test-Path $godot)) { throw "Godot 4.6 not found. Run setup.ps1." }
$check = Start-Process -FilePath $godot -ArgumentList @('--headless', '--path', 'game', '--script', 'res://scripts/validate_drive.gd') -NoNewWindow -PassThru
$null = $check.Handle
$check.WaitForExit()
exit $check.ExitCode
