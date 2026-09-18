# 扫描文件浏览器

绕过 Windows SMB 兼容性问题，用独立桌面窗口浏览和下载打印机扫描文件。

## 背景

富士施乐 Apeos C5571 打印机将扫描文件保存到局域网 SMB 共享 `\\server\扫描共享文件`。该共享使用 SMBv1 协议，Windows 10/11 默认禁用，即使手动开启后资源管理器也经常无法正常访问。

本工具使用 Python SMBv1 客户端直连共享，自己渲染界面，彻底绕过 Windows 的兼容性问题。

## 两种运行模式

| | 桌面模式（默认） | 浏览器模式 |
|---|---|---|
| 启动方式 | 双击 EXE | `python app.py --browser` |
| 界面 | 独立窗口，无地址栏/标签页 | 系统默认浏览器 |
| 预览 | 窗口内嵌显示（iframe / img） | 打开新标签页 |
| 下载 | 系统「另存为」对话框 | 浏览器下载 |
| 用途 | 发给同事日常使用 | 开发调试、出问题时的回退入口 |

模式规则：不带参数时，**打包后的 EXE 走桌面窗口，源码运行走浏览器**；也可以用 `--desktop` / `--browser` 强制指定。

## 功能

- **文件列表**：展示 PDF、图片（JPG/JPEG/PNG）与 TIFF，带类型徽标；自动解析文件名中的时间戳显示扫描时间
- **自动下钻子目录**：扫描仪有时会把成品放进 `YYYYMMDDHHMMSS/` 子文件夹，程序会递归列出（最多 3 层），并在行内标出来自哪个文件夹 —— 不会像只看根目录那样整批漏掉
- **今日优先**：今日扫描文件置顶显示，历史文件按日期分组
- **真实连接状态**：顶部状态灯由 `/api/health` 实际探测 SMB 得出，不是装饰；连不上时给出错误原因和「重新连接」入口
- **在线预览**：PDF 与 JPG/PNG 在窗口内直接查看，不弹新窗口；TIFF 浏览器内核无法内联渲染，只提供下载
- **一键下载**：走系统「另存为」对话框
- **手动刷新**：实时获取最新扫描文件
- **可开多个窗口**：重复双击会各自使用不同端口，互不影响，关掉其中一个不会影响其它
- **浅色标题栏**：桌面窗口保留系统原生边框与按钮，但把默认那条深色标题栏换成与应用一致的浅色
- **完全离线**：不依赖任何公网资源（字体、CDN 全部去掉）

## 扫描文件是怎么存的

同一台打印机存在两种落盘方式，程序两种都认：

| 方式 | 位置 | 命名 | 例 |
|---|---|---|---|
| 直落根目录 | 共享根 | `YYYYMMDDHHMMSS.扩展名` | `20260917154658.pdf` |
| 落子目录 | `YYYYMMDDHHMMSS/` | `YYYYMMDDHHMMSS-000N.扩展名` | `20260918094501/20260918094501-0001.jpg` |

图片类扫描常走第二种（一次扫描的多页放进同一个以开始时间命名的子目录），所以**只读根目录会整批看不到**；本程序会递归下钻。


## 使用方法

### 方式一：EXE（推荐，无需安装 Python）

**内部版** `扫描文件浏览器-MCF.exe` —— SMB 地址已写死，拿到就能用：

1. 双击运行
2. 直接看到「扫描文件」窗口

**公开版** `扫描文件浏览器.exe` —— 需要自己配地址：

1. 把 `config.example.json` 复制为 `config.json`，改好 `smb_host`
2. exe 与 config.json 放在同一目录
3. 双击运行

### 方式二：Python 源码

```bash
pip install -r requirements.txt
python app.py                 # 浏览器模式（开发调试）
python app.py --desktop       # 桌面窗口
```

或双击 `启动.bat`（会自动安装依赖并启动）。

### 打包 / 升级依赖须知

`requirements.txt` 面向开发（宽泛范围）；**打包**必须叠加 `constraints-build.txt`
（钉住已验证的版本组合，Windows 与 macOS 共用一套）：

```bash
pip install -r requirements.txt -c constraints-build.txt
pip install pyinstaller -c constraints-build.txt
```

要升级依赖：改 `constraints-build.txt`（根目录与 `for-mac-build/` 两处同步），
Windows 重新打包并冒烟（列表/预览/子目录另存为/关窗），macOS 跑一次 Actions
构建确认闭环验证（含 codesign）全绿，两边都过再提交。流程细节见
`constraints-build.txt` 文件头注释。

## 配置指南

编辑 `config.json`：

```json
{
    "smb_host": "192.168.1.115",
    "smb_port": 445,
    "smb_share": "扫描共享文件",
    "server_port": 5088
}
```

| 字段 | 说明 | 如何获取 |
|------|------|----------|
| `smb_host` | SMB 服务器 IP | 在服务器上运行 `ipconfig` 或找 IT 查询 |
| `smb_share` | 共享名 | 在服务器上运行 `net share` 查看共享列表 |
| `server_port` | 本地端口 | 端口冲突时程序会自动改用空闲端口，一般不用管 |

> **提示**：连不上时，窗口顶部的状态灯会变红并显示具体错误。

## 分享给同事

| 场景 | 发什么 |
|---|---|
| 同一台 SMB 服务器 | 只发 `扫描文件浏览器-MCF.exe`，一个文件双击即用 |
| SMB 地址不同 | 发 `扫描文件浏览器.exe` + 已填好 IP 的 `config.json` |

**前置条件**：连的是公司内网，能通到 `smb_host`。

**需要对方机器有 Microsoft Edge WebView2 运行时**（Win10/11 基本都自带，随 Edge 一起更新）。
万一没有，程序会自动改用浏览器模式打开，不会白屏卡住。

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python + Flask |
| SMB 访问 | pysmb（用户态 SMBv1 实现） |
| 桌面壳 | pywebview（Windows 走 WebView2，macOS 走 WKWebView） |
| 前端 | 原生 HTML/CSS/JS，系统字体，零外部依赖 |
| 打包 | PyInstaller（单文件 EXE，windowed 无控制台） |

## 项目结构

```
scan_browser/
├── app.py                  # 公开版入口（读 config.json）
├── app_internal.py         # 内部版入口（配置写死）
├── launcher.py             # 启动编排：日志/崩溃兜底/参数/模式分派
├── webapp.py               # Flask 应用工厂（所有路由）
├── smb_client.py           # SMB 访问层：连接/列举/读取/健康检查
├── desktop.py              # pywebview 桌面壳
├── templates/
│   └── index.html          # 前端界面
├── 图标.png                 # 图标源图
├── icon.ico                # Windows 图标（打包用）
├── make_icons.py           # 由源图生成 icon.ico / icon.icns
├── config.json             # 本地配置（不提交 Git）
├── config.example.json     # 配置模板
├── requirements.txt        # Python 依赖（开发用，宽泛范围）
├── constraints-build.txt   # 打包版本约束（钉住已验证组合，构建必用）
├── tests/
│   └── test_core.py        # 业务单元测试（不依赖真实共享）
├── 启动.bat / 启动.command   # 一键启动脚本
├── build_exe.sh            # Windows EXE 打包脚本
├── for-mac-build/          # macOS 打包分发包（spec + icon.icns + 文档）
├── .github/
│   ├── workflows/
│   │   ├── build-macos.yml           # 云端构建 macOS 版
│   │   └── build-windows.yml         # 云端构建 Windows 版
│   └── scripts/
│       ├── make_macos_zip.py         # 打分发 ZIP（云端/本地共用）
│       ├── verify_macos_bundle.py    # 校验 PyInstaller 产物（.app）
│       ├── verify_macos_zip.py       # 闭环校验：解开分发 ZIP 再验一遍
│       └── smoke_windows.sh          # Windows EXE 冒烟（localhost 探针）
└── 扫描文件浏览器.log        # 运行日志（排障用，运行后生成）
```

## API

| 路径 | 说明 |
|---|---|
| `GET /` | 界面 |
| `GET /api/config` | SMB 地址、共享名、当前模式（`browser` / `desktop`） |
| `GET /api/health` | 真实 SMB 连通状态：`{ok, smb_host, share, latency_ms, file_count?, error?}` |
| `GET /api/files` | 文件列表（递归含子目录，每条带 `path` / `dir` 字段） |
| `GET /api/preview/<路径>` | 预览（inline），路径可含子目录 |
| `GET /api/download/<路径>` | 下载（attachment），路径可含子目录 |

服务始终只监听 `127.0.0.1`，不暴露到局域网。预览/下载路径会做显式安全校验
（穿越、绝对路径、反斜杠、空段等一律 `400`），不依赖 SMB 服务端拒绝。

## 构建 EXE

推荐直接用仓库里的脚本（依赖版本由 `constraints-build.txt` 钉住）：

```bash
# CI 里也是这么跑的（见 .github/workflows/build-windows.yml）
python -m venv _build_env
_build_env\Scripts\pip install -r requirements.txt -c constraints-build.txt
_build_env\Scripts\pip install pyinstaller -c constraints-build.txt
PYBIN="$(pwd)/_build_env/Scripts/python.exe" bash build_exe.sh   # Git Bash / CI
```

Windows 包也可以云端构建：仓库 → **Actions** → **Build Windows** → **Run workflow**，
产物 Artifact「扫描文件浏览器-Windows-x64」含两个 EXE + `SHA256SUMS.txt`，
构建时会先跑单元测试再做 localhost 冒烟探针。

手打单条命令（等价于 `build_exe.sh` 的公开版）：

```bash
python -m venv _build_env
_build_env\Scripts\pip install -r requirements.txt -c constraints-build.txt
_build_env\Scripts\pip install pyinstaller -c constraints-build.txt

_build_env\Scripts\pyinstaller --onefile --windowed ^
  --add-data "templates;templates" ^
  --hidden-import webview.platforms.winforms ^
  --hidden-import webview.platforms.edgechromium ^
  --icon icon.ico ^
  --name "扫描文件浏览器" --distpath ./dist app.py
```

> ⚠️ 一定要用**干净的虚拟环境**打包。系统 Python 里若装了 torch / matplotlib 等大库，
> PyInstaller 会把它们一起卷进去，产物体积暴涨且打包极慢。

## 构建 macOS 版（无需 Mac）

macOS 包只能在 macOS 上打，但**不用为此专门养一台 Mac** —— 交给 GitHub Actions：

1. 仓库 → **Actions** → **Build macOS** → **Run workflow**
2. 选架构（`arm64` 默认 / `x64` / `both`），点 **Run workflow**
3. 等 5～10 分钟后，在该次 run 页面底部 **Artifacts** 下载
   `扫描文件浏览器-macOS-arm64`
4. **下载到的是外层 ZIP**（Actions 自己打的）；解开后里面的
   `扫描文件浏览器-macOS-arm64.zip` 才是真正要发给同事的分发包

产物是**内部测试版**：程序带构建时生成的 ad-hoc 签名（完整性自校验，CI 已验证），
但未使用 Apple Developer ID 签名、未经 Apple notarization（公证）。同事首次打开
需按新版 macOS 流程放行：先双击打开一次 → 系统设置 → 隐私与安全性 →
「仍要打开」→ 再确认（右键打开已不被支持；若提示「已损坏」，用
`xattr -dr com.apple.quarantine 扫描文件浏览器.app` 去掉隔离标记）。
CI 做两轮校验 —— 先验 PyInstaller 生成的 `.app`，再**把分发 ZIP 解开重验一遍**
（含中文路径与权限位、`codesign --verify --deep --strict` 签名、启动探针），
两轮都通过才允许上传 Artifact；全程**不会去连公司内网 SMB**。

细节、架构选择与排障见 `for-mac-build/BUILD_MAC.md`；需要在 Mac 上本地打包的
备用流程也在同一份文档里。

## 应用图标

- `图标.png` —— 图标源图（1145×1151，带透明圆角）
- `icon.ico` —— Windows 用，多尺寸（16/24/32/48/64/128/256），打包时用 `--icon icon.ico` 嵌入
- `for-mac-build/icon.icns` —— macOS 用，由 `scan-browser-mac.spec` 的 `icon=` 引用

换图标时把新的 `图标.png` 换成正方形（1024×1024 以上），再用 Pillow 重新生成即可：

```bash
pip install pillow
python -c "from PIL import Image; im=Image.open('图标.png').convert('RGBA'); \
im.save('icon.ico', format='ICO', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]); \
im.save('for-mac-build/icon.icns', format='ICNS')"
```

## 界面外观

桌面窗口保留系统**原生**标题栏与按钮（最小化 / 最大化 / 关闭、拖拽、边缘缩放全部照旧），
只是把颜色改成与应用一致的浅色纸张风格。做法是用 DWM 设置三个颜色属性，不动任何窗口样式位：

| 属性 | 值 | 对应 CSS 变量 |
|---|---|---|
| 标题栏底色 | `#fbfbfa` | `--surface-0` |
| 标题文字 | `#22222a` | `--text-primary` |
| 窗口描边 | `#e3e3e0` | `--border` |

同时关闭「沉浸式深色标题栏」，避免系统深色主题把标题栏又拉回黑色。

> 颜色属性需要 **Windows 11（build 22000+）**；旧系统上调用会失败并被静默忽略，
> 标题栏保持系统默认外观，不影响使用。非 Windows（macOS）自动跳过。

页面顶部 header 在内边距上做了区分：桌面模式因为窗口自带一条标题栏，顶部留白压缩到
24px（浏览器模式保持 56px），让首屏内容更靠上。

## 排障

程序日志写在 EXE 同目录的 `扫描文件浏览器.log`（写不进去时落到 `%LOCALAPPDATA%\ScanBrowser\`）。
窗口无控制台输出，出问题先看这个日志。

**缓存目录**：桌面模式每次运行会在系统临时目录建一个 WebView2 缓存目录
（`%TEMP%\ScanBrowser-<PID>-xxxx`），关窗后自动删除；若是被任务管理器强杀等异常退出，
残留目录会在下次启动时按 PID 回收。**不要**给它设成固定复用目录 —— 实测复用会让
WebView2 缓存越堆越大，关窗耗时从 1 秒恶化到 20~60 秒，且两个窗口共用同一目录会白屏。

**开多个窗口**：重复双击会各用各的端口和缓存，互不影响。

## 许可

MIT
