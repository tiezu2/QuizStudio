# -*- coding: utf-8 -*-
"""把 QuizStudio 题库项目导出成一个「解压即用」的包。

布局和项目本身一致（server.py 与数据库同级，ROOT 解析才对）：
    QuizStudio-项目导出-<时间>/
      ├─ 启动-网页版.cmd
      ├─ server.py  index.html  quiz_studio.db
      ├─ quiz_studio_llm.json  quiz_studio_ide.json  README.md
      ├─ 题库导出.json          （全部卷子的 JSON，方便二次使用）
      ├─ 桌面版/  QuizStudio.exe + 使用说明.txt
      └─ 导出说明.md

用法：
    py -3 _dev/export_project.py            # 全部
    py -3 _dev/export_project.py --no-exe   # 不带桌面版
"""
import json
import os
import shutil
import sqlite3
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAMP = time.strftime("%Y%m%d-%H%M")
NAME = "QuizStudio-项目导出-%s" % STAMP
OUT = os.path.join(ROOT, "_export", NAME)

FLAT = ["server.py", "index.html", "quiz_studio_llm.json", "quiz_studio_ide.json",
        "README.md", "start_quiz_studio.cmd", "start_local_llm.cmd", "quiz_studio.db"]
EXE = [os.path.join("desktop", "release", "QuizStudio.exe"),
       os.path.join("desktop", "release", "使用说明.txt")]


def checkpoint():
    con = sqlite3.connect(os.path.join(ROOT, "quiz_studio.db"))
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()


def bank_stats():
    con = sqlite3.connect(os.path.join(ROOT, "quiz_studio.db"))
    banks = [json.loads(r[0]) for r in con.execute("SELECT data FROM banks ORDER BY title")]
    con.close()
    total = sum(len(b.get("questions") or []) for b in banks)
    code = sum(1 for b in banks for q in (b.get("questions") or []) if q.get("type") == "code")
    ai = sum(1 for b in banks for q in (b.get("questions") or []) if q.get("_aiAnswer"))
    subj = {}
    for b in banks:
        s = b.get("subject") or "未分类"
        subj[s] = subj.get(s, 0) + 1
    return banks, total, code, ai, subj


def main():
    no_exe = "--no-exe" in sys.argv
    checkpoint()
    banks, total, code_n, ai_n, subj = bank_stats()

    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)

    for name in FLAT:
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(OUT, name))

    with open(os.path.join(OUT, "题库导出.json"), "w", encoding="utf-8") as f:
        json.dump(banks, f, ensure_ascii=False, indent=1)

    if not no_exe:
        d = os.path.join(OUT, "桌面版")
        os.makedirs(d, exist_ok=True)
        for rel in EXE:
            p = os.path.join(ROOT, rel)
            if os.path.exists(p):
                shutil.copy2(p, os.path.join(d, os.path.basename(rel)))

    with open(os.path.join(OUT, "启动-网页版.cmd"), "w", encoding="gbk") as f:
        f.write("@echo off\r\nchcp 65001 >nul\r\ncd /d %~dp0\r\n"
                "echo QuizStudio 网页版启动中，浏览器会自动打开 http://127.0.0.1:8770/\r\n"
                "start \"\" http://127.0.0.1:8770/\r\n"
                "py -3 server.py\r\npause\r\n")

    lines = [
        "# QuizStudio 题库项目导出", "",
        "导出时间：%s" % time.strftime("%Y-%m-%d %H:%M"), "",
        "## 题库概况", "",
        "- 卷子 **%d 卷**，题目 **%d 题**（编程题 %d 道，AI 补过答案 %d 道）" % (len(banks), total, code_n, ai_n),
        "- 科目分布：%s" % "、".join("%s（%d 卷）" % (k, v) for k, v in subj.items()), "",
        "## 目录", "",
        "| 文件 | 说明 |", "| --- | --- |",
        "| `server.py` | 本地服务（127.0.0.1:8770），纯标准库，无第三方依赖 |",
        "| `index.html` | 单文件前端（答题 / 章节 / 报告 / 导入 / 桌面皮肤）|",
        "| `quiz_studio.db` | 题库数据库（SQLite，卷子 + 题目 + 提交记录）|",
        "| `题库导出.json` | 同样的题库导出成 JSON，方便二次处理 |",
        "| `quiz_studio_llm.json` | AI 配置（判分 / 分章 / 补答案），默认已带 Key |",
        "| `quiz_studio_ide.json` | Eclipse 联动配置（换机器要改 eclipse_exe / project_src）|",
        "| `README.md` | 完整使用与开发说明 |",
        "| `启动-网页版.cmd` | 双击启动（需要 Python 3.8+）|",
    ]
    if not no_exe:
        lines.append("| `桌面版/QuizStudio.exe` | 双击即用，内置题库，给别人时直接发这个 |")
    lines += [
        "", "## 怎么用", "",
        "**给别人**：发 `桌面版/QuizStudio.exe`（或整个 `桌面版/` 目录）。数据会写到 "
        "`%LOCALAPPDATA%\\QuizStudio\\quiz_studio.db`，升级不丢。", "",
        "**自己改代码**：解压后双击 `启动-网页版.cmd`，改完 `index.html` / `server.py` 刷新页面即可。", "",
        "**换机器要注意**：`quiz_studio_ide.json` 里的 `eclipse_exe`、`project_src` 是本机路径，"
        "要用 Eclipse 联动就改成新机器的；`start_local_llm.cmd` 里的本地模型路径同理。", "",
        "## 没打包进来的", "",
        "- `_dev/`、`_import/`（开发脚本）、`新大题/`（15 张教材照片）、`*.bak-*` 备份、"
        "`desktop/build|dist`、`__pycache__`、`_export/`。", "",
    ]
    with open(os.path.join(OUT, "导出说明.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    zip_path = OUT + ".zip"
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for base, _d, files in os.walk(OUT):
            for fn in files:
                full = os.path.join(base, fn)
                z.write(full, os.path.join(NAME, os.path.relpath(full, OUT)))

    print("目录：%s" % OUT)
    print("压缩包：%s（%.1f MB）" % (zip_path, os.path.getsize(zip_path) / 1024 / 1024))
    print("题库：%d 卷 / %d 题（编程 %d，AI 补答案 %d）" % (len(banks), total, code_n, ai_n))
    for base, _d, files in os.walk(OUT):
        rel = os.path.relpath(base, OUT)
        for fn in sorted(files):
            p = os.path.join(base, fn)
            print("  %-40s %9.1f KB" % (fn if rel == "." else os.path.join(rel, fn),
                                        os.path.getsize(p) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
