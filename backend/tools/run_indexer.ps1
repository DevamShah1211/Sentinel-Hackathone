# Start the continuous ANPR indexer detached, so it survives terminal closure.
#
# The playbook's single highest-leverage decision: the grid replays roughly twelve
# hours of footage per camera on a loop, so an indexer started early has already
# seen every plate at every camera by the time it is needed. Start it and leave it.
#
#   powershell -File tools\run_indexer.ps1                 # 6 cameras
#   powershell -File tools\run_indexer.ps1 -MaxStreams 10  # more, if CPU allows
#   powershell -File tools\run_indexer.ps1 -Stop           # stop it
#
# Measured capacity on a 20-core CPU: ~26 concurrent tiled-ANPR streams.
# See DOCS/MEASUREMENTS.md.

param(
    [int]$MaxStreams = 6,
    [switch]$Stop,
    [string]$LogDir = "$PSScriptRoot\..\logs"
)

$ErrorActionPreference = "Stop"
$backend = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $LogDir "indexer.pid"

if ($Stop) {
    if (Test-Path $pidFile) {
        $indexerPid = Get-Content $pidFile
        try {
            Stop-Process -Id $indexerPid -Force -ErrorAction Stop
            Write-Host "Stopped indexer (pid $indexerPid)"
        } catch {
            Write-Host "Indexer pid $indexerPid was not running"
        }
        Remove-Item $pidFile -Force
    } else {
        Write-Host "No indexer pid file found at $pidFile"
    }
    exit 0
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out = Join-Path $LogDir "indexer_$stamp.log"
$err = Join-Path $LogDir "indexer_$stamp.err"

Push-Location $backend
try {
    $process = Start-Process python `
        -ArgumentList "anpr_worker.py", "--max-streams", $MaxStreams `
        -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $out -RedirectStandardError $err
    $process.Id | Set-Content $pidFile
    Write-Host "ANPR indexer started (pid $($process.Id)), indexing $MaxStreams streams"
    Write-Host "  log:  $out"
    Write-Host "  stop: powershell -File tools\run_indexer.ps1 -Stop"
} finally {
    Pop-Location
}
