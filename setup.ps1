# Windows setup for Earth2Road (Godot + SUMO). Does not regenerate maps.
# Installs the offline example map when no map exists yet. Linux: ./setup.sh
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Replace-Stub([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        $item = Get-Item -LiteralPath $Path -Force
        if (-not $item.PSIsContainer) {
            Write-Host "Removing symlink stub $Path ($($item.Length) bytes)"
            Remove-Item -LiteralPath $Path -Force
        }
    }
}

Replace-Stub '.venv'
Replace-Stub '.tools'
New-Item -ItemType Directory -Force -Path .tools, .cache, logs | Out-Null

$py = Get-Command python -ErrorAction Stop
& $py.Source -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.11+ is required (3.14 is the pinned, validated version)." }
& $py.Source -m venv .venv
$venvPy = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPy)) {
    throw "venv python missing at $venvPy"
}
# Remove the old distribution first: its RECORD owns the same akadem_maps files
# and CLI aliases, so uninstalling it after installing Earth2Road would delete them.
& $venvPy -m pip uninstall -y terra-drive
if ($LASTEXITCODE -ne 0) { throw "Old distribution cleanup failed" }
& $venvPy -m pip install --cache-dir .cache/pip -c requirements.lock ".[generator,traffic]"
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

$godot = Join-Path $PSScriptRoot '.tools\Godot_v4.6-stable_win64.exe'
if (-not (Test-Path -LiteralPath $godot)) {
    $zip = Join-Path $PSScriptRoot '.tools\godot.zip'
    curl.exe -fL --retry 2 -o $zip "https://github.com/godotengine/godot/releases/download/4.6-stable/Godot_v4.6-stable_win64.exe.zip"
    if ($LASTEXITCODE -ne 0) { throw "Godot download failed" }
    Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $PSScriptRoot '.tools') -Force
}

& $venvPy tools/fetch_assets.py
if ($LASTEXITCODE -ne 0) { throw "fetch_assets failed" }
& $venvPy tools/fetch_textures.py
if ($LASTEXITCODE -ne 0) { Write-Host "Textures not downloaded — the game will use flat materials." }
& $venvPy tools/fetch_visual_assets.py
if ($LASTEXITCODE -ne 0) { Write-Host "CC0 visual pack not downloaded — benches and lamps stay procedural." }

# Builds game/.godot (class_name cache for the vehicle addon); start.ps1 repeats it if missing.
$godotAppData = Join-Path $PSScriptRoot '.cache\godot-user'
New-Item -ItemType Directory -Force -Path $godotAppData | Out-Null
$savedAppData = $env:APPDATA
$env:APPDATA = $godotAppData
Start-Process -FilePath $godot -ArgumentList @('--headless', '--path', 'game', '--import') -Wait -NoNewWindow
$env:APPDATA = $savedAppData

# A fresh checkout has no maps (game/data/ is not in Git): install the offline example so
# start.ps1 works right away. Skipped when any map is already installed.
if (-not (Test-Path -LiteralPath 'game\data\active_map')) {
    $cli = Join-Path $PSScriptRoot '.venv\Scripts\earth2road.exe'
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    & $cli build --config examples/tiny/config.json --inputs examples/tiny/inputs --offline --output "out/tiny-world-$stamp"
    if ($LASTEXITCODE -ne 0) { throw "Example map build failed" }
    & $cli export --target godot --world "out/tiny-world-$stamp" --output "out/tiny-godot-$stamp" --offline
    if ($LASTEXITCODE -ne 0) { throw "Example map export failed" }
    & $cli install --target godot --export "out/tiny-godot-$stamp" --root . --activate
    if ($LASTEXITCODE -ne 0) { throw "Example map install failed" }
}

Write-Host "Setup done. Run .\start.ps1 (the offline example map 'tiny' is installed if no other map was)."
Write-Host "To rebuild a map: .\.venv\Scripts\python.exe tools\prepare.py --config config\<id>.json --install [--replace] [--activate]"
Write-Host "BeamNG ZIP of a map: .\.venv\Scripts\earth2road export --target beamng --world out\generated\<id> --output out\<id>_beamng"
Write-Host "New map anywhere: .\start.ps1 --generate LAT LON [--size KM] [--name NAME], or M -> New map in the game."
