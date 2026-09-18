#!/usr/bin/env bash
# 重新打包两个 Windows EXE，带上应用图标
# 用干净 venv，避免把系统 Python 的大库卷进来
#
# 依赖版本由 constraints-build.txt 约束（与 macOS CI 同一套），
# 保证两边用的都是已验证过的组合。venv 里怎么装：
#   python -m venv <venv>
#   <venv>/python -m pip install -r requirements.txt -c constraints-build.txt
#   <venv>/python -m pip install pyinstaller -c constraints-build.txt
#
# CI 里通过环境变量换 Python：PYBIN=/path/to/venv/Scripts/python.exe bash build_exe.sh
set -e

cd "$(dirname "$0")"
VPY="${PYBIN:-C:/Users/zxf_s/.workbuddy/binaries/python/envs/scanner-build/Scripts/python.exe}"
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
