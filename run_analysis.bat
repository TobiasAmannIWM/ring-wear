@echo off
chcp 65001 >nul
echo Ring Wear Analysis
echo ==================

set PYTHON=C:\Users\ama\AppData\Local\miniforge3\python.exe
set INDIR=%~dp0data\worn
set NEUDIR=%~dp0data\neu
set OUTDIR=%~dp0ring_wear_out

echo Input:   %INDIR%
echo New-ref: %NEUDIR%
echo Output:  %OUTDIR%
echo.

REM ── Step 1: main analysis (all worn images) ──────────────────────────────
%PYTHON% -m ringwear "%INDIR%" -o "%OUTDIR%" --neu-dir "%NEUDIR%"

if errorlevel 1 (
    echo.
    echo ERROR: Analysis failed.
    pause
    exit /b 1
)

REM ── Step 2: repeatability (runs only when >= 2 repetitions are present) ──
%PYTHON% -m ringwear repeat "%INDIR%" -o "%OUTDIR%" --neu-dir "%NEUDIR%" 2>nul
REM (exit code ignored — repeat is optional; no repetitions = silent skip)

echo.
echo Opening results ...
if exist "%OUTDIR%\results.xlsx"  start "" "%OUTDIR%\results.xlsx"
if exist "%OUTDIR%\results.html"  start "" "%OUTDIR%\results.html"
if exist "%OUTDIR%\repeat_report.csv" (
    echo Repeatability report: %OUTDIR%\repeat_report.csv
)

pause
