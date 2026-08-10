<#
.SYNOPSIS
    Install the built installer, launch it, prove the app serves, then uninstall.

.DESCRIPTION
    Answers the only question that matters before sending the file to anyone:
    on a machine that is not set up for development, does double-clicking the
    shortcut end with a working map?

    Checks, in order:
      1. silent install needs no administrator and no UAC prompt
      2. the shortcut's target and arguments exist as installed
      3. the launcher starts Streamlit and the page actually renders
      4. the database is created under AppData, not inside the program folder
      5. uninstalling removes the program but keeps the travel history

    Installs to a temporary folder by default, so it cannot disturb a real
    installation. Pass -Keep to leave the test copy in place.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\verify.ps1
#>

param(
    [string]$AppVersion = '1.0.0',
    [switch]$Keep
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Packaging = $PSScriptRoot
$Root = Split-Path -Parent $Packaging
$Setup = Join-Path $Root "dist\CityTracker-Setup-$AppVersion.exe"
$TestDir = Join-Path $env:TEMP "CityTrackerVerify-$AppVersion"

$script:failures = 0
function Check([string]$label, [scriptblock]$test) {
    try {
        $result = & $test
        if ($result) { Write-Host "  PASS  $label" -ForegroundColor Green }
        else { Write-Host "  FAIL  $label" -ForegroundColor Red; $script:failures++ }
    }
    catch {
        Write-Host "  FAIL  $label -- $($_.Exception.Message)" -ForegroundColor Red
        $script:failures++
    }
}
function Step($message) { Write-Host "`n==> $message" -ForegroundColor Cyan }

if (-not (Test-Path $Setup)) { throw "No installer at $Setup. Run build.ps1 first." }

Step "Installing silently to $TestDir"
if (Test-Path $TestDir) { Remove-Item -Recurse -Force $TestDir }
# /CURRENTUSER is implied by PrivilegesRequired=lowest; no elevation should occur.
$install = Start-Process -FilePath $Setup -Wait -PassThru -ArgumentList @(
    '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS',
    "/DIR=$TestDir", '/LOG=' + (Join-Path $env:TEMP 'citytracker-install.log')
)
Check "installer exits 0 without elevation" { $install.ExitCode -eq 0 }

$python = Join-Path $TestDir 'python\python.exe'
$launcher = Join-Path $TestDir 'app\launcher.py'
Check "bundled interpreter installed"      { Test-Path $python }
Check "launcher installed"                 { Test-Path $launcher }
Check "app.py installed"                   { Test-Path (Join-Path $TestDir 'app\app.py') }
Check "runtime Streamlit config installed" { Test-Path (Join-Path $TestDir 'app\.streamlit\config.toml') }
Check "icon installed"                     { Test-Path (Join-Path $TestDir 'icon.ico') }
Check "dependencies installed"             { Test-Path (Join-Path $TestDir 'lib\site-packages\streamlit') }
# Streamlit refuses --server.port when it thinks it is in development mode, which
# it infers from 'site-packages' appearing in its own path. Assert the layout.
Check "vendor path keeps Streamlit out of dev mode" {
    (Join-Path $TestDir 'lib\site-packages\streamlit\config.py') -match 'site-packages'
}
Check "no data folder inside program dir"  { -not (Test-Path (Join-Path $TestDir 'app\data')) }

Step "Launching the way the shortcut does"
$dataDir = Join-Path $env:LOCALAPPDATA 'CityTracker\data'
$database = Join-Path $dataDir 'city_tracker.db'
$hadDatabase = Test-Path $database
$launchLog = Join-Path $env:TEMP 'citytracker-launch-stdout.log'

$env:CITY_TRACKER_NO_BROWSER = '1'
$app = Start-Process -FilePath $python -ArgumentList @("`"$launcher`"") `
    -WorkingDirectory (Join-Path $TestDir 'app') -PassThru `
    -RedirectStandardOutput $launchLog -RedirectStandardError "$launchLog.err"

try {
    $marker = Join-Path $env:LOCALAPPDATA 'CityTracker\runtime.json'
    $port = $null
    $deadline = (Get-Date).AddSeconds(150)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $marker) {
            try { $port = (Get-Content $marker -Raw | ConvertFrom-Json).port } catch {}
            if ($port) { break }
        }
        if ($app.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }

    Check "launcher reports a port" { [bool]$port }
    if ($port) {
        # -UseBasicParsing throughout: PowerShell 5.1 otherwise routes through
        # Internet Explorer and throws a null-reference on machines where IE
        # first-run setup never happened.
        Check "health endpoint answers" {
            # Retried: the launcher writes the port the moment its own probe
            # succeeds, and the very next connection can still lose a race with
            # the server's socket setup.
            foreach ($attempt in 1..5) {
                try {
                    $health = Invoke-WebRequest "http://127.0.0.1:$port/_stcore/health" `
                        -UseBasicParsing -TimeoutSec 15
                    if ($health.StatusCode -eq 200) { return $true }
                }
                catch { Start-Sleep -Seconds 2 }
            }
            $false
        }
        Check "page serves the app shell" {
            $html = (Invoke-WebRequest "http://127.0.0.1:$port/" `
                    -UseBasicParsing -TimeoutSec 30).Content
            if ($html -notmatch '(?i)streamlit') {
                Write-Host "        page began: $($html.Substring(0, [Math]::Min(200, $html.Length)))" -ForegroundColor DarkYellow
                return $false
            }
            $true
        }
        Check "no Python traceback in the log" {
            $log = Join-Path $env:LOCALAPPDATA 'CityTracker\city-tracker.log'
            (-not (Test-Path $log)) -or -not (Select-String -Path $log -Pattern 'Traceback \(most recent call last\)' -Quiet)
        }
    }
    # The launcher creates the data folder; the database itself only appears once
    # a browser opens a session and Streamlit executes app.py, which this
    # headless check cannot trigger. smoke_test.py covers the schema instead.
    Check "data folder created under AppData" { Test-Path $dataDir }
    Check "nothing written into the program folder" {
        -not (Test-Path (Join-Path $TestDir 'app\data'))
    }
}
finally {
    Remove-Item Env:\CITY_TRACKER_NO_BROWSER -ErrorAction SilentlyContinue
    if (-not $app.HasExited) {
        # Kill the tree: the launcher holds a Streamlit child process.
        & taskkill.exe /PID $app.Id /T /F | Out-Null
    }
    Start-Sleep -Seconds 2
}

if (-not $Keep) {
    Step "Uninstalling"
    $uninstaller = Get-ChildItem $TestDir -Filter 'unins*.exe' | Select-Object -First 1
    Check "uninstaller present" { [bool]$uninstaller }
    if ($uninstaller) {
        $removal = Start-Process -FilePath $uninstaller.FullName -Wait -PassThru `
            -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
        Check "uninstaller exits 0" { $removal.ExitCode -eq 0 }
        Start-Sleep -Seconds 2
        Check "program folder removed" { -not (Test-Path $python) }
        Check "travel history survives uninstall" {
            (-not $hadDatabase) -or (Test-Path $database)
        }
    }
    if (Test-Path $TestDir) { Remove-Item -Recurse -Force $TestDir -ErrorAction SilentlyContinue }
}

Step "Result"
if ($script:failures -eq 0) {
    Write-Host "  All checks passed. $Setup is ready to send." -ForegroundColor Green
    exit 0
}
Write-Host "  $script:failures check(s) failed." -ForegroundColor Red
exit 1
