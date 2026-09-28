param([ValidateSet('shots','drive','surface','benchmark')][string]$Mode='surface')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$env:AKADEM_MAP='rivne_mykolaiv'
$env:APPDATA=Join-Path (Get-Location) '.cache/godot-user'
$env:PYTHONUTF8='1'
$env:PYTHONUNBUFFERED='1'
$env:AKADEM_PORT='8771'
$qaDir=Join-Path (Get-Location) '.cache/rivne-qa'
New-Item -ItemType Directory -Path $qaDir,$env:APPDATA -Force | Out-Null
$bridge=$null
$proc=$null
try {
    if ($Mode -eq 'benchmark') {
        $bridge=Start-Process -FilePath '.venv/Scripts/python.exe' -ArgumentList 'tools/traffic.py --port 8771 --density 20 --threads 1' -WindowStyle Hidden -PassThru -RedirectStandardOutput "$qaDir/bridge.log" -RedirectStandardError "$qaDir/bridge.err.log"
        $ready=$false
        for ($i=0;$i -lt 60;$i++) {
            if ($bridge.HasExited) { throw 'Traffic bridge exited before readiness' }
            if ((Test-Path "$qaDir/bridge.log") -and (Select-String -LiteralPath "$qaDir/bridge.log" -Pattern 'Traffic bridge ready' -Quiet)) { $ready=$true; break }
            Start-Sleep -Milliseconds 500
        }
        if (-not $ready) { throw 'Traffic bridge readiness timeout' }
    }
    $godotArgs='--path game --audio-driver Dummy '
    switch ($Mode) {
        'surface' { $godotArgs+='--headless --script res://scripts/validate_surface.gd' }
        'drive' { $godotArgs+='--headless --fixed-fps 120 --script res://scripts/validate_rural_drive.gd' }
        'shots' { $godotArgs+='--resolution 1920x1080 -- --offline --shots' }
        'benchmark' { $godotArgs+='--resolution 1920x1080 -- --seconds=60 --no-vsync --capture' }
    }
    $proc=Start-Process -FilePath '.tools/Godot_v4.6-stable_win64.exe' -ArgumentList $godotArgs -WindowStyle Hidden -PassThru -RedirectStandardOutput "$qaDir/$Mode.log" -RedirectStandardError "$qaDir/$Mode.err.log"
    Set-Content -LiteralPath "$qaDir/$Mode.pid" -Value $proc.Id
    $watch=[Diagnostics.Stopwatch]::StartNew()
    while (-not $proc.WaitForExit(500)) {
        if ($watch.Elapsed.TotalSeconds -gt 240) { throw 'Godot QA timed out' }
        if ((Test-Path "$qaDir/$Mode.err.log") -and (Select-String -LiteralPath "$qaDir/$Mode.err.log" -Pattern 'Parse Error|Failed to load script' -Quiet)) { throw 'Godot script error; inspect QA log' }
    }
    $code=$proc.ExitCode
    if (Test-Path "$qaDir/$Mode.err.log") { Get-Content "$qaDir/$Mode.err.log" -Tail 12 }
    Get-Content "$qaDir/$Mode.log" -Tail 8
    if ($Mode -eq 'benchmark' -and (Test-Path 'logs/render_metrics.json')) {
        Copy-Item -LiteralPath 'logs/render_metrics.json' -Destination "$qaDir/render_metrics.json" -Force
    }
    exit $code
} finally {
    if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
    if ($bridge -and -not $bridge.HasExited) { Stop-Process -Id $bridge.Id -Force }
}
