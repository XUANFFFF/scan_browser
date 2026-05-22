# 扫描文件浏览器

绕过 Windows SMB 兼容性问题，通过浏览器直接浏览和下载打印机扫描文件。

## 背景

富士施乐 Apeos C5571 打印机将扫描文件保存到局域网 SMB 共享 `\\server\扫描共享文件`。该共享使用 SMBv1 协议，Windows 10/11 默认禁用，即使手动开启后资源管理器也经常无法正常访问。

本工具使用 Python SMBv1 客户端直连共享，提供 Web 界面，彻底绕过 Windows 的兼容性问题。

## 功能

- **文件列表**：展示扫描 PDF，自动解析文件名中的时间戳显示扫描时间
- **今日优先**：今日扫描文件置顶显示，历史文件按日期分组
- **在线预览**：点击预览在新标签页打开 PDF
- **一键下载**：点击下载保存到本地
- **手动刷新**：实时获取最新扫描文件

## 使用方法

### 方式一：EXE（推荐，无需安装 Python）

1. 下载 Releases 中的 `扫描文件浏览器.exe`
2. **重要**：将 `config.example.json` 复制为 `config.json`，修改 `smb_host` 为你的 SMB 服务器 IP
3. 将 exe 和 config.json 放在同一目录
4. 双击运行，浏览器自动打开

### 方式二：Python 源码

```bash
# 配置
cp config.example.json config.json
# 编辑 config.json，修改 smb_host 为实际 IP

# 安装依赖
pip install -r requirements.txt

# 启动
python app.py
```

或双击 `启动.bat`（会自动安装依赖并启动）。

## 配置指南

编辑 `config.json`：

```json
{
    "smb_host": "192.168.1.115",   // SMB 服务器 IP 地址
    "smb_port": 445,                // SMB 端口（通常无需修改）
    "smb_share": "扫描共享文件",      // 共享文件夹名称
    "server_port": 5088             // 本地 Web 服务端口（通常无需修改）
}
```

| 字段 | 说明 | 如何获取 |
|------|------|----------|
| `smb_host` | SMB 服务器 IP | 在服务器上运行 `ipconfig` 或找 IT 查询 |
| `smb_share` | 共享名 | 在服务器上运行 `net share` 查看共享列表 |
| `server_port` | 本地端口 | 如端口冲突改为其他值（如 5090） |

> **提示**：如果不知道共享名，运行程序后在浏览器打开 `http://127.0.0.1:5088/api/files`，错误信息中会显示可用的共享路径。

## 分享给同事

### EXE 方式（最简单）

发送两个文件：
1. `扫描文件浏览器.exe`
2. `config.json`（已填好 IP）

对方放在同一目录，双击 exe 即可。

### 源码方式

将整个项目文件夹打包发送（不含 `dist/`）。对方需要安装 Python 3，然后双击 `启动.bat`。

**前置条件**：需在公司内网，能 ping 通 `config.json` 中配置的 `smb_host`。

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python + Flask |
| SMB 访问 | pysmb（SMBv1 协议） |
| 前端 | 原生 HTML/CSS/JS |
| 打包 | PyInstaller（单文件 EXE） |

## 项目结构

```
scan_browser/
├── app.py                  # Flask 后端
├── templates/
│   └── index.html          # 前端界面
├── config.json             # 本地配置（不提交 Git）
├── config.example.json     # 配置模板
├── requirements.txt        # Python 依赖
├── 启动.bat                # 一键启动脚本
└── .gitignore
```

## 构建 EXE

```bash
python -m venv _build_env
_build_env\Scripts\pip install flask pysmb pyinstaller
_build_env\Scripts\pyinstaller --onefile --add-data "templates;templates" --name "扫描文件浏览器" --distpath ./dist app.py
```

生成 `dist\扫描文件浏览器.exe`，配合 `config.json` 分发给同事。

## 许可

MIT
