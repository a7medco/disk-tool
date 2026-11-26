<#
Builds a custom WinPE amd64 ISO using the official Windows ADK + WinPE add-on
(Microsoft "Create a bootable Windows PE drive" / "copype" docs). Adds the
optional components needed for PowerShell, basic storage, and networking.

Must run on Windows with the ADK + WinPE add-on already installed (silent,
Deployment Tools + WinPE features only). Run from an elevated PowerShell.

Output: $OutIso (default .\WinPE_amd64.iso)
#>
param(
    [string]$WorkDir = "$env:RUNNER_TEMP\WinPE_amd64",
    [string]$OutIso = ".\WinPE_amd64.iso",
    [string]$AdkRoot = "${env:ProgramFiles(x86)}\Windows Kits\10",
    [string]$ToolsSrcDir = (Join-Path (Split-Path $PSScriptRoot -Parent) "winpe-tools"),
    [switch]$SkipSafetyScanner
)
$ErrorActionPreference = "Stop"

Write-Host "Using ADK root: $AdkRoot"
$OCs = Join-Path $AdkRoot "Assessment and Deployment Kit\Windows Preinstallation Environment\amd64\WinPE_OCs"
$OCsEn = Join-Path $OCs "en-us"

if (Test-Path $WorkDir) { Remove-Item $WorkDir -Recurse -Force }

# copype lives in the ADK's WinPE add-on folder, not in Deployment Tools
$CopypeCmd = Join-Path $AdkRoot "Assessment and Deployment Kit\Windows Preinstallation Environment\copype.cmd"
if (-not (Test-Path $CopypeCmd)) { throw "copype.cmd not found under $AdkRoot - is the WinPE add-on installed?" }
if (-not (Test-Path $OCs)) { throw "WinPE_OCs folder not found: $OCs" }

# copype reads several env vars (WinPERoot, OSCDImgRoot, ...) that only the ADK's own
# "Deployment and Imaging Tools Environment" sets up (Microsoft docs: run copype from
# there). DandISetEnv.bat must run in the SAME cmd session as copype.cmd.
$DandISetEnv = Join-Path $AdkRoot "Assessment and Deployment Kit\Deployment Tools\DandISetEnv.bat"
if (-not (Test-Path $DandISetEnv)) { throw "DandISetEnv.bat not found: $DandISetEnv" }

Write-Host "1/4  copype amd64 $WorkDir"
& cmd /c """$DandISetEnv"" && ""$CopypeCmd"" amd64 ""$WorkDir"""
if ($LASTEXITCODE -ne 0) { throw "copype failed ($LASTEXITCODE)" }

$Mount = Join-Path $WorkDir "mount"
$Boot = Join-Path $WorkDir "media\sources\boot.wim"

Write-Host "2/4  Mounting boot.wim and adding optional components"
Dism /Mount-Image /ImageFile:"$Boot" /index:1 /MountDir:"$Mount"
if ($LASTEXITCODE -ne 0) { throw "Mount-Image failed" }

# Order matters (Microsoft "WinPE: Add packages"):
#   WinPE-WMI -> WinPE-NetFX -> WinPE-Scripting -> WinPE-PowerShell -> WinPE-StorageWMI
# Each *-neutral cab needs its en-us language cab added right after it.
$Components = @(
    "WinPE-WMI",
    "WinPE-NetFX",
    "WinPE-Scripting",
    "WinPE-PowerShell",
    "WinPE-StorageWMI",
    "WinPE-DismCmdlets",
    "WinPE-SecureBootCmdlets",
    "WinPE-SecureStartup",
    "WinPE-EnhancedStorage"
)
try {
    foreach ($c in $Components) {
        $cab = Join-Path $OCs "$c.cab"
        if (-not (Test-Path $cab)) { throw "Missing optional component: $cab" }
        Write-Host "    + $c"
        Dism /Image:"$Mount" /Add-Package /PackagePath:"$cab"
        if ($LASTEXITCODE -ne 0) { throw "Add-Package failed for $c" }
        $cabEn = Join-Path $OCsEn "$c`_en-us.cab"
        if (Test-Path $cabEn) {
            Dism /Image:"$Mount" /Add-Package /PackagePath:"$cabEn"
            if ($LASTEXITCODE -ne 0) { throw "Add-Package failed for $c en-us" }
        }
    }

    Write-Host "3/4  Making the network stack start automatically (wpeinit)"
    $StartNet = Join-Path $Mount "Windows\System32\startnet.cmd"
    $content = Get-Content $StartNet -Raw
    if ($content -notmatch "wpeinit") {
        Add-Content $StartNet "`r`nwpeinit`r`n"
    }

    # EXPERIMENT (Phase 3): Microsoft Safety Scanner (msert.exe) - official, free, but
    # Microsoft documents it only for a running Windows install, not WinPE. Downloaded
    # fresh on every build (it expires 10 days after download) so it's always current.
    # Whether it actually runs here at all is what this experiment is testing.
    if (-not $SkipSafetyScanner) {
        Write-Host "    Downloading Microsoft Safety Scanner (64-bit, official link)"
        $ToolsDir = Join-Path $Mount "Windows\System32\Tools"
        New-Item -ItemType Directory -Force $ToolsDir | Out-Null
        Invoke-WebRequest "https://go.microsoft.com/fwlink/?LinkId=212732" -OutFile (Join-Path $ToolsDir "msert.exe")
        Write-Host ("    msert.exe: {0:N0} MB" -f ((Get-Item (Join-Path $ToolsDir "msert.exe")).Length / 1MB))
    }
} finally {
    Write-Host "    Unmounting (commit)"
    Dism /Unmount-Image /MountDir:"$Mount" /commit
}

if (Test-Path $ToolsSrcDir) {
    Write-Host "    Copying portable tools onto the media (not into boot.wim - keeps RAM use low)"
    $MediaTools = Join-Path $WorkDir "media\Tools"
    New-Item -ItemType Directory -Force $MediaTools | Out-Null
    Copy-Item (Join-Path $ToolsSrcDir "*") $MediaTools -Recurse -Force
    Write-Host ("    {0:N0} MB of tools added" -f ((Get-ChildItem $MediaTools -Recurse -File | Measure-Object Length -Sum).Sum / 1MB))
} else {
    Write-Host "    (no bin\tools folder found - skipping portable tools)"
}

Write-Host "4/4  Building the ISO"
# MakeWinPEMedia.cmd lives directly under the WinPE add-on root. DandISetEnv.bat (and/or
# MakeWinPEMedia.cmd itself) can change the current directory, so resolve the output path
# to an absolute one first - a relative $OutIso would otherwise land somewhere else.
$MakeWinPEMedia = Join-Path $AdkRoot "Assessment and Deployment Kit\Windows Preinstallation Environment\MakeWinPEMedia.cmd"
if (-not (Test-Path $MakeWinPEMedia)) { throw "MakeWinPEMedia.cmd not found" }
$OutIsoAbs = if ([System.IO.Path]::IsPathRooted($OutIso)) { $OutIso } else { Join-Path (Get-Location) $OutIso }
& cmd /c """$DandISetEnv"" && ""$MakeWinPEMedia"" /ISO ""$WorkDir"" ""$OutIsoAbs"""
if ($LASTEXITCODE -ne 0) { throw "MakeWinPEMedia failed ($LASTEXITCODE)" }

if (-not (Test-Path $OutIsoAbs)) { throw "ISO was not created: $OutIsoAbs" }
$OutIso = $OutIsoAbs
$size = (Get-Item $OutIso).Length
Write-Host ("[OK] {0} ({1:N0} MB)" -f $OutIso, ($size / 1MB))
if ($size -lt 200MB) { throw "ISO looks too small ($([math]::Round($size/1MB)) MB) - something is missing" }
