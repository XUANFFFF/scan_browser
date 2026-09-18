"""扫描文件浏览器 — 内部版入口（MCF）。

SMB 地址与共享名已写死在 launcher.py 里，同事拿到就能用，不需要任何配置。

用法：
    python app_internal.py                源码运行 → 浏览器模式（开发调试用）
    python app_internal.py --desktop      强制独立桌面窗口
    扫描文件浏览器-MCF.exe                 打包后默认 桌面窗口
    扫描文件浏览器-MCF.exe --browser       强制回退到浏览器模式

具体的启动逻辑都在 launcher.py，这里只说明用哪套配置。
"""
from launcher import main

if __name__ == "__main__":
    raise SystemExit(main("internal"))
