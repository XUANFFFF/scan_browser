"""pywebview 桌面壳：把现有的 Web UI 装进一个原生窗口。

设计原则：只套壳，不重写。
Flask 与 SMB 逻辑一行不改，这里只负责「开窗口 / 关窗口 / 收拾残局」。

三个必须显式覆盖的 pywebview 默认行为（都已实测确认）：

1. ``ALLOW_DOWNLOADS`` 默认是 **False** —— 不打开的话，点「下载」会被
   WebView2 直接取消，用户什么也拿不到。设为 True 后 pywebview 会弹
   系统「另存为」对话框，并默认定位到用户「下载」文件夹。

2. ``OPEN_EXTERNAL_LINKS_IN_BROWSER`` 默认是 **True** —— 这意味着页面里任何
   ``window.open`` 都会去调起系统默认浏览器（正好是本 Issue 要消灭的行为）；
   若设为 False，则会在**当前窗口内导航**，把文件列表顶掉且没有后退按钮。
   两条路都不能走，所以前端在桌面模式下压根不使用 window.open：
   预览走页面内嵌 iframe/img，下载走 ``<a download>``。

3. WebView2 必须存在。缺失时会退化到 IE(MSHTML) 内核，而本项目的
   前端用了 fetch / async 等 IE 不支持的语法，页面会直接空白 ——
   所以宁可提前检测、降级到浏览器模式，也不要给用户一个白窗口。

另外两处实测踩过的坑：

4. WebView2 的 user data folder 既是**独占资源**（两实例共用会白屏），
   又会越用越脏（堆到 50MB 时关窗要 20~60s）。所以每次运行都用全新临时
   目录、退出即删（见 _storage_path）。

5. 本地服务端口在 Windows 上要关掉 SO_REUSEADDR，否则第二个实例会「成功」
   绑到同一端口，两个窗口实际共用一个服务（见 _port_is_free）。

外观（不改窗口结构）：

6. 窗口保留系统原生边框与按钮（最小化/最大化/关闭/拖拽/缩放全部照旧），
   但 Windows 默认那条深色标题栏与应用浅色纸张风格不搭，所以用 DWM 把
   标题栏底色、标题文字色、窗口描边色改成浅色（见 _apply_light_titlebar）。
   只设置 DWM 颜色属性，不动任何窗口样式，因此原生行为完全不受影响。
"""
import logging
import os
import shutil
import socket
import tempfile
import threading
import time

from werkzeug.serving import ThreadedWSGIServer

logger = logging.getLogger("scan_browser")

WINDOW_TITLE = "扫描文件浏览器"
WINDOW_WIDTH = 1040
WINDOW_HEIGHT = 720
WINDOW_MIN_SIZE = (760, 520)

# WebView2 运行时的常规安装位置
_WEBVIEW2_GLOBS = (
    r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application\*\msedgewebview2.exe",
    r"C:\Program Files\Microsoft\EdgeWebView\Application\*\msedgewebview2.exe",
    r"%LOCALAPPDATA%\Microsoft\EdgeWebView\Application\*\msedgewebview2.exe",
)


class DesktopUnavailable(RuntimeError):
    """本机无法提供桌面窗口，调用方应降级到浏览器模式。"""


# ── WebView2 检测 ──

def find_webview2_runtime():
    """返回 WebView2 运行时目录；找不到返回 None。"""
    import glob
    for pattern in _WEBVIEW2_GLOBS:
        expanded = os.path.expandvars(pattern)
        matches = glob.glob(expanded)
        if matches:
            # 目录名是版本号，字符串排序对同级版本号够用；取最新的
            return os.path.dirname(sorted(matches)[-1])
    return None


# ── 本地服务线程 ──

class _LocalServer(ThreadedWSGIServer):
    """本地 HTTP 服务。

    ``allow_reuse_address`` 在 Windows 上必须关掉，原因很关键：
    Windows 的 SO_REUSEADDR 语义与 POSIX 不同 —— 它允许**第二个进程绑到
    已被监听的端口**（前提是双方都开了这个选项）。开着的话，用户双击两次
    EXE 时第二个实例会「成功」绑到同一个 5088，两个窗口实际上共用同一个
    服务进程；此时关掉先开的那个窗口，另一个窗口的页面就再也拉不到数据了。

    关掉之后重复绑定会直接抛 OSError(WSAEADDRINUSE)，从而触发 start_server
    里的随机端口回退，真正实现「两个窗口各连各的服务」。

    POSIX 上 SO_REUSEADDR 不会导致同端口双监听（只是避开 TIME_WAIT），
    所以保持默认开启。
    """

    daemon_threads = True
    allow_reuse_address = os.name != "nt"


class ServerThread(threading.Thread):
    """把 Flask 跑在后台线程，主线程才能去开窗口。"""

    def __init__(self, app, host, port):
        threading.Thread.__init__(self, name="scan-browser-http", daemon=True)
        self._server = _LocalServer(host, port, app)

    @property
    def port(self):
        return self._server.server_address[1]

    def run(self):
        self._server.serve_forever()

    def stop(self, timeout=3.0):
        """让 serve_forever 退出；超时也不纠缠，线程本来就是 daemon。"""
        try:
            self._server.shutdown()
        except Exception:
            pass
        if self.is_alive():
            self.join(timeout)


def _port_is_free(host, port):
    """端口当前能否绑定。

    Windows 下**绝不能**给探测 socket 开 SO_REUSEADDR：Windows 的语义是
    「只要两边都开了这个选项，就能绑到同一个已被监听的端口」，于是探测会
    误判为「空闲」，第二个窗口就静默挤到同一端口上了。关掉它才能拿到真实的
    WSAEADDRINUSE(10048)。

    POSIX 下开着 SO_REUSEADDR 不影响判定（内核不允许两个监听套接字同端口），
    还能避开 TIME_WAIT 造成的误判，所以保持开启。
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name != "nt":
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def start_server(app, host, preferred_port):
    """启动本地服务。

    端口被占用时（例如用户又双击了一次 EXE）退回系统随机空闲端口，
    而不是直接报错打不开 —— 两个窗口各连各的服务，互不影响。
    无论走哪个端口，都只监听 127.0.0.1，不会暴露到局域网。
    """
    port = preferred_port
    if not _port_is_free(host, preferred_port):
        logger.warning("端口 %s 已被占用，改用系统分配的空闲端口", preferred_port)
        port = 0

    try:
        thread = ServerThread(app, host, port)
    except SystemExit:
        # werkzeug 绑定失败时直接 sys.exit(1) 而不是抛 OSError。
        # 探测和真正绑定之间被抢走端口是极小概率事件，兜一下即可。
        logger.warning("端口 %s 绑定失败，改用系统分配的空闲端口", port)
        thread = ServerThread(app, host, 0)
    thread.start()
    return thread


def wait_until_ready(host, port, timeout=15.0):
    """等端口开始接受连接，避免窗口先于服务加载导致白屏。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(0.5)
        try:
            if probe.connect_ex((host, port)) == 0:
                return True
        finally:
            probe.close()
        time.sleep(0.1)
    return False


# ── 浅色标题栏（仅 Windows）──
#
# 只设置 DWM 的「颜色」属性，不添加/移除任何窗口样式位，所以原生标题栏的
# 最小化/最大化/关闭、拖拽、边缘缩放全部保持系统默认行为。
#   * DWMWA_USE_IMMERSIVE_DARK_MODE 关掉（设 0）—— 否则系统深色主题会把标题栏
#     又拉回深色，颜色设置也会被压制；
#   * DWMWA_CAPTION_COLOR / TEXT_COLOR / BORDER_COLOR 依次是标题栏底色、
#     标题文字色、窗口外描边色。
# 后三个属性需要 Windows 11（build 22000+），旧系统调用会返回失败 —— 静默忽略，
# 标题栏保持系统默认外观，不影响任何功能。
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20        # Win10 1809~2004 上该属性号是 19，都设一遍
_DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY = 19
_DWMWA_BORDER_COLOR = 34
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36


def _colorref(hex_rgb):
    """'#rrggbb' → Windows COLORREF。

    注意字节序与网页相反：COLORREF 是 0x00BBGGRR，所以要反过来拼。
    """
    h = hex_rgb.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


# 与应用浅色主题对齐的标题栏配色（对应 CSS 里的 --surface-0 / --text-primary / --border）
TITLEBAR_CAPTION_COLOR = _colorref("#fbfbfa")
TITLEBAR_TEXT_COLOR = _colorref("#22222a")
TITLEBAR_BORDER_COLOR = _colorref("#e3e3e0")


def _find_window_hwnd(title):
    """找到「本进程 + 标题含 title」的可见顶层窗口句柄，找不到返回 None。

    按 PID 过滤很关键：用户可能同时开着多个实例，不能把别人的标题栏也改了。
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int

    pid = os.getpid()
    found = []

    def _enum(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value != pid:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if title in buf.value:
            found.append(hwnd)
            return False          # 找到了，停止枚举
        return True

    user32.EnumWindows(WNDENUMPROC(_enum), 0)
    return found[0] if found else None


def _apply_light_titlebar(title, timeout=12.0):
    """窗口一出现就把标题栏染成浅色。

    由后台线程调用：窗口是主线程建的，这里只轮询等待它出现，找到后设置颜色。
    整个过程失败只影响「好不好看」，绝不影响窗口能不能用，所以全程吞异常。
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
        dwmapi = ctypes.windll.dwmapi
        dwmapi.DwmSetWindowAttribute.argtypes = [
            wintypes.HWND, ctypes.c_uint, ctypes.POINTER(ctypes.c_int), ctypes.c_uint]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
    except Exception:
        return

    # 轮询等窗口出现（首次启动要等 WebView2 + 本地服务都起来）
    hwnd = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            hwnd = _find_window_hwnd(title)
        except Exception:
            hwnd = None
        if hwnd:
            break
        time.sleep(0.2)
    if not hwnd:
        logger.info("未找到桌面窗口句柄，跳过标题栏配色")
        return

    def _set(attr, value):
        try:
            v = ctypes.c_int(value)
            dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
        except Exception:
            pass

    # 设三遍：窗口刚出现时设一次，之后 1s、2s 再各补一次 ——
    # WebView2 加载完成时可能重设窗口主题，补设可以覆盖回去。
    for delay in (0.0, 1.0, 2.0):
        if delay:
            time.sleep(delay)
        _set(_DWMWA_USE_IMMERSIVE_DARK_MODE, 0)
        _set(_DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY, 0)
        _set(_DWMWA_CAPTION_COLOR, TITLEBAR_CAPTION_COLOR)
        _set(_DWMWA_TEXT_COLOR, TITLEBAR_TEXT_COLOR)
        _set(_DWMWA_BORDER_COLOR, TITLEBAR_BORDER_COLOR)
    logger.info("已应用浅色标题栏（hwnd=%s）", hwnd)


# ── 桌面窗口 ──

_STORAGE_PREFIX = "ScanBrowser-"


def _pid_alive(pid):
    """判断进程是否还在（用于识别缓存目录是否仍被占用）。"""
    try:
        if os.name == "nt":
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            k32 = ctypes.windll.kernel32
            handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                if k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return code.value == STILL_ACTIVE
                return False
            finally:
                k32.CloseHandle(handle)
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def sweep_stale_storage():
    """清掉以前异常退出（被强杀）留下的临时缓存目录。

    目录名里带了拥有者的 PID（ScanBrowser-<pid>-xxxx），所以能精确判断该实例
    是否还活着：活着的跳过，绝不误删正在运行的窗口的缓存。
    """
    base = tempfile.gettempdir()
    try:
        names = os.listdir(base)
    except Exception:
        return
    for name in names:
        if not name.startswith(_STORAGE_PREFIX):
            continue
        parts = name[len(_STORAGE_PREFIX):].split("-", 1)
        if not parts or not parts[0].isdigit():
            continue
        if _pid_alive(int(parts[0])):
            continue                       # 还有实例在用，跳过
        try:
            shutil.rmtree(os.path.join(base, name), ignore_errors=True)
        except Exception:
            pass


def _storage_path():
    """给 WebView2 一个**每次全新**的临时缓存目录，返回 (路径, 是否为临时目录)。

    为什么不复用持久缓存（下面两条都有实测数据）：

    1. WebView2 的 user data folder 是**独占资源**。两个实例共用同一目录时，
       第二个窗口拿不到 WebView2 环境，直接白屏（日志里只有「监听端口」那行，
       之后连一个 HTTP 请求都没有）。
    2. 这个目录会不断堆积 BrowserMetrics / GPUCache / Crashpad / 各种 .tmp，
       实测每跑一轮涨约 8MB；堆到 50MB 左右时，**关窗收尾会从 1s 恶化到
       20~60s**（WebView2 要清理这一堆东西）。换成全新目录立刻恢复 1s 上下。

    本工具加载的是本地页面、字体与图标全部本地化，持久缓存没有收益，
    所以每次重建、退出即删 —— 两个坑一起解决。
    目录名带上本进程 PID，方便下次启动时精确回收异常退出的残留（见 sweep_stale_storage）。
    """
    try:
        return tempfile.mkdtemp(prefix="%s%d-" % (_STORAGE_PREFIX, os.getpid())), True
    except Exception:
        return None, False


def _remove_storage(path, attempts=6, delay=0.5):
    """尽力删除临时缓存目录（WebView2 子进程退出需要点时间，删不掉就退避重试）。

    重试后仍失败也无所谓：下次启动时 sweep_stale_storage 会按 PID 回收。
    """
    for _ in range(attempts):
        if not os.path.exists(path):
            return True
        try:
            shutil.rmtree(path)
            return True
        except Exception:
            time.sleep(delay)
    return False


def check_available():
    """桌面模式可用的前置检查；不满足则抛 DesktopUnavailable。"""
    try:
        import webview  # noqa: F401
    except Exception as exc:
        raise DesktopUnavailable("未安装 pywebview（%s）" % exc)

    if os.name != "nt":
        # macOS 用系统 WebKit、Linux 用 GTK/Qt，不需要额外运行时检查
        return

    from webview import settings as webview_settings
    if webview_settings.get("WEBVIEW2_RUNTIME_PATH"):
        return
    runtime = find_webview2_runtime()
    if not runtime:
        raise DesktopUnavailable(
            "未检测到 Microsoft Edge WebView2 运行时，无法创建桌面窗口"
        )
    # 顺手告诉 pywebview 用哪个运行时，省得它自己再找一遍
    webview_settings["WEBVIEW2_RUNTIME_PATH"] = runtime
    logger.info("使用 WebView2 运行时：%s", runtime)


def run(app, host, port, title=WINDOW_TITLE):
    """开一个桌面窗口，阻塞到用户关闭它。

    返回后：本地服务已停止、SMB 连接已断开。
    """
    import webview

    check_available()

    # 覆盖 pywebview 会破坏预期行为的默认值（详见模块顶部的说明）
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False

    server = start_server(app, host, port)
    actual_port = server.port
    url = "http://%s:%d" % (host, actual_port)
    logger.info("桌面模式监听 %s（仅本机可访问）", url)

    # 先把以前被强杀留下的临时缓存收掉（不会碰正在运行的实例）
    sweep_stale_storage()

    storage_path, storage_is_temp = _storage_path()

    try:
        if not wait_until_ready(host, actual_port):
            raise DesktopUnavailable("本地服务未能在超时前就绪：%s" % url)

        window = webview.create_window(
            title,
            url,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            min_size=WINDOW_MIN_SIZE,
            text_select=True,   # 默认不可选中文字，这里放开，方便复制文件名
        )
        if window is None:
            raise DesktopUnavailable("创建桌面窗口失败")

        # 窗口一出现就把标题栏改成浅色（后台轮询；失败只影响美观，不影响功能）
        threading.Thread(
            target=_apply_light_titlebar,
            args=(title,),
            name="titlebar-tint",
            daemon=True,
        ).start()

        try:
            # private_mode=False：本工具不需要 WebView2 保存任何会话数据，
            # 但开成私有模式的话，pywebview 会在关闭时尝试删掉整个用户数据目录，
            # 而那个时机 WebView2 的进程信息已经拿不到了，会稳定吐一条
            # "Failed to delete user data folder" 警告。关掉私有模式既没副作用
            # （本来就无 Cookie/登录态），还能留下缓存让下次启动更快。
            webview.start(private_mode=False, storage_path=storage_path)
        except Exception as exc:
            raise DesktopUnavailable("桌面窗口启动失败：%s" % exc)
    finally:
        # 窗口关掉（或启动失败）后必须收摊，否则进程会带着服务线程挂着不走
        server.stop()
        client = app.config.get("SMB_CLIENT")
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        # 临时缓存目录是自己建的，退出时收拾干净（删不掉就留给下次启动回收）
        if storage_is_temp and storage_path:
            _remove_storage(storage_path)
        try:
            backend = webview.guilib.__name__
        except Exception:
            backend = "unknown"
        logger.info("桌面窗口已关闭（GUI 后端 %s），本地服务与 SMB 连接均已断开", backend)
