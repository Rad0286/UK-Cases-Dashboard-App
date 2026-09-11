@echo off
title GCS Streamlit Dashboard
echo ============================================================
echo   GCS PDF vs XML Dashboard  —  Streamlit Edition
echo ============================================================
echo.
echo   Starting...
echo.
echo   YOUR dashboard URL:
echo   http://localhost:8501
echo.
echo   TEAM members on the same network can use:
echo   http://%COMPUTERNAME%:8501
echo.
echo   Press Ctrl+C to stop the dashboard.
echo ============================================================
echo.

"C:\Users\0119944\.lou\python\venv\Scripts\streamlit.exe" run "%~dp0dashboard_streamlit.py" ^
    --server.port 8501 ^
    --server.address 0.0.0.0 ^
    --server.headless true ^
    --browser.gatherUsageStats false

echo.
pause
