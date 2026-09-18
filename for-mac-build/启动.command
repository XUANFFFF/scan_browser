#!/bin/bash
# 扫描文件浏览器（macOS 分发包）—— 诊断入口
#
# 双击运行：打印环境信息、检查 .app 的签名与 Gatekeeper 状态，
# 尝试启动，失败时给出准确的处理步骤。
#
# 注意：这不是「备用启动方式」。分发包里程序本体只有 .app 一份，
# 本脚本不带源码、也不带 Python 环境，它的价值在于把失败原因说清楚，
# 而不是重复一个注定失败的启动。

cd "$(dirname "$0")" || exit 1
SCRIPT_DIR="$(pwd)"

APP_NAME="扫描文件浏览器"
APP_PATH="$SCRIPT_DIR/${APP_NAME}.app"

hr() { echo "------------------------------------------------------------"; }

echo "==================================="
echo "   ${APP_NAME} · 启动诊断"
echo "==================================="
echo

# ── 环境信息 ──
OS_VER="$(sw_vers -productVersion 2>/dev/null || echo 未知)"
ARCH="$(uname -m)"
echo "macOS 版本：${OS_VER}"
echo "CPU 架构 ：${ARCH}"
if [ "$ARCH" != "arm64" ]; then
    echo
    echo "⚠️  本机是 ${ARCH} 架构，而本包是 arm64（Apple Silicon）版。"
    echo "    Intel Mac 无法直接运行本包，请向维护者要 x64 包。"
fi
echo

# ── 应用存在性 ──
if [ ! -d "$APP_PATH" ]; then
    hr
    echo "[错误] 未找到 ${APP_NAME}.app"
    echo "       本脚本必须与 .app 在同一目录里。"
    hr
    read -p "按回车键关闭本窗口..." _
    exit 1
fi
echo "找到应用 ：${APP_NAME}.app"

# ── 签名与 Gatekeeper 状态 ──
hr
echo "── 签名状态（ad-hoc，构建时生成）──"
codesign -dv "$APP_PATH" 2>&1 | sed 's/^/    /'
echo
echo "── Gatekeeper 评估 ──"
spctl -a -vv "$APP_PATH" 2>&1 | sed 's/^/    /'
echo
echo "（内部测试版没有 Developer ID 签名、也没有公证，上面显示"
echo "  rejected 属于正常现象，不代表包坏了；「已损坏」才是真出了问题。）"

# ── 尝试启动 ──
hr
echo "正在尝试启动 ${APP_NAME} ..."
# open 在被 Gatekeeper 拦时也可能返回 0（弹窗即成功返回），
# 所以这里的结果仅供参考，判断以弹窗和 Dock 为准。
open "$APP_PATH" 2>&1 | sed 's/^/    /'
echo "启动命令已发出。若 Dock 里没有出现应用，请按下面的步骤处理。"

# ── 失败处理步骤 ──
hr
echo "双击 .app 提示「无法验证开发者」时，按顺序尝试："
echo
echo "① 先直接双击打开一次（哪怕失败也没关系），然后："
echo "      系统设置 → 隐私与安全性 → 在页面底部找到「${APP_NAME}」"
echo "      → 点「仍要打开」→ 在弹窗里再点一次「打开」"
echo
echo "② 若提示「已损坏，无法打开」，是 macOS 给下载文件打了隔离标记，"
echo "   打开「终端」进入本目录后执行："
echo "      xattr -dr com.apple.quarantine \"${APP_NAME}.app\""
echo "   （这不是什么破解操作，只是移除隔离属性，之后就能正常打开。）"
echo
echo "③ 仍打不开的话，把上面「签名状态」「Gatekeeper 评估」两段"
echo "   截图发给维护者。"
hr
read -p "按回车键关闭本窗口..." _
