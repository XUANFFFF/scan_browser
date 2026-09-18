#!/bin/bash
# 扫描文件浏览器 - macOS 启动脚本
# 将此文件与 scan_browser.app 放在同一目录，双击即可运行

cd "$(dirname "$0")"

APP_NAME="扫描文件浏览器"
APP_PATH="./${APP_NAME}.app"
SCRIPT_DIR="$(dirname "$0")"

echo "==================================="
echo "   扫描文件浏览器"
echo "==================================="
echo ""

# ── 优先使用 .app ──
if [ -d "$APP_PATH" ]; then
    echo "正在启动 $APP_NAME..."
    open "$APP_PATH"
    exit 0
fi

# ── 其次尝试 Python 源码 ──
if command -v python3 &> /dev/null; then
    echo "正在检查依赖..."
    if [ ! -f ".deps_installed" ]; then
        echo "安装依赖中..."
        pip3 install -r "$SCRIPT_DIR/requirements.txt" -q
        touch "$SCRIPT_DIR/.deps_installed"
        echo "依赖安装完成"
    fi
    echo "正在启动 (Python 源码)..."
    open "http://127.0.0.1:5088"
    python3 "$SCRIPT_DIR/app.py"
    exit 0
fi

# ── 都找不到则报错 ──
echo ""
echo "[错误] 未找到 $APP_NAME.app"
echo "       请确保 $APP_NAME.app 与此脚本在同一目录"
echo ""
echo "       或在 Mac 上安装 Python 3 后双击本脚本"
echo "       brew install python3"
echo ""
read -p "按回车键退出..."
exit 1
