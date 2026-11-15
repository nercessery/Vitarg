# One-step build: venv -> dependencies -> tools -> tests -> PyInstaller -> self-test -> Inno Setup Installer
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Use-Venv($pythonExe) {
    $ErrorActionPreference = "Continue"
    $vp = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path $vp) {
        & $vp -c "import PIL, PySide6, fitz, docx, py7zr, win32com, PyInstaller" 2>&1 | Out-Host
        if ($LASTEXITCODE -eq 0) { return $true }
    }
    Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue
    & $pythonExe -m venv --system-site-packages .venv | Out-Host
    if ($LASTEXITCODE -ne 0) { return $false }
    & $vp -c "import PIL, PySide6, fitz, docx, py7zr, win32com, PyInstaller" 2>&1 | Out-Host
    if ($LASTEXITCODE -eq 0) { return $true }
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
& $py -m unittest discover -s tests -p "test_*.py" -v 2>&1 | Tee-Object -FilePath test-results.txt
$testExitCode = $LASTEXITCODE
$testsOk = ($testExitCode -eq 0)
$ErrorActionPreference = "Stop"
if (-not $testsOk -or $testExitCode -ne 0) {
    Write-Error "Unit tests failed with exit code $testExitCode (see test-results.txt). Halting build."
    exit 1
}

Write-Host "=== Building Application ==="
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
& $py -m PyInstaller --noconfirm --clean --windowed --name Vitarg `
    --icon assets\vitarg.ico `
    --add-data "assets;assets" --add-data "tools;tools" `
    --collect-all pillow_heif --collect-all py7zr --collect-all fitz --collect-all pymupdf `
    --hidden-import win32com.client --hidden-import pythoncom --hidden-import winsound `
    run_vitarg.py
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller build failed with exit code $LASTEXITCODE"
    exit 1
}

# Ensure tools and assets directories are accessible at dist\Vitarg root for layout compatibility
if (Test-Path "$root\dist\Vitarg\_internal\tools") {
    if (-not (Test-Path "$root\dist\Vitarg\tools")) {
        try {
            New-Item -ItemType Junction -Path "$root\dist\Vitarg\tools" -Target "$root\dist\Vitarg\_internal\tools" -ErrorAction SilentlyContinue | Out-Null
        } catch {}
    }
}
if (Test-Path "$root\dist\Vitarg\_internal\assets") {
    if (-not (Test-Path "$root\dist\Vitarg\assets")) {
        try {
            New-Item -ItemType Junction -Path "$root\dist\Vitarg\assets" -Target "$root\dist\Vitarg\_internal\assets" -ErrorAction SilentlyContinue | Out-Null
        } catch {}
    }
}

Write-Host "=== Self-test ==="
$exe = Join-Path $root "dist\Vitarg\Vitarg.exe"
if (-not (Test-Path $exe)) {
    Write-Error "Vitarg.exe not found at $exe"
    exit 1
}
$p = Start-Process $exe -ArgumentList "--selftest" -PassThru
$exited = $p.WaitForExit(30000)
if (-not $exited) {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    $report = Get-Content (Join-Path $env:TEMP "vitarg-selftest.txt") -ErrorAction SilentlyContinue
    Write-Error "Self-test timed out after 30 seconds! Report: $report"
    exit 1
}
$report = Get-Content (Join-Path $env:TEMP "vitarg-selftest.txt") -ErrorAction SilentlyContinue
Write-Host "Self-test exit code $($p.ExitCode): $report"
if ($p.ExitCode -ne 0) {
    Write-Error "Self-test failed with exit code $($p.ExitCode): $report"
    exit 1
}

Write-Host "=== Building Installer (Vitarg-Setup.exe) ==="
$iscc = @(
    (Get-Command iscc -ErrorAction SilentlyContinue).Source,
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if ($iscc) {
    & $iscc installer\Vitarg.iss
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Inno Setup compiler failed with exit code $LASTEXITCODE"
        exit 1
    }
    Write-Host "Installer built successfully: dist\Vitarg-Setup.exe"
} else {
    Write-Warning "Inno Setup compiler (iscc.exe) not found. Skipping installer creation. On GitHub Actions it will be installed automatically."
}

Write-Host "=== Build Completed Successfully ==="
exit 0
