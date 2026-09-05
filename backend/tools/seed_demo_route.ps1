# Seed several distinct vehicle journeys for the demonstration.
#
#   powershell -File tools\seed_demo_route.ps1
#   powershell -File tools\seed_demo_route.ps1 -Reset    # clear the index first
#
# Each vehicle gets its OWN route: different cameras, different times, different
# speeds. An earlier version replayed the whole clip at every camera, which meant
# every plate appeared at every camera at the same instant and so every search
# returned an identical route — obviously wrong the moment you search a second
# plate.
#
# Timings are chosen from the real distances between these cameras, giving
# ordinary city speeds of roughly 20-55 km/h. One journey deliberately ends with
# an Ahmedabad-to-Rajkot leg minutes later, which is physically impossible and
# which the platform flags rather than hides — that is the behaviour worth
# demonstrating.
#
# Every plate written is read by the real detector and OCR from the clip. Only
# the timestamp is supplied, and only because the footage is a replay.

param(
    [string]$Video = "sample_feeds\own_feed_demo.mp4",
    [switch]$Reset
)

# Deliberately not "Stop": Python writes deprecation warnings to stderr, and
# PowerShell would treat those as terminating errors and abandon the seed
# part-way through. Failures are reported by the tools themselves.
$ErrorActionPreference = "Continue"
Push-Location (Split-Path -Parent $PSScriptRoot)

# One entry per vehicle. Cameras and minute offsets differ so the reconstructed
# routes are genuinely distinct.
$journeys = @(
    @{
        plate = "GJ01AB1234"
        note  = "City centre, then an impossible jump to Rajkot"
        legs  = @(
            @{ cam = "cam01"; minutes = 0 },    # Chimanbhai Bridge
            @{ cam = "cam14"; minutes = 6 },    # Delight RLVD      ~2.6 km
            @{ cam = "cam04"; minutes = 14 },   # Paldi Circle      ~4.5 km
            @{ cam = "cam13"; minutes = 21 },   # C N Vidyalaya     ~3.0 km
            @{ cam = "cam17"; minutes = 25 }    # Rajkot — 215 km. Impossible.
        )
    },
    @{
        plate = "GJ18CD5678"
        note  = "Northbound towards Gandhinagar"
        legs  = @(
            @{ cam = "cam04"; minutes = 8 },    # Paldi Circle
            @{ cam = "cam02"; minutes = 17 },   # Janpath, Ashram Road
            @{ cam = "cam05"; minutes = 29 },   # Visat Teen Rasta
            @{ cam = "cam12"; minutes = 44 }    # Adalaj Toll Naka
        )
    },
    @{
        plate = "MH12DE1433"
        note  = "Out-of-state vehicle crossing the city west to east"
        legs  = @(
            @{ cam = "cam15"; minutes = 3 },    # Suvidha Park
            @{ cam = "cam13"; minutes = 15 },   # C N Vidyalaya
            @{ cam = "cam14"; minutes = 26 },   # Delight RLVD
            @{ cam = "cam03"; minutes = 40 }    # ONGC, Chandkheda
        )
    },
    @{
        plate = "GJ05JV7219"
        note  = "Short hop, two sightings only"
        legs  = @(
            @{ cam = "cam16"; minutes = 12 },   # Visat P2
            @{ cam = "cam05"; minutes = 19 }    # Visat Teen Rasta
        )
    },
    @{
        plate = "RJ14GH9012"
        note  = "Northern corridor"
        legs  = @(
            @{ cam = "cam12"; minutes = 5 },    # Adalaj Toll Naka
            @{ cam = "cam05"; minutes = 22 },   # Visat Teen Rasta
            @{ cam = "cam01"; minutes = 34 }    # Chimanbhai Bridge
        )
    },
    @{
        plate = "GJ27XY4455"
        note  = "Single sighting — a vehicle seen once"
        legs  = @(
            @{ cam = "cam13"; minutes = 30 }    # C N Vidyalaya
        )
    }
)

if ($Reset) {
    Write-Host "Clearing existing detections and alerts..."
    python tools\reset_index.py --yes
}

$start = (Get-Date).ToUniversalTime().AddHours(-2)

foreach ($journey in $journeys) {
    Write-Host "`n$($journey.plate) — $($journey.note)"
    foreach ($leg in $journey.legs) {
        $stamp = $start.AddMinutes($leg.minutes).ToString("yyyy-MM-ddTHH:mm:ssZ")
        Write-Host "  $($leg.cam) at +$($leg.minutes) min"
        python tools\demo_seed.py --video $Video --camera $leg.cam `
            --detected-at $stamp --only-plate $journey.plate |
            Select-String -Pattern "plates indexed|alerts raised"
    }
}

Pop-Location
Write-Host "`nSix distinct journeys seeded. Search any plate and choose"
Write-Host "'Show Route on Map' — each returns its own route."
Write-Host "GJ01AB1234 ends with a flagged impossible transition to Rajkot."
