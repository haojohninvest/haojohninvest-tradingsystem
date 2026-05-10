@echo off
REM 豪強資本交易系統 - 自動排程服務啟動器
REM 此腳本會在背景啟動排程服務

echo ========================================
echo 豪強資本交易系統 - 自動排程服務
echo ========================================
echo.
echo 啟動時間：%date% %time%
echo.
echo 正在啟動排程服務...
echo 按 Ctrl+C 可停止服務
echo.

REM 切換到專案目錄
cd /d "%~dp0"

REM 啟動排程服務
python manage.py start_scheduler

pause
