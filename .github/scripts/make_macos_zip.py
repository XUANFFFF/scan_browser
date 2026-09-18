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

（因此**分发给同事的 .app 包只能在 macOS 上打** —— 主程序的可执行位只有
macOS 文件系统才有。这也是 CI 用 macOS runner 的原因。）

关于 UTF-8 标志位
-----------------
标准库的 `ZipInfo` 在写非 ASCII 文件名时**本来就会自动**补上 bit 11，所以下面
那行显式设置其实是冗余的 —— 保留是为了把意图写明：这是**必须**成立的属性，
而不是依赖实现细节。真正会踩坑的是 `ditto`/`zip` 这类外部工具（它们不设）。

用法
----
    python make_macos_zip.py <待打包目录> <输出.zip>
    python make_macos_zip.py <待打包目录> <输出.zip> --quiet
    python make_macos_zip.py <待打包目录> <输出.zip> --exclude .buildenv

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

# 默认跳过：这些是本地环境的副产物，不该进分发包
DEFAULT_EXCLUDES = (".DS_Store", "__pycache__", ".buildenv")


def build(stage_dir, out_zip, quiet=False, excludes=DEFAULT_EXCLUDES):
    stage_dir = os.path.abspath(stage_dir)
    parent = os.path.dirname(stage_dir)          # 保留顶级目录名用
    if not os.path.isdir(stage_dir):
        raise SystemExit("待打包目录不存在：%s" % stage_dir)

    skip = set(excludes or ())
    entries = []                                  # (绝对路径, 归档内路径)
    for dirpath, dirnames, filenames in os.walk(stage_dir):
        # 路径里任意一层叫这个名字就跳过（本地 venv / 缓存目录等）
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        filenames = sorted(f for f in filenames if f not in skip)
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
            # 去掉「组/其他可写」：Windows 产出的文件常是 0666，解到 Mac 上
            # 就变成人人可写，没必要。只清写位，不动读位与执行位。
            mode &= ~0o022

            zi = zipfile.ZipInfo(arc + "/" if is_dir else arc,
                                 time.localtime(st.st_mtime)[:6])
            zi.flag_bits |= 0x800                 # 声明 UTF-8 文件名（见下方说明）
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
    if skip:
        print("  已跳过：%s" % ", ".join(sorted(skip)))
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
    ap.add_argument("--exclude", action="append", default=[], metavar="NAME",
                    help="额外跳过路径中任意一层名为 NAME 的目录/文件（可重复）")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    excludes = tuple(DEFAULT_EXCLUDES) + tuple(args.exclude)
    return build(args.stage_dir, args.out_zip, args.quiet, excludes)


if __name__ == "__main__":
    raise SystemExit(main())
