# Rebuild SumitSpeak.exe and copy it to every known location on this
# machine, so the portable copy and the installed copy can never
# silently drift apart the way they did on 2026-07-22 (the installed
# copy sat two releases behind before anyone noticed the About tab
# still said "1.1.0").
#
# Run from the project root: .\scripts\rebuild.ps1
# Must run under PowerShell, not Bash/Git Bash -- Bash eats the
# backslash in --icon assets\icon.ico and silently breaks the build.

$ErrorActionPreference = "Stop"

$running = Get-Process SumitSpeak -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "SumitSpeak is currently running (PID $($running.Id -join ', '))."
    Write-Host "Stop it first (this script won't kill it for you), then re-run."
    exit 1
}

& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed `
    --name SumitSpeak --icon assets\icon.ico `
    --collect-all ctranslate2 --collect-all faster_whisper --collect-all av `
    --collect-all tokenizers --collect-all uiautomation `
    --hidden-import win32timezone main.py

$built = Get-Item dist\SumitSpeak.exe
Write-Host "Built dist\SumitSpeak.exe ($($built.LastWriteTime))"

Copy-Item dist\SumitSpeak.exe SumitSpeak.exe -Force
Write-Host "Copied to project root."

$installedDir = "$env:LOCALAPPDATA\Programs\Sumit Speak"
$installedExe = Join-Path $installedDir "SumitSpeak.exe"
if (Test-Path $installedExe) {
    Copy-Item dist\SumitSpeak.exe $installedExe -Force
    Write-Host "Copied to installed location: $installedExe"
} else {
    Write-Host "No installed copy found at $installedDir -- skipped (nothing to keep in sync)."
}

Write-Host "Done. Remember: this only updates the app EXE, not the installer -- rebuild installer\SumitSpeak.iss separately if you're publishing a release."
