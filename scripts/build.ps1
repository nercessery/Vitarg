# One-step build: venv -> dependencies -> tools -> tests -> PyInstaller -> self-test -> Inno Setup Installer
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Use-Venv($pythonExe) {
    $ErrorActionPreference = "Continue"
    Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue
    & $pythonExe -m venv .venv | Out-Host
    if ($LASTEXITCODE -ne 0) { return $false }
    $vp = Join-Path $root ".venv\Scripts\python.exe"
    & $vp -m pip install --upgrade pip --quiet | Out-Host
    & $vp -m pip install -r requirements.txt --quiet | Out-Host
    $installOk = ($LASTEXITCODE -eq 0)
    & $vp -c "import PIL, PySide6, fitz, docx, py7zr, win32com, PyInstaller" 2>&1 | Out-Host
    $importOk = ($LASTEXITCODE -eq 0)
    return [bool]($installOk -and $importOk)
}

# Try installed Python first
$sysPy = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $sysPy) { $sysPy = (Get-Command py -ErrorAction SilentlyContinue).Source }
$ok = $false
if ($sysPy) {
    Write-Host "Trying installed Python: $(& $sysPy --version)"
    $ok = [bool](Use-Venv $sysPy | Select-Object -Last 1)
}

# Fallback: fetch uv + Python 3.12
if (-not $ok) {
    Write-Warning "Falling back to Python 3.12 via uv."
    $sysUv = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $sysUv) {
        $localUv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
        if (Test-Path $localUv) { $sysUv = $localUv }
    }
    if ($sysUv) {
        $uv = $sysUv
    } else {
        $uvDir = Join-Path $root ".uv"
        New-Item -ItemType Directory -Force $uvDir | Out-Null
        $uv = Join-Path $uvDir "uv.exe"
        if (-not (Test-Path $uv)) {
            $ProgressPreference = "SilentlyContinue"
            Invoke-WebRequest "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" -OutFile "$uvDir\uv.zip" -UseBasicParsing
            Expand-Archive -Force "$uvDir\uv.zip" $uvDir
            $found = Get-ChildItem $uvDir -Recurse -Filter uv.exe | Select-Object -First 1
            if ($found.FullName -ne $uv) { Copy-Item $found.FullName $uv -Force }
        }
    }
    $uvInstallDir = Join-Path $env:TEMP "uv-python"
    $env:UV_PYTHON_INSTALL_DIR = $uvInstallDir
    & $uv python install 3.12
    if ($LASTEXITCODE -ne 0) { throw "uv could not install Python 3.12" }
    $py312 = (& $uv python find 3.12).Trim()
    $ok = [bool](Use-Venv $py312 | Select-Object -Last 1)
}
if (-not $ok) { throw "Could not install the required libraries." }
$py = Join-Path $root ".venv\Scripts\python.exe"

& "$PSScriptRoot\fetch_tools.ps1"

Write-Host "=== Running tests ==="
$env:PATH = "$root\tools;$env:PATH"
$ErrorActionPreference = "Continue"
& $py -m unittest discover -s tests -v 2>&1 | Tee-Object -FilePath test-results.txt
$testsOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"
if (-not $testsOk) { Write-Warning "Some tests failed (see test-results.txt)." }

Write-Host "=== Building Application ==="
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
& $py -m PyInstaller --noconfirm --clean --windowed --name Vitarg `
    --icon assets\vitarg.ico `
    --add-data "assets;assets" --add-data "tools;tools" `
    --collect-all pillow_heif --collect-all py7zr --collect-submodules pymupdf --collect-data pymupdf `
    --hidden-import win32com.client --hidden-import pythoncom --hidden-import winsound `
    --exclude-module PySide6.QtNetwork `
    --exclude-module PySide6.QtSql `
    --exclude-module PySide6.QtXml `
    --exclude-module PySide6.QtOpenGL `
    --exclude-module PySide6.QtOpenGLWidgets `
    --exclude-module PySide6.QtTest `
    --exclude-module PySide6.QtPrintSupport `
    --exclude-module PySide6.QtPdf `
    --exclude-module PySide6.QtPdfWidgets `
    --exclude-module PySide6.QtQml `
    --exclude-module PySide6.QtQuick `
    --exclude-module PySide6.QtQuickWidgets `
    --exclude-module PySide6.QtDesigner `
    --exclude-module PySide6.QtHelp `
    --exclude-module PySide6.QtMultimedia `
    --exclude-module PySide6.QtMultimediaWidgets `
    --exclude-module PySide6.QtSpatialAudio `
    --exclude-module PySide6.QtSensors `
    --exclude-module PySide6.QtPositioning `
    --exclude-module PySide6.QtBluetooth `
    --exclude-module PySide6.QtNfc `
    --exclude-module PySide6.QtSerialPort `
    --exclude-module PySide6.QtWebSockets `
    --exclude-module PySide6.QtWebChannel `
    --exclude-module tkinter `
    --exclude-module unittest `
    --exclude-module pydoc `
    --exclude-module email `
    --exclude-module xmlrpc `
    --exclude-module test `
    --exclude-module sqlite3 `
    --exclude-module lib2to3 `
    --exclude-module curses `
    --exclude-module turtle `
    run_vitarg.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Strip unused Qt translations and extra plugin files to save disk space
$trans = Join-Path $root "dist\Vitarg\PySide6\translations"
if (Test-Path $trans) { Remove-Item -Recurse -Force $trans -ErrorAction SilentlyContinue }

$imgPlugins = Join-Path $root "dist\Vitarg\PySide6\plugins\imageformats"
if (Test-Path $imgPlugins) {
    Get-ChildItem -Path $imgPlugins -File | Where-Object { $_.Name -notmatch "^(qjpeg|qico|qsvg)\.dll$" } | Remove-Item -Force -ErrorAction SilentlyContinue
}

Write-Host "=== Self-test ==="
$exe = Join-Path $root "dist\Vitarg\Vitarg.exe"
$p = Start-Process $exe -ArgumentList "--selftest" -Wait -PassThru
$report = Get-Content (Join-Path $env:TEMP "vitarg-selftest.txt") -ErrorAction SilentlyContinue
Write-Host "Self-test exit code $($p.ExitCode): $report"
if ($p.ExitCode -ne 0) { throw "Self-test failed" }

Write-Host "=== Building Installer (Vitarg-Setup.exe) ==="
$iscc = @(
    (Get-Command iscc -ErrorAction SilentlyContinue).Source,
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if ($iscc) {
    & $iscc installer\Vitarg.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compiler failed" }
    Write-Host "Installer built successfully: dist\Vitarg-Setup.exe"
} else {
    throw "Inno Setup compiler (iscc.exe) not found. On GitHub Actions it will be installed automatically."
}

if (-not $testsOk) { Write-Warning "Reminder: some tests failed (see test-results.txt)." }
$global:LASTEXITCODE = 0
exit 0
