"""SMB 访问层。

把「怎么连共享、怎么读文件」从 Web 层里剥出来：
Web 层只负责请求/响应，桌面壳只负责窗口生命周期，两边都调用这里。

之所以用 pysmb 而不是系统的 SMB 驱动：pysmb 是纯 Python 的用户态实现，
不依赖操作系统的 SMB 协议栈，所以在默认禁用 SMBv1 的 Windows 10/11 上照样能连。
"""
import io
import os
import time
from datetime import datetime

from smb.SMBConnection import SMBConnection

# 连接复用窗口（秒）：30 秒内的连续请求复用同一条 SMB 连接，避免每次都重新握手
SMB_CONN_TTL = 30

# ── 文件类型识别 ──
# 扩展名 → MIME：PDF + 浏览器/WebView 可原生预览的图片（JPG/JPEG/PNG）
MIME_MAP = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

# 扩展名 → 分类：前端用它决定分组与徽标
TYPE_MAP = {
    ".pdf": "pdf",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
}


def file_ext(filename):
    """取小写扩展名（含点），如 '.jpg'"""
    return os.path.splitext(filename)[1].lower()


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
    """从 14 位时间戳文件名中解析出时间，解析不出就返回 '—'。

    有些扫描仪会把文件命名为 20260918100415.pdf，这里尽量榨出时间信息；
    命名规则不同的（例如中文描述名）就显示 '—'，不猜。
    """
    try:
        stem = filename.rsplit(".", 1)[0]
        if len(stem) == 14 and stem.isdigit():
            return datetime.strptime(stem, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, IndexError):
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
        """列出共享根目录下的所有文件（跳过后台目录项与子目录）。"""
        conn = self.connect()
        files = []
        for entry in conn.listPath(self.config.share, "/"):
            if entry.filename in (".", "..") or entry.isDirectory:
                continue
            ext = file_ext(entry.filename)
            files.append({
                "name": entry.filename,
                "size": entry.file_size,
                "size_display": format_size(entry.file_size),
                "date": parse_date(entry.filename),
                "create_time": entry.create_time,
                "type": file_type(entry.filename),
                "ext": ext.lstrip("."),
            })
        files.sort(key=lambda f: f["name"], reverse=True)
        return files

    def retrieve_file(self, filename):
        """把共享里的文件读进内存，返回 seek 到开头的 BytesIO。"""
        conn = self.connect()
        buf = io.BytesIO()
        conn.retrieveFile(self.config.share, "/" + filename, buf)
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
