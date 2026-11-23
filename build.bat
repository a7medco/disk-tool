@echo off
REM ==== Build DiskTool.exe (run once on YOUR Windows PC, needs Python + internet) ====
cd /d "%~dp0"
echo [1/3] Installing build tools...
python -m pip install --upgrade pyinstaller pywebview || goto :err
echo [2/3] Building DiskTool.exe ...
python -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin ^
  --name DiskTool --icon DiskTool.ico ^
  --add-data "web;web" --add-data "redist;redist" ^
  app.py || goto :err
echo [3/3] Copying the bin folder next to the exe...
xcopy /e /i /y bin dist\bin >nul
echo.
echo DONE:  dist\DiskTool.exe + dist\bin  (Ventoy + VeraCrypt inside)
echo Give your friends the whole "dist" folder.
pause
exit /b 0
:err
echo.
echo BUILD FAILED - read the red lines above.
pause
exit /b 1
