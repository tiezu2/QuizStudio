# -*- coding: utf-8 -*-
"""审计：题库里的编程题，能不能从题干里抠出「题目源码/父类」。

看三类：
  A 题干带代码且能识别出父类  → 文件里会有父类 + 待写的一个类
  B 题干带代码但没识别出父类（改错题/只有零散代码）→ 文件里原样放代码
  C 题干完全没有代码 → 只生成一个空的待写类
"""
import json
import sys

sys.path.insert(0, r"E:\桌面映射\Java\QuizStudio答题系统")
import server  # noqa: E402

TESTS = r"E:\桌面映射\Java\QuizStudio答题系统"
import urllib.request  # noqa: E402

op = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(p):
    with op.open("http://127.0.0.1:8770" + p, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


banks = get("/api/banks?full=1")["banks"]
stat = {"A": 0, "B": 0, "C": 0}
rows = []
for b in banks:
    for q in b["questions"]:
        if q.get("type") != "code":
            continue
        stem = q.get("stem") or ""
        text, code = server._split_stem(stem)
        is_fix = "FOUND" in code or "改错" in stem or "改正" in stem
        has_parent = bool(code) and bool(_importers__("re").search(r"class\s+[A-Za-z_]\w*\s*\{", code))
        cls = "" if is_fix else server._guess_answer_class(text, code)
        if has_parent and not is_fix:
            kind = "A"
        elif code:
            kind = "B"
        else:
            kind = "C"
        stat[kind] += 1
        rows.append((kind, b["id"], q.get("id"), q.get("no"), cls, is_fix,
                     len(code), (stem[:70]).replace("\n", " / ")))

print("编程题合计: %d   A(有父类)=%d  B(有代码无父类/改错)=%d  C(题干无代码)=%d" % (
    sum(stat.values()), stat["A"], stat["B"], stat["C"]))

print("\n--- C 类（只生成空骨架，可能是你说的『没法用源码生成』）---")
for r in rows:
    if r[0] == "C":
        print("  %-14s %-5s no=%-4s cls=%-10s %s" % (r[1], r[2], r[3], r[4], r[7]))

print("\n--- B 类（有代码但没抠出父类）---")
for r in rows:
    if r[0] == "B":
        print("  %-14s %-5s no=%-4s cls=%-10s fix=%-5s code=%dB  %s" % (
            r[1], r[2], r[3], r[4], r[5], r[6], r[7]))

print("\n--- A 类前 8 条（正常）---")
n = 0
for r in rows:
    if r[0] == "A":
        n += 1
        if n <= 8:
            print("  %-14s %-5s no=%-4s cls=%-10s code=%dB  %s" % (r[1], r[2], r[3], r[4], r[6], r[7]))
