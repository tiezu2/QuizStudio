# -*- coding: utf-8 -*-
"""按版本号把项目打包成「网页版 / 桌面版」两套，并各出一个 zip。

产物：
    dist/v<版本>/
      ├─ 版本信息.md
      ├─ 网页版/             server.py + index.html + quiz_studio.db + 配置 + 文档 + 启动脚本
      │   └─ ../QuizStudio-v<版本>-网页版.zip
      └─ 桌面版/             QuizStudio.exe + 使用说明.txt
          └─ ../QuizStudio-v<版本>-桌面版.zip
    dist/QuizStudio-v<版本>-完整包.zip     （两套 + 版本信息）

    py -3 tools/package_release.py
    py -3 tools/package_release.py --no-exe     # 只打网页版
"""
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_version():
    src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    m = re.search(r'VERSION\s*=\s*"([^"]+)"', src)
    return m.group(1) if m else "0.0.0"


def bank_stats():
    con = sqlite3.connect(os.path.join(ROOT, "quiz_studio.db"))
    banks = [json.loads(r[0]) for r in con.execute("SELECT data FROM banks ORDER BY title")]
    con.close()
    total = sum(len(b.get("questions") or []) for b in banks)
    exp = sum(1 for b in banks for q in (b.get("questions") or []) if (q.get("exp") or "").strip())
    ch = sum(1 for b in banks if b.get("kind") == "chapter")
    return banks, total, exp, ch, len(banks) - ch


WEB_FILES = [
    "server.py", "index.html", "quiz_studio.db",
    "quiz_studio_llm.example.json", "quiz_studio_ide.json",
    "README.md", "版本说明.md", "start_quiz_studio.cmd", "start_local_llm.cmd",
]

START_CMD = """@echo off
chcp 65001 >nul
cd /d %~dp0
echo QuizStudio 网页版启动中…浏览器会自动打开 http://127.0.0.1:8770/
start "" http://127.0.0.1:8770/
py -3 server.py
pause
"""

DESKTOP_README = """QuizStudio 题库 · 桌面版
====================================
双击 QuizStudio.exe：
  1) 在本机起服务（127.0.0.1:8770，被占用会自动换端口）
  2) 弹控制窗口，并自动用浏览器打开答题界面

题库数据
  · 首次运行把内置题库复制到 %LOCALAPPDATA%\\QuizStudio\\quiz_studio.db
  · 之后新增/修改的卷子都在这里，升级不丢；控制窗口可「打开数据目录」

功能
  · 题库分「分章节 / 原卷子」两类；支持导入卷子、自动分章
  · 客观题即时判分；每题有解析（大题提交后可点「解析」弹窗查看）
  · 章节分类、错题回顾、正确率报告

AI（可选，默认关闭）
  · 编辑 %LOCALAPPDATA%\\QuizStudio\\quiz_studio_llm.json，把 enabled 改 true 并填 api_key

Eclipse 联动（桌面版默认关闭）
  · 编辑 %LOCALAPPDATA%\\QuizStudio\\quiz_studio_ide.json，填 eclipse_exe 与 project_src

退出
  · 控制窗口点关闭 → 确认退出

排查
  · 日志：%LOCALAPPDATA%\\QuizStudio\\quizstudio.log
"""


def main():
    no_exe = "--no-exe" in sys.argv
    version = read_version()
    banks, total, exp, ch, pa = bank_stats()
    base = os.path.join(ROOT, "dist", "v%s" % version)
    if os.path.exists(base):
        shutil.rmtree(base)
    web = os.path.join(base, "网页版")
    desk = os.path.join(base, "桌面版")
    os.makedirs(web, exist_ok=True)

    for name in WEB_FILES:
        src = os.path.join(ROOT, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(web, name))
    with open(os.path.join(web, "启动-网页版.cmd"), "w", encoding="gbk") as f:
        f.write(START_CMD.replace("\n", "\r\n"))
    with open(os.path.join(web, "VERSION.txt"), "w", encoding="utf-8") as f:
        f.write(version + "\n")

    exe_src = os.path.join(ROOT, "desktop", "release", "QuizStudio.exe")
    if not no_exe:
        os.makedirs(desk, exist_ok=True)
        if os.path.exists(exe_src):
            shutil.copy2(exe_src, os.path.join(desk, "QuizStudio.exe"))
        with open(os.path.join(desk, "使用说明.txt"), "w", encoding="utf-8") as f:
            f.write(DESKTOP_README)

    info = [
        "# QuizStudio v%s" % version, "",
        "打包时间：%s" % time.strftime("%Y-%m-%d %H:%M"), "",
        "## 题库", "",
        "- 卷子 **%d 卷**（分章节 %d / 原卷子 %d）" % (len(banks), ch, pa),
        "- 题目 **%d 道**，其中 **%d 道有解析**" % (total, exp), "",
        "## 两套产物", "",
        "| 目录 | 内容 | 怎么用 |",
        "| --- | --- | --- |",
        "| `网页版/` | server.py、index.html、quiz_studio.db、配置、文档、启动脚本 | 双击 `启动-网页版.cmd`（需 Python 3.8+，无第三方依赖）|",
    ]
    if not no_exe:
        info.append("| `桌面版/` | QuizStudio.exe（内置题库） | 双击即用，发给别人选这个 |")
    info += ["", "## 说明", "",
             "- 网页版与桌面版**同一套代码**，桌面版就是把网页版 + 浏览器外壳打成一个 exe",
             "- `quiz_studio_llm.example.json` 是 AI 配置示例；实际用 `quiz_studio_llm.json`（含 Key，不进包）",
             "- 换机器用 Eclipse 联动要改 `quiz_studio_ide.json` 里的路径", ""]
    with open(os.path.join(base, "版本信息.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(info))

    def zipdir(src, out):
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for b, _d, files in os.walk(src):
                for fn in files:
                    full = os.path.join(b, fn)
                    z.write(full, os.path.join("QuizStudio-v%s-%s" % (version, os.path.basename(src)),
                                               os.path.relpath(full, src)))
        return out

    made = [zipdir(web, os.path.join(base, "QuizStudio-v%s-网页版.zip" % version))]
    if not no_exe and os.path.isdir(desk):
        made.append(zipdir(desk, os.path.join(base, "QuizStudio-v%s-桌面版.zip" % version)))

    full_zip = os.path.join(ROOT, "dist", "QuizStudio-v%s-完整包.zip" % version)
    with zipfile.ZipFile(full_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for b, _d, files in os.walk(base):
            for fn in files:
                if fn.endswith(".zip"):
                    continue
                full = os.path.join(b, fn)
                z.write(full, os.path.join("QuizStudio-v%s" % version, os.path.relpath(full, base)))
    made.append(full_zip)

    print("版本：v%s" % version)
    print("目录：%s" % base)
    for f in made:
        print("  %-46s %6.1f MB" % (os.path.basename(f), os.path.getsize(f) / 1024 / 1024))
    print("\n内容清单：")
    for b, _d, files in os.walk(base):
        rel = os.path.relpath(b, base)
        for fn in sorted(files):
            p = os.path.join(b, fn)
            print("  %-52s %9.1f KB" % (fn if rel == "." else os.path.join(rel, fn),
                                        os.path.getsize(p) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
