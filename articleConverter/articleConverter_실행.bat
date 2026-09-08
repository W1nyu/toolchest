@echo off
cd /d "%~dp0"
python article_converter_gui.py
if errorlevel 1 pause
