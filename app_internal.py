"""扫描文件浏览器（内部版）- 通过 SMBv1 协议访问打印机扫描共享"""
import io
import os
import sys
import time
import webbrowser
from datetime import datetime
from flask import Flask, render_template, send_file, jsonify
from smb.SMBConnection import SMBConnection


def _setup_console():
    """Windows 控制台编码兜底。

    中文版 Windows 控制台默认是 GBK(936)，直接 print 中文/符号（如 ⚠）
    会抛 UnicodeEncodeError，导致程序刚启动就崩溃。
    这里优先把控制台切到 UTF-8；失败则退回 errors="replace"，保证永不崩溃。
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
    try:
        if utf8_ok:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        else:
            sys.stdout.reconfigure(errors="replace")
            sys.stderr.reconfigure(errors="replace")
    except Exception:
        pass


_setup_console()

# PyInstaller 打包后模板路径适配
_is_frozen = getattr(sys, "frozen", False)
if _is_frozen:
    template_dir = os.path.join(sys._MEIPASS, "templates")
else:
    template_dir = os.path.join(os.path.dirname(__file__), "templates")

# ── 内部版硬编码 ──
SMB_HOST = "192.168.1.115"
SMB_PORT = 445
SMB_SHARE = "扫描共享文件"
SERVER_PORT = 5088
SMB_CONN_TTL = 30

app = Flask(__name__, template_folder=template_dir)

# ── 公共配置 API ──

@app.route("/api/config")
def get_config():
    return jsonify({"smb_host": SMB_HOST, "smb_share": SMB_SHARE})

# ── SMB 连接管理 ──

_conn_cache = {"conn": None, "ts": 0}

def _smb_connect():
    now = time.time()
    if _conn_cache["conn"] and (now - _conn_cache["ts"]) < SMB_CONN_TTL:
        try:
            _conn_cache["conn"].listPath(SMB_SHARE, "/")
            return _conn_cache["conn"]
        except Exception:
            pass

    conn = SMBConnection("", "", "scan_browser", SMB_HOST.split(".")[0],
                         use_ntlm_v2=False, is_direct_tcp=True)
    conn.connect(SMB_HOST, SMB_PORT)
    _conn_cache["conn"] = conn
    _conn_cache["ts"] = now
    return conn


# ── 文件类型识别 ──
# 扩展名 → MIME 类型：PDF + 浏览器可原生预览的图片（JPG/JPEG/PNG）
_MIME_MAP = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

# 扩展名 → 类型分类：用于前端分组与徽标展示
_TYPE_MAP = {
    ".pdf": "pdf",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
}


def _file_ext(filename):
    """取小写扩展名（含点），如 '.jpg'"""
    return os.path.splitext(filename)[1].lower()


def _file_mime(filename):
    """按扩展名返回 MIME 类型，未知类型回退为二进制流"""
    return _MIME_MAP.get(_file_ext(filename), "application/octet-stream")


def _file_type(filename):
    """按扩展名返回类型：'pdf' / 'image' / 'other'"""
    return _TYPE_MAP.get(_file_ext(filename), "other")


def _serve_file(filename, as_attachment):
    """从 SMB 读取文件并返回，MIME 按扩展名自动识别（支持 PDF 与图片）"""
    conn = _smb_connect()
    buf = io.BytesIO()
    conn.retrieveFile(SMB_SHARE, f"/{filename}", buf)
    buf.seek(0)
    return send_file(buf, mimetype=_file_mime(filename),
                     as_attachment=as_attachment,
                     download_name=filename if as_attachment else None)


def _format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1048576:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _parse_date(filename):
    try:
        stem = filename.rsplit(".", 1)[0]
        if len(stem) == 14 and stem.isdigit():
            return datetime.strptime(stem, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, IndexError):
        pass
    return "—"


# ── 路由 ──

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/files")
def list_files():
    try:
        conn = _smb_connect()
        entries = conn.listPath(SMB_SHARE, "/")
        files = []
        for e in entries:
            if e.filename in (".", "..") or e.isDirectory:
                continue
            ext = _file_ext(e.filename)
            files.append({
                "name": e.filename,
                "size": e.file_size,
                "size_display": _format_size(e.file_size),
                "date": _parse_date(e.filename),
                "create_time": e.create_time,
                "type": _file_type(e.filename),
                "ext": ext.lstrip("."),
            })
        files.sort(key=lambda f: f["name"], reverse=True)
        return jsonify({"success": True, "files": files})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/download/<filename>")
def download_file(filename):
    try:
        return _serve_file(filename, as_attachment=True)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/preview/<filename>")
def preview_file(filename):
    try:
        return _serve_file(filename, as_attachment=False)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── 启动 ──

if __name__ == "__main__":
    url = f"http://127.0.0.1:{SERVER_PORT}"
    print(f"  扫描文件浏览器  内部版")
    print(f"  地址: {url}")
    print(f"  共享: \\\\{SMB_HOST}\\{SMB_SHARE}")
    print(f"  ⚠ 仅监听 127.0.0.1，仅本机可访问")
    webbrowser.open(url)
    app.run(host="127.0.0.1", port=SERVER_PORT, debug=False)
