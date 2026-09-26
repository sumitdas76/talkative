# Build dist\Talkative.exe. The one place the PyInstaller command lives:
# scripts\rebuild.ps1 (this machine) and .github\workflows\build.yml
# (GitHub Actions) both call this, so a local build and a CI build can't
# drift apart. The --collect-all flags are load-bearing -- see CLAUDE.md's
# "Packaging notes".
#
# Usage (from the project root): .\scripts\build_exe.ps1 [-Python <path>]
# Must run under PowerShell, not Bash -- Bash eats the backslash in
# assets\icon.ico.

param([string]$Python = ".\.venv\Scripts\python.exe")

$ErrorActionPreference = "Stop"

& $Python scripts\version_info.py
if ($LASTEXITCODE -ne 0) { throw "version_info.py failed" }

& $Python -m PyInstaller --noconfirm --onefile --windowed `
    --name Talkative --icon assets\icon.ico `
    --version-file build\version_info.txt `
    --collect-all ctranslate2 --collect-all faster_whisper --collect-all av `
    --collect-all tokenizers --collect-all uiautomation `
    --hidden-import win32timezone main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
