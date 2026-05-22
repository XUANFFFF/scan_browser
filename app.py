"""扫描文件浏览器 - 通过 SMBv1 协议访问打印机扫描共享"""
import io
import json
import os
import sys
import time
import webbrowser
from datetime import datetime
from flask import Flask, render_template, send_file, jsonify
from smb.SMBConnection import SMBConnection

# PyInstaller 打包后模板路径适配
_is_frozen = getattr(sys, "frozen", False)
_base_dir = os.path.dirname(sys.executable) if _is_frozen else os.path.dirname(__file__)
_template_dir = os.path.join(sys._MEIPASS, "templates") if _is_frozen else os.path.join(_base_dir, "templates")

# ── 加载配置 ──
_config_path = os.path.join(_base_dir, "config.json")
_config = {}
if os.path.exists(_config_path):
    with open(_config_path, "r", encoding="utf-8") as f:
        _config = json.load(f)

SMB_HOST = _config.get("smb_host", "192.168.1.115")
SMB_PORT = _config.get("smb_port", 445)
SMB_SHARE = _config.get("smb_share", "扫描共享文件")
SERVER_PORT = _config.get("server_port", 5088)
SMB_CONN_TTL = 30

app = Flask(__name__, template_folder=_template_dir)

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
    print(f"  配置: {_config_path}")
    print(f"  地址: {url}")
    print(f"  共享: \\\\{SMB_HOST}\\{SMB_SHARE}")
    print(f"  ⚠ 仅监听 127.0.0.1，仅本机可访问")
    webbrowser.open(url)
    app.run(host="127.0.0.1", port=SERVER_PORT, debug=False)
