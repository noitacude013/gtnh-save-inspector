@echo off
rem Console launcher for GTNH Save Inspector GUI.
rem Double-click it or pass GUI arguments, e.g. --browser --no-open.
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" -m gtnh_save_inspector gui %*
if errorlevel 1 pause
