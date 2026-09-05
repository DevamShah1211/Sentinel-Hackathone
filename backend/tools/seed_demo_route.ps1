# Seed a realistic vehicle route for the demonstration.
#
# Sightings are spaced by the time a vehicle would actually take between these
# cameras, so the reconstructed route shows plausible city speeds rather than a
# wall of "physically impossible" flags. One deliberately impossible leg is left
# at the end — an Ahmedabad-to-Rajkot jump in minutes — so the demonstration can
# show the system catching its own error, which is the point worth making.
#
#   powershell -File tools\seed_demo_route.ps1
#
# Every plate written is read by the real detector and OCR from the clip; only
# the timestamp is supplied, and only because the clip is replayed footage.

param([string]$Video = "sample_feeds\own_feed_demo.mp4")

$ErrorActionPreference = "Stop"
Push-Location (Split-Path -Parent $PSScriptRoot)

# Camera, minutes after the start. Distances are real, so these intervals give
# 25-55 km/h through Ahmedabad — ordinary city traffic.
$legs = @(
    @{ cam = "cam01"; minutes = 0 },    # Chimanbhai Bridge, Ahmedabad
    @{ cam = "cam14"; minutes = 6 },    # Delight RLVD, ~2.6 km
    @{ cam = "cam04"; minutes = 14 },   # Paldi Circle, ~4.5 km
    @{ cam = "cam13"; minutes = 21 },   # C N Vidyalaya, ~3.0 km
    @{ cam = "cam15"; minutes = 32 },   # Suvidha Park, ~5.8 km
    @{ cam = "cam05"; minutes = 41 },   # Visat Teen Rasta, ~4.4 km
    @{ cam = "cam12"; minutes = 55 },   # Adalaj Toll Naka, ~8.0 km
    # Rajkot is ~215 km away. Four minutes later is impossible, and the platform
    # flags it rather than hiding it.
    @{ cam = "cam17"; minutes = 59 }
)

$start = (Get-Date).ToUniversalTime().AddHours(-2)

foreach ($leg in $legs) {
    $stamp = $start.AddMinutes($leg.minutes).ToString("yyyy-MM-ddTHH:mm:ssZ")
    Write-Host "seeding $($leg.cam) at +$($leg.minutes) min ($stamp)"
    python tools\demo_seed.py --video $Video --camera $leg.cam --detected-at $stamp |
        Select-String -Pattern "plates indexed|alerts raised"
}

Pop-Location
Write-Host "`nRoute seeded. Search a plate (e.g. GJ01AB1234) and choose 'Show Route on Map'."
