# 📦 macOS 版扫描文件浏览器 — 内部版打包包

> 把这个文件夹发给用 Mac 的同事，里面是一个**完整的 AI 代理提示词**，
> 让同事直接丢给 AI agent（如 WorkBuddy）就能自动完成打包。
>
> **此包为内部版，IP 已硬编码，零配置，双击即用。**
> 打包后是一个**独立桌面窗口**（pywebview + 系统 WKWebView），不依赖浏览器。

---

## 文件夹内容

| 文件 | 用途 |
|---|---|
| `app_internal.py` | 内部版入口（只负责指定用哪套配置） |
| `launcher.py` | 启动编排：日志 / 崩溃兜底 / 参数 / 模式分派（IP 硬编码在这里） |
| `webapp.py` | Flask 应用工厂（所有 HTTP 路由） |
| `smb_client.py` | SMB 访问层（连接 / 列举 / 读取 / 健康检查） |
| `desktop.py` | pywebview 桌面壳（开窗口 / 关窗口 / 收尾） |
| `templates/index.html` | 前端页面 |
| `icon.icns` | 应用图标（已由源图生成，spec 会引用） |
| `scan-browser-mac.spec` | PyInstaller 打包配置文件 |
| `requirements.txt` | Python 依赖清单 |
| `启动.command` | macOS 双击启动脚本（备选，.app 打不开时用） |
| `BUILD_MAC.md` | 人工打包说明（备选阅读） |
| `PROMPT_FOR_AGENT.md` | ← 给 AI agent 的 prompt，下方可直接复制 |

---

## 👇 以下是给 AI agent 的 prompt（可直接复制使用）

> 把下面这段内容直接发给你的 AI 助手（如 WorkBuddy），它会自动完成打包。
> 过程中会问你 SMB 服务器 IP。

---

```
# 任务：将扫描文件浏览器打包为 macOS 独立 .app（内部版）

## 项目背景

办公室打印机（富士施乐 Apeos C5571）通过 SMB 协议把扫描文件存到局域网共享。
此工具用 Python 的 `pysmb` 库直连共享，提供一个**独立桌面窗口**浏览和下载扫描文件
（PDF / 图片）。窗口用 `pywebview` 实现，macOS 上走系统自带的 WKWebView，
不需要安装浏览器，也不需要用户手动访问 127.0.0.1。已有一个 Windows 版 .exe，现在需要 macOS 版。

当前目录已包含所有需要的源文件：
- `app_internal.py` — 内部版入口
- `launcher.py` — 启动编排（内部版 SMB 地址硬编码在 INTERNAL_SMB_HOST）
- `webapp.py` — Flask 应用工厂（路由）
- `smb_client.py` — SMB 访问层
- `desktop.py` — pywebview 桌面壳
- `scan-browser-mac.spec` — PyInstaller 打包配置（已固化为内部版）
- `requirements.txt` — Python 依赖（flask / pysmb / pywebview）
- `启动.command` — macOS 双击启动脚本
- `templates/index.html` — 前端页面
- `icon.icns` — 应用图标（spec 已引用，无需改动）

## 打包步骤

### 1️⃣ 确认 IP 配置

先问我：**你们办公室的 SMB 服务器 IP 是多少？**
- 如果 IP 是 `192.168.1.115` → 不用改代码，直接进行下一步
- 如果 IP 不同 → 我告诉你正确 IP，你修改 `launcher.py` 中的 `INTERNAL_SMB_HOST` 常量

### 2️⃣ 安装依赖

**务必用独立虚拟环境**，不要直接 `pip3 install`（新版 macOS 的系统 Python 受保护，
直接安装常报 `externally-managed-environment` 或权限错误，也会污染系统环境）：

```bash
cd <本文件夹路径>
python3 -m venv .buildenv
source .buildenv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt pyinstaller
```

### 3️⃣ 执行打包

```bash
pyinstaller scan-browser-mac.spec
```

### 4️⃣ 验证

```bash
ls -lah dist/扫描文件浏览器.app
# 直接跑一次，确认会弹出独立桌面窗口（不是浏览器）
dist/扫描文件浏览器.app/Contents/MacOS/扫描文件浏览器
```

确认 .app 存在（约 30~60 MB），并且双击/命令行启动后**弹出的是应用自己的窗口**，
窗口标题为「扫描文件浏览器」。

## 交付

- 将 `dist/扫描文件浏览器.app` 和 `启动.command` 放入同一文件夹
- 告知我打包成功、文件大小
- 提醒同事：首次打开 `.app` 需右键 →「打开」绕过 macOS 安全提示
- 打包用的 `.buildenv/` 虚拟环境**不要**放进交付文件夹
```
