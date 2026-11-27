<#
Runs inside the booted WinPE environment, as a winpeshl.ini LaunchApps step
BEFORE explorer.exe starts. The ISO/media's drive letter isn't fixed (it was
E: in testing, but that depends on what else is attached), so this finds the
Tools folder itself by checking each drive letter for it, then builds one
desktop shortcut per bundled .exe so Explorer's desktop has clickable icons.
#>
$ErrorActionPreference = "Continue"

$toolsRoot = $null
foreach ($i in 65..90) {
    $candidate = "$([char]$i):\Tools"
    if (Test-Path (Join-Path $candidate "x64")) { $toolsRoot = $candidate; break }
}
if (-not $toolsRoot) {
    Write-Host "winpe-desktop-setup: no Tools folder found on any drive - no shortcuts created"
    exit 0
}
Write-Host "winpe-desktop-setup: Tools folder found at $toolsRoot"

$desktop = "X:\Desktop"
New-Item -ItemType Directory -Force $desktop | Out-Null

# Point Explorer's desktop (both the per-user and "common"/all-users shell folders -
# WinPE has no real multi-user profiles, so set both to be safe) at X:\Desktop.
foreach ($key in @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
)) {
    New-Item -Path $key -Force | Out-Null
    Set-ItemProperty -Path $key -Name "Desktop" -Value $desktop
    Set-ItemProperty -Path $key -Name "Common Desktop" -Value $desktop -ErrorAction SilentlyContinue
}

$shell = New-Object -ComObject WScript.Shell
$count = 0
Get-ChildItem $toolsRoot -Recurse -Filter *.exe | ForEach-Object {
    $name = $_.BaseName -replace '_All$', '' -replace '_x64$', '' -replace '-x64$', '' -replace '_x86$', '' -replace '-x86$', '' -replace '_Eng$', ''
    $lnkPath = Join-Path $desktop "$name.lnk"
    $i = 1
    while (Test-Path $lnkPath) { $lnkPath = Join-Path $desktop "$name ($i).lnk"; $i++ }
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath = $_.FullName
    $lnk.WorkingDirectory = $_.DirectoryName
    $lnk.IconLocation = $_.FullName
    $lnk.Save()
    $count++
}
Write-Host "winpe-desktop-setup: created $count desktop shortcut(s) from $toolsRoot"
