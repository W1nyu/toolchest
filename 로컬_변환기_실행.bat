@echo off
cd /d "%~dp0"
python src\converter_gui.py
if errorlevel 1 pause
