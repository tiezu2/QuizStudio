# -*- coding: utf-8 -*-
"""专门给「编程题」补参考答案：要求模型输出可直接编译的 Java 代码。

流程：生成 → 去掉顶层 public（一个文件里放多个类）→ javac 试编译
     → 编不过就加大预算重试一次 → 还不行就留着并打 _aiCodeWeak=1

    py -3 _import/backfill_code_answers.py --dry
    py -3 _import/backfill_code_answers.py
    py -3 _import/backfill_code_answers.py --bank bank_ch08
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402

BASE = "http://127.0.0.1:8770"
SYS = ("你是 Java 助教。只输出一段可直接编译运行的 Java 代码，不要解释、不要用 markdown 代码块标记、"
       "不要重复题目、不要在代码里写文件名注释。"
       "题目要求几个类就写几个类；顶层类一律不加 public（要放在同一个文件里）。"
       "需要验证的题目就写一个带 main 的测试类。代码必须完整、括号闭合。")
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
    t = str(t or "").strip()
    t = t.replace("```", "")
    # 去掉 "// Printer.java" 这类文件名注释行
    t = re.sub(r"(?m)^\s*//\s*[\w.]+\.java\s*$", "", t)
    # 顶层类型去掉 public（一个文件里只能有一个 public 类型）
    t = re.sub(r"(?m)^(\s*)public(\s+(?:abstract\s+|final\s+)?(?:class|interface|enum)\s+)", r"\1\2", t)
    return t.strip()


def balanced(t):
    return t.count("{") == t.count("}") and t.count("{") > 0


def try_compile(code):
    d = tempfile.mkdtemp()
    try:
        f = os.path.join(d, "Main.java")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(code)
        r = subprocess.run(["javac", "-encoding", "UTF-8", "-nowarn", "-d", d, f],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.returncode == 0, (r.stderr or "")[:200]
    except FileNotFoundError:
        return None, "没有 javac"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def gen(q, budget):
    user = "请写出这道题的参考实现（Java，一个文件里可以放多个类）：\n" + (q.get("stem") or "")[:1500]
    txt, prov = server.ai_chat(SYS, user, max_tokens=budget)
    return clean(txt), prov


def main():
    dry = "--dry" in sys.argv
    only = sys.argv[sys.argv.index("--bank") + 1] if "--bank" in sys.argv else ""
    force = "--all" in sys.argv          # 连已经像代码的也重写
    fix_bad = "--fix-failing" in sys.argv  # 只重写 javac 编不过的
    server.load_ai_config()

    todo = []
    for b in get("/api/banks")["banks"]:
        if only and b["id"] != only:
            continue
        full = get("/api/banks/" + b["id"])["bank"]
        for q in full["questions"]:
            if q.get("type") != "code":
                continue
            ref = q.get("ref") or ""
            is_code = bool(re.search(r"\b(class|interface)\s+[A-Za-z_]\w*", ref)) and "{" in ref
            if fix_bad:
                if not is_code:
                    continue
                bad, _err = try_compile(ref)
                if bad is False:
                    todo.append((full, q))
                continue
            if force or not is_code or not balanced(ref):
                todo.append((full, q))

    print("待重写的编程题：%d 道" % len(todo))
    if dry or not todo:
        return 0

    done = weak = 0
    t0 = time.time()
    by_bank = {}
    for full, q in todo:
        code, prov = "", ""
        ok = False
        for budget in (1600, 3000):
            try:
                code, prov = gen(q, budget)
            except Exception as exc:  # noqa: BLE001
                print("  [x] %s %s：%s" % (full["id"], q["id"], exc), flush=True)
                code = ""
                break
            if not balanced(code):
                continue
            good, err = try_compile(code)
            if good or good is None:
                ok = True
                break
        if not code:
            continue
        q["ref"] = code[:6000]
        q["_aiAnswer"] = 1
        q["_aiCode"] = 1
        if ok:
            done += 1
        else:
            q["_aiCodeWeak"] = 1
            weak += 1
        by_bank.setdefault(full["id"], {"bank": full, "n": 0})["n"] += 1
        if (done + weak) % 5 == 0:
            print("  已处理 %d 道（编译通过 %d / 未通过 %d），用时 %.0fs（%s）" % (
                done + weak, done, weak, time.time() - t0, prov), flush=True)

    for bid, item in by_bank.items():
        post("/api/banks", item["bank"])
        print("  写回 %-16s %d 道" % (bid, item["n"]), flush=True)

    print("\n完成：编译通过 %d 道，未通过 %d 道，总 %d 道，用时 %.1f 分钟" % (
        done, weak, done + weak, (time.time() - t0) / 60.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
