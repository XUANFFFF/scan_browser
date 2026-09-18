#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建产物校验（GitHub Actions 里构建完 .app 之后跑）。

设计原则
--------
1. **绝不连接任何 SMB**。GitHub 托管的 macOS runner 访问不到公司内网
   （192.168.1.115），所以这里只碰「不依赖网络」的接口：
   `GET /`（渲染模板）与 `GET /api/config`（读内存里的配置）。
   `/api/health`、`/api/files` 一律不调 —— 它们会真的去连 SMB。
2. **只做静态 + 启动级校验**，不做端到端功能测试。CI 只要能证明
   「程序起得来、页面回得来、资源都在 bundle 里」就够了。
3. **桌面壳（pywebview）的验证靠启动探针完成**：launcher 在桌面模式下
   是先 `import webview`、再 `start_server()` 的，所以「HTTP 服务能起来」
   就等价于「pywebview / PyObjC 已成功加载」。GUI 窗口本身在 CI 里可能
   开不出来（headless 限制），这不算失败。
4. 任何一条硬校验失败都以非 0 退出；不确定的情况只报警告，不假装通过。

用法
----
    # macOS bundle（CI 主用法）
    python verify_macos_bundle.py --app "dist/扫描文件浏览器.app" --expect-arch arm64

    # 纯 onefile 可执行文件（本地 Windows 冒烟，只跑静态 + 探针）
    python verify_macos_bundle.py --app "dist/扫描文件浏览器.exe" --skip-probe
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

# ── 与打包配置一致的常量 ──────────────────────────────────────────────
# 这些值必须和 for-mac-build/scan-browser-mac.spec 保持一致，
# spec 里改了名/改了 bundle id，这里也要跟着改。
APP_NAME = "扫描文件浏览器"
BUNDLE_ID = "com.scanbrowser.app"
LOG_NAME = "扫描文件浏览器.log"

# 页面必须命中的标记：能命中就说明 index.html 真的被打进了产物。
# 一旦模板没被打包，Flask 会抛 TemplateNotFound，这里必然失败。
PAGE_MARKERS = [
    "<title>扫描文件浏览器</title>",
    'id="viewer"',
]

# onefile 归档里必须存在的资源（用 PyInstaller 的归档读接口列举）
ARCHIVE_MUST_HAVE = [
    "templates/index.html",
]

PROBE_PORTS = {"browser": 5098, "desktop": 5099}


# ── 输出小工具 ────────────────────────────────────────────────────────

class Report:
    """收集每一条校验结果，最后统一决定退出码。"""

    def __init__(self):
        self.failures = []
        self.warnings = []
        self.facts = {}          # 给 Job Summary 用的键值对
        self.lines = []          # 给 Job Summary 用的 markdown 行

    def ok(self, cond, msg, detail=""):
        flag = "✅" if cond else "❌"
        line = "  %s %s" % (flag, msg)
        if detail:
            line += "  →  %s" % detail
        print(line, flush=True)
        if not cond:
            self.failures.append(msg)
        return bool(cond)

    def warn(self, msg, detail=""):
        line = "  ⚠️ %s" % msg
        if detail:
            line += "  →  %s" % detail
        print(line, flush=True)
        self.warnings.append(msg)

    def info(self, msg):
        print("  ·  %s" % msg, flush=True)

    def fact(self, key, value):
        self.facts[key] = value

    def md(self, line):
        self.lines.append(line)


def _human(n):
    """字节数转人读格式。"""
    if n is None:
        return "—"
    f = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if f < 1024 or unit == "GB":
            return "%.1f %s" % (f, unit) if unit != "B" else "%d B" % int(f)
        f /= 1024


def _tail(path, n=40):
    """读文件末尾若干行，用来在失败时把 app 自己的日志打出来。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return "".join(fh.readlines()[-n:])
    except Exception as exc:
        return "(读取失败：%s)" % exc


# ── 1) bundle 结构 / Info.plist ───────────────────────────────────────

def check_bundle(app_dir, r):
    print("\n== bundle 结构 ==", flush=True)

    r.md("### bundle 结构")
    r.ok(os.path.isdir(app_dir), "%s 存在" % app_dir)
    if not os.path.isdir(app_dir):
        return None

    exe = os.path.join(app_dir, "Contents", "MacOS", APP_NAME)
    exists = os.path.isfile(exe)
    r.md("- 主程序 `Contents/MacOS/%s`：%s" % (APP_NAME, "存在" if exists else "**缺失**"))
    r.ok(exists, "Contents/MacOS/%s 存在" % APP_NAME)
    if not exists:
        return None

    size = os.path.getsize(exe)
    r.ok(size > 0, "主程序非空", _human(size))
    r.fact("主程序大小", _human(size))

    # macOS 上没有可执行位就双击不了，这是必须保住的属性
    executable = os.access(exe, os.X_OK)
    if os.name == "posix":
        r.md("- 主程序可执行位：%s" % ("是" if executable else "**否**"))
        r.ok(executable, "主程序带可执行位 (X_OK)")
    else:
        r.warn("非 POSIX 平台，跳过可执行位检查")

    # Info.plist：CFBundleName / CFBundleDisplayName / bundle_identifier 必须保留
    print("\n== Info.plist ==", flush=True)
    r.md("### Info.plist")
    plist_path = os.path.join(app_dir, "Contents", "Info.plist")
    if not r.ok(os.path.isfile(plist_path), "Contents/Info.plist 存在"):
        return exe

    try:
        with open(plist_path, "rb") as fh:
            info = plistlib.load(fh)
    except Exception as exc:
        r.ok(False, "Info.plist 可解析", "%s: %s" % (type(exc).__name__, exc))
        return exe

    interesting = ("CFBundleName", "CFBundleDisplayName", "CFBundleIdentifier",
                   "CFBundleExecutable", "CFBundleIconFile",
                   "CFBundleShortVersionString")
    for key in interesting:
        r.info("%-26s %r" % (key, info.get(key)))
    r.md("| 键 | 值 |")
    r.md("|---|---|")
    for key in interesting:
        r.md("| `%s` | `%r` |" % (key, info.get(key)))

    r.ok(info.get("CFBundleName") == APP_NAME, "CFBundleName == %s" % APP_NAME)
    r.ok(info.get("CFBundleDisplayName") == APP_NAME,
         "CFBundleDisplayName == %s" % APP_NAME)
    r.ok(info.get("CFBundleIdentifier") == BUNDLE_ID,
         "CFBundleIdentifier == %s" % BUNDLE_ID)
    r.ok(bool(info.get("CFBundleIconFile")), "CFBundleIconFile 已声明")
    r.fact("CFBundleVersion", info.get("CFBundleShortVersionString"))

    return exe


# ── 2) 图标资源 ───────────────────────────────────────────────────────

def check_icon(app_dir, r):
    print("\n== 图标资源 ==", flush=True)
    r.md("### 图标资源")

    found = []
    for base, _dirs, files in os.walk(app_dir):
        for fn in files:
            if fn.lower().endswith(".icns"):
                p = os.path.join(base, fn)
                found.append((os.path.relpath(p, app_dir), os.path.getsize(p)))

    for rel, size in found:
        r.info("%s  (%s)" % (rel, _human(size)))
    for rel, size in found:
        r.md("- `%s` — %s" % (rel, _human(size)))

    if r.ok(bool(found), "bundle 内含 .icns 图标资源"):
        r.fact("图标", "%d 个 .icns（最大 %s）"
               % (len(found), _human(max(s for _, s in found))))


# ── 3) onefile 归档里有没有把资源打进去 ────────────────────────────────

def check_archive(exe, r):
    """用 PyInstaller 的归档读接口列举 TOC，确认模板等资源真的在包里。

    onefile 模式下 datass 会被压缩后塞进可执行文件，所以不能在文件里
    直接搜字符串（内容是 zlib 压过的），必须走归档接口列举。
    """
    print("\n== 内嵌资源（onefile 归档）==", flush=True)
    r.md("### 内嵌资源")

    try:
        from PyInstaller.archive.readers import CArchiveReader
    except Exception as exc:
        r.warn("读不到 PyInstaller 归档接口，跳过静态资源检查（启动探针仍会验证）",
               "%s: %s" % (type(exc).__name__, exc))
        return

    try:
        reader = CArchiveReader(exe)
        # Windows 上路径分隔符是反斜杠，统一成正斜杠再比
        names = [n.replace("\\", "/") for n in reader.toc.keys()]
    except Exception as exc:
        r.warn("归档列举失败，跳过静态资源检查",
               "%s: %s" % (type(exc).__name__, exc))
        return

    r.info("归档条目总数：%d" % len(names))
    r.md("- 归档条目总数：%d" % len(names))

    for want in ARCHIVE_MUST_HAVE:
        r.ok(want in names, "归档内含 %s" % want)

    # 顺带确认关键依赖模块确实进了包（缺了启动就会崩）
    for mod in ("webview", "webview/platforms/cocoa", "flask", "smb"):
        hit = any(n == mod + ".py" or n.startswith(mod + "/") for n in names)
        if hit:
            r.info("依赖模块 %-26s 已打包" % mod)
        else:
            # 纯 Python 模块可能在嵌套的 PYZ 里，这里只作提示不下结论
            r.info("依赖模块 %-26s 未在顶层 TOC 出现（可能在 PYZ 内，属正常）" % mod)


# ── 4) CPU 架构 ───────────────────────────────────────────────────────

def check_arch(exe, expect, r):
    print("\n== 产物架构 ==", flush=True)
    r.md("### 产物架构")

    r.info("runner 本机架构：%s" % _uname_m())
    r.md("- runner 本机架构：`%s`" % _uname_m())

    actual = None
    if shutil.which("lipo"):
        try:
            out = subprocess.run(["lipo", "-archs", exe], capture_output=True,
                                 text=True, timeout=60)
            actual = (out.stdout or out.stderr).strip()
            r.info("lipo -archs：%s" % actual)
        except Exception as exc:
            r.warn("lipo 执行失败", str(exc))
    else:
        r.warn("找不到 lipo，跳过架构判定")

    if shutil.which("file"):
        try:
            out = subprocess.run(["file", "-b", exe], capture_output=True,
                                 text=True, timeout=60)
            r.info("file：%s" % (out.stdout or "").strip())
            r.md("- `file`：`%s`" % (out.stdout or "").strip())
        except Exception as exc:
            r.warn("file 执行失败", str(exc))

    if actual:
        r.fact("产物架构", actual)
        r.md("- `lipo -archs`：`%s`" % actual)
        if expect:
            r.ok(expect in actual.split(),
                 "产物架构符合预期（%s）" % expect,
                 "实际 %s" % actual)


def _uname_m():
    try:
        return os.uname().machine
    except AttributeError:
        return os.environ.get("PROCESSOR_ARCHITECTURE", "unknown")


# ── 5) 启动探针 ───────────────────────────────────────────────────────

def _no_proxy_opener():
    """永远绕开代理：runner 上可能设了 http_proxy，会让 127.0.0.1 走代理。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _terminate(proc, grace=6.0):
    """结束探针进程。

    PyInstaller 的 onefile 无论哪个平台都是「父进程 fork/派生出真正干活的
    子进程」的双进程模型：
      - POSIX：只 kill 父进程会留下孤儿子进程 → 用进程组整组结束
      - Windows：terminate 只杀父进程，子进程会变成孤儿（界面上表现为
        窗口关不掉）→ 用 taskkill /T 按进程树收拾
    """
    if proc.poll() is not None:
        return

    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=30)
        except Exception:
            pass
        try:
            proc.wait(timeout=grace)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        return

    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except Exception:
            try:
                proc.terminate() if sig == signal.SIGTERM else proc.kill()
            except Exception:
                pass
        try:
            proc.wait(timeout=grace)
            return
        except Exception:
            continue


def _find_log(exe):
    """找 app 自己写的日志（launcher._log_path 的几个候选位置）。"""
    candidates = [os.path.join(os.path.dirname(exe), LOG_NAME)]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(os.path.join(local, "ScanBrowser", LOG_NAME))
    candidates.append(os.path.join(tempfile.gettempdir(), LOG_NAME))
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def _discover_port_from_log(log_path, fallback):
    """端口被占用时 app 会回退到随机端口，从日志里解析出真正生效的地址。

    只认「127.0.0.1:<port>」这种明确写法 —— 日志里还有时间戳、文件大小、
    耗时等一堆数字，模糊匹配很容易抓错。
    """
    if not log_path:
        return []
    ports, seen = [], set()
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            found = re.findall(r"127\.0\.0\.1:(\d{2,5})", fh.read())
    except Exception:
        return []
    # 倒序：最后打印的地址最可能是最终生效的那个
    for token in reversed(found):
        p = int(token)
        if 1024 <= p <= 65535 and p != fallback and p not in seen:
            seen.add(p)
            ports.append(p)
    return ports


def _get(opener, port, path, timeout=4.0):
    url = "http://127.0.0.1:%d%s" % (port, path)
    with opener.open(url, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def probe(exe, mode, r, required=True, timeout=150.0):
    """启动冻结程序，轮询本地 HTTP，验证「起得来 + 页面回得来」。

    mode='browser' → 必需项：证明核心模块（flask/werkzeug/pysmb）都加载成功
    mode='desktop' → 参考项：能起来就说明 pywebview/PyObjC 也加载成功
    """
    print("\n== 启动探针（%s 模式）==" % mode, flush=True)
    port = PROBE_PORTS[mode]
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # 关掉自动开浏览器：browser 模式会 webbrowser.open()，CI 里没必要真开
    env["BROWSER"] = "true" if os.name == "posix" else "echo"
    env.pop("http_proxy", None)
    env.pop("https_proxy", None)
    env.pop("HTTP_PROXY", None)
    env.pop("HTTPS_PROXY", None)

    log_before = _find_log(exe)
    try:
        proc = subprocess.Popen(
            [exe, "--" + mode, "--port", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env, start_new_session=(os.name == "posix"),
        )
    except Exception as exc:
        r.ok(False, "启动 %s" % exe, "%s: %s" % (type(exc).__name__, exc))
        return False

    opener = _no_proxy_opener()
    deadline = time.time() + timeout
    status = None
    body = ""
    used_port = None
    died = None

    while time.time() < deadline:
        if proc.poll() is not None:
            died = proc.returncode
            break
        for p in [port] + _discover_port_from_log(_find_log(exe), port):
            try:
                status, body = _get(opener, p, "/")
                used_port = p
                break
            except Exception:
                continue
        if status is not None:
            break
        time.sleep(1.5)

    try:
        if status is None:
            detail = "进程已退出，exit=%s" % died if died is not None else "等待 %.0fs 未起来" % timeout
            if required:
                r.ok(False, "%s 模式启动并响应 HTTP" % mode, detail)
            else:
                r.warn("%s 模式未起来（CI 无 GUI 会话时属正常）" % mode, detail)
            log_path = _find_log(exe)
            if log_path:
                print("  ---- %s 末尾日志 ----" % log_path, flush=True)
                print(_tail(log_path), flush=True)
            return False

        r.ok(status == 200, "GET / 返回 200", "实际 %s（端口 %d）" % (status, used_port))
        r.info("页面大小：%s" % _human(len(body.encode("utf-8"))))

        for marker in PAGE_MARKERS:
            hit = marker in body
            r.ok(hit, "页面含标记 %s" % marker)

        # /api/config：只读内存配置，不会碰 SMB
        try:
            st2, body2 = _get(opener, used_port, "/api/config")
            cfg = json.loads(body2)
            r.ok(st2 == 200, "GET /api/config 返回 200")
            r.info("当前模式：%s，共享：\\\\%s\\%s"
                   % (cfg.get("mode"), cfg.get("smb_host"), cfg.get("smb_share")))
            r.fact("%s 模式" % mode, str(cfg.get("mode")))
            r.md("- %s 模式探针：HTTP 200，页面 %s，`/api/config` 模式 = `%s`"
                 % (mode, _human(len(body.encode("utf-8"))), cfg.get("mode")))
        except Exception as exc:
            r.warn("GET /api/config 失败", "%s: %s" % (type(exc).__name__, exc))

        return True
    finally:
        _terminate(proc)
        # 顺便确认关掉后不留进程/端口
        time.sleep(0.5)
        if proc.poll() is None:
            r.warn("%s 模式探针进程未完全退出" % mode)


# ── 入口 ──────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="校验 macOS 构建产物")
    ap.add_argument("--app", required=True,
                    help=".app 目录，或（本地冒烟时）纯可执行文件")
    ap.add_argument("--expect-arch", default=None,
                    choices=["arm64", "x86_64"],
                    help="期望的 CPU 架构；不符即失败")
    ap.add_argument("--skip-probe", action="store_true",
                    help="跳过启动探针，只做静态校验")
    ap.add_argument("--summary-out", default=None,
                    help="把 markdown 报告追加写入该文件（给 Job Summary 用）")
    args = ap.parse_args()

    # Windows 控制台默认 GBK，中文/emoji 会抛 UnicodeEncodeError
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    r = Report()
    target = os.path.abspath(args.app)
    is_bundle = target.endswith(".app") and os.path.isdir(target)

    print("校验目标：%s" % target, flush=True)
    print("平台：%s (%s)" % (sys.platform, _uname_m()), flush=True)
    print("bundle 形态：%s" % ("macOS .app" if is_bundle else "纯可执行文件"), flush=True)
    r.fact("产物形态", "macOS .app" if is_bundle else "纯可执行文件")
    r.md("### 基本信息")
    r.md("- 目标：`%s`" % os.path.basename(target))
    r.md("- 形态：%s" % ("macOS `.app`" if is_bundle else "纯可执行文件"))
    r.md("- runner 架构：`%s`" % _uname_m())

    if is_bundle:
        exe = check_bundle(target, r)
        if exe:
            check_icon(target, r)
    else:
        exe = target
        r.ok(os.path.isfile(exe), "%s 存在" % exe)
        if os.path.isfile(exe):
            r.fact("主程序大小", _human(os.path.getsize(exe)))

    if exe and os.path.isfile(exe):
        check_archive(exe, r)
        check_arch(exe, args.expect_arch, r)

        if args.skip_probe:
            r.info("按参数要求跳过启动探针")
        else:
            # 桌面壳探针在临时副本里跑：app 会在同目录写日志，
            # 直接跑会污染原始 bundle（多一个文件会破坏签名封条）
            tmp_dir = tempfile.mkdtemp(prefix="verify-probe-")
            try:
                probe_exe = exe
                if is_bundle:
                    copy = os.path.join(tmp_dir, os.path.basename(target))
                    _copy_bundle(target, copy)
                    probe_exe = os.path.join(copy, "Contents", "MacOS", APP_NAME)
                # 浏览器模式：必需项，证明核心模块与模板都在
                probe(probe_exe, "browser", r, required=True)
                # 桌面模式：参考项，能起来即说明 pywebview/PyObjC 加载成功
                probe(probe_exe, "desktop", r, required=False)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── 结论 ──
    print("\n" + "=" * 66, flush=True)
    if r.failures:
        print("❌ 校验未通过，失败 %d 项：" % len(r.failures), flush=True)
        for f in r.failures:
            print("   - %s" % f, flush=True)
    else:
        print("✅ 全部校验通过", flush=True)
    if r.warnings:
        print("⚠️  警告 %d 条：" % len(r.warnings), flush=True)
        for w in r.warnings:
            print("   - %s" % w, flush=True)
    print("=" * 66, flush=True)

    if args.summary_out:
        try:
            with open(args.summary_out, "a", encoding="utf-8") as fh:
                fh.write("\n".join(r.lines) + "\n")
                fh.write("\n**结论：%s**\n"
                         % ("❌ 校验未通过" if r.failures else "✅ 全部校验通过"))
                if r.facts:
                    fh.write("\n| 项 | 值 |\n|---|---|\n")
                    for k, v in r.facts.items():
                        fh.write("| %s | %s |\n" % (k, v))
        except Exception as exc:
            print("写 summary 失败：%s" % exc, flush=True)

    return 1 if r.failures else 0


def _copy_bundle(src, dst):
    """复制 .app。macOS 上用 ditto（能保住元数据/签名），其它平台退回 shutil。"""
    if os.name == "posix" and shutil.which("ditto"):
        subprocess.run(["ditto", src, dst], check=True, timeout=300)
    else:
        shutil.copytree(src, dst, symlinks=True)
    return dst


if __name__ == "__main__":
    raise SystemExit(main())
