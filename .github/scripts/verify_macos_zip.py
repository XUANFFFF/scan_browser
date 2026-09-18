#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对「最终分发 ZIP」做闭环验证（CI 里在打包之后、上传 Artifact 之前跑）。

为什么单靠 verify_macos_bundle.py 不够
--------------------------------------
verify_macos_bundle.py 验的是 PyInstaller 刚生成的 `dist/*.app` —— 那是
「我们以为要发的东西」。用户实际下载到的是**我们自己打的 ZIP**，中间还隔着
「复制到暂存目录 → 写 ZIP」这一整段。此前 `ditto -c -k` 不设 ZIP 的 UTF-8
标志位导致中文名乱码，就是典型的「生成物没问题、分发物有问题」：
只有把 ZIP 解开、在解出来的东西上再验一遍，才抓得到这类缺口。

这个脚本做什么
--------------
1. **解压前**，先断言 ZIP *记录* 的内容正确（不依赖任何解压工具的行为）：
   - 中文路径 `.../扫描文件浏览器.app` 存在；
   - 非 ASCII 文件名都设了 UTF-8 标志位（general purpose bit 11）——
     防的正是上面那个乱码坑；
   - 主程序与 `启动.command` 在 ZIP 里**记录了**可执行位。
2. 用 Python `zipfile` 按 `external_attr` **还原 Unix 权限位**解压到临时目录
   （标准库自带的 `extract()` 不还原权限，自己来才不会误判）。
3. 在解压出来的文件系统上再确认一次：`.app` 存在、主程序与 `启动.command`
   仍然可执行。
4. `codesign --verify --deep --strict` 校验解压后 `.app` 的签名。
   PyInstaller 6.x 在 `codesign_identity=None` 时会做 **ad-hoc 签名**
   （bundle 里能看到 `Contents/_CodeSignature/CodeResources`），签名信息嵌在
   Mach-O 的 `LC_CODE_SIGNATURE` 里、与文件系统权限无关，所以解压后再验应当
   通过。**若失败，把 codesign 的输出与签名详情原样打出来，不做静默降级** ——
   这只可能是分发链路上真出了问题。
5. 复用 `verify_macos_bundle.py` 对「解压后的 `.app`」再跑一遍
   （结构 / Info.plist / 图标 / 内嵌资源 / 架构 / 启动探针）。
   探针规则不变：**browser 必需、desktop 可选**。

全部通过才返回 0，工作流因此才允许 upload-artifact。

用法
----
    # CI 用法
    python verify_macos_zip.py \
        --zip "扫描文件浏览器-macOS-arm64.zip" \
        --dest "$RUNNER_TEMP/roundtrip" \
        --expect-arch arm64 \
        --summary-out "$RUNNER_TEMP/verify-zip-summary.md"

    # 本地只测 ZIP 层逻辑（跳过探针与嵌套校验）
    python verify_macos_zip.py --zip x.zip --dest /tmp/rt --skip-probe
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile

# 与打包配置一致（和 verify_macos_bundle.py 保持同名常量）
APP_NAME = "扫描文件浏览器"
BUNDLE_DIRNAME = APP_NAME + ".app"
LAUNCH_SCRIPT = "启动.command"
README_FILE = "使用说明.txt"

# .app 内部关键路径（相对 bundle 根）
EXE_REL = "Contents/MacOS/" + APP_NAME
PLIST_REL = "Contents/Info.plist"
CODESIGN_REL = "Contents/_CodeSignature/CodeResources"

# 复用 verify_macos_bundle.py 的 Report / 工具函数，避免两套报告逻辑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_macos_bundle as vb  # noqa: E402


# ── 1) 解压前的 ZIP 记录检查 ──────────────────────────────────────────

def check_zip_records(zip_path, root, r):
    """只看 ZIP 里**写了什么**，与解压工具无关。

    这一步能在不解压的情况下抓到最典型的分发问题：中文名没设 UTF-8 标志位、
    可执行位没被记录。
    """
    print("\n== ZIP 记录检查（解压前，不依赖解压工具）==", flush=True)
    r.md("### ZIP 记录检查（解压前）")

    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()

    # 目录条目可能带尾斜杠，也可能压根没有目录条目；两种都认
    def norm(arc):
        return arc.replace("\\", "/")

    names = [norm(i.filename) for i in infos]
    by_name = {norm(i.filename): i for i in infos}

    def has_dir(rel):
        """rel 本身是条目，或存在以 rel + '/' 开头的条目，都算这个目录存在。"""
        return rel in by_name or any(n.startswith(rel + "/") for n in names)

    app_dir = "%s/%s" % (root, BUNDLE_DIRNAME)
    r.info("ZIP 顶级目录：%s（共 %d 个条目）" % (root, len(infos)))
    r.md("- ZIP 顶级目录：`%s`，共 %d 个条目" % (root, len(infos)))

    r.ok(has_dir(app_dir), "ZIP 内含中文路径 %s" % app_dir)
    r.ok(has_dir("%s/%s" % (app_dir, os.path.dirname(EXE_REL))),
         "ZIP 内 %s/Contents/MacOS 目录存在" % app_dir)
    r.ok(has_dir("%s/%s" % (app_dir, os.path.dirname(PLIST_REL))),
         "ZIP 内 %s/Contents 目录存在" % app_dir)

    # ── 中文名乱码坑：非 ASCII 的文件名必须设 UTF-8 标志位（bit 11）──
    # 没设的话，Info-ZIP 会按规范默认的 cp437 解码 → 中文全乱。
    bad_flag = [n for i, n in zip(infos, names)
                if not (i.flag_bits & 0x800) and any(ord(c) > 127 for c in n)]
    r.ok(not bad_flag, "非 ASCII 文件名都设置了 UTF-8 标志位 (bit 11)",
         "" if not bad_flag else "缺标志位：%s" % bad_flag[:5])

    # ── 关键条目 + 可执行位 ──
    def check_entry(rel, want_exec, label):
        key = "%s/%s" % (root, rel)
        zi = by_name.get(key)
        if not r.ok(zi is not None, "ZIP 内含 %s" % label, key):
            return
        mode = (zi.external_attr >> 16) & 0o7777
        if want_exec:
            r.ok(bool(mode & 0o111),
                 "%s 在 ZIP 里记录了可执行位" % label,
                 "mode=%s" % oct(mode))
        else:
            r.info("%s  mode=%s" % (label, oct(mode)))

    check_entry("%s.app/%s" % (APP_NAME, EXE_REL), True,
                "主程序 Contents/MacOS/%s" % APP_NAME)
    check_entry(LAUNCH_SCRIPT, True, LAUNCH_SCRIPT)
    check_entry("%s.app/%s" % (APP_NAME, PLIST_REL), False, "Contents/Info.plist")
    check_entry("%s.app/%s" % (APP_NAME, CODESIGN_REL), False,
                "Contents/_CodeSignature/CodeResources")
    # 使用说明是可选的（早期包没有），只提示不判错
    if "%s/%s" % (root, README_FILE) not in by_name:
        r.info("（未包含 %s，可选）" % README_FILE)


# ── 2) 解压（按 external_attr 还原权限位）─────────────────────────────

def extract_zip(zip_path, dest, r):
    """自己解压：标准库的 `extract()` 不还原 Unix 权限位与符号链接。"""
    print("\n== 解压 ZIP ==", flush=True)
    r.md("### 解压")
    os.makedirs(dest, exist_ok=True)

    count = 0
    with zipfile.ZipFile(zip_path) as z:
        for zi in z.infolist():
            arc = zi.filename.replace("\\", "/")
            rel = arc.replace("/", os.sep).rstrip(os.sep)
            if not rel:
                continue
            target = os.path.join(dest, rel)

            if arc.endswith("/"):
                os.makedirs(target, exist_ok=True)
                continue

            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)

            mode = zi.external_attr >> 16
            if stat.S_ISLNK(mode):                     # 符号链接：还原成链接
                linkto = z.read(zi).decode("utf-8", "replace")
                if os.path.lexists(target):
                    os.remove(target)
                os.symlink(linkto, target)
                continue

            with z.open(zi) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            if mode:
                try:
                    os.chmod(target, mode & 0o7777)
                except OSError as exc:
                    r.warn("还原权限失败：%s" % arc, str(exc))
            count += 1

    r.info("已解压 %d 个文件到 %s" % (count, dest))
    r.md("- 解压 %d 个文件到 `%s`" % (count, dest))
    return count


# ── 3) 解压后的文件系统检查 ───────────────────────────────────────────

def check_extracted(dest, root, r):
    print("\n== 解压后的文件系统 ==", flush=True)
    r.md("### 解压后的文件系统（用户拿到的就是这份）")

    app = os.path.join(dest, root, BUNDLE_DIRNAME)
    if not r.ok(os.path.isdir(app),
                "解压后 %s/%s 存在（中文路径能正确落地）" % (root, BUNDLE_DIRNAME)):
        return None

    exe = os.path.join(app, EXE_REL.replace("/", os.sep))
    if not r.ok(os.path.isfile(exe), "解压后 Contents/MacOS/%s 存在" % APP_NAME):
        return None

    if os.name == "posix":
        r.ok(os.access(exe, os.X_OK), "解压后主程序仍带可执行位 (X_OK)")
    else:
        r.warn("非 POSIX 平台，可执行位以 ZIP 记录检查为准")

    cmd = os.path.join(dest, root, LAUNCH_SCRIPT)
    if r.ok(os.path.isfile(cmd), "解压后 %s 存在" % LAUNCH_SCRIPT):
        if os.name == "posix":
            r.ok(os.access(cmd, os.X_OK), "解压后 %s 仍带可执行位 (X_OK)" % LAUNCH_SCRIPT)

    r.fact("解压后主程序大小", vb._human(os.path.getsize(exe)))
    return app


# ── 4) 签名校验 ───────────────────────────────────────────────────────

def check_codesign(app, r):
    print("\n== 签名校验 ==", flush=True)
    r.md("### 签名校验（codesign）")

    cr = os.path.join(app, CODESIGN_REL.replace("/", os.sep))
    r.ok(os.path.isfile(cr),
         "bundle 内含 %s（构建时确实做过签名）" % CODESIGN_REL)

    if not shutil.which("codesign"):
        r.warn("当前环境没有 codesign，跳过签名校验（非 macOS 平台属正常）")
        return

    # 类型提示（ad-hoc / Developer ID …），给人看的
    try:
        d = subprocess.run(["codesign", "-d", "--verbose=2", app],
                           capture_output=True, text=True, timeout=120)
        det = (d.stdout or "") + (d.stderr or "")
        m = re.search(r"^Signature=(\S+)", det, re.M)
        if m:
            r.info("签名类型：%s" % m.group(1))
            r.md("- 签名类型：`%s`" % m.group(1))
    except Exception:
        pass

    cmd = ["codesign", "--verify", "--deep", "--strict", "--verbose=2", app]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as exc:
        r.ok(False, "执行 codesign 失败", "%s: %s" % (type(exc).__name__, exc))
        return

    out = ((p.stdout or "") + (p.stderr or "")).strip()
    # 成功时 codesign 也可能往 stderr 写 "valid on disk / satisfies..."
    for line in out.splitlines():
        print("     %s" % line, flush=True)

    ok = p.returncode == 0
    r.ok(ok, "codesign --verify --deep --strict 通过",
         "" if ok else "exit=%d" % p.returncode)

    if not ok:
        # 不吞错误：把签名详情一并打出来，方便直接定位
        try:
            d = subprocess.run(["codesign", "-d", "--verbose=4", app],
                               capture_output=True, text=True, timeout=120)
            dump = ((d.stdout or "") + (d.stderr or "")).strip()
            if dump:
                print("  ---- codesign -d --verbose=4 ----", flush=True)
                print(dump, flush=True)
        except Exception:
            pass
        r.md("- **codesign 校验未通过**：上方已打印 codesign 输出与签名详情")


# ── 5) 复用 verify_macos_bundle.py 再验一遍 ───────────────────────────

def run_bundle_verify(app, verify_script, expect_arch, summary_out, skip_probe, r):
    print("\n== 复用 verify_macos_bundle.py 校验解压后的 .app ==", flush=True)
    r.md("### 复用 verify_macos_bundle.py（对解压后的 .app）")

    cmd = [sys.executable, verify_script, "--app", app]
    if expect_arch:
        cmd += ["--expect-arch", expect_arch]
    if skip_probe:
        cmd += ["--skip-probe"]
    if summary_out:
        cmd += ["--summary-out", summary_out]

    print("  $ %s" % " ".join("'%s'" % c if " " in c else c for c in cmd), flush=True)
    try:
        p = subprocess.run(cmd, text=True)
        code = p.returncode
    except Exception as exc:
        r.ok(False, "调用 verify_macos_bundle.py 失败",
             "%s: %s" % (type(exc).__name__, exc))
        return

    ok = code == 0
    r.ok(ok, "verify_macos_bundle.py 在解压后的 .app 上通过",
         "" if ok else "exit=%d" % code)


# ── 入口 ──────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="校验 macOS 分发 ZIP 的闭环正确性")
    ap.add_argument("--zip", required=True, dest="zip_path",
                    help="待验证的分发 ZIP")
    ap.add_argument("--dest", required=True,
                    help="解压目标目录（不存在会自动创建）")
    ap.add_argument("--root", default=None,
                    help="ZIP 内顶级目录名；默认由 ZIP 文件名推断")
    ap.add_argument("--expect-arch", default=None, choices=["arm64", "x86_64"],
                    help="期望的 CPU 架构，透传给 bundle 校验")
    ap.add_argument("--verify-script", default=None,
                    help="verify_macos_bundle.py 路径；默认取同目录")
    ap.add_argument("--skip-probe", action="store_true",
                    help="跳过启动探针（本地无 .app 时用）")
    ap.add_argument("--summary-out", default=None,
                    help="把 markdown 报告追加写入该文件（给 Job Summary 用）")
    args = ap.parse_args()

    # Windows 控制台默认 GBK，中文/emoji 会抛 UnicodeEncodeError
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    zip_path = os.path.abspath(args.zip_path)
    root = args.root or os.path.splitext(os.path.basename(zip_path))[0]
    verify_script = args.verify_script or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "verify_macos_bundle.py")

    r = vb.Report()
    r.md("## 分发 ZIP 闭环验证")
    r.md("- ZIP：`%s`" % os.path.basename(zip_path))
    r.md("- 预期顶级目录：`%s`" % root)

    print("=" * 66, flush=True)
    print("分发 ZIP 闭环验证：%s" % zip_path, flush=True)
    print("平台：%s (%s)" % (sys.platform, vb._uname_m()), flush=True)
    print("=" * 66, flush=True)

    if not os.path.isfile(zip_path):
        r.ok(False, "ZIP 文件存在", zip_path)
    else:
        r.ok(True, "ZIP 文件存在", os.path.basename(zip_path))
        r.fact("分发 ZIP 大小", vb._human(os.path.getsize(zip_path)))

        check_zip_records(zip_path, root, r)
        extract_zip(zip_path, os.path.abspath(args.dest), r)
        app = check_extracted(os.path.abspath(args.dest), root, r)
        if app:
            check_codesign(app, r)
            if args.skip_probe and not os.path.isfile(verify_script):
                r.warn("找不到 %s，跳过嵌套校验" % verify_script)
            else:
                run_bundle_verify(app, verify_script, args.expect_arch,
                                  args.summary_out, args.skip_probe, r)

    print("\n" + "=" * 66, flush=True)
    if r.failures:
        print("❌ ZIP 闭环校验未通过，失败 %d 项：" % len(r.failures), flush=True)
        for f in r.failures:
            print("   - %s" % f, flush=True)
    else:
        print("✅ ZIP 闭环校验全部通过（用户下载解压后即为已验证状态）", flush=True)
    if r.warnings:
        print("⚠️  警告 %d 条：" % len(r.warnings), flush=True)
        for w in r.warnings:
            print("   - %s" % w, flush=True)
    print("=" * 66, flush=True)

    if args.summary_out:
        try:
            with open(args.summary_out, "a", encoding="utf-8") as fh:
                fh.write("\n".join(r.lines) + "\n")
                fh.write("\n**ZIP 闭环结论：%s**\n"
                         % ("❌ 校验未通过" if r.failures else "✅ 全部校验通过"))
                if r.facts:
                    fh.write("\n| 项 | 值 |\n|---|---|\n")
                    for k, v in r.facts.items():
                        fh.write("| %s | %s |\n" % (k, v))
        except Exception as exc:
            print("写 summary 失败：%s" % exc, flush=True)

    return 1 if r.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
