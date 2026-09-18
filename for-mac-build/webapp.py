"""Flask 应用工厂：所有 HTTP 路由集中在这里。

公开版（app.py）和内部版（app_internal.py）都调用 create_app()，
这样同一份路由只维护一遍 —— 之前是两份代码各改一次，很容易漏。
"""
import os
import sys

from flask import Flask, jsonify, render_template, send_file

from smb_client import SMBClient, file_mime


def resource_path(*parts):
    """取资源目录。

    PyInstaller 打包后资源被解到 sys._MEIPASS；源码运行时就是本文件所在目录。
    """
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


def _error_text(exc):
    """把异常整理成给前端看的一行文字"""
    return "%s: %s" % (type(exc).__name__, exc)


def create_app(config, mode="browser"):
    """建立 Flask 应用。

    config: SMBConfig 实例
    mode:   'browser' | 'desktop' —— 会通过 /api/config 告诉前端，
            前端据此决定预览/下载走哪条路径（桌面模式不能用 window.open，
            那会被 pywebview 转成系统浏览器或直接顶掉当前窗口）。
    """
    app = Flask(__name__, template_folder=resource_path("templates"))
    client = SMBClient(config)

    # 挂在 app 上，便于桌面壳在窗口关闭时取出来关闭 SMB 连接
    app.config["SMB_CLIENT"] = client
    app.config["APP_MODE"] = mode

    # ── 页面 ──

    @app.route("/")
    def index():
        return render_template("index.html")

    # ── API ──

    @app.route("/api/config")
    def api_config():
        return jsonify({
            "smb_host": config.host,
            "smb_share": config.share,
            "mode": mode,
        })

    @app.route("/api/health")
    def api_health():
        """真实的 SMB 连通状态，供页面顶部状态灯使用。"""
        result = client.health_check()
        result["smb_host"] = config.host
        result["share"] = config.share
        result["mode"] = mode
        # 固定返回 200：连通失败是业务结果而不是 HTTP 错误，
        # 这样前端不用区分 fetch 异常和业务失败，判断 ok 字段即可。
        return jsonify(result)

    @app.route("/api/files")
    def api_files():
        try:
            return jsonify({"success": True, "files": client.list_files()})
        except Exception as exc:
            return jsonify({"success": False, "error": _error_text(exc)})

    @app.route("/api/download/<filename>")
    def api_download(filename):
        return _serve_file(client, filename, as_attachment=True)

    @app.route("/api/preview/<filename>")
    def api_preview(filename):
        return _serve_file(client, filename, as_attachment=False)

    return app


def _serve_file(client, filename, as_attachment):
    """从 SMB 读文件并按扩展名给出正确的 MIME。

    PDF 与图片都是 inline 返回，这样子才能在内嵌 iframe / img 里预览；
    只有 download 走 attachment 触发另存。
    """
    try:
        buf = client.retrieve_file(filename)
        return send_file(
            buf,
            mimetype=file_mime(filename),
            as_attachment=as_attachment,
            download_name=filename if as_attachment else None,
        )
    except Exception as exc:
        return jsonify({"success": False, "error": _error_text(exc)}), 500
