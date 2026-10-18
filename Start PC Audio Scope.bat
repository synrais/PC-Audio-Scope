@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (start "" pythonw pc_audio_scope.py) else (start "" pyw pc_audio_scope.py)
