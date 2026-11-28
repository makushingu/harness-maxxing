# Harness Maxxing on Windows, through WSL 2 (the Linux that ships with Windows 10 and 11).
#
#   irm https://raw.githubusercontent.com/makushingu/harness-maxxing/main/install.ps1 | iex
#
# What it does, each step only when it is not done yet:
#   1. turns WSL on (once, needs an administrator PowerShell and a restart of Windows);
#   2. installs an Ubuntu distribution in it (or uses the one named by $env:HM_DISTRO);
#   3. turns systemd on in that distribution (/etc/wsl.conf);
#   4. runs the Linux installer (install.sh) inside it, as root: the same one as on a server;
#   5. adds a task that starts the distribution when you sign in to Windows and keeps it running
#      (Windows stops a WSL distribution nobody uses, and Harness Maxxing with it).
# Harness Maxxing then answers on http://localhost:8787 in the browser of this PC.
#
# Settings (environment variables, all optional):
#   $env:HM_DISTRO = "Ubuntu-24.04"   the WSL distribution to install into (created when missing)
#   $env:HM_BRANCH = "main"           the branch to install (beta = the test channel)
#   $env:HM_KEEPALIVE = "0"           no task at sign-in (start it yourself: wsl -d <distro>)
# Remove: wsl -d <distro> -u root -- maxxing uninstall     (the distribution itself: wsl --unregister <distro>)
#         Unregister-ScheduledTask -TaskName "Harness Maxxing (WSL)" -Confirm:$false

$ErrorActionPreference = "Stop"
$env:WSL_UTF8 = "1"                    # wsl.exe answers in UTF-16 otherwise

$Distro = if ($env:HM_DISTRO) { $env:HM_DISTRO } else { "Ubuntu-24.04" }
$Branch = if ($env:HM_BRANCH) { $env:HM_BRANCH } else { "main" }
$TaskName = "Harness Maxxing (WSL)"
$Raw = "https://raw.githubusercontent.com/makushingu/harness-maxxing/$Branch/install.sh"

function Say($text) { Write-Host "  $text" }
function Ok($text) { Write-Host "  + $text" -ForegroundColor Green }
function Stop-Install($text) { Write-Host ""; Write-Host "  x $text" -ForegroundColor Red; Write-Host ""; exit 1 }

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Run wsl.exe, return its output as text; $LASTEXITCODE says whether it worked. Never throws.
function Wsl-Out {
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try { $out = & wsl.exe @args 2>&1 | Out-String } catch { $out = ""; $global:LASTEXITCODE = 1 }
    $ErrorActionPreference = $old
    return ($out -replace "`0", "")
}

function Distro-Exists {
    $list = Wsl-Out --list --quiet
    return [bool](($list -split "`r?`n") | Where-Object { $_.Trim() -eq $Distro })
}

function As-Root($command) {
    & wsl.exe -d $Distro -u root --exec bash -c $command | Out-Host      # --exec: no second parsing by a shell
    return $LASTEXITCODE
}

Write-Host ""
Write-Host "  Harness Maxxing - installation on Windows (WSL 2)" -ForegroundColor Cyan
Write-Host ""

# ---- 1. WSL -----------------------------------------------------------------------------------
if ([Environment]::OSVersion.Version.Build -lt 19041) {
    Stop-Install "Windows 10 version 2004 (build 19041) or later is needed for WSL 2 - update Windows first."
}
$hasWsl = [bool](Get-Command wsl.exe -ErrorAction SilentlyContinue)
if ($hasWsl) { Wsl-Out --status | Out-Null; $hasWsl = ($LASTEXITCODE -eq 0) }
if (-not $hasWsl) {
    if (-not (Test-Admin)) {
        Stop-Install "WSL is not turned on yet. Open PowerShell as administrator (right-click -> Run as administrator) and run this command again."
    }
    Say "turning WSL on (a few minutes)..."
    & wsl.exe --install --no-distribution
    Write-Host ""
    Ok "WSL is installed. Restart Windows, then run this command again: it goes on from here."
    Write-Host ""
    exit 0
}
Wsl-Out --set-default-version 2 | Out-Null
Ok "WSL is on"

# ---- 2. the distribution ----------------------------------------------------------------------
if (-not (Distro-Exists)) {
    Say "installing $Distro (a few minutes)..."
    & wsl.exe --install -d $Distro --no-launch
    if ($LASTEXITCODE -ne 0) { Stop-Install "$Distro could not be installed (wsl --install -d $Distro). See the message above; wsl --list --online shows the names available." }
    if (-not (Distro-Exists)) {
        # older WSL: the distribution is only registered by its first start - done here as root, with no account to create
        $launcher = ($Distro -replace "[-.]", "").ToLower() + ".exe"          # Ubuntu-24.04 -> ubuntu2404.exe
        if (Get-Command $launcher -ErrorAction SilentlyContinue) { & $launcher install --root }
    }
    if (-not (Distro-Exists)) { Stop-Install "$Distro is downloaded but not registered: start it once from the Start menu, then run this command again." }
    Ok "$Distro installed"
} else {
    Ok "$Distro is already here: Harness Maxxing is installed into it"
}
$version = Wsl-Out --list --verbose
if (($version -split "`r?`n") | Where-Object { $_ -match [regex]::Escape($Distro) -and $_.Trim() -match "\s1\s*$" }) {
    Say "$Distro runs under WSL 1: converting it to WSL 2..."
    & wsl.exe --set-version $Distro 2
    if ($LASTEXITCODE -ne 0) { Stop-Install "$Distro could not be converted to WSL 2 (wsl --set-version $Distro 2)." }
}
if ((As-Root "true") -ne 0) { Stop-Install "$Distro does not start (wsl -d $Distro -u root). See the message above." }

# ---- 3. systemd -------------------------------------------------------------------------------
if ((As-Root "test -d /run/systemd/system") -ne 0) {
    # single quotes only inside: Windows PowerShell 5 loses double quotes on the way to a program
    $conf = "grep -qs '^systemd *= *true' /etc/wsl.conf || { if grep -qs '^\[boot\]' /etc/wsl.conf; then sed -i 's/^\[boot\]/[boot]\nsystemd=true/' /etc/wsl.conf; else printf '\n[boot]\nsystemd=true\n' >> /etc/wsl.conf; fi; }"
    if ((As-Root $conf) -ne 0) { Stop-Install "could not turn systemd on in /etc/wsl.conf of $Distro." }
    Wsl-Out --terminate $Distro | Out-Null
    Start-Sleep -Seconds 3
    $up = $false
    foreach ($i in 1..20) {
        if ((As-Root "test -d /run/systemd/system") -eq 0) { $up = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $up) { Stop-Install "systemd does not start in $Distro. Update WSL (wsl --update), then run this command again." }
}
Ok "systemd runs in $Distro"

# ---- 4. the Linux installer -------------------------------------------------------------------
Say "running the installer inside $Distro..."
Write-Host ""
$inner = "command -v curl >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq curl ca-certificates; }; " +
         "curl -fsSL '$Raw' -o /tmp/hm-install.sh && BRANCH='$Branch' bash /tmp/hm-install.sh; rc=`$?; rm -f /tmp/hm-install.sh; exit `$rc"
& wsl.exe -d $Distro -u root --cd "~" --exec bash -c $inner
if ($LASTEXITCODE -ne 0) {
    Stop-Install "the installer stopped (see above). Fix it, then run this command again: every step keeps what is already done."
}

# ---- 5. start with Windows, keep running ------------------------------------------------------
if ($env:HM_KEEPALIVE -ne "0") {
    try {
        # conhost --headless: no console window stays open on the desktop
        $action = New-ScheduledTaskAction -Execute "conhost.exe" -Argument "--headless wsl.exe -d $Distro -u root --exec /bin/sleep infinity"
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -Hidden
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
        Start-ScheduledTask -TaskName $TaskName
        Ok "starts when you sign in to Windows and keeps running (task '$TaskName')"
    } catch {
        Say "! the task that keeps it running could not be created ($($_.Exception.Message))"
        Say "  Harness Maxxing runs while a terminal of $Distro is open: wsl -d $Distro"
    }
}

Write-Host ""
Ok "Harness Maxxing answers on http://localhost:8787 in the browser of this PC."
Say "Open the one-time link printed above to create your password."
Say "A terminal inside it: wsl -d $Distro -u root        Check: wsl -d $Distro -u root -- maxxing doctor"
Write-Host ""
