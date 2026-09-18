"""扫描文件浏览器 — 公开版入口。

配置读同目录的 config.json，适合分发给 SMB 服务器地址不同的同事。

用法：
    python app.py                源码运行 → 浏览器模式（开发调试用）
    python app.py --desktop      强制独立桌面窗口
    扫描文件浏览器.exe            打包后默认 桌面窗口
    扫描文件浏览器.exe --browser  强制回退到浏览器模式

具体的启动逻辑都在 launcher.py，这里只说明用哪套配置。
"""
from launcher import main

if __name__ == "__main__":
    raise SystemExit(main("public"))
