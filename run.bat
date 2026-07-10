@echo off
chcp 65001 >nul
title 本地语义搜索 / Local Semantic Search
cd /d "%~dp0"
echo ================================================================
echo   本地语义搜索  .  Local Semantic Search
echo ----------------------------------------------------------------
echo   正在启动，浏览器会自动打开（首次要加载模型，请稍候）。
echo   Starting... the browser opens shortly (first run loads the model).
echo   别关这个窗口 —— 关了就停。Keep this window open; closing it stops the app.
echo ================================================================
echo.
python -m localsearch.app
if errorlevel 1 (
  echo.
  echo 启动失败？先安装依赖 / If it failed to start, install deps first:
  echo     pip install -r requirements.txt
)
echo.
echo 已退出 / Stopped.  按任意键关闭 / Press any key to close.
pause >nul
