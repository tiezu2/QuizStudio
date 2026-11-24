# -*- coding: utf-8 -*-
"""把「教材大题」单独抽成一份卷子：面向对象大题。

数据来源：题库里 _src 以「教材大题」开头的题（含 Java OOP 教材照片 + Java面向对象基础练习题.docx）。
同一道题在多份卷子里有副本，这里按题干去重，只留一份。

    py -3 源码/tools/make_oop_bank.py
    py -3 源码/tools/make_oop_bank.py --title 面向对象大题
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

BANK_ID = "bank_oop_bigq"
SRC_PREFIX = "教材大题"


def norm(s):
    t = re.sub(r"\s+", "", str(s or ""))
    t = re.sub(r"[（(]\s*[)）]", "", t)
    return re.sub(r"第\s*\d+\s*题", "", t)


def main():
    title = "面向对象大题"
    if "--title" in sys.argv:
        title = sys.argv[sys.argv.index("--title") + 1]

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [(r["id"], json.loads(r["data"])) for r in con.execute("SELECT id, data FROM banks")]

    seen, picked = set(), []
    for bid, bank in rows:
        if bid == BANK_ID:
            continue
        for q in bank.get("questions") or []:
            if not (q.get("_src") or "").startswith(SRC_PREFIX):
                continue
            key = norm(q.get("stem"))
            if key in seen:
                continue
            seen.add(key)
            picked.append(dict(q))

    if not picked:
        print("没找到 %s 来源的题，先确认 _src 标记" % SRC_PREFIX)
        return 1

    # 章节：沿用原题 ch，标题用原卷里的 chapter 名
    chapters = {}
    for _bid, bank in rows:
        for c in bank.get("chapters") or []:
            chapters.setdefault(c.get("id"), c.get("name"))

    questions = []
    for i, q in enumerate(picked, 1):
        nq = dict(q)
        nq["id"] = "oop%d" % i
        nq["no"] = i
        nq["kind"] = "paper"
        questions.append(nq)

    ch_ids = sorted({q.get("ch") for q in questions if q.get("ch")})
    bank = {
        "id": BANK_ID,
        "title": title,
        "subject": (rows[0][1].get("subject") if rows else "") or "Java语言程序设计III",
        "time": time.strftime("%Y-%m-%d %H:%M"),
        "kind": "paper",
        "chapters": [{"id": k, "name": chapters.get(k) or ("第 %d 章" % k), "tag": ""}
                     for k in ch_ids],
        "questions": questions,
        "warnings": ["这份卷子是从教材大题里抽出来的专项卷，题目与其他卷子的副本一致"],
    }

    now = time.time()
    payload = json.dumps(bank, ensure_ascii=False)
    old = con.execute("SELECT created FROM banks WHERE id=?", (BANK_ID,)).fetchone()
    if old:
        con.execute("UPDATE banks SET title=?, time=?, n_questions=?, updated=?, data=? WHERE id=?",
                    (bank["title"], bank["time"], len(questions), now, payload, BANK_ID))
    else:
        con.execute("INSERT INTO banks(id,title,time,n_questions,created,updated,data) VALUES(?,?,?,?,?,?,?)",
                    (BANK_ID, bank["title"], bank["time"], len(questions), now, now, payload))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()

    print("已生成卷子：%s" % bank["title"])
    print("  题目 %d 道（来源：%s）" % (len(questions), SRC_PREFIX))
    types = {}
    for q in questions:
        types[q.get("type")] = types.get(q.get("type"), 0) + 1
    print("  题型：%s" % types)
    print("  章节：%d 个" % len(bank["chapters"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
