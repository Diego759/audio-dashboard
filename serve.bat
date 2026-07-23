@echo off
REM Windows: double-click to serve the dashboard locally and open it.
cd /d "%~dp0"
start "" "http://localhost:8768/index.html"
python -m http.server 8768
