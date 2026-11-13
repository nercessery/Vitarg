# Downloads the Windows conversion tools into .\tools (FFmpeg, FFprobe, Pandoc). Run by build.ps1.
$ErrorActionPreference = "Stop"
$root  = Split-Path $PSScriptRoot -Parent
$tools = Join-Path $root "tools"
New-Item -ItemType Directory -Force -Path $tools, "$tools\licenses" | Out-Null
$tmp = Join-Path $env:TEMP "vitarg-tools"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Get-File($url, $out) {
    Write-Host "Downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
}

if (-not (Test-Path "$tools\ffmpeg.exe") -or -not (Test-Path "$tools\ffprobe.exe")) {
    $zip = "$tmp\ffmpeg.zip"
    # BtbN GPL build: includes libx264, libvpx, libopus, libvorbis, libmp3lame, libwebp
    Get-File "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" $zip
    Expand-Archive -Force $zip "$tmp\ffmpeg"
    $bin = Get-ChildItem "$tmp\ffmpeg" -Recurse -Filter ffmpeg.exe | Select-Object -First 1
    Copy-Item $bin.FullName "$tools\ffmpeg.exe" -Force
    Copy-Item (Join-Path $bin.DirectoryName "ffprobe.exe") "$tools\ffprobe.exe" -Force
    $lic = Get-ChildItem "$tmp\ffmpeg" -Recurse -Filter "LICENSE*" | Select-Object -First 1
    if ($lic) { Copy-Item $lic.FullName "$tools\licenses\FFmpeg-LICENSE.txt" -Force }
}

if (-not (Test-Path "$tools\pandoc.exe")) {
    $zip = "$tmp\pandoc.zip"
    try {
        Get-File "https://github.com/jgm/pandoc/releases/download/3.6.4/pandoc-3.6.4-windows-x86_64.zip" $zip
    } catch {
        Write-Host "Pinned Pandoc URL failed; asking the GitHub API for the latest release"
        $rel = Invoke-RestMethod "https://api.github.com/repos/jgm/pandoc/releases/latest"
        $asset = $rel.assets | Where-Object { $_.name -like "*windows-x86_64.zip" } | Select-Object -First 1
        Get-File $asset.browser_download_url $zip
    }
    Expand-Archive -Force $zip "$tmp\pandoc"
    $p = Get-ChildItem "$tmp\pandoc" -Recurse -Filter pandoc.exe | Select-Object -First 1
    Copy-Item $p.FullName "$tools\pandoc.exe" -Force
    $c = Get-ChildItem "$tmp\pandoc" -Recurse -Filter "COPYING*" | Select-Object -First 1
    if ($c) { Copy-Item $c.FullName "$tools\licenses\Pandoc-COPYING.txt" -Force }
}

foreach ($f in "ffmpeg.exe", "ffprobe.exe", "pandoc.exe") {
    if (-not (Test-Path "$tools\$f")) { throw "Tool missing after download: $f" }
}

# Optimize: Compress large binaries with UPX if available (saves ~300 MB)
$upx = (Get-Command upx -ErrorAction SilentlyContinue).Source
if ($upx) {
    Write-Host "Optimizing tools with UPX..."
    foreach ($f in "ffmpeg.exe", "ffprobe.exe", "pandoc.exe") {
        & $upx --best -q "$tools\$f" 2>&1 | Out-Null
    }
}
Write-Host "Tools ready in $tools"
