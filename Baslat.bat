@echo off
setlocal
cd /d "%~dp0"
set "PY="
for %%P in (pythonw.exe) do set "PY=%%~$PATH:P"
if defined PY echo %PY% | find /i "WindowsApps" >nul && set "PY="
if not defined PY for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do if exist "%%D\pythonw.exe" set "PY=%%D\pythonw.exe"
if not defined PY for /d %%D in ("%ProgramFiles%\Python3*") do if exist "%%D\pythonw.exe" set "PY=%%D\pythonw.exe"
if not defined PY (
  echo Python bulunamadi.
  echo Terminalde su komutu calistir, bitince bu dosyayi tekrar ac:
  echo   winget install -e --id Python.Python.3.12 --scope user
  pause
  exit /b 1
)
set "PYC=%PY:pythonw.exe=python.exe%"
"%PYC%" -c "import pystray, PIL" >nul 2>nul || (
  echo Ilk calistirma: bildirim alani simgesi icin pystray ve pillow kuruluyor...
  "%PYC%" -m pip install --user --quiet pystray pillow
)
start "" "%PY%" "%~dp0radar.py" %*
