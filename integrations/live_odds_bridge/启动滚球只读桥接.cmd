@echo off
chcp 65001 >nul
cd /d "%~dp0\..\.."
python scripts\live_odds_bridge.py
echo.
echo 桥接服务已停止。按任意键关闭窗口。
pause >nul
