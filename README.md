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

- **文件列表**：展示扫描文件（PDF 与图片 JPG/JPEG/PNG，带类型徽标），自动解析文件名中的时间戳显示扫描时间
- **今日优先**：今日扫描文件置顶显示，历史文件按日期分组
- **真实连接状态**：顶部状态灯由 `/api/health` 实际探测 SMB 得出，不是装饰；连不上时给出错误原因和「重新连接」入口
- **在线预览**：PDF 与图片在窗口内直接查看，不弹新窗口
- **一键下载**：走系统「另存为」对话框
- **手动刷新**：实时获取最新扫描文件
- **完全离线**：不依赖任何公网资源（字体、CDN 全部去掉）

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
├── config.json             # 本地配置（不提交 Git）
├── config.example.json     # 配置模板
├── requirements.txt        # Python 依赖
├── 启动.bat / 启动.command   # 一键启动脚本
└── 扫描文件浏览器.log        # 运行日志（排障用，运行后生成）
```

## API

| 路径 | 说明 |
|---|---|
| `GET /` | 界面 |
| `GET /api/config` | SMB 地址、共享名、当前模式（`browser` / `desktop`） |
| `GET /api/health` | 真实 SMB 连通状态：`{ok, smb_host, share, latency_ms, file_count?, error?}` |
| `GET /api/files` | 文件列表 |
| `GET /api/preview/<文件名>` | 预览（inline） |
| `GET /api/download/<文件名>` | 下载（attachment） |

服务始终只监听 `127.0.0.1`，不暴露到局域网。

## 构建 EXE

```bash
python -m venv _build_env
_build_env\Scripts\pip install flask pysmb pywebview pyinstaller

_build_env\Scripts\pyinstaller --onefile --windowed ^
  --add-data "templates;templates" ^
  --hidden-import webview.platforms.winforms ^
  --hidden-import webview.platforms.edgechromium ^
  --name "扫描文件浏览器" --distpath ./dist app.py
```

> ⚠️ 一定要用**干净的虚拟环境**打包。系统 Python 里若装了 torch / matplotlib 等大库，
> PyInstaller 会把它们一起卷进去，产物体积暴涨且打包极慢。
>
> macOS 版打包见 `for-mac-build/`。

## 排障

程序日志写在 EXE 同目录的 `扫描文件浏览器.log`（写不进去时落到 `%LOCALAPPDATA%\ScanBrowser\`）。
窗口无控制台输出，出问题先看这个日志。

## 许可

MIT
