#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一个分发目录打成 ZIP（macOS 构建用）。

为什么不用 `ditto -c -k` 或 `zip -r`
------------------------------------
ZIP 规范里，非 ASCII 文件名应当同时设置「UTF-8 / EFS 标志位」（general
purpose bit 11）。macOS 自带的 `ditto` 写进去的是 UTF-8 字节，但**不设这个
标志**，后果：

- 终端里 `unzip`（Info-ZIP）解压 → 按规范默认的 cp437 解码 → 中文名全乱
- Python 的 `zipfile` 读出来同样是乱码（CI 日志里一片 `µë½µÅÅ...`）

Finder / Archive Utility 会「猜」成 UTF-8，所以看起来没事 —— 一换工具就露馅。
这里自己写 zip：显式设置 UTF-8 标志位 + 保留 Unix 权限位，谁解压都对。

关于可执行位
------------
在 Windows 上生成分发包时，文件系统根本没有可执行位，`.command` / `.sh`
会被打成 `-rw-rw-rw-`，Mac 同事解压后双击直接失败。脚本因此对这两类后缀
强制补上 `0o111`。

用法
----
    python make_macos_zip.py <待打包目录> <输出.zip>
    python make_macos_zip.py <待打包目录> <输出.zip> --quiet

打包后的 ZIP 里会保留顶级目录名（等价于 ditto 的 --keepParent）。
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
import time
import zipfile

# Windows 上没有可执行位，这几类文件需要强制补
EXEC_SUFFIXES = (".command", ".sh")


def build(stage_dir, out_zip, quiet=False):
    stage_dir = os.path.abspath(stage_dir)
    parent = os.path.dirname(stage_dir)          # 保留顶级目录名用
    if not os.path.isdir(stage_dir):
        raise SystemExit("待打包目录不存在：%s" % stage_dir)

    entries = []                                  # (绝对路径, 归档内路径)
    for dirpath, dirnames, filenames in os.walk(stage_dir):
        dirnames.sort()
        filenames.sort()
        for name in dirnames:
            full = os.path.join(dirpath, name)
            entries.append((full, os.path.relpath(full, parent)))
        for name in filenames:
            full = os.path.join(dirpath, name)
            entries.append((full, os.path.relpath(full, parent)))
    # 目录在文件前面出现，解压时父目录先建好
    entries.sort(key=lambda x: x[1].replace(os.sep, "/"))

    total = 0
    written = []
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for full, arc in entries:
            arc = arc.replace(os.sep, "/")
            st = os.lstat(full)
            mode = st.st_mode & 0xFFFF
            is_dir = stat.S_ISDIR(st.st_mode)
            if arc.endswith(EXEC_SUFFIXES):
                mode |= 0o111                     # 补可执行位

            zi = zipfile.ZipInfo(arc + "/" if is_dir else arc,
                                 time.localtime(st.st_mtime)[:6])
            zi.flag_bits |= 0x800                 # ← 关键：声明 UTF-8 文件名
            zi.external_attr = mode << 16         # Unix 权限位
            if is_dir:
                zi.external_attr |= 0x10          # MS-DOS 目录位，兼容老解压工具
                zi.compress_type = zipfile.ZIP_STORED
                z.writestr(zi, b"")
            else:
                zi.compress_type = zipfile.ZIP_DEFLATED
                with open(full, "rb") as fh:
                    data = fh.read()
                z.writestr(zi, data)
                total += len(data)
                written.append((arc, stat.filemode(mode), len(data)))

    print("已生成 %s（%d 个条目，解压后 %.1f MB）"
          % (os.path.basename(out_zip), len(entries), total / 1048576))
    if not quiet:
        print("  %-11s %10s  %s" % ("权限", "大小", "路径"))
        for arc, perm, size in written:
            print("  %-11s %10d  %s" % (perm, size, arc))
    return 0


def main():
    ap = argparse.ArgumentParser(description="打包 macOS 分发 ZIP")
    ap.add_argument("stage_dir", help="待打包的目录（其目录名会作为 ZIP 的顶级目录）")
    ap.add_argument("out_zip", help="输出的 .zip 路径")
    ap.add_argument("--quiet", action="store_true", help="不打印逐条清单")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    return build(args.stage_dir, args.out_zip, args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
