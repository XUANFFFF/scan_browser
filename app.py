"""扫描文件浏览器（内部版）- 通过 SMBv1 协议访问打印机扫描共享"""
import io
import os
import sys
import time
import webbrowser
from datetime import datetime
from flask import Flask, render_template, send_file, jsonify
from smb.SMBConnection import SMBConnection

# PyInstaller 打包后模板路径适配
_is_frozen = getattr(sys, "frozen", False)
if _is_frozen:
    template_dir = os.path.join(sys._MEIPASS, "templates")
else:
    template_dir = os.path.join(os.path.dirname(__file__), "templates")

# ── 配置（内部版直接写死）──
SMB_HOST = "192.168.1.115"
SMB_PORT = 445
SMB_SHARE = "扫描共享文件"
SERVER_PORT = 5088
SMB_CONN_TTL = 30

app = Flask(__name__, template_folder=template_dir)

# ── 公共配置 API ──

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


def _serve_pdf(filename, as_attachment):
    conn = _smb_connect()
    buf = io.BytesIO()
    conn.retrieveFile(SMB_SHARE, f"/{filename}", buf)
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf",
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
            files.append({
                "name": e.filename,
                "size": e.file_size,
                "size_display": _format_size(e.file_size),
                "date": _parse_date(e.filename),
                "create_time": e.create_time,
            })
        files.sort(key=lambda f: f["name"], reverse=True)
        return jsonify({"success": True, "files": files})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/download/<filename>")
def download_file(filename):
    try:
        return _serve_pdf(filename, as_attachment=True)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/preview/<filename>")
def preview_file(filename):
    try:
        return _serve_pdf(filename, as_attachment=False)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── 启动 ──

if __name__ == "__main__":
    url = f"http://127.0.0.1:{SERVER_PORT}"
    print(f"  扫描文件浏览器  v1.1")
    print(f"  地址: {url}")
    print(f"  共享: \\\\{SMB_HOST}\\{SMB_SHARE}")
    print(f"  ⚠ 仅监听 127.0.0.1，仅本机可访问")
    webbrowser.open(url)
    app.run(host="127.0.0.1", port=SERVER_PORT, debug=False)
