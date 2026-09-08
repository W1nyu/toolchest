@echo off
cd /d "%~dp0"
python converter_gui.py
if errorlevel 1 pause
