@echo off
set "S=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\RepoRadar.bat"
(
echo @echo off
echo call "%~dp0Baslat.bat" --no-open
) > "%S%"
echo Repo Radar artik Windows acilisinda arka planda baslayacak.
echo Kaldirmak icin su dosyayi sil: %S%
pause
