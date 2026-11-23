# -*- coding: utf-8 -*-
"""把「编程题 / 改错题 / 填空题」三份大题卷按 AI 判定重新分章，并按章节排序。

    py -3 源码/tools/classify_bigq_chapters.py
    py -3 源码/tools/classify_bigq_chapters.py --dry
"""
import json
import os
import re
import sys
import urllib.request

BASE = "http://127.0.0.1:8770"
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
SUBJECT = "Java语言程序设计III"
CHAPTERS = [
    "第 1 章 · Java 语言概述与运行机制", "第 2 章 · 数据类型与运算符", "第 3 章 · 分支结构",
    "第 4 章 · 循环结构", "第 5 章 · 方法", "第 6 章 · 数组", "第 7 章 · 类与对象",
    "第 8 章 · 继承与多态", "第 9 章 · 抽象类与接口", "第 10 章 · 异常处理",
    "第 11 章 · 字符串与常用类", "第 12 章 · 集合框架", "第 13 章 · JDBC 数据库编程",
]
BANKS = ["bank_bigq_prog", "bank_bigq_fix", "bank_bigq_fill"]


def get(path):
    with OP.open(BASE + path, timeout=120) as r:
        return json.loads(r.read().decode())


def post(path, obj, timeout=1800):
    req = urllib.request.Request(BASE + path, data=json.dumps(obj, ensure_ascii=False).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    with OP.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def ch_num(name):
    m = re.search(r"第\s*(\d+)\s*章", str(name or ""))
    if m:
        return int(m.group(1))
    for i, full in enumerate(CHAPTERS, 1):
        if str(name or "") and str(name) in full:
            return i
    return 0


def main():
    dry = "--dry" in sys.argv
    for bid in BANKS:
        bank = get("/api/banks/" + bid)["bank"]
        qs = bank.get("questions") or []
        todo = [{"id": q["id"], "stem": (q.get("stem") or "")[:400],
                 "opts": " | ".join("%s.%s" % (o.get("k"), o.get("v"))
                                    for o in (q.get("options") or []))[:300]} for q in qs]
        mapping, provider = {}, ""
        for i in range(0, len(todo), 40):
            r = post("/api/chapters", {"subject": SUBJECT, "chapters": CHAPTERS,
                                       "questions": todo[i:i + 40]})
            if r.get("ok"):
                mapping.update(r.get("map") or {})
                provider = r.get("provider") or provider
            print("  %s 批 %d：累计 %d/%d（%s）" % (bid, i // 40 + 1, len(mapping), len(todo), provider),
                  flush=True)

        changed = 0
        for q in qs:
            n = ch_num(mapping.get(q["id"]))
            if n and q.get("ch") != n:
                q["ch"] = n
                changed += 1
            if not q.get("ch"):
                q["ch"] = 0
        # 按章节、再按题号排序并重编 no
        qs.sort(key=lambda q: (q.get("ch") or 99, str(q.get("no") or "")))
        for i, q in enumerate(qs, 1):
            q["no"] = i

        used = sorted({q.get("ch") or 0 for q in qs})
        bank["chapters"] = [{"id": c, "name": CHAPTERS[c - 1] if c else "未分章", "tag": ""}
                            for c in used]
        bank["questions"] = qs
        if dry:
            print("  [dry] %s 会改 %d 题，章节 %d 个" % (bank["title"], changed, len(used)))
            continue
        post("/api/banks", bank)
        stat = {}
        for q in qs:
            stat[q.get("ch") or 0] = stat.get(q.get("ch") or 0, 0) + 1
        print("  ✓ %-16s %d 题，改章 %d 题，分布 %s" % (
            bank["title"], len(qs), changed,
            {k: v for k, v in sorted(stat.items()) if k}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
