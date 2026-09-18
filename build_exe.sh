#!/usr/bin/env bash
# 重新打包两个 Windows EXE，带上应用图标
# 用干净 venv，避免把系统 Python 的大库卷进来
set -e

cd "$(dirname "$0")"
VPY="C:/Users/zxf_s/.workbuddy/binaries/python/envs/scanner-build/Scripts/python.exe"
COMMON=(
  --noconfirm --onefile --windowed
  --add-data "templates;templates"
  --hidden-import webview.platforms.winforms
  --hidden-import webview.platforms.edgechromium
  --icon icon.ico
  --distpath ./dist
)

echo "===== 公开版 ====="
"$VPY" -m PyInstaller "${COMMON[@]}" --name "扫描文件浏览器" app.py

echo "===== 内部版 ====="
"$VPY" -m PyInstaller "${COMMON[@]}" --name "扫描文件浏览器-MCF" app_internal.py

echo "===== 完成 ====="
ls -la dist/*.exe
