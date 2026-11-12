# Build dist\Talkative.exe. The one place the PyInstaller command lives:
# scripts\rebuild.ps1 (this machine) and .github\workflows\build.yml
# (GitHub Actions) both call this, so a local build and a CI build can't
# drift apart. The --collect-all flags are load-bearing -- see CLAUDE.md's
# "Packaging notes".
#
# Usage (from the project root): .\scripts\build_exe.ps1 [-Python <path>] [-OneDir]
#
# -OneDir: the Microsoft Store build (scripts\build_msix.ps1) -- a folder,
# dist\store\Talkative\, instead of the single EXE. Inside a package the
# single EXE would unpack ~250 MB to %TEMP% at every start for nothing.
# Must run under PowerShell, not Bash -- Bash eats the backslash in
# assets\icon.ico.

param([string]$Python = ".\.venv\Scripts\python.exe", [switch]$OneDir)

$ErrorActionPreference = "Stop"

& $Python scripts\version_info.py
if ($LASTEXITCODE -ne 0) { throw "version_info.py failed" }

# The Store build keeps its .spec under build\store so it never overwrites
# the tracked Talkative.spec; PyInstaller then reads relative paths from
# the spec's folder, hence absolute paths -- for that build only: in the
# normal build they'd land in the tracked Talkative.spec.
$root = if ($OneDir) { (Resolve-Path .).Path + "\" } else { "" }
# @(...) around the whole if: a one-item result would otherwise come out as
# a plain string, and splatting a string hands PyInstaller garbage (CI run
# 43273861816, 2026-11-12).
$layout = @(if ($OneDir) {
    "--onedir", "--distpath", "${root}dist\store", "--workpath", "${root}build\store", "--specpath", "${root}build\store"
} else { "--onefile" })

& $Python -m PyInstaller --noconfirm @layout --windowed `
    --name Talkative --icon "${root}assets\icon.ico" `
    --version-file "${root}build\version_info.txt" `
    --collect-all ctranslate2 --collect-all faster_whisper --collect-all av `
    --collect-all tokenizers --collect-all uiautomation `
    --hidden-import win32timezone main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
