"""启动编排：控制台/日志/崩溃兜底 → 解析参数 → 建应用 → 分派到桌面或浏览器模式。

两个入口脚本（app.py / app_internal.py）都只做一件事：告诉这里用哪套配置。

模式规则：
    --desktop   强制桌面窗口
    --browser   强制浏览器模式
    不带参数    打包后的 EXE 走桌面窗口；源码运行走浏览器（方便开发调试）
"""
import argparse
import json
import os
import sys
import tempfile
import traceback
import webbrowser

from webapp import create_app
from smb_client import SMBConfig

# ── 常量 ──

HOST = "127.0.0.1"          # 固定只监听本机，绝不放宽到局域网
LOG_FILENAME = "扫描文件浏览器.log"

# 内部版（MCF）硬编码配置
INTERNAL_SMB_HOST = "192.168.1.115"
INTERNAL_SMB_SHARE = "扫描共享文件"
INTERNAL_SMB_PORT = 445
INTERNAL_SERVER_PORT = 5088

# 公开版缺省值（config.json 未提供时使用）
DEFAULT_SMB_HOST = "192.168.1.115"
DEFAULT_SMB_SHARE = "扫描共享文件"
DEFAULT_SERVER_PORT = 5088

VERSION = "v2.0"


# ── 控制台 ──

def _setup_console():
    """Windows 控制台编码兜底。

    中文版 Windows 控制台默认是 GBK(936)，直接 print 中文/符号（如 ⚠）
    会抛 UnicodeEncodeError，导致程序刚启动就崩溃。
    这里优先把控制台切到 UTF-8；失败则退回 errors="replace"，保证永不崩溃。
    打包成无控制台窗口的 EXE 时 stdout 可能为 None，下面的 try/except 也兜住了。
    """
    if sys.platform != "win32":
        return
    utf8_ok = False
    try:
        import ctypes
        # 65001 = UTF-8 代码页
        utf8_ok = bool(ctypes.windll.kernel32.SetConsoleOutputCP(65001))
    except Exception:
        utf8_ok = False
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            if utf8_ok:
                stream.reconfigure(encoding="utf-8", errors="replace")
            else:
                stream.reconfigure(errors="replace")
        except Exception:
            pass


class _Tee(object):
    """把输出同时写到控制台和日志文件。

    无控制台窗口的 EXE 里 sys.stdout 是 None，这里会自动跳过那一路；
    任何一路写失败都不允许影响另一路，更不允许把程序带崩。
    """

    def __init__(self, *streams):
        self._streams = [s for s in streams if s is not None]

    def write(self, data):
        for stream in self._streams:
            try:
                stream.write(data)
            except Exception:
                pass

    def flush(self):
        for stream in self._streams:
            try:
                stream.flush()
            except Exception:
                pass

    def isatty(self):
        return False


# ── 路径 ──

def base_dir():
    """EXE 所在目录（打包后）或源码目录（开发时）。

    公开版的 config.json 与日志文件都放这里，方便同事「把日志发我」。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _log_path(directory):
    """挑一个能写的日志位置，EXE 目录优先，失败就退到用户目录。"""
    candidates = [directory]
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(os.path.join(local, "ScanBrowser"))
    candidates.append(tempfile.gettempdir())

    for folder in candidates:
        try:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, LOG_FILENAME)
            with open(path, "a", encoding="utf-8"):
                pass
            return path
        except Exception:
            continue
    return None


def setup_logging(log_path):
    """把 stdout/stderr 接一份到日志文件，并让 logging 也走同一条路。

    注意：sys.stdout/stderr 必须先换成 Tee，再配置 logging —— 这样
    StreamHandler 捕获到的是 Tee，日志才会同时进控制台和文件。
    不配置的话 Python 默认只把 WARNING 以上送给 stderr，
    我们自己的 info 级排障信息（用了哪个 WebView2、端口是否回退等）会全部丢掉。
    """
    import logging

    log_file = None
    if log_path:
        try:
            log_file = open(log_path, "a", encoding="utf-8", buffering=1)
        except Exception:
            log_file = None
    sys.stdout = _Tee(sys.stdout, log_file)
    sys.stderr = _Tee(sys.stderr, log_file)

    # force=True：万一有库在我们之前动过 root logger，也要保证配置生效
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
        force=True,
    )
    # pywebview 自带一个 handler，若继续向 root 传播，每条日志会被写两遍
    logging.getLogger("pywebview").propagate = False
    # pysmb 每建一条连接都会刷 11 行握手细节，压到 WARNING，
    # 免得把真正的排查信息淹掉（连不上时错误信息会直接显示在界面上）
    logging.getLogger("SMB").setLevel(logging.WARNING)
    return log_file


# ── 崩溃兜底 ──

def _message_box(text, title):
    """Windows 原生弹窗。无控制台的 EXE 崩溃时，这是唯一能告诉用户出事了的方式。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
    except Exception:
        pass


def install_crash_handler(log_path):
    """把未捕获异常写进日志；打包环境下再弹个窗提示看日志。"""

    def _hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            sys.stderr.write("[FATAL] " + text + "\n")
        except Exception:
            pass
        if getattr(sys, "frozen", False):
            detail = text if len(text) <= 900 else text[-900:]
            _message_box(
                u"程序启动失败。\n\n错误信息：\n%s\n\n完整日志：\n%s"
                % (detail, log_path or u"(未生成日志)"),
                u"扫描文件浏览器",
            )

    sys.excepthook = _hook


# ── 参数 ──

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="扫描文件浏览器",
        description=u"通过 SMB 浏览打印机扫描共享里的 PDF 与图片。",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--desktop", dest="mode", action="store_const", const="desktop",
                       help=u"用独立桌面窗口打开（打包后的 EXE 默认行为）")
    group.add_argument("--browser", dest="mode", action="store_const", const="browser",
                       help=u"用系统默认浏览器打开（开发/回退用）")
    parser.add_argument("--port", type=int, default=None,
                        help=u"本地服务端口，默认读配置（5088）")
    return parser.parse_args(argv)


# ── 配置 ──

def load_public_config(directory):
    """公开版：读同目录的 config.json。"""
    path = os.path.join(directory, "config.json")
    data = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            print(u"  配置文件读取失败，改用默认值：%s" % exc)

    config = SMBConfig(
        data.get("smb_host", DEFAULT_SMB_HOST),
        data.get("smb_share", DEFAULT_SMB_SHARE),
        data.get("smb_port", INTERNAL_SMB_PORT),
    )
    return config, data.get("server_port", DEFAULT_SERVER_PORT), path


def load_internal_config(directory):
    """内部版：配置写死在代码里，同事拿到就能用，零配置。"""
    config = SMBConfig(INTERNAL_SMB_HOST, INTERNAL_SMB_SHARE, INTERNAL_SMB_PORT)
    return config, INTERNAL_SERVER_PORT, None


# ── 启动 ──

def _resolve_mode(requested):
    """决定用哪种模式。"""
    if requested:
        return requested
    # 打包后的 EXE 默认开桌面窗口；源码运行默认走浏览器，方便改一行刷新一次
    return "desktop" if getattr(sys, "frozen", False) else "browser"


def main(variant):
    """variant: 'internal'（内部版）或 'public'（公开版）"""
    directory = base_dir()
    log_path = _log_path(directory)

    _setup_console()
    setup_logging(log_path)
    install_crash_handler(log_path)

    args = parse_args()
    mode = _resolve_mode(args.mode)

    if variant == "internal":
        config, server_port, config_path = load_internal_config(directory)
        label = u"内部版"
    else:
        config, server_port, config_path = load_public_config(directory)
        label = u"公开版"

    if args.port:
        server_port = args.port

    app = create_app(config, mode=mode)

    print(u"  扫描文件浏览器  %s  %s" % (VERSION, label))
    print(u"  地址: http://%s:%d" % (HOST, server_port))
    print(u"  共享: \\\\%s\\%s" % (config.host, config.share))
    if config_path:
        print(u"  配置: %s" % config_path)
    if log_path:
        print(u"  日志: %s" % log_path)
    print(u"  仅监听 127.0.0.1，仅本机可访问")

    if mode == "desktop":
        from desktop import DesktopUnavailable, run as run_desktop
        try:
            run_desktop(app, HOST, server_port)
            return 0
        except DesktopUnavailable as exc:
            # 桌面壳不可用（多为缺 WebView2 运行时）时降级到浏览器，
            # 保证「工具还能用」优先于「界面更好看」
            print(u"  [警告] 无法使用桌面窗口：%s" % exc)
            print(u"          已自动改用浏览器模式")
            mode = "browser"
            # 重新建应用，让 /api/config 回报正确的模式
            app = create_app(config, mode=mode)

    url = "http://%s:%d" % (HOST, server_port)
    print(u"  正在打开浏览器：%s" % url)
    webbrowser.open(url)
    app.run(host=HOST, port=server_port, debug=False)
    return 0
