# -*- coding: utf-8 -*-
"""把「编程题 · 按章节」按章节拆成一份份卷子：

    编程题 · 第 1 章 Java 语言概述与运行机制
    编程题 · 第 4 章 循环结构
    ...

    py -3 源码/tools/make_prog_chapter_banks.py
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

SRC = "bank_bigq_prog"
CHAPTERS = {
    1: "Java 语言概述与运行机制", 2: "数据类型与运算符", 3: "分支结构", 4: "循环结构",
    5: "方法", 6: "数组", 7: "类与对象", 8: "继承与多态", 9: "抽象类与接口",
    10: "异常处理", 11: "字符串与常用类", 12: "集合框架", 13: "JDBC 数据库编程",
}


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT data FROM banks WHERE id=?", (SRC,)).fetchone()
    if not row:
        print("没有 %s，先跑 make_bigq_banks.py" % SRC)
        return 1
    src = json.loads(row["data"])
    groups = {}
    for q in src.get("questions") or []:
        groups.setdefault(q.get("ch") or 0, []).append(q)

    now = time.time()
    made = []
    for ch, qs in sorted(groups.items()):
        if not ch:
            continue
        bank_id = "bank_prog_ch%02d" % ch
        name = CHAPTERS.get(ch, "第 %d 章" % ch)
        title = "编程题 · 第 %d 章 %s" % (ch, name)
        qs = sorted(qs, key=lambda q: str(q.get("no")))
        questions = []
        for i, q in enumerate(qs, 1):
            nq = dict(q)
            nq["id"] = "p%02d_%d" % (ch, i)
            nq["no"] = i
            questions.append(nq)
        bank = {
            "id": bank_id,
            "title": title,
            "subject": "Java语言程序设计III",
            "time": time.strftime("%Y-%m-%d %H:%M"),
            "kind": "prog",
            "chapters": [{"id": ch, "name": "第 %d 章 · %s" % (ch, name), "tag": ""}],
            "questions": questions,
            "warnings": ["编程题按章节拆分的单章卷子"],
        }
        payload = json.dumps(bank, ensure_ascii=False)
        old = con.execute("SELECT created FROM banks WHERE id=?", (bank_id,)).fetchone()
        if old:
            con.execute("UPDATE banks SET title=?, time=?, n_questions=?, updated=?, data=? WHERE id=?",
                        (title, bank["time"], len(questions), now, payload, bank_id))
        else:
            con.execute("INSERT INTO banks(id,title,time,n_questions,created,updated,data) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (bank_id, title, bank["time"], len(questions), now, now, payload))
        made.append((bank_id, title, len(questions)))

    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    print("已拆成 %d 份单章编程卷：" % len(made))
    for bid, title, n in made:
        print("  %-18s %-34s %3d 题" % (bid, title, n))
    print("  合计 %d 题" % sum(n for _b, _t, n in made))
    return 0


if __name__ == "__main__":
    sys.exit(main())
