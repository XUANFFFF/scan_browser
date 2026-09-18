# 冒烟测试：启动打包好的 EXE（browser 模式），探 localhost API。
#
# 刻意只请求 GET / 与 GET /api/config —— 这两个只读内存配置，
# 不碰 SMB。/api/health、/api/files 会真的去连公司内网，
# CI 里一律不调（见 verify_macos_bundle.py 同样的约定）。
#
# 用法：在仓库根目录执行  bash .github/scripts/smoke_windows.sh
# 前置：dist/ 里已有两个 EXE；公开版需要 dist/config.json（脚本会从
#       config.example.json 生成，示例配置里的内网地址不可达没关系，
#       反正探针不触发 SMB 连接）。
#
# 注意：Git Bash 会对以 / 开头的参数做路径转换（/F → F:\ 之类）。
# 传统写法是双斜杠 //F，但那依赖「转换恰好开启」；这里按调用环境
# 显式关掉转换、用单斜杠，两种环境下行为一致。

set -euo pipefail

cd "$(dirname "$0")/../.."

# 进程工具：Windows 下用 taskkill/tasklist；参数统一单斜杠 +
# 关闭 MSYS 路径转换，避免 //F 在某些环境下变成非法参数。
kill_exe() {
    MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*" \
        taskkill /F /T /IM "$1.exe" >/dev/null 2>&1 || true
}

alive_exe() {
    MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*" \
        tasklist /FI "IMAGENAME eq $1.exe" 2>/dev/null | grep -q "$1.exe"
}

probe_one() {
    local NAME="$1" PORT="$2"
    local BASE="http://127.0.0.1:$PORT"
    echo "--- 冒烟: $NAME (端口 $PORT) ---"

    kill_exe "$NAME"

    ./"dist/$NAME.exe" --browser --port "$PORT" &
    local launcher_pid=$!

    # 轮询 /api/config，最多 25 秒（onefile 自解压 + 启动需要几秒）
    local ok=""
    for _ in $(seq 1 50); do
        if curl -sf "$BASE/api/config" >/dev/null 2>&1; then ok=1; break; fi
        sleep 0.5
    done
    if [ -z "$ok" ]; then
        echo "[错误] $NAME 未在 25s 内响应 $BASE"
        echo "--- 日志（若有）---"
        cat "dist/$NAME.log" 2>/dev/null || true
        kill_exe "$NAME"
        exit 1
    fi

    # 页面能渲染（模板真打进了 onefile）
    local page
    page=$(curl -sf "$BASE/")
    echo "$page" | grep -q "<title>扫描文件浏览器</title>"
    echo "$page" | grep -q 'id="viewer"'
    echo "  GET /            200 + 页面标记 ✅"

    # 模式回报正确
    local cfg
    cfg=$(curl -sf "$BASE/api/config")
    echo "$cfg" | grep -q '"mode": *"browser"'
    echo "  GET /api/config  $cfg"

    # 收尾：onefile 是父子双进程，/T 连进程树一起杀
    kill_exe "$NAME"
    sleep 1
    if alive_exe "$NAME"; then
        echo "[错误] $NAME 进程未被清理干净"
        exit 1
    fi
    echo "  进程清理干净 ✅"
}

# 公开版没有配置文件起不来，从示例复制一份（探针不触发 SMB，地址无关紧要）
if [ ! -f dist/config.json ]; then
    cp config.example.json dist/config.json
fi

probe_one "扫描文件浏览器" 5097
probe_one "扫描文件浏览器-MCF" 5098

echo ""
echo "=== 冒烟全部通过 ✅ ==="
