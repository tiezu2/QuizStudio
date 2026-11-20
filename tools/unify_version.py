# -*- coding: utf-8 -*-
"""把项目统一成「一个版本」：清掉重复/遗留/构建中间物，只留一套源码 + 一套产物。

    py -3 tools/unify_version.py --dry    # 只打印会做什么
    py -3 tools/unify_version.py          # 真的执行

做四件事：
 1. 把旧备份（*.bak*）、遗留文件（seed.html / demo-bank.txt / java-bank.json）、
    重复的 desktop (2)、深色主题、调试 spec、构建中间目录挪到 archive/日期-统一前/；
 2. 删掉 __pycache__、运行时状态 _opened_code.json；
 3. 报告统一后的目录树；
 4. 不动 desktop/release 与 exports（那是要交付的产物）。
"""
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAMP = time.strftime("%Y%m%d-%H%M")
ARCHIVE = os.path.join(ROOT, "archive", "%s-统一前" % STAMP)

LEGACY_FILES = ["seed.html", "demo-bank.txt", "java-bank.json", "_opened_code.json"]
LEGACY_DIRS = ["desktop (2)", "__pycache__",
               os.path.join("desktop", "__pycache__"),
               os.path.join("desktop", "build"),
               os.path.join("desktop", "dist")]
LEGACY_FILES_IN_DESKTOP = ["arknights-theme.css", "QuizStudioDbg.spec"]


def move(src, dst_dir, dry):
    if not os.path.exists(src):
        return None
    name = os.path.basename(src.rstrip("\\/"))
    dst = os.path.join(dst_dir, name)
    n = 1
    while os.path.exists(dst):
        n += 1
        base, ext = os.path.splitext(name)
        dst = os.path.join(dst_dir, "%s_%d%s" % (base, n, ext))
    print("  归档 %-42s → %s" % (os.path.relpath(src, ROOT), os.path.relpath(dst, ROOT)))
    if not dry:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
    return dst


def main():
    dry = "--dry" in sys.argv
    print("目标归档目录：%s" % ARCHIVE)
    print("\n[1] 备份与遗留文件")

    for fn in os.listdir(ROOT):
        if ".bak" in fn and os.path.isfile(os.path.join(ROOT, fn)):
            move(os.path.join(ROOT, fn), ARCHIVE, dry)
    for name in LEGACY_FILES:
        move(os.path.join(ROOT, name), ARCHIVE, dry)
    for name in LEGACY_FILES_IN_DESKTOP:
        move(os.path.join(ROOT, "desktop", name), ARCHIVE, dry)
    for name in LEGACY_DIRS:
        move(os.path.join(ROOT, name), ARCHIVE, dry)

    # 生成的文件挪到 exports 下，别堆在根目录
    out_dir = os.path.join(ROOT, "exports", "报告")
    for name in ("题库问题清单.docx", "题库问题清单.md"):
        src = os.path.join(ROOT, name)
        if os.path.exists(src):
            print("  移动 %-42s → %s" % (name, os.path.relpath(os.path.join(out_dir, name), ROOT)))
            if not dry:
                os.makedirs(out_dir, exist_ok=True)
                shutil.move(src, os.path.join(out_dir, name))

    print("\n[2] 统一后的根目录")
    for e in sorted(os.listdir(ROOT)):
        p = os.path.join(ROOT, e)
        if os.path.isdir(p):
            n = sum(len(f) for _r, _d, f in os.walk(p))
            size = sum(os.path.getsize(os.path.join(r, f)) for r, _d, fs in os.walk(p) for f in fs)
            print("  %-32s 目录  %3d 文件  %7.1f MB" % (e, n, size / 1024 / 1024))
        else:
            print("  %-32s 文件  %14.1f KB" % (e, os.path.getsize(p) / 1024))

    total = sum(os.path.getsize(os.path.join(r, f)) for r, _d, fs in os.walk(ROOT) for f in fs)
    print("\n  项目总占用：%.1f MB" % (total / 1024 / 1024))
    if dry:
        print("\n[dry] 没有真的移动任何东西")
    return 0


if __name__ == "__main__":
    sys.exit(main())
