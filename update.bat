@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
py -3 tools\update_from_github.py %*
pause
