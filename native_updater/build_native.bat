@echo on
call "C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\Tools\VsDevCmd.bat" -arch=amd64 -no_logo > E:\zhibodou\native_updater\build_log.txt 2>&1
set "PATH=C:\Program Files\CMake\bin;%PATH%"
cd /d E:\zhibodou\native_updater
cmake -S . -B build2 -G "Visual Studio 17 2022" -A x64 >> E:\zhibodou\native_updater\build_log.txt 2>&1
if errorlevel 1 goto :fail
cmake --build build2 --config Release >> E:\zhibodou\native_updater\build_log.txt 2>&1
if errorlevel 1 goto :fail
echo BUILD_OK >> E:\zhibodou\native_updater\build_log.txt
exit /b 0
:fail
echo BUILD_FAILED >> E:\zhibodou\native_updater\build_log.txt
exit /b 1
