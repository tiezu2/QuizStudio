# -*- coding: utf-8 -*-
"""只修「javac 编不过」的编程题参考答案。

判定口径和做题一样：先去掉顶层 public（一个文件放多个类），再 javac -encoding UTF-8。
生成 → 编译；编不过就加大预算重来；最多两轮，仍然是坏的就保留原样不动。

    py -3 importers/fix_code_refs.py --dry
    py -3 importers/fix_code_refs.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.path.isdir(os.path.join(PROJ, "源码")):            # 脚本在 源码\tools|importers 下时上跳
    PROJ = os.path.dirname(PROJ)
# 运行时文件（server.py / index.html / 数据库 / 配置）都在 PROJ\程序 下
ROOT = os.path.join(PROJ, "程序") if os.path.isdir(os.path.join(PROJ, "程序")) else PROJ
sys.path.insert(0, ROOT)
import server  # noqa: E402

BASE = "http://127.0.0.1:8770"
SYS = ("你是 Java 助教。只输出一段可直接编译运行的 Java 代码，不要解释、不要用 markdown 代码块、"
       "不要重复题目、不要写文件名注释。顶层类一律不加 public（都要放在同一个文件里）。"
       "代码必须完整、括号闭合、类型正确；需要验证就写一个带 main 的测试类。")
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(path):
    with OP.open(BASE + path, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, obj):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with OP.open(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def clean(t):
    t = str(t or "").replace("```", "").strip()
    t = re.sub(r"(?m)^\s*//\s*[\w.]+\.java\s*$", "", t)
    t = re.sub(r"(?m)^(\s*)public(\s+(?:abstract\s+|final\s+)?(?:class|interface|enum)\s+)", r"\1\2", t)
    return t.strip()


def compiles(code):
    if not code.strip() or code.count("{") != code.count("}"):
        return False
    d = tempfile.mkdtemp()
    try:
        f = os.path.join(d, "Main.java")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(clean(code))
        r = subprocess.run(["javac", "-encoding", "UTF-8", "-nowarn", "-d", d, f],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.returncode == 0
    except FileNotFoundError:
        return False
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    dry = "--dry" in sys.argv
    server.load_ai_config()

    bad = []
    for b in get("/api/banks")["banks"]:
        full = get("/api/banks/" + b["id"])["bank"]
        for q in full["questions"]:
            if q.get("type") != "code":
                continue
            ref = q.get("ref") or ""
            if "{" in ref and not compiles(ref):
                bad.append((full, q))
    print("javac 编不过的编程题：%d 道" % len(bad))
    for full, q in bad:
        print("  %-16s %-5s %s" % (full["id"], q["id"], (q.get("stem") or "")[:44].replace("\n", " ")))
    if dry or not bad:
        return 0

    fixed = still = 0
    t0 = time.time()
    by_bank = {}
    for full, q in bad:
        best, ok = "", False
        for budget in (2000, 3200):
            try:
                txt, prov = server.ai_chat(
                    SYS, "请写出这道题的参考实现（Java，一个文件里可以放多个类）：\n"
                         + (q.get("stem") or "")[:1500], max_tokens=budget)
            except Exception as exc:  # noqa: BLE001
                print("  [x] %s %s：%s" % (full["id"], q["id"], exc), flush=True)
                break
            code = clean(txt)
            if compiles(code):
                best, ok = code, True
                break
            if not best:
                best = code
        if not best:
            still += 1
            continue
        q["ref"] = best[:6000]
        q["_aiAnswer"] = 1
        q["_aiCode"] = 1
        if ok:
            fixed += 1
        else:
            q["_aiCodeWeak"] = 1
            still += 1
        by_bank.setdefault(full["id"], {"bank": full, "n": 0})["n"] += 1
        print("  %s %s -> %s" % (full["id"], q["id"], "编译通过" if ok else "仍编不过"), flush=True)

    for bid, item in by_bank.items():
        post("/api/banks", item["bank"])
        print("  写回 %-16s %d 道" % (bid, item["n"]), flush=True)
    print("\n完成：修好 %d 道，仍是坏 %d 道，用时 %.1f 分钟" % (fixed, still, (time.time() - t0) / 60.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
