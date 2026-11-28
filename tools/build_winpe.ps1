<#
Builds a custom WinPE amd64 ISO using the official Windows ADK + WinPE add-on
(Microsoft "Create a bootable Windows PE drive" / "copype" docs). Adds the
optional components needed for PowerShell, basic storage, and networking.

EXPERIMENTAL additions (Phase 3b): a full .NET Framework runtime (fixes .NET
apps like the real HDD Low Level Format Tool exe, which WinPE-NetFx's partial
v4.0.30319 folder can't run), plus an auto-login Explorer desktop shell with
one shortcut per bundled tool, instead of the bare cmd.exe prompt. Neither of
these is an official, Microsoft-supported WinPE configuration - see the
comments at each section. Pass -SkipDesktopShell to keep the old cmd.exe-only
shell if the Explorer shell causes problems.

Must run on Windows with the ADK + WinPE add-on already installed (silent,
Deployment Tools + WinPE features only). Run from an elevated PowerShell.

Output: $OutIso (default .\WinPE_amd64.iso)
#>
param(
    [string]$WorkDir = "$env:RUNNER_TEMP\WinPE_amd64",
    [string]$OutIso = ".\WinPE_amd64.iso",
    [string]$AdkRoot = "${env:ProgramFiles(x86)}\Windows Kits\10",
    [string]$ToolsSrcDir = (Join-Path (Split-Path $PSScriptRoot -Parent) "winpe-tools"),
    [switch]$SkipSafetyScanner,
    [switch]$SkipDesktopShell
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
    # DIAGNOSTIC: five full boot-tests in a row (different ownership handling, CRLF-fixed
    # winpeshl.ini, running this section first vs last) all found explorer.exe/winpeshl.ini
    # confirmed present right after writing (Test-Path passes at write-time every time), yet
    # completely absent from the final booted ISO every single time. The one pattern that
    # held across every success (WinSxS, the full .NET copy, msert.exe) and every failure
    # (explorer.exe, winpeshl.ini, winpe-desktop-setup.ps1) is: every file that DOES survive
    # lives in a SUBFOLDER (new or pre-existing) under Windows\ or Windows\System32\, while
    # every file that's dropped was written DIRECTLY as an immediate child of Windows\ or
    # Windows\System32\ themselves. These two canary files test that theory in isolation,
    # independent of winpeshl.exe's own parsing: the CI smoke-test checks for them in the
    # final ISO. If they're also missing, direct writes to these two root folders don't
    # survive DISM's /commit at all (regardless of feature); if they DO survive, the theory
    # is wrong and the real cause is still unknown.
    New-Item -ItemType File -Force (Join-Path $Mount "Windows\zzz-canary-winroot.txt") -Value "canary" | Out-Null
    New-Item -ItemType File -Force (Join-Path $Mount "Windows\System32\zzz-canary-sys32.txt") -Value "canary" | Out-Null

    # EXPERIMENT (Phase 3b): auto-login Explorer desktop instead of bare cmd.exe. This is
    # NOT an official/supported WinPE configuration - WinPE has no real logon or user
    # profile system, and modern Explorer's Start menu/taskbar search depend on AppX/UWP
    # packages (ShellExperienceHost, StartMenuExperienceHost) that don't exist in WinPE at
    # all, so those pieces may not work even though this gets the desktop + icons showing.
    # Falls back to the old cmd.exe-only shell (by simply not creating winpeshl.ini) if the
    # build machine itself has no explorer.exe (e.g. a Server Core runner) or -SkipDesktopShell.
    #
    # explorer.exe and winpe-desktop-setup.ps1 now go into a dedicated new subfolder
    # (Windows\System32\DiskToolShell\), matching the msert.exe\Tools pattern that's
    # consistently survived every build - per the canary-file theory above. winpeshl.ini
    # itself has no such option: winpeshl.exe hardcodes %SYSTEMROOT%\System32\winpeshl.ini
    # as its only lookup location, so it must stay at the System32 root regardless.
    $ExplorerSrc = Join-Path $env:WINDIR "explorer.exe"
    if ($SkipDesktopShell) {
        Write-Host "    -SkipDesktopShell passed - keeping the cmd.exe-only shell"
    } elseif (-not (Test-Path $ExplorerSrc)) {
        Write-Host "    ! $ExplorerSrc not found on the build machine - keeping the cmd.exe-only shell"
    } else {
        Write-Host "    Adding an auto-login Explorer desktop with shortcuts to the bundled tools"
        $Sys32 = Join-Path $Mount "Windows\System32"
        $ShellDir = Join-Path $Sys32 "DiskToolShell"
        New-Item -ItemType Directory -Force $ShellDir | Out-Null
        Copy-Item $ExplorerSrc (Join-Path $ShellDir "explorer.exe") -Force
        Copy-Item (Join-Path $PSScriptRoot "winpe-desktop-setup.ps1") (Join-Path $ShellDir "winpe-desktop-setup.ps1") -Force

        # winpeshl.ini, if present, REPLACES the default cmd.exe/startnet.cmd auto-start -
        # so startnet.cmd (which calls wpeinit - network/storage driver init) has to be
        # called explicitly here as the first step, or it would silently stop running.
        #
        # winpeshl.exe's own [LaunchApps] parser silently ignores the whole file if its
        # lines aren't CRLF-terminated - it doesn't error, it just behaves exactly as if
        # winpeshl.ini didn't exist at all. This script is edited/saved with LF-only line
        # endings (a Mac editor), so a bare here-string's embedded newlines are LF, not
        # CRLF. Join the lines with an explicit "`r`n" instead of relying on the source
        # file's own line endings, so the written winpeshl.ini has real CRLF regardless of
        # how this .ps1 is saved.
        $WinpeShlIni = @(
            "[LaunchApps]",
            "cmd.exe, /c %SYSTEMDRIVE%\Windows\System32\startnet.cmd",
            "powershell.exe, -NoProfile -ExecutionPolicy Bypass -File %SYSTEMDRIVE%\Windows\System32\DiskToolShell\winpe-desktop-setup.ps1",
            "%SYSTEMDRIVE%\Windows\System32\DiskToolShell\explorer.exe"
        ) -join "`r`n"
        $WinpeShlIni += "`r`n"
        Set-Content -Path (Join-Path $Sys32 "winpeshl.ini") -Value $WinpeShlIni -Encoding ascii -NoNewline
        Write-Host "    + DiskToolShell\explorer.exe, DiskToolShell\winpe-desktop-setup.ps1, winpeshl.ini"

        foreach ($f in @((Join-Path $ShellDir "explorer.exe"), (Join-Path $Sys32 "winpeshl.ini"), (Join-Path $ShellDir "winpe-desktop-setup.ps1"))) {
            if (-not (Test-Path $f)) { throw "DEBUG: $f missing immediately after writing it (still mounted) - write itself failed silently" }
        }
        Write-Host "    [debug] DiskToolShell\explorer.exe/winpeshl.ini/DiskToolShell\winpe-desktop-setup.ps1 all confirmed present in the mounted image"
    }

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

    # Best-effort: newer/older ADK releases sometimes ship extra .NET-related OCs under
    # these or similar names (current ADKs only have WinPE-NetFX, already added above -
    # it provides .NET's own WMI/PowerShell needs but not a full CLR for arbitrary .NET
    # apps, which the manual CLR copy below actually fixes). Add them if present; skip
    # quietly if this ADK doesn't have them so the build never fails over an optional cab.
    foreach ($c in @("WinPE-NetFx4", "WinPE-NetFX45")) {
        $cab = Join-Path $OCs "$c.cab"
        if (-not (Test-Path $cab)) {
            Write-Host "    (optional component $c.cab not present in this ADK - skipping)"
            continue
        }
        Write-Host "    + $c (optional)"
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

    # Fix: themed GUI apps (TeraCopy, CrystalDiskInfo, HWiNFO, ...) fail in bare WinPE with
    # "the application has failed to start because its side-by-side configuration is
    # incorrect" - WinPE's boot.wim doesn't carry the Microsoft.Windows.Common-Controls v6
    # (comctl32 v6, themed controls) assembly that their manifests ask for. The build
    # machine's own Windows install always has it; copy it (the real DLL assembly plus its
    # publisher-policy redirect assembly) into the WinPE image's WinSxS store.
    Write-Host "    Adding Common Controls v6 to WinSxS (fixes themed GUI tools in WinPE)"
    # Most of the bundled 32-bit tools' manifests ask for processorArchitecture="X86" even
    # though WinPE is amd64 - that's the x86_* WinSxS entry (used via WOW64), not amd64_*.
    # Checked each tool's embedded manifest directly (strings winpe-tools\*.exe): confirmed
    # most request X86, a couple (built 64-bit) request amd64 - so both must be copied.
    $ccDirs = Get-ChildItem "$env:WINDIR\WinSxS" -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^(amd64|x86)_.*common-controls_6595b64144ccf1df' }
    if (-not $ccDirs) { throw "Common Controls v6 assembly not found under $env:WINDIR\WinSxS - can't fix the SxS error" }
    # WinSxS itself (and its WinSxS\Manifests subfolder) is TrustedInstaller-owned even in a
    # DISM-mounted image - Administrators can't create new entries under it without this.
    foreach ($p in @("Windows\WinSxS", "Windows\WinSxS\Manifests")) {
        $full = Join-Path $Mount $p
        takeown /f $full | Out-Null
        icacls $full /grant "*S-1-5-32-544:(OI)(CI)F" | Out-Null
    }
    foreach ($dir in $ccDirs) {
        $dst = Join-Path $Mount "Windows\WinSxS\$($dir.Name)"
        if (Test-Path $dst) {
            # WinPE may already ship an older copy, owned by TrustedInstaller - take it over first
            takeown /f $dst /r /d Y | Out-Null
            icacls $dst /grant "*S-1-5-32-544:(OI)(CI)F" /t /c | Out-Null
            Remove-Item $dst -Recurse -Force
        }
        Copy-Item $dir.FullName $dst -Recurse -Force
        $manifest = Join-Path "$env:WINDIR\WinSxS\Manifests" "$($dir.Name).manifest"
        if (Test-Path $manifest) {
            $dstManifest = Join-Path $Mount "Windows\WinSxS\Manifests\$($dir.Name).manifest"
            if (Test-Path $dstManifest) {
                takeown /f $dstManifest | Out-Null
                icacls $dstManifest /grant "*S-1-5-32-544:F" | Out-Null
            }
            Copy-Item $manifest $dstManifest -Force
        }
        Write-Host "    + $($dir.Name)"
    }

    # EXPERIMENT (Phase 3b): full .NET Framework runtime (CLR), not just WinPE-NetFx's
    # partial one. Boot-testing found WinPE-NetFx's v4.0.30319 folder has only a few
    # sbscmp*/SharedReg dlls and no clr.dll - any real .NET app (e.g. the HDD Low Level
    # Format Tool's actual LLFTOOL.exe) launches and exits instantly with no window and
    # no error. Copy the build machine's own full Framework/Framework64 v4.0.30319
    # folders over WinPE's partial ones, same "take it from the host OS" approach as the
    # Common Controls fix above.
    Write-Host "    Adding full .NET Framework runtime (fixes .NET apps silently failing)"
    $netDirs = @(
        "Microsoft.NET\Framework64\v4.0.30319",
        "Microsoft.NET\Framework\v4.0.30319"
    )
    $netRoot = Join-Path $Mount "Windows\Microsoft.NET"
    if (Test-Path $netRoot) {
        takeown /f $netRoot /r /d Y | Out-Null
        icacls $netRoot /grant "*S-1-5-32-544:(OI)(CI)F" /t /c | Out-Null
    }
    foreach ($rel in $netDirs) {
        $src = Join-Path $env:WINDIR $rel
        if (-not (Test-Path $src)) {
            Write-Host "    ! $src not found on the build machine - skipping ($rel)"
            continue
        }
        $dst = Join-Path $Mount "Windows\$rel"
        New-Item -ItemType Directory -Force (Split-Path $dst -Parent) | Out-Null
        if (Test-Path $dst) {
            # Deleting WinPE-NetFx's existing (partial) folder outright hit "Access is
            # denied" on individual files even after takeown/icacls (CI run 46078760099) -
            # clearing attributes and overwriting file-by-file instead is more forgiving.
            Get-ChildItem $dst -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object {
                try { $_.Attributes = "Normal" } catch {}
            }
        }
        Copy-Item $src $dst -Recurse -Force
        Write-Host ("    + {0} ({1:N0} MB)" -f $rel, ((Get-ChildItem $dst -Recurse -File | Measure-Object Length -Sum).Sum / 1MB))
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
    # A forced-failure debug run (commit 17123dd) confirmed HDDLowLevelFormatTool_x64.exe
    # DOES reach the checkout and the media copy correctly (116,472,244 bytes, proper "MZ" PE
    # header, both before and after Copy-Item) once `lfs: true` is on the checkout step - two
    # earlier boot-tests that found the old 41,959,413-byte file were most likely a one-off
    # flaky LFS fetch in actions/checkout, not a real bug here. Kept a real (OR, not AND) size
    # guard so a future flake fails loud instead of silently shipping the wrong exe.
    $llfSrc = Join-Path $ToolsSrcDir "x64\HDDLowLevelFormatTool_x64.exe"
    if (Test-Path $llfSrc) {
        Write-Host ("    HDDLowLevelFormatTool_x64.exe at checkout: {0:N0} bytes" -f (Get-Item $llfSrc).Length)
    }
    $MediaTools = Join-Path $WorkDir "media\Tools"
    New-Item -ItemType Directory -Force $MediaTools | Out-Null
    Copy-Item (Join-Path $ToolsSrcDir "*") $MediaTools -Recurse -Force
    Write-Host ("    {0:N0} MB of tools added" -f ((Get-ChildItem $MediaTools -Recurse -File | Measure-Object Length -Sum).Sum / 1MB))
    $llfMedia = Join-Path $MediaTools "x64\HDDLowLevelFormatTool_x64.exe"
    if (-not (Test-Path $llfMedia) -or (Get-Item $llfMedia).Length -lt 50MB) {
        $actual = if (Test-Path $llfMedia) { "{0:N0} bytes" -f (Get-Item $llfMedia).Length } else { "missing" }
        throw "HDDLowLevelFormatTool_x64.exe on the media is wrong ($actual) - expected ~116MB (real exe via git-lfs). The checkout likely didn't fetch real LFS content this time (lfs: true can be flaky) - rerun the job."
    }
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
