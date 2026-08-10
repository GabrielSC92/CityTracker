<#
.SYNOPSIS
    Build dist\CityTracker-Setup-<version>.exe - a self-contained Windows
    installer for people who have neither Python nor an IDE.

.DESCRIPTION
    Stages three things into build\payload and hands them to Inno Setup:

      python\             Python's official embeddable distribution, unzipped
      lib\site-packages\  every dependency in requirements.txt, as wheels
      app\                the application plus launcher.py

    The vendor folder must be named site-packages: Streamlit decides whether it
    is running in "development mode" by looking for that word in its own
    __file__, and development mode refuses --server.port outright.

    The embeddable distribution ignores the machine's registry and PATH, so the
    installed copy cannot be broken by whatever Python a friend installs later.

.PARAMETER PythonVersion
    Embeddable runtime to bundle. Must match the *minor* version of the Python
    on this machine, since that Python resolves the wheels.

.PARAMETER AppVersion
    Stamped into the installer filename, Add/Remove Programs and the exe.

.PARAMETER NoPrune
    Keep dependency test suites (roughly 40 MB) instead of deleting them.

.PARAMETER Unpinned
    Ignore packaging\requirements-lock.txt, resolve requirements.txt afresh and
    rewrite the lock. Use after deliberately upgrading a dependency - then run
    the app from a checkout and make sure it still behaves before shipping.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -AppVersion 1.0.0
#>

param(
    [string]$PythonVersion = '3.13.13',
    [string]$AppVersion = '1.0.0',
    [switch]$NoPrune,
    [switch]$Unpinned
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Packaging = $PSScriptRoot
$Root = Split-Path -Parent $Packaging
$Build = Join-Path $Root 'build'
$Cache = Join-Path $Build 'cache'
$Payload = Join-Path $Build 'payload'
$Dist = Join-Path $Root 'dist'

$AppFiles = @('app.py', 'db.py', 'geocode.py', 'continents.py')

function Step($message) { Write-Host "`n==> $message" -ForegroundColor Cyan }
function Note($message) { Write-Host "    $message" -ForegroundColor DarkGray }

function Resolve-Iscc {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    $onPath = Get-Command 'iscc' -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    throw "Inno Setup 6 not found. Install it with: winget install JRSoftware.InnoSetup"
}

function Resolve-HostPython([string]$version) {
    # The wheels are resolved by this interpreter but executed by the bundled
    # one, so the minor version and architecture have to agree.
    $wanted = ($version -split '\.')[0, 1] -join '.'
    # No quotes anywhere in the probe: PowerShell strips inner quotes when it
    # hands an argument to a native executable, which mangles f-strings.
    $probe = 'import sys,platform;print(sys.version_info.major,sys.version_info.minor,platform.machine())'

    $candidates = @(
        @{ Exe = 'py'; Args = @("-$wanted") },
        @{ Exe = 'python'; Args = @() },
        @{ Exe = 'py'; Args = @() }
    )
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
        $label = (@($candidate.Exe) + $candidate.Args) -join ' '
        try {
            $reported = & $candidate.Exe @($candidate.Args + @('-c', $probe))
        }
        catch { continue }
        if ($LASTEXITCODE -ne 0 -or -not $reported) { continue }
        $major, $minor, $machine = ("$reported" -split '\s+')
        $found = "$major.$minor"
        if ($found -eq $wanted -and $machine -eq 'AMD64') { return $candidate }
        Note "skipping '$label' (Python $found $machine)"
    }
    throw "No 64-bit Python $wanted found to resolve wheels with. Install it, or pass -PythonVersion to match a Python you do have."
}

function Invoke-HostPython($python, [string[]]$arguments) {
    & $python.Exe @($python.Args + $arguments)
}

# ---------------------------------------------------------------- fetch runtime
$iscc = Resolve-Iscc
$hostPython = Resolve-HostPython $PythonVersion
Note "Inno Setup:  $iscc"
Note "Wheel host:  $((@($hostPython.Exe) + $hostPython.Args) -join ' ')"

Step "Fetching Python $PythonVersion (embeddable)"
New-Item -ItemType Directory -Force $Cache | Out-Null
$embedZip = Join-Path $Cache "python-$PythonVersion-embed-amd64.zip"
if (Test-Path $embedZip) {
    Note "cached: $embedZip"
}
else {
    $url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
    Note $url
    Invoke-WebRequest -Uri $url -OutFile $embedZip -TimeoutSec 300
}

# ------------------------------------------------------------------ stage files
Step "Staging payload"
if (Test-Path $Payload) { Remove-Item -Recurse -Force $Payload }
$pythonDir = Join-Path $Payload 'python'
# Named site-packages on purpose - see the note in the header comment.
$libDir = Join-Path $Payload 'lib\site-packages'
$appDir = Join-Path $Payload 'app'
New-Item -ItemType Directory -Force $pythonDir, $libDir, $appDir | Out-Null

Expand-Archive -Path $embedZip -DestinationPath $pythonDir -Force

# The embeddable build disables site-packages by default. Point its path file at
# the vendor folder and re-enable `site` so plain imports find the dependencies.
# Paths in a ._pth file are relative to the folder holding python.exe.
$pthFile = Get-ChildItem $pythonDir -Filter 'python*._pth' | Select-Object -First 1
if (-not $pthFile) { throw "No python*._pth in the embeddable zip - layout changed?" }
$stdlibZip = (Get-ChildItem $pythonDir -Filter 'python*.zip' | Select-Object -First 1).Name
@($stdlibZip, '.', '..\lib\site-packages', '', 'import site') |
    Set-Content -Path $pthFile.FullName -Encoding ascii
Note "patched $($pthFile.Name) -> ..\lib\site-packages"

$lockFile = Join-Path $Packaging 'requirements-lock.txt'
$usingLock = (Test-Path $lockFile) -and -not $Unpinned
$requirements = if ($usingLock) { $lockFile } else { Join-Path $Root 'requirements.txt' }

Step "Resolving dependencies into lib\"
Note $(if ($usingLock) { "pinned: $lockFile" } else { "re-resolving from requirements.txt" })
Invoke-HostPython $hostPython @(
    '-m', 'pip', 'install',
    '--disable-pip-version-check', '--no-input', '--no-warn-script-location',
    '--only-binary=:all:', '--target', $libDir,
    '-r', $requirements
)
if ($LASTEXITCODE -ne 0) { throw "pip install failed with exit code $LASTEXITCODE" }

if (-not $usingLock) {
    # Record exactly what shipped. Friends' installs should not differ from the
    # set the app was last tested against just because a build happened later.
    $frozen = Invoke-HostPython $hostPython @(
        '-m', 'pip', 'list', '--disable-pip-version-check',
        '--path', $libDir, '--format=freeze'
    )
    if ($LASTEXITCODE -eq 0 -and $frozen) {
        @(
            '# Generated by packaging\build.ps1 -Unpinned. Every dependency that',
            '# went into the last installer, so a rebuild ships the same set.',
            '# Refresh with: packaging\build.ps1 -Unpinned'
        ) + $frozen | Set-Content -Path $lockFile -Encoding ascii
        Note "wrote $lockFile"
    }
}

if (-not $NoPrune) {
    Step "Pruning test suites and console shims"
    # Test suites are dead weight at runtime; *.dist-info is NOT touched, since
    # Streamlit reads its own version through importlib.metadata at startup.
    $pruned = 0
    foreach ($package in @('pandas', 'numpy', 'pyarrow')) {
        $packageDir = Join-Path $libDir $package
        if (-not (Test-Path $packageDir)) { continue }
        # Recurse: numpy keeps test suites in submodules too (numpy\random\tests).
        $suites = Get-ChildItem $packageDir -Recurse -Directory -Filter 'tests' -ErrorAction SilentlyContinue
        foreach ($suite in $suites) {
            if (-not (Test-Path $suite.FullName)) { continue }
            $pruned += (Get-ChildItem $suite.FullName -Recurse -File | Measure-Object Length -Sum).Sum
            Remove-Item -Recurse -Force $suite.FullName
        }
    }
    $binDir = Join-Path $libDir 'bin'
    if (Test-Path $binDir) { Remove-Item -Recurse -Force $binDir }
    Note ("removed {0:N0} MB" -f ($pruned / 1MB))
}

Step "Copying application"
foreach ($file in $AppFiles) {
    $source = Join-Path $Root $file
    if (-not (Test-Path $source)) { throw "Missing application file: $source" }
    Copy-Item $source $appDir
}
Copy-Item (Join-Path $Packaging 'launcher.py') $appDir
Copy-Item (Join-Path $Packaging 'icon.ico') $Payload
$streamlitDir = Join-Path $appDir '.streamlit'
New-Item -ItemType Directory -Force $streamlitDir | Out-Null
Copy-Item (Join-Path $Packaging 'runtime-config.toml') (Join-Path $streamlitDir 'config.toml')

$staged = (Get-ChildItem $Payload -Recurse -File | Measure-Object Length -Sum).Sum
Note ("payload: {0:N0} MB across {1:N0} files" -f ($staged / 1MB), (Get-ChildItem $Payload -Recurse -File).Count)

# ------------------------------------------------------------- smoke-test first
# Runs with the bundled interpreter, from the staged app folder, so it exercises
# the same runtime, dependency set and Streamlit config a friend will get.
Step "Smoke-testing the bundled runtime"
$bundledPython = Join-Path $pythonDir 'python.exe'
Push-Location $appDir
try {
    & $bundledPython (Join-Path $Packaging 'smoke_test.py') $appDir
}
finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw "The staged bundle failed its smoke test - not compiling an installer." }

# ------------------------------------------------------------------- compile it
Step "Compiling installer"
New-Item -ItemType Directory -Force $Dist | Out-Null
& $iscc "/DAppVersion=$AppVersion" "/DPayloadDir=$Payload" (Join-Path $Packaging 'installer.iss')
if ($LASTEXITCODE -ne 0) { throw "ISCC failed with exit code $LASTEXITCODE" }

$setup = Join-Path $Dist "CityTracker-Setup-$AppVersion.exe"
Step "Done"
Write-Host ("    {0}" -f $setup) -ForegroundColor Green
Write-Host ("    {0:N1} MB to send your friends" -f ((Get-Item $setup).Length / 1MB)) -ForegroundColor Green
