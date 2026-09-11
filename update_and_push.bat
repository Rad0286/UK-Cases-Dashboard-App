@echo off
title GCS Data Updater
echo ============================================================
echo   GCS Data Updater
echo   Pulls new files from FileBrowser, updates data.json,
echo   and pushes to GitHub so Streamlit Cloud stays current.
echo ============================================================
echo.
echo   Make sure ZScaler is connected before running.
echo.

"C:\Users\0119944\.lou\python\venv\Scripts\python.exe" "%~dp0update_data.py"

echo.
pause
