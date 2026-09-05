param(
    [string]$FFmpegDirectory = "",
    [string]$DenoPath = ""
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$Python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Execute instalar.bat primeiro." }
if (-not $FFmpegDirectory) {
    $FFmpegDirectory = Split-Path -Parent (Get-Command ffmpeg.exe -ErrorAction Stop).Source
}
if (-not $DenoPath) { $DenoPath = (Get-Command deno.exe -ErrorAction Stop).Source }
$FFmpegPath = Join-Path $FFmpegDirectory "ffmpeg.exe"
$FFprobePath = Join-Path $FFmpegDirectory "ffprobe.exe"
foreach ($Binary in @($FFmpegPath, $FFprobePath, $DenoPath)) {
    if (-not (Test-Path $Binary -PathType Leaf)) { throw "Executavel nao encontrado: $Binary" }
}
& $Python -m pip install ".[build]"
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar as dependencias de build." }
& $Python -m PyInstaller --noconfirm --clean --windowed --onedir `
    --name CarriolaDownloaderDev `
    --collect-all customtkinter --collect-all yt_dlp --collect-all yt_dlp_ejs `
    --collect-all plyer `
    --add-binary "$FFmpegPath;." --add-binary "$FFprobePath;." --add-binary "$DenoPath;." `
    carriola_v6.2.py
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar o aplicativo." }
Write-Host "Build criado em dist\CarriolaDownloaderDev. Distribua a pasta inteira."
Write-Host "Inclua as licencas das dependencias e do build de FFmpeg utilizado antes de distribuir."
