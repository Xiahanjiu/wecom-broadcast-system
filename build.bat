@echo off
chcp 65001 >nul
echo ============================================
echo   企业微信群发系统 - 一键构建脚本
echo ============================================
echo.

cd /d "%~dp0"

echo [1/2] 构建主控端...
python -m PyInstaller build_master.spec --noconfirm
if %errorlevel% neq 0 (
    echo 主控端构建失败!
    pause
    exit /b 1
)
echo   主控端构建完成: dist\wecom-broadcast-master\

echo.
echo [2/2] 构建执行端...
python -m PyInstaller build_worker.spec --noconfirm
if %errorlevel% neq 0 (
    echo 执行端构建失败!
    pause
    exit /b 1
)
echo   执行端构建完成: dist\wecom-broadcast-worker\

echo.
echo ============================================
echo   构建完成!
echo   主控端: dist\wecom-broadcast-master\wecom-broadcast-master.exe
echo   执行端: dist\wecom-broadcast-worker\wecom-broadcast-worker.exe
echo ============================================
pause
