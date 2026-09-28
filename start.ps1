# Launch Godot + the SUMO traffic bridge on Windows. Linux: ./start.sh
# .\start.ps1 [--map ID] [--scenario NAME] [--density N] [--threads N] [--near N] [--teleport N] [-- godot args...]
# .\start.ps1 --generate LAT LON [--size KM] [--name NAME]: build a new map around a point first
#   (tools/generate_map.py; the same as "New map" in the game's map menu, M).
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$venvPy = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPy)) {
    throw "Missing .venv. Run .\setup.ps1 first."
}

function Find-Godot {
    $dir = Join-Path $PSScriptRoot '.tools'
    # Console build first: its log goes to this terminal.
    foreach ($name in @('Godot_v4.6-stable_win64_console.exe', 'Godot_v4.6-stable_win64.exe')) {
        $path = Join-Path $dir $name
        if (Test-Path -LiteralPath $path) { return $path }
    }
    throw "Godot 4.6 not found in .tools. Run .\setup.ps1."
}

$godot = Find-Godot
$env:PYTHONUNBUFFERED = '1'
# Map names and scenario titles are Ukrainian; a redirected stdout must not use cp1252.
$env:PYTHONUTF8 = '1'
$env:XDG_DATA_HOME = Join-Path $PSScriptRoot '.cache\data'
$env:XDG_CONFIG_HOME = Join-Path $PSScriptRoot '.cache\config'
$env:XDG_CACHE_HOME = Join-Path $PSScriptRoot '.cache'
$godotAppData = Join-Path $PSScriptRoot '.cache\godot-user'
New-Item -ItemType Directory -Force -Path logs, $env:XDG_DATA_HOME, $env:XDG_CONFIG_HOME, $godotAppData | Out-Null

# Godot resolves class_name types (the vehicle addon's Vehicle/Wheel) from game/.godot, which
# only an import creates. Without it main.gd fails to compile and the car never spawns.
$classCache = Join-Path $PSScriptRoot 'game\.godot\global_script_class_cache.cfg'
if (-not (Test-Path -LiteralPath $classCache)) {
    Write-Host 'First run: importing the Godot project (once)...'
    $savedAppData = $env:APPDATA
    $env:APPDATA = $godotAppData
    $import = Start-Process -FilePath $godot -ArgumentList @('--headless', '--path', 'game', '--import') `
        -Wait -PassThru -NoNewWindow
    $env:APPDATA = $savedAppData
    if (-not (Test-Path -LiteralPath $classCache)) {
        throw "Godot import failed (exit $($import.ExitCode)); run: $godot --headless --path game --import"
    }
}

$bridgeArgs = [System.Collections.Generic.List[string]]::new()
$explicitMap = $false
$generate = $null
$i = 0
while ($i -lt $args.Count) {
    $a = [string]$args[$i]
    if ($a -eq '--') { $i++; break }
    if ($a -eq '--map') {
        $explicitMap = $true
        $env:AKADEM_MAP = [string]$args[$i + 1]
        $i += 2
        continue
    }
    if ($a -eq '--generate') {
        $generate = [System.Collections.Generic.List[string]]::new()
        $generate.AddRange([string[]]@('--lat', [string]$args[$i + 1], '--lon', [string]$args[$i + 2]))
        $i += 3
        continue
    }
    if ($a -in @('--size', '--name') -and $null -ne $generate) {
        $generate.Add($(if ($a -eq '--size') { '--size-km' } else { '--name' }))
        $generate.Add([string]$args[$i + 1])
        $i += 2
        continue
    }
    if ($a -in @('--scenario', '--density', '--threads', '--near', '--teleport')) {
        $bridgeArgs.Add($a)
        $bridgeArgs.Add([string]$args[$i + 1])
        $i += 2
        continue
    }
    break
}
$godotArgs = @()
while ($i -lt $args.Count) {
    $godotArgs += [string]$args[$i]
    $i++
}

$mapFile = Join-Path $PSScriptRoot 'game\data\active_map'
if ($null -ne $generate) {
    & $venvPy tools/generate_map.py @generate
    if ($LASTEXITCODE -ne 0) { throw "Map generation failed (exit $LASTEXITCODE)." }
    # generate_map installs with --activate: active_map now names the new map.
    $env:AKADEM_MAP = (Get-Content -LiteralPath $mapFile -Raw).Trim()
    $explicitMap = $true
}
# No --map: the game opens its map menu first (M switches maps later as well).
$env:AKADEM_MAP_MENU = if ($explicitMap) { '' } else { '1' }
if (-not $env:AKADEM_MAP) {
    if (Test-Path -LiteralPath $mapFile) {
        $env:AKADEM_MAP = (Get-Content -LiteralPath $mapFile -Raw).Trim()
    } else {
        $env:AKADEM_MAP = 'akadem'
    }
}
$index = Join-Path $PSScriptRoot "game\data\$($env:AKADEM_MAP)\index.json"
if (-not (Test-Path -LiteralPath $index)) {
    throw "Map '$($env:AKADEM_MAP)' is not built. Run tools\prepare.py --config config\$($env:AKADEM_MAP).json --install"
}

# AKADEM_PORT (also read by the game) runs a second session side by side, with its own logs.
$logName = if ($env:AKADEM_PORT) { "bridge-$($env:AKADEM_PORT)" } else { 'bridge' }
if ($env:AKADEM_PORT) { $bridgeArgs.Add('--port'); $bridgeArgs.Add([string]$env:AKADEM_PORT) }
$bridgeLog = Join-Path $PSScriptRoot "logs\$logName.log"
$bridgeErr = Join-Path $PSScriptRoot "logs\$logName.err.log"
if (Test-Path -LiteralPath $bridgeLog) { Remove-Item -LiteralPath $bridgeLog -Force }
if (Test-Path -LiteralPath $bridgeErr) { Remove-Item -LiteralPath $bridgeErr -Force }
$bridgeArgArray = @('tools/traffic.py') + @($bridgeArgs)
function Start-Bridge {
    Start-Process -FilePath $venvPy -ArgumentList $bridgeArgArray -WorkingDirectory $PSScriptRoot `
        -RedirectStandardOutput $bridgeLog -RedirectStandardError $bridgeErr -PassThru -NoNewWindow
}
$bridge = Start-Bridge
$ready = $false
try {
    for ($n = 0; $n -lt 240; $n++) {
        Start-Sleep -Milliseconds 500
        $hit = $false
        if (Test-Path -LiteralPath $bridgeLog) {
            if (Select-String -LiteralPath $bridgeLog -Pattern 'Traffic bridge ready' -Quiet -ErrorAction SilentlyContinue) {
                $hit = $true
            }
        }
        if (-not $hit -and (Test-Path -LiteralPath $bridgeErr)) {
            if (Select-String -LiteralPath $bridgeErr -Pattern 'Traffic bridge ready' -Quiet -ErrorAction SilentlyContinue) {
                $hit = $true
            }
        }
        if ($hit) { $ready = $true; break }
        if ($bridge.HasExited) {
            if (Test-Path -LiteralPath $bridgeLog) { Get-Content -LiteralPath $bridgeLog -Tail 30 }
            if (Test-Path -LiteralPath $bridgeErr) { Get-Content -LiteralPath $bridgeErr -Tail 30 }
            throw "Traffic bridge exited before it was ready (code $($bridge.ExitCode))."
        }
    }
    if (-not $ready) {
        throw "Traffic bridge did not become ready in time. See logs\bridge.log"
    }
    $godotEnv = @{
        AKADEM_MAP = $env:AKADEM_MAP
        APPDATA = $godotAppData
        LOCALAPPDATA = $godotAppData
        XDG_DATA_HOME = $env:XDG_DATA_HOME
        XDG_CONFIG_HOME = $env:XDG_CONFIG_HOME
        XDG_CACHE_HOME = $env:XDG_CACHE_HOME
    }
    foreach ($key in $godotEnv.Keys) {
        Set-Item -Path "Env:$key" -Value $godotEnv[$key]
    }
    $godotCmd = @('--path', 'game') + $godotArgs
    # Wait for the game explicitly: PowerShell's `&` returns at once for a GUI-subsystem
    # executable, and the finally block below would then kill the traffic bridge while the
    # game is still starting (the "connecting to traffic" banner that never went away).
    $quoted = $godotCmd | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }
    $game = Start-Process -FilePath $godot -ArgumentList $quoted -NoNewWindow -PassThru
    $null = $game.Handle      # keeps ExitCode readable after the process ends
    # Supervise the bridge while the game runs: if it dies (SUMO runs in-process, so a native
    # crash takes Python with it), keep its logs and start a new one. The game reconnects on
    # its own and asks for its current map.
    $restarts = 0
    while (-not $game.WaitForExit(1000)) {
        if ($bridge.HasExited -and $restarts -lt 5) {
            $restarts++
            $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
            foreach ($pair in @(@($bridgeLog, "$logName.crash-$stamp.log"), @($bridgeErr, "$logName.crash-$stamp.err.log"))) {
                if (Test-Path -LiteralPath $pair[0]) {
                    Copy-Item -LiteralPath $pair[0] -Destination (Join-Path $PSScriptRoot "logs\$($pair[1])") -Force
                }
            }
            Write-Host "Traffic bridge stopped (code $($bridge.ExitCode)); restarting ($restarts/5). Logs: logs\$logName.crash-$stamp.*"
            $bridge = Start-Bridge
        }
    }
    exit $game.ExitCode
} finally {
    if ($bridge -and -not $bridge.HasExited) {
        Stop-Process -Id $bridge.Id -Force -ErrorAction SilentlyContinue
        try { $bridge.WaitForExit(5000) } catch { }
    }
}
