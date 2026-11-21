# -*- coding: utf-8 -*-
"""按版本把项目打包成「自用 / 分享」两个文件夹（各带 zip）。

    dist/v<版本>/
      ├─ 版本信息.md
      ├─ 自用/                    ← 你自己用：网页版全套，配置带 Key、Eclipse 联动开着
      │   ├─ 启动-网页版.cmd
      │   ├─ server.py / index.html / quiz_studio.db
      │   ├─ quiz_studio_llm.json（含 Key）/ quiz_studio_ide.json（本机路径）
      │   ├─ README.md / 版本说明.md / VERSION.txt
      │   ├─ start_quiz_studio.cmd / start_local_llm.cmd
      │   └─ 自用.zip
      └─ 分享/                    ← 给别人：桌面版 exe + 干净网页版（无 Key、IDE 关闭）
          ├─ QuizStudio.exe / 使用说明.txt
          ├─ 网页版（干净版）/ 启动-网页版.cmd …
          └─ 分享.zip

    py -3 tools/package_release.py
    py -3 tools/package_release.py --no-exe
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

START_CMD = """@echo off
chcp 65001 >nul
cd /d %~dp0
echo QuizStudio 网页版启动中…浏览器会自动打开 http://127.0.0.1:8770/
start "" http://127.0.0.1:8770/
py -3 server.py
pause
"""

SHARE_README = """QuizStudio 题库 · 桌面版
====================================
双击 QuizStudio.exe：
  1) 本机起服务（127.0.0.1:8770，被占用会自动换端口）
  2) 弹控制窗口，并自动打开浏览器

题库数据
  · 首次运行复制到 %LOCALAPPDATA%\\QuizStudio\\quiz_studio.db，之后改动都在这里，升级不丢
  · 控制窗口「打开数据目录」可直达

功能
  · 题库分「分章节 / 原卷子」；可直接导入卷子、自动分章
  · 客观题即时判分；每题都有解析（大题提交后点「解析」弹窗查看）
  · 章节分类、错题回顾、正确率报告

AI 判分（可选，默认关闭）
  · 编辑 %LOCALAPPDATA%\\QuizStudio\\quiz_studio_llm.json：enabled 改 true，填 api_key

Eclipse 联动（默认关闭）
  · 编辑 %LOCALAPPDATA%\\QuizStudio\\quiz_studio_ide.json ：填 eclipse_exe、project_src

退出 / 排查
  · 控制窗口关闭即退出；日志在 %LOCALAPPDATA%\\QuizStudio\\quizstudio.log
"""

# 网页版「干净版」用的配置（不带 Key）
CLEAN_LLM = {
    "_说明": "AI 配置。想开 AI 判分/写解析，把 enabled 改 true 并填 api_key（智谱 BigModel 免费模型即可）。",
    "enabled": False,
    "mode": "off",
    "api_key": "",
    "model": "glm-4-flash",
    "timeout": 60,
    "budget": 600,
    "min_gap": 0,
    "judge_batch": 8,
    "max_judge_calls": 8,
    "providers": [],
}
CLEAN_IDE = {
    "_说明": "Eclipse 联动。要用就改 enabled=true，并填 eclipse_exe 与 project_src。",
    "enabled": False,
    "clearOnSubmit": False,
    "eclipse_exe": "",
    "project_src": "",
    "package": "bank",
}


def read_version():
    src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    m = re.search(r'VERSION\s*=\s*"([^"]+)"', src)
    return m.group(1) if m else "0.0.0"


def bank_stats():
    con = sqlite3.connect(os.path.join(ROOT, "quiz_studio.db"))
    banks = [json.loads(r[0]) for r in con.execute("SELECT data FROM banks")]
    con.close()
    total = sum(len(b.get("questions") or []) for b in banks)
    exp = sum(1 for b in banks for q in (b.get("questions") or []) if (q.get("exp") or "").strip())
    ch = sum(1 for b in banks if b.get("kind") == "chapter")
    return len(banks), total, exp, ch, len(banks) - ch


def copy_web(dst, with_key=True):
    os.makedirs(dst, exist_ok=True)
    for name in ("server.py", "index.html", "quiz_studio.db", "quiz_studio_llm.example.json",
                 "quiz_studio_ide.json", "README.md", "版本说明.md",
                 "start_quiz_studio.cmd", "start_local_llm.cmd"):
        src = os.path.join(ROOT, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(dst, name))
    if with_key:
        src = os.path.join(ROOT, "quiz_studio_llm.json")
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(dst, "quiz_studio_llm.json"))
    else:
        with open(os.path.join(dst, "quiz_studio_llm.json"), "w", encoding="utf-8") as f:
            json.dump(CLEAN_LLM, f, ensure_ascii=False, indent=2)
        with open(os.path.join(dst, "quiz_studio_ide.json"), "w", encoding="utf-8") as f:
            json.dump(CLEAN_IDE, f, ensure_ascii=False, indent=2)
    with open(os.path.join(dst, "启动-网页版.cmd"), "w", encoding="gbk") as f:
        f.write(START_CMD.replace("\n", "\r\n"))


def zipdir(src, out, arc_root):
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for b, _d, files in os.walk(src):
            for fn in files:
                if fn.endswith(".zip"):
                    continue
                full = os.path.join(b, fn)
                z.write(full, os.path.join(arc_root, os.path.relpath(full, src)))
    return out


def main():
    no_exe = "--no-exe" in sys.argv
    ver = read_version()
    n_bank, total, exp, ch, pa = bank_stats()
    base = os.path.join(ROOT, "dist", "v%s" % ver)
    if os.path.exists(base):
        shutil.rmtree(base)
    self_dir = os.path.join(base, "自用")
    share_dir = os.path.join(base, "分享")
    os.makedirs(self_dir, exist_ok=True)
    os.makedirs(share_dir, exist_ok=True)

    # ---------- 自用 ----------
    copy_web(self_dir, with_key=True)
    with open(os.path.join(self_dir, "VERSION.txt"), "w", encoding="utf-8") as f:
        f.write(ver + "\n")
    with open(os.path.join(self_dir, "自用说明.md"), "w", encoding="utf-8") as f:
        f.write("# 自用版 v%s\n\n- 双击 `启动-网页版.cmd`，浏览器打开 http://127.0.0.1:8770/\n"
                "- 带你的 AI Key（quiz_studio_llm.json）与 Eclipse 路径（quiz_studio_ide.json），"
                "换机器记得改路径\n- 题库：%d 卷（分章节 %d / 原卷子 %d），%d 题，%d 题有解析\n"
                % (ver, n_bank, ch, pa, total, exp))

    # ---------- 分享 ----------
    exe_src = os.path.join(ROOT, "desktop", "release", "QuizStudio.exe")
    if not no_exe:
        if os.path.exists(exe_src):
            shutil.copy2(exe_src, os.path.join(share_dir, "QuizStudio.exe"))
        with open(os.path.join(share_dir, "使用说明.txt"), "w", encoding="utf-8") as f:
            f.write(SHARE_README)
    copy_web(os.path.join(share_dir, "网页版（干净版）"), with_key=False)
    with open(os.path.join(share_dir, "网页版（干净版）", "VERSION.txt"), "w", encoding="utf-8") as f:
        f.write(ver + "\n")

    # ---------- 版本信息 ----------
    info = ["# QuizStudio v%s" % ver, "", "打包时间：%s" % time.strftime("%Y-%m-%d %H:%M"), "",
            "## 题库", "", "- 卷子 **%d 卷**（分章节 %d / 原卷子 %d）" % (n_bank, ch, pa),
            "- 题目 **%d 道**，**%d 道有解析**" % (total, exp), "",
            "## 两个文件夹", "",
            "| 文件夹 | 给谁 | 内容 |", "| --- | --- | --- |",
            "| `自用/` | 你自己 | 网页版全套，**带 AI Key 和 Eclipse 路径**，双击 `启动-网页版.cmd` |",
            "| `分享/` | 发给别人 | 桌面版 `QuizStudio.exe` + 使用说明，另附**干净网页版**（无 Key、Eclipse 关闭）|",
            "",
            "## 注意", "",
            "- `自用/` 里有你的 API Key，**不要发给别人**",
            "- 桌面版首次运行会把题库复制到 `%LOCALAPPDATA%\\QuizStudio\\`，之后升级不丢数据",
            ""]
    with open(os.path.join(base, "版本信息.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(info))

    made = []
    made.append(zipdir(self_dir, os.path.join(base, "QuizStudio-v%s-自用.zip" % ver),
                       "QuizStudio-v%s-自用" % ver))
    made.append(zipdir(share_dir, os.path.join(base, "QuizStudio-v%s-分享.zip" % ver),
                       "QuizStudio-v%s-分享" % ver))
    full = os.path.join(ROOT, "dist", "QuizStudio-v%s-完整包.zip" % ver)
    with zipfile.ZipFile(full, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for b, _d, files in os.walk(base):
            for fn in files:
                if fn.endswith(".zip"):
                    continue
                z.write(os.path.join(b, fn),
                        os.path.join("QuizStudio-v%s" % ver, os.path.relpath(os.path.join(b, fn), base)))
    made.append(full)

    print("版本：v%s　题库：%d 卷 / %d 题（%d 有解析）" % (ver, n_bank, total, exp))
    print("目录：%s" % base)
    for f in made:
        print("  %-42s %6.1f MB" % (os.path.basename(f), os.path.getsize(f) / 1024 / 1024))
    print("\n清单：")
    for b, _d, files in os.walk(base):
        rel = os.path.relpath(b, base)
        for fn in sorted(files):
            p = os.path.join(b, fn)
            print("  %-56s %8.1f KB" % (fn if rel == "." else os.path.join(rel, fn),
                                        os.path.getsize(p) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
