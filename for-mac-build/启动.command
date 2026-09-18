#!/bin/bash
# 扫描文件浏览器 - macOS 启动脚本
# 将此文件与「扫描文件浏览器.app」放在同一目录，双击即可运行。
# 若没有 .app，则回退到 Python 源码方式启动（会自动建独立虚拟环境）。

cd "$(dirname "$0")" || exit 1
SCRIPT_DIR="$(pwd)"

APP_NAME="扫描文件浏览器"
APP_PATH="$SCRIPT_DIR/${APP_NAME}.app"

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
# 优先复用已建好的打包虚拟环境，其次用系统 python3
PY_CMD=""
if [ -x "$SCRIPT_DIR/.buildenv/bin/python" ]; then
    PY_CMD="$SCRIPT_DIR/.buildenv/bin/python"
elif command -v python3 > /dev/null 2>&1; then
    PY_CMD="$(command -v python3)"
fi

if [ -n "$PY_CMD" ]; then
    # 依赖不齐时，在独立虚拟环境里安装，避免污染系统 Python
    # （新版 macOS 的系统 Python 受保护，直接 pip3 install 常报权限错误）
    if ! "$PY_CMD" -c "import flask, smb" > /dev/null 2>&1; then
        echo "依赖未就绪，正在创建虚拟环境并安装（仅首次，约需 1 分钟）..."
        if [ ! -x "$SCRIPT_DIR/.buildenv/bin/python" ]; then
            python3 -m venv "$SCRIPT_DIR/.buildenv" || {
                echo "[错误] 创建虚拟环境失败"
                read -p "按回车键退出..."
                exit 1
            }
        fi
        PY_CMD="$SCRIPT_DIR/.buildenv/bin/python"
        "$PY_CMD" -m pip install --upgrade pip
        "$PY_CMD" -m pip install -r "$SCRIPT_DIR/requirements.txt" || {
            echo "[错误] 依赖安装失败，请检查网络"
            read -p "按回车键退出..."
            exit 1
        }
        echo "依赖安装完成"
    fi

    echo "正在启动（Python 源码）..."
    echo "浏览器会自动打开；关闭本窗口即停止服务。"
    echo ""
    "$PY_CMD" "$SCRIPT_DIR/app_internal.py"
    exit 0
fi

# ── 都找不到则报错 ──
echo ""
echo "[错误] 未找到 $APP_NAME.app"
echo "       请确保 $APP_NAME.app 与本脚本在同一目录"
echo ""
echo "       或在 Mac 上安装 Python 3 后重新双击本脚本："
echo "        brew install python3"
echo ""
read -p "按回车键退出..."
exit 1
