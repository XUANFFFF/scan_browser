"""扫描文件浏览器 —— 核心业务逻辑单元测试。

零外部依赖（标准库 unittest + Flask test_client + 内存假 SMB），
不连接真实共享，Windows / macOS / CI 里都能直接跑：

    python -m unittest discover -s tests -v

覆盖面：
- parse_date()：时间戳命名 / -000N 序号命名 / 无法解析的命名
- 文件类型映射（file_ext / file_mime / file_type）
- 递归列目录：深度限制、跳过系统噪音文件、子目录 path/dir 字段
- 路径安全校验 sanitize_share_path()：穿越 / 绝对路径 / 反斜杠 / 空段
- HTTP 路由：预览 / 下载（根目录 + 子目录）、非法路径 400、下载名为 basename
- 前端「另存为」用完整 path 的源码级回归（防止再退回从标题取值）
"""

import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import smb_client as sc                      # noqa: E402
import webapp                                # noqa: E402
from smb_client import (                     # noqa: E402
    InvalidSharePath,
    file_ext,
    file_mime,
    file_type,
    parse_date,
    sanitize_share_path,
)


# ── 内存假 SMB ──────────────────────────────────────────────

class _Entry:
    """模拟 pysmb 的 SharedFile 接口里我们用到的字段。"""

    def __init__(self, name, isdir, size=0):
        self.filename = name
        self.isDirectory = isdir
        self.file_size = size
        self.create_time = self.last_write_time = 0


class FakeConn:
    """listPath(path) 返回该层直接子项；retrieveFile 按内存树返回字节。"""

    def __init__(self, tree):
        self._tree = tree

    def listPath(self, share, path):
        prefix = path.strip("/")
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        seen, out = set(), []
        for rel, val in sorted(self._tree.items()):
            if not rel.startswith(prefix):
                continue
            rest = rel[len(prefix):]
            if not rest:
                continue
            if "/" in rest:
                sub = rest.split("/", 1)[0]
                if sub not in seen:
                    seen.add(sub)
                    out.append(_Entry(sub, True))
            else:
                out.append(_Entry(rest, False, len(val) if val != "DIR" else 0))
        return out

    def retrieveFile(self, share, path, buf):
        rel = path.strip("/")
        if rel not in self._tree or self._tree[rel] == "DIR":
            raise RuntimeError("Unable to open file: %s" % rel)
        buf.write(self._tree[rel])
        buf.seek(0)

    def close(self):
        pass


TREE = {
    "20260918/a-0001.jpg": b"jpg-subdir",
    "20260918/deep/b-0001.tif": b"tif-deep",
    "root.pdf": b"%PDF-root",
    "same.jpg": b"root-same",
    # 噪音：应被 list_files 跳过
    "Thumbs.db": b"noise",
    ".DS_Store": b"noise",
    "._meta.jpg": b"noise",
}


class FakeClient(sc.SMBClient):
    """绕过真实网络，直接喂内存树。"""

    def __init__(self, config):
        self.config = config

    def connect(self):
        return FakeConn(TREE)

    def health_check(self):
        return {"ok": True, "file_count": 3, "latency_ms": 1}


def make_client(mode="browser"):
    """构造挂了假 SMB 的 Flask 测试应用。"""
    old = webapp.SMBClient
    webapp.SMBClient = FakeClient
    try:
        app = webapp.create_app(sc.SMBConfig("fhost", "fshare"), mode)
    finally:
        webapp.SMBClient = old
    return app.test_client()


# ── 基础工具函数 ────────────────────────────────────────────

class TestParseDate(unittest.TestCase):
    def test_timestamp_name(self):
        self.assertEqual(parse_date("20260918115533.jpg"), "2026-09-18 11:55:33")

    def test_timestamp_with_seq(self):
        # 扫描仪一次扫描多页时是 YYYYMMDDHHMMSS-000N 命名
        self.assertEqual(parse_date("20260918094501-0002.jpg"),
                         "2026-09-18 09:45:01")

    def test_undecodable_name(self):
        self.assertEqual(parse_date("扫描件-重要合同.pdf"), "—")

    def test_wrong_length_digits(self):
        self.assertEqual(parse_date("20260918.jpg"), "—")


class TestTypeMaps(unittest.TestCase):
    def test_file_ext_lowercases(self):
        self.assertEqual(file_ext("A.JPG"), ".jpg")
        self.assertEqual(file_ext("noext"), "")

    def test_mime(self):
        self.assertEqual(file_mime("a.pdf"), "application/pdf")
        self.assertEqual(file_mime("a.jpeg"), "image/jpeg")
        self.assertEqual(file_mime("a.tif"), "image/tiff")
        self.assertEqual(file_mime("a.xyz"), "application/octet-stream")

    def test_type(self):
        self.assertEqual(file_type("a.pdf"), "pdf")
        self.assertEqual(file_type("a.png"), "image")
        self.assertEqual(file_type("a.tiff"), "tiff")


# ── 路径安全 ────────────────────────────────────────────────

class TestSanitizeSharePath(unittest.TestCase):
    def test_accepts_normal_paths(self):
        for p in ("a.jpg",
                  "20260918094501/20260918094501-0001.jpg",
                  "子 目录/照 片.PNG",
                  "deep/nested/dir/file.tif"):
            self.assertEqual(sanitize_share_path(p), p)

    def test_rejects_traversal(self):
        for p in ("../x.jpg", "a/../b.jpg", "..", "a/../../b.jpg"):
            with self.assertRaises(InvalidSharePath):
                sanitize_share_path(p)

    def test_rejects_absolute_and_backslash(self):
        for p in ("/a.jpg", "a/", "\\", "a\\b.jpg", "C:/x.jpg"):
            with self.assertRaises(InvalidSharePath):
                sanitize_share_path(p)

    def test_rejects_empty_and_dot_segments(self):
        for p in ("", "   ", "a//b.jpg", "a/./b.jpg", ".", "/"):
            with self.assertRaises(InvalidSharePath):
                sanitize_share_path(p)

    def test_rejects_control_chars_and_colon(self):
        for p in ("a\x00.jpg", "a\n.jpg", "a.jpg:stream", "a:b/c.jpg"):
            with self.assertRaises(InvalidSharePath):
                sanitize_share_path(p)

    def test_rejects_hidden_segments(self):
        # 顺带排除 ._* 之类的隐藏段（与 list_files 的跳过规则一致）
        with self.assertRaises(InvalidSharePath):
            sanitize_share_path(".hidden/a.jpg")

    def test_rejects_non_string(self):
        with self.assertRaises(InvalidSharePath):
            sanitize_share_path(None)


# ── 递归列目录 ──────────────────────────────────────────────

class TestListFiles(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient(sc.SMBConfig("fhost", "fshare"))

    def _paths(self):
        return sorted(f["path"] for f in self.client.list_files())

    def test_recurses_into_subdirectories(self):
        paths = self._paths()
        self.assertIn("20260918/a-0001.jpg", paths)
        self.assertIn("20260918/deep/b-0001.tif", paths)

    def test_skips_noise_files(self):
        for noise in ("Thumbs.db", ".DS_Store", "._meta.jpg"):
            self.assertNotIn(noise, self._paths())

    def test_records_carry_path_and_dir(self):
        rec = next(f for f in self.client.list_files()
                   if f["path"] == "20260918/a-0001.jpg")
        self.assertEqual(rec["dir"], "20260918")
        self.assertEqual(rec["name"], "a-0001.jpg")
        self.assertEqual(rec["type"], "image")

    def test_deep_layer_within_max_depth(self):
        # TREE 里 deep 在第 2 层（< MAX_DEPTH=3），必须被列出
        self.assertIn("20260918/deep/b-0001.tif", self._paths())

    def test_retrieve_file_supports_subpath(self):
        buf = self.client.retrieve_file("20260918/deep/b-0001.tif")
        self.assertEqual(buf.read(), b"tif-deep")


# ── HTTP 路由（预览 / 下载 / 400）───────────────────────────

class TestHTTPRoutes(unittest.TestCase):
    def setUp(self):
        self.c = make_client()

    def test_files_endpoint(self):
        r = self.c.get("/api/files")
        self.assertEqual(r.status_code, 200)
        d = json.loads(r.get_data(as_text=True))
        self.assertTrue(d["success"])
        paths = sorted(f["path"] for f in d["files"])
        self.assertIn("20260918/a-0001.jpg", paths)

    def test_config_endpoint(self):
        d = json.loads(self.c.get("/api/config").get_data(as_text=True))
        self.assertEqual(d["mode"], "browser")
        self.assertEqual(d["smb_host"], "fhost")

    def test_preview_root_and_subdir(self):
        self.assertEqual(self.c.get("/api/preview/root.pdf").status_code, 200)
        r = self.c.get("/api/preview/20260918/a-0001.jpg")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, b"jpg-subdir")

    def test_download_subdir_uses_basename(self):
        r = self.c.get("/api/download/20260918/deep/b-0001.tif")
        self.assertEqual(r.status_code, 200)
        cd = r.headers.get("Content-Disposition", "")
        self.assertIn("attachment", cd)
        self.assertIn("b-0001.tif", cd)
        # 子目录不能出现在下载文件名里
        self.assertNotIn("deep", cd.split("filename")[-1].replace("b-0001.tif", ""))

    def test_traversal_attempts_return_400(self):
        for url in ("/api/download/../../etc/passwd",
                    "/api/download/%2e%2e/%2e%2e/etc/passwd",
                    "/api/download/20260918/../../x",
                    "/api/preview/a%5Cb.jpg",          # 反斜杠
                    "/api/download/a.jpg%3Astream",    # NTFS 数据流
                    "/api/download/a//b.jpg",          # 空段
                    "/api/download/a/%2e/b.jpg"):      # 点段
            with self.subTest(url=url):
                self.assertEqual(self.c.get(url).status_code, 400)

    def test_preview_and_download_share_validation(self):
        # 同一个非法路径，预览与下载都要 400（共用同一校验函数）
        for route in ("preview", "download"):
            r = self.c.get("/api/%s/../secret" % route)
            self.assertEqual(r.status_code, 400, route)


# ── 前端回归：另存为必须用完整 path ─────────────────────────

class TestViewerSaveAsRegression(unittest.TestCase):
    """「另存为」曾从 viewerTitle 文本反推文件名，子目录文件会请求错路径。

    前端无 JS 运行时，这里做源码级断言：关键行为存在、错误模式不存在。
    """

    @classmethod
    def setUpClass(cls):
        tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "templates", "index.html")
        with open(tpl, encoding="utf-8") as fh:
            cls.html = fh.read()

    def test_saves_viewer_path_on_open_and_clears_on_close(self):
        self.assertIn("_viewerPath = f.path", self.html)
        self.assertIn("_viewerPath = null", self.html)

    def test_save_as_uses_path_not_title(self):
        # 事件处理器里只允许出现 _viewerPath，不允许再从标题取值
        idx = self.html.index('getElementById("viewerSaveAs")')
        handler = self.html[idx:idx + 400]
        self.assertIn("doDownload(_viewerPath)", handler)
        self.assertNotIn("viewerTitle", handler)

    def test_download_attr_is_basename(self):
        # <a download> 的值必须是 basename（浏览器会清洗路径分隔符）
        self.assertIn('a.download = fn.split("/").pop()', self.html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
