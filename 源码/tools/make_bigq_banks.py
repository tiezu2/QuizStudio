# -*- coding: utf-8 -*-
"""把全库的「大题」（type=code）按细分类型 + 章节整理成三份卷子：

    编程题（按章节）   要求自己写完整类的题
    改错题（按章节）   带 FOUND 标记的改错题
    填空题（按章节）   带 SPACE 标记的程序填空题

同一道题在多份卷子里有副本，这里按题干去重；答案/解析取最完整的那份。

    py -3 源码/tools/make_bigq_banks.py
"""
import json
import os
import re
import sqlite3
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.path.isdir(os.path.join(PROJ, "源码")):
    PROJ = os.path.dirname(PROJ)
ROOT = os.path.join(PROJ, "程序") if os.path.isdir(os.path.join(PROJ, "程序")) else PROJ
DB = os.path.join(ROOT, "quiz_studio.db")

TARGETS = [
    ("bank_bigq_prog", "编程题 · 按章节", "prog"),
    ("bank_bigq_fix", "改错题 · 按章节", "fix"),
    ("bank_bigq_fill", "填空题 · 按章节", "fill"),
]

# 章节关键词（用于给没有 ch 的题补章节）
CH_RULES = [
    (9, ("抽象", "接口", "interface", "abstract", "implements")),
    (8, ("继承", "多态", "super", "覆盖", "override", "父类", "子类", "extends", "上转型")),
    (13, ("jdbc", "数据库", "sql", "connection", "resultset", "statement")),
    (12, ("集合", "arraylist", "hashmap", "list", "map", "set<")),
    (11, ("字符串", "string ", "stringbuffer", "stringbuilder", "正则", "equals")),
    (10, ("异常", "try", "catch", "finally", "throw", "exception")),
    (6, ("数组", "array", "[]")),
    (5, ("方法", "重载", "return", "参数")),
    (4, ("循环", "for", "while", "do-while")),
    (3, ("if", "switch", "分支")),
    (2, ("数据类型", "int ", "double", "char", "运算符", "变量")),
    (1, ("jdk", "jre", "jvm", "环境")),
]


def norm(s):
    t = re.sub(r"\s+", "", str(s or ""))
    t = re.sub(r"[（(）)：:，,。．、\"'`；;]", "", t)
    return re.sub(r"第\s*\d+\s*题", "", t)


def subtype(stem):
    s = stem or ""
    if "SPACE" in s or "【?】" in s or "[?]" in s:
        return "fill"
    if "FOUND" in s:
        return "fix"
    return "prog"


def guess_ch(q):
    ch = q.get("ch") or 0
    if ch:
        return ch
    low = (q.get("stem") or "").lower()
    for cid, words in CH_RULES:
        for w in words:
            if w in low:
                return cid
    return 0


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [(r["id"], json.loads(r["data"])) for r in con.execute("SELECT id, data FROM banks")]
    skip = {t[0] for t in TARGETS}

    ch_names = {}
    for _bid, bank in rows:
        for c in bank.get("chapters") or []:
            ch_names.setdefault(c.get("id"), c.get("name"))

    best = {}
    for bid, bank in rows:
        if bid in skip:
            continue
        for q in bank.get("questions") or []:
            if q.get("type") != "code":
                continue
            key = norm(q.get("stem"))
            if not key:
                continue
            score = (len(q.get("exp") or "") + len(q.get("ref") or "") * 2
                     + len(q.get("answer") or "") * 3 + len(q.get("stem") or "") // 4)
            if key not in best or score > best[key][0]:
                best[key] = (score, q)

    groups = {"prog": [], "fix": [], "fill": []}
    for _key, (_score, q) in best.items():
        item = dict(q)
        item["ch"] = guess_ch(item)
        groups[subtype(item.get("stem"))].append(item)

    now = time.time()
    for bank_id, title, kind in TARGETS:
        items = groups[kind]
        items.sort(key=lambda q: (q.get("ch") or 99, str(q.get("no"))))
        chapters = {}
        for q in items:
            c = q.get("ch") or 0
            chapters.setdefault(c, ch_names.get(c) or ("第 %d 章" % c if c else "未分章"))
        questions = []
        for i, q in enumerate(items, 1):
            nq = dict(q)
            nq["id"] = "%s_%d" % (kind, i)
            nq["no"] = i
            questions.append(nq)

        bank = {
            "id": bank_id,
            "title": title,
            "subject": "Java语言程序设计III",
            "time": time.strftime("%Y-%m-%d %H:%M"),
            "kind": "chapter",
            "chapters": [{"id": c, "name": n, "tag": ""} for c, n in
                         sorted(chapters.items(), key=lambda x: x[0] or 99)],
            "questions": questions,
            "warnings": ["按细分类型 + 章节整理的大题专项卷；同题只保留一份，答案/解析取最完整的副本"],
        }
        payload = json.dumps(bank, ensure_ascii=False)
        old = con.execute("SELECT created FROM banks WHERE id=?", (bank_id,)).fetchone()
        if old:
            con.execute("UPDATE banks SET title=?, time=?, n_questions=?, updated=?, data=? WHERE id=?",
                        (bank["title"], bank["time"], len(questions), now, payload, bank_id))
        else:
            con.execute("INSERT INTO banks(id,title,time,n_questions,created,updated,data) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (bank_id, bank["title"], bank["time"], len(questions), now, now, payload))
        by_ch = {}
        for q in questions:
            by_ch[q.get("ch") or 0] = by_ch.get(q.get("ch") or 0, 0) + 1
        print("%-16s %2d 题  章节分布 %s" % (title, len(questions),
                                          {k: v for k, v in sorted(by_ch.items())}))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    print("\n完成（去重后共 %d 道大题）" % sum(len(v) for v in groups.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
