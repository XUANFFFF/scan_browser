"""SMB 访问层。

把「怎么连共享、怎么读文件」从 Web 层里剥出来：
Web 层只负责请求/响应，桌面壳只负责窗口生命周期，两边都调用这里。

之所以用 pysmb 而不是系统的 SMB 驱动：pysmb 是纯 Python 的用户态实现，
不依赖操作系统的 SMB 协议栈，所以在默认禁用 SMBv1 的 Windows 10/11 上照样能连。
"""
import io
import os
import posixpath
import re
import time
from datetime import datetime

from smb.SMBConnection import SMBConnection

# 连接复用窗口（秒）：30 秒内的连续请求复用同一条 SMB 连接，避免每次都重新握手
SMB_CONN_TTL = 30

# 列举子目录的最大深度（根目录算第 0 层）。
# 扫描仪会把一次扫描的成品放进 YYYYMMDDHHMMSS/ 子目录，所以必须下钻；
# 但设个上限，防止共享被塞进深层目录时无限递归、每层都发一次 listPath。
MAX_DEPTH = 3

# 列举时要跳过的噪音文件（缩略图缓存 / 系统标记 / macOS 垃圾文件）
SKIP_FILES = {"Thumbs.db", "desktop.ini", "ehthumbs.db", ".DS_Store"}

# ── 文件类型识别 ──
# 扩展名 → MIME：PDF + 可内联预览的图片（JPG/JPEG/PNG）+ TIFF（可下载，浏览器不内联）
MIME_MAP = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

# 扩展名 → 分类：前端用它决定分组、徽标与「能否内联预览」
#   pdf   —— 内嵌 iframe 预览
#   image —— 内嵌 <img> 预览
#   tiff  —— 列表展示 + 下载，但无法内联预览（浏览器/WebView 不支持 TIFF）
TYPE_MAP = {
    ".pdf": "pdf",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".tif": "tiff",
    ".tiff": "tiff",
}


def file_ext(filename):
    """取小写扩展名（含点），如 '.jpg'"""
    return os.path.splitext(filename)[1].lower()


class InvalidSharePath(ValueError):
    """请求的共享路径不合法（目录穿越 / 绝对路径等），对应 HTTP 400。"""


# 合法的共享路径段：不含空段 / 点段，且不是「.」开头（顺带排除 macOS 的 ._* 元数据）
_SEGMENT_RE = re.compile(r"^[^.].*$")


def sanitize_share_path(path):
    """校验「相对共享根的文件路径」，返回原字符串；不合法抛 InvalidSharePath。

    HTTP 边界（/api/preview、/api/download）拿到的路径一律先过这里，
    不依赖 SMB 服务端拒绝异常路径。规则从紧：
    - 必须是相对路径，禁止盘符 / 反斜杠 / 开头结尾的 /
    - 逐段校验：不允许空段（a//b）、点段（a/./b）、..（穿越）
    - 禁止控制字符与冒号（NTFS 备用数据流 file:stream）
    - 规范化后必须与原串一致，杜绝任何形式的逃逸
    """
    if not isinstance(path, str):
        raise InvalidSharePath("路径类型不合法")
    p = path.strip()
    if not p:
        raise InvalidSharePath("路径为空")
    if "\x00" in p or any(ord(c) < 32 for c in p):
        raise InvalidSharePath("路径含控制字符")
    if "\\" in p:
        raise InvalidSharePath("路径不允许反斜杠")
    if ":" in p:
        raise InvalidSharePath("路径不允许包含冒号")
    if p.startswith("/") or p.endswith("/"):
        raise InvalidSharePath("路径不能以 / 开头或结尾")
    segments = p.split("/")
    for seg in segments:
        if not _SEGMENT_RE.match(seg) or seg == "..":
            raise InvalidSharePath("路径段不合法: %r" % seg)
    # 双保险：规范化后必须与原串一致（仍为相对路径且无冗余段）
    norm = posixpath.normpath(p)
    if norm != p or norm.startswith("/"):
        raise InvalidSharePath("路径规范化后越界")
    return p


def file_mime(filename):
    """按扩展名返回 MIME 类型，未知类型回退为二进制流"""
    return MIME_MAP.get(file_ext(filename), "application/octet-stream")


def file_type(filename):
    """按扩展名返回类型：'pdf' / 'image' / 'other'"""
    return TYPE_MAP.get(file_ext(filename), "other")


def format_size(size_bytes):
    """人类可读的体积"""
    if size_bytes < 1024:
        return "%d B" % size_bytes
    if size_bytes < 1048576:
        return "%.1f KB" % (size_bytes / 1024)
    return "%.1f MB" % (size_bytes / (1024 * 1024))


def parse_date(filename):
    """从文件名前缀的时间戳解析出时间，解析不出就返回 '—'。

    扫描仪有两种命名，都要能认出来：
      1. 纯 14 位时间戳：      20260917154658.pdf
      2. 时间戳-序号（子目录）：20260918094501-0001.jpg
    命名规则完全不同的（例如中文描述名）就显示 '—'，不猜。
    """
    stem = filename.rsplit(".", 1)[0]
    m = re.match(r"^(\d{14})", stem)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return "—"


class SMBConfig(object):
    """SMB 连接参数。"""

    def __init__(self, host, share, port=445):
        self.host = host
        self.share = share
        self.port = int(port)

    def __repr__(self):
        return "SMBConfig(host=%r, share=%r, port=%r)" % (
            self.host, self.share, self.port)


class SMBClient(object):
    """SMBv1 客户端：连接复用 + 文件列举/读取 + 健康检查。

    线程安全性说明：连接缓存没有加锁，因为使用场景是单用户本地工具，
    请求量极低；真要并发也只会退化成多建几条连接，不会出错。
    """

    def __init__(self, config):
        self.config = config
        self._conn = None
        self._conn_ts = 0.0

    # ── 连接 ──

    def connect(self):
        """取一条可用连接。

        缓存命中且仍然有效（listPath 能跑通）就直接复用；
        否则重新握手。任何情况下返回的连接都是可用的。
        """
        now = time.time()
        if self._conn is not None and (now - self._conn_ts) < SMB_CONN_TTL:
            try:
                self._conn.listPath(self.config.share, "/")
                return self._conn
            except Exception:
                # 缓存的连接已经死了，丢掉重连
                self._discard()

        conn = SMBConnection(
            "", "",
            "scan_browser",
            self.config.host.split(".")[0],
            use_ntlm_v2=False,   # 打印机共享通常只认 SMBv1 / NTLMv1
            is_direct_tcp=True,  # 直连 445 端口，不走 NetBIOS
        )
        conn.connect(self.config.host, self.config.port)
        self._conn = conn
        self._conn_ts = now
        return conn

    def _discard(self):
        """丢弃（并尽力关闭）当前缓存的连接"""
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def close(self):
        """窗口关闭 / 进程退出前调用，主动断开 SMB 会话"""
        self._discard()

    # ── 业务 ──

    def list_files(self):
        """递归列出共享下的所有文件（含子目录）。

        扫描仪有两种落盘方式：
          - 直接落在根目录，命名 YYYYMMDDHHMMSS.pdf
          - 放进 YYYYMMDDHHMMSS/ 子目录，命名 YYYYMMDDHHMMSS-000N.jpg（图片类常见）
        只列根目录会整批漏掉后者，所以这里下钻子目录；每条记录带 path（相对共享根），
        供前端做预览/下载的唯一标识。
        """
        conn = self.connect()
        files = []
        self._walk(conn, "", 0, files)
        files.sort(key=lambda f: f["name"], reverse=True)
        return files

    def _walk(self, conn, subdir, depth, out):
        """递归收集 subdir（相对共享根，根目录为 ""）下的文件。"""
        if depth > MAX_DEPTH:
            return
        share_path = "/" + subdir.rstrip("/")   # "/" 或 "/20260918094501"
        try:
            entries = conn.listPath(self.config.share, share_path)
        except Exception:
            # 某个子目录读不到（权限 / 被占用）不应拖垮整份列表
            return
        for entry in entries:
            name = entry.filename
            if name in (".", ".."):
                continue
            if entry.isDirectory:
                # 跳过隐藏 / 系统目录（.Trashes、$RECYCLE.BIN 等）
                if name.startswith((".", "$")):
                    continue
                self._walk(conn, subdir + name + "/", depth + 1, out)
                continue
            # 跳过噪音文件与 macOS 资源分叉文件（._xxx）
            if name in SKIP_FILES or name.startswith("._"):
                continue
            out.append({
                "name": name,
                "path": subdir + name,          # 相对共享根的路径（可能含子目录）
                "dir": subdir.rstrip("/"),      # 所在子目录，根目录为空串
                "size": entry.file_size,
                "size_display": format_size(entry.file_size),
                "date": parse_date(name),
                "create_time": entry.create_time,
                "type": file_type(name),
                "ext": file_ext(name).lstrip("."),
            })

    def retrieve_file(self, relpath):
        """把共享里的文件读进内存，返回 seek 到开头的 BytesIO。

        relpath 是相对共享根的路径，可能含子目录（如 20260918094501/xxx.jpg）。
        先过 sanitize_share_path：这是 SMB 层的边界，无论调用方有没有校验
        （webapp 校验过，但未来新调用方未必），这里都要再拦一次。
        """
        relpath = sanitize_share_path(relpath)
        conn = self.connect()
        buf = io.BytesIO()
        conn.retrieveFile(self.config.share, "/" + relpath, buf)
        buf.seek(0)
        return buf

    def health_check(self):
        """真实探测 SMB 是否可达（不是看缓存标志，是实际跑一次 listPath）。

        返回 dict，绝不抛异常 —— 让调用方（/api/health）能直接把结果转成响应。
        """
        started = time.time()
        result = {"ok": False}
        try:
            conn = self.connect()
            entries = conn.listPath(self.config.share, "/")
            result["ok"] = True
            result["file_count"] = sum(
                1 for e in entries
                if e.filename not in (".", "..") and not e.isDirectory
            )
        except Exception as exc:
            result["error"] = "%s: %s" % (type(exc).__name__, exc)
        result["latency_ms"] = int((time.time() - started) * 1000)
        return result
