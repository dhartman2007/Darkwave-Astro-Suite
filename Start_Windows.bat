@echo off
cd /d "%~dp0"
if exist .venv\Scripts\python.exe goto install
set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%PYTHON_EXE%" goto create
set "PYTHON_EXE=python"
:create
"%PYTHON_EXE%" -m venv .venv
if errorlevel 1 (
  echo Failed to create the Python virtual environment.
  pause
  exit /b 1
)
:install
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
pause
