@echo off
rem Build RAS.exe with PyInstaller (run from the repository root)
cd /d "%~dp0src"
python -m PyInstaller --onefile --windowed --name RAS --icon "..\assets\icon.ico" --distpath "..\dist\RAS" --workpath "..\build" --specpath "..\build" ras.py
copy /Y "..\monitor_config.json" "..\dist\RAS\monitor_config.json" >nul
echo Done: dist\RAS\RAS.exe
