param(
    [Parameter(Mandatory=$true)][string]$UserPath,
    [int]$TimeoutSeconds = 3600
)
$ErrorActionPreference = 'Stop'
$qaRoot = (Resolve-Path -LiteralPath $UserPath).Path
$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $qaRoot.StartsWith($workspace + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'QA userpath must be inside this workspace.'
}
$cfg = Get-Content -Raw -LiteralPath (Join-Path $qaRoot 'current/kyiv-qa-input.json') | ConvertFrom-Json
$exe = 'C:\Program Files (x86)\Steam\steamapps\common\BeamNG.drive\Bin64\BeamNG.drive.x64.exe'
$argsList = @('-userpath', $qaRoot, '-level', $cfg.level, '-onLevelLoad_ext', 'kyivqa', '-nosteam')
if ($qaRoot.Contains(' ')) { throw 'Use a QA path without spaces (BeamNG argument parser limitation).' }
$process = Start-Process -FilePath $exe -ArgumentList $argsList -WorkingDirectory (Split-Path $exe) -WindowStyle Hidden -PassThru
Write-Output "BeamNG QA PID $($process.Id), profile $qaRoot"
$watch = [Diagnostics.Stopwatch]::StartNew()
$memorySamples = [System.Collections.Generic.List[object]]::new()
$logPath = Join-Path $qaRoot 'current/beamng.log'
while (-not $process.HasExited) {
    Start-Sleep -Seconds 5
    $process.Refresh()
    if (-not $process.HasExited) {
        $memorySamples.Add([pscustomobject]@{seconds=$watch.Elapsed.TotalSeconds; workingSetBytes=$process.WorkingSet64; privateBytes=$process.PrivateMemorySize64})
    }
    if ($watch.Elapsed.TotalSeconds -gt $TimeoutSeconds) {
        Stop-Process -Id $process.Id -Force
        throw 'BeamNG QA process exceeded timeout.'
    }
    if (Test-Path -LiteralPath $logPath) {
        $tail = Get-Content -LiteralPath $logPath -Tail 40
        if ($tail -match 'TS_PROCESS_OOM|CefManager::fatalSubprocessError') {
            Stop-Process -Id $process.Id -Force
            throw 'BeamNG QA CEF process failed; see profile beamng.log.'
        }
    }
}
Write-Output "BeamNG exit code: $($process.ExitCode)"
$perf = [pscustomobject]@{elapsedSeconds=$watch.Elapsed.TotalSeconds; exitCode=$process.ExitCode; samples=$memorySamples}
$perf | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $qaRoot 'process-performance.json') -Encoding UTF8
$resultPath = Join-Path $qaRoot 'current/kyiv-qa-result.json'
if (Test-Path -LiteralPath $resultPath) {
    $result = Get-Content -Raw -LiteralPath $resultPath | ConvertFrom-Json
    Write-Output "QA status: $($result.status); cases: $($result.cases.Count); nav: $($result.navNodes)"
}
