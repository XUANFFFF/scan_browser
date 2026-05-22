# 扫描文件浏览器

绕过 Windows SMB 兼容性问题，通过浏览器直接浏览和下载打印机扫描文件。

## 背景

富士施乐 Apeos C5571 打印机将扫描文件保存到局域网 SMB 共享 `\\server\扫描共享文件`。该共享使用 SMBv1 协议，Windows 10/11 默认禁用，即使手动开启后资源管理器也经常无法正常访问。

本工具使用 Python SMBv1 客户端直连共享，提供 Web 界面，彻底绕过 Windows 的兼容性问题。

## 功能

- **文件列表**：展示扫描 PDF，自动解析文件名中的时间戳显示扫描时间
- **今日优先**：今日扫描文件置顶显示（琥珀色高亮），历史文件按日期分组
- **在线预览**：点击预览在新标签页打开 PDF
- **一键下载**：点击下载保存到本地
- **手动刷新**：实时获取最新扫描文件

## 使用方法

### 方式一：EXE（推荐，无需安装 Python）

1. 下载 Releases 中的 `扫描文件浏览器.exe`
2. 双击运行，浏览器自动打开 `http://127.0.0.1:5088`
3. 关闭命令行窗口即可停止

### 方式二：Python 源码

```bash
# 安装依赖
pip install -r requirements.txt

# 启动
python app.py
```

或双击 `启动.bat`（会自动安装依赖并启动）。

## 分享给同事

将整个文件夹（不含 `dist/`）打包发送。对方需要：

1. 安装 Python 3（[python.org](https://www.python.org/downloads/)）
2. 双击 `启动.bat`
3. 或直接使用 EXE 版本（无需安装任何东西）

**前置条件**：需在公司内网，能 ping 通 `192.168.1.115`。

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
├── app.py               # Flask 后端
├── templates/
│   └── index.html       # 前端界面
├── requirements.txt     # Python 依赖
├── 启动.bat             # 一键启动脚本
└── .gitignore
```

## 构建 EXE

```bash
python -m venv _build_env
_build_env\Scripts\pip install flask pysmb pyinstaller
_build_env\Scripts\pyinstaller --onefile --add-data "templates;templates" --name "扫描文件浏览器" --distpath ./dist app.py
```

## 许可

MIT
