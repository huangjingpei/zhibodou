@echo off
rem ============================================================
rem 交付版（release）一键打包：注入生产后端 https://pdk.graddu.com
rem 调试/测试打包请直接运行:  python build_exe.py --windowed
rem ============================================================
chcp 65001 >nul
cd /d %~dp0
set PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe
%PY% build_exe.py --release --windowed %*
echo.
echo [done] 产物在 dist\zhibodou\ ，可用 Fiddler 抓包验证应连 pdk.graddu.com
pause
