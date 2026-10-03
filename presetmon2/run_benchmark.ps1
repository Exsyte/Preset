<#
.SYNOPSIS
  Runs the PresetMon2 benchmark: one BEFORE pass and several AFTER passes captured
  with the PresentMon 2 console application, then builds the HTML report.

.DESCRIPTION
  Every setting comes from preset.json (process, 104 s duration, PresentMon flags,
  output folder, pass file names). Run from an elevated PowerShell, or from an
  account in the "Performance Log Users" group - PresentMon needs ETW access.

.PARAMETER Preset      Path to the preset JSON (default: preset.json next to this script).
.PARAMETER PresentMon  Path to the PresentMon 2 console exe (default: capture.executable from the preset).
.PARAMETER OutputDir   Folder for the CSVs/report (default: capture.output_dir from the preset).
.PARAMETER Pass        Only run these pass keys, e.g. -Pass after,after_second (BEFORE id is kept).
.PARAMETER NoPrompt    Do not wait for Enter before each pass.
.PARAMETER NoReport    Capture only; skip the report step.

.EXAMPLE
  .\run_benchmark.ps1 -PresentMon C:\Tools\PresentMon-2.3.0-x64.exe
#>
[CmdletBinding()]
param(
    [string]$Preset = (Join-Path $PSScriptRoot 'preset.json'),
    [string]$PresentMon,
    [string]$OutputDir,
    [string[]]$Pass,
    [switch]$NoPrompt,
    [switch]$NoReport
)

$ErrorActionPreference = 'Stop'

$cfg = Get-Content -LiteralPath $Preset -Raw | ConvertFrom-Json
$cap = $cfg.capture

if (-not $OutputDir) { $OutputDir = [Environment]::ExpandEnvironmentVariables($cap.output_dir) }
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

if (-not $PresentMon) { $PresentMon = $cap.executable }
$found = Get-Command $PresentMon -ErrorAction SilentlyContinue
if (-not $found) {
    throw "PresentMon console not found: '$PresentMon'. Get the PresentMon 2 console application from https://github.com/GameTechDev/PresentMon/releases and pass -PresentMon <path>."
}
$exe = $found.Source

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Warning 'Not elevated. PresentMon needs administrator rights or membership of "Performance Log Users".'
}

$passes = @($cap.passes)
if ($Pass) { $passes = @($passes | Where-Object { $Pass -contains $_.key }) }
if ($passes.Count -eq 0) { throw 'No passes selected.' }

# A new benchmark id is generated with each BEFORE pass; AFTER-only runs reuse the stored one.
$idFile = Join-Path $OutputDir $cfg.benchmark_id.file
$runsBefore = @($passes | Where-Object { $_.key -eq 'before' }).Count -gt 0
if ($runsBefore -or -not (Test-Path -LiteralPath $idFile)) {
    $suffix = [guid]::NewGuid().ToString('N').Substring(0, [int]$cfg.benchmark_id.hex_digits).ToUpper()
    $id = '{0}-{1}' -f $cfg.benchmark_id.prefix, $suffix
    Set-Content -LiteralPath $idFile -Value $id -Encoding ascii -NoNewline
}
Write-Host ("Benchmark ID: " + (Get-Content -LiteralPath $idFile -Raw))

foreach ($p in $passes) {
    $csv = Join-Path $OutputDir $p.csv
    if (-not $NoPrompt) {
        Read-Host ("[{0}] Put {1} on the benchmark map, then press Enter to start the {2}s capture" -f $p.label, $cap.process_name, $cap.duration_secs) | Out-Null
    }
    if (Test-Path -LiteralPath $csv) { Remove-Item -LiteralPath $csv -Force }

    $pmArgs = @('--process_name', $cap.process_name,
                '--output_file', $csv,
                '--timed', [string]$cap.duration_secs,
                '--session_name', $cap.session_name)
    if ([int]$cap.delay_secs -gt 0) { $pmArgs += @('--delay', [string]$cap.delay_secs) }
    $pmArgs += @($cap.args)

    Write-Host ("[{0}] {1} {2}" -f $p.label, $exe, ($pmArgs -join ' '))
    & $exe @pmArgs
    if ($LASTEXITCODE -ne 0) { throw "PresentMon exited with code $LASTEXITCODE during pass '$($p.label)'." }
    if (-not (Test-Path -LiteralPath $csv) -or (Get-Item -LiteralPath $csv).Length -eq 0) {
        throw "No frames were captured for pass '$($p.label)'. Is $($cap.process_name) running and presenting frames?"
    }
    Write-Host ("[{0}] saved {1}" -f $p.label, $csv)
}

if ($NoReport) { return }

$python = Get-Command py -ErrorAction SilentlyContinue
$pyArgs = @()
if ($python) { $pyArgs = @('-3') } else { $python = Get-Command python -ErrorAction SilentlyContinue }
if (-not $python) {
    Write-Warning "Python 3 not found - captures are saved. Build the report later with: python -m presetmon2 report --dir `"$OutputDir`""
    return
}

Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    & $python.Source @pyArgs -m presetmon2 --preset $Preset report --dir $OutputDir
    if ($LASTEXITCODE -ne 0) { throw "Report generation failed (exit code $LASTEXITCODE)." }
} finally {
    Pop-Location
}
Invoke-Item (Join-Path $OutputDir 'benchmark_report.html')
