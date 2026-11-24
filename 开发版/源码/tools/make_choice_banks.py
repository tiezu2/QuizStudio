# -*- coding: utf-8 -*-
"""把「选择题」（单选 + 多选）像大题那样按章节拆卷：

    选择题 · 按章节          全库选择题总卷（按章节排序）
    选择题 · 第 N 章 …       每个章节一份

    py -3 源码/tools/make_choice_banks.py
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

CHAPTERS = {
    1: "Java 语言概述与运行机制", 2: "数据类型与运算符", 3: "分支结构", 4: "循环结构",
    5: "方法", 6: "数组", 7: "类与对象", 8: "继承与多态", 9: "抽象类与接口",
    10: "异常处理", 11: "字符串与常用类", 12: "集合框架", 13: "JDBC 数据库编程",
}
SKIP_PREFIX = ("bank_bigq_", "bank_prog_ch", "bank_fix_ch", "bank_fill_ch",
               "bank_choice_ch", "bank_bigq_choice", "bank_java3_253")


def norm(s):
    t = re.sub(r"\s+", "", str(s or ""))
    t = re.sub(r"[（(）)：:，,。．、\"'`；;？?]", "", t)
    return re.sub(r"第\s*\d+\s*题", "", t)


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [(r["id"], json.loads(r["data"])) for r in con.execute("SELECT id, data FROM banks")]

    best, sources = {}, {}
    for bid, bank in rows:
        if bid.startswith(SKIP_PREFIX):
            continue
        title = (bank.get("title") or bid).replace("Java语言程序设计III · ", "")
        for q in bank.get("questions") or []:
            if q.get("type") not in ("single", "multi"):
                continue
            key = norm(q.get("stem"))
            if not key:
                continue
            sources.setdefault(key, [])
            if title not in sources[key]:
                sources[key].append(title)
            score = (len(q.get("exp") or "") + len(q.get("answer") or "") * 3
                     + len(q.get("stem") or "") // 4)
            if key not in best or score > best[key][0]:
                best[key] = (score, q)

    items = []
    for key, (_s, q) in best.items():
        nq = dict(q)
        nq["_from"] = sources.get(key, [])[:4]
        items.append(nq)
    items.sort(key=lambda q: (q.get("ch") or 99, str(q.get("no") or "")))

    now = time.time()
    made = []

    def save(bank):
        payload = json.dumps(bank, ensure_ascii=False)
        old = con.execute("SELECT created FROM banks WHERE id=?", (bank["id"],)).fetchone()
        if old:
            con.execute("UPDATE banks SET title=?, time=?, n_questions=?, updated=?, data=? WHERE id=?",
                        (bank["title"], bank["time"], len(bank["questions"]), now, payload, bank["id"]))
        else:
            con.execute("INSERT INTO banks(id,title,time,n_questions,created,updated,data) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (bank["id"], bank["title"], bank["time"], len(bank["questions"]),
                         now, now, payload))
        made.append((bank["id"], bank["title"], len(bank["questions"])))

    # 总卷
    agg = {
        "id": "bank_bigq_choice", "title": "选择题 · 按章节", "subject": "Java语言程序设计III",
        "time": time.strftime("%Y-%m-%d %H:%M"), "kind": "choice",
        "chapters": [{"id": c, "name": "第 %d 章 · %s" % (c, CHAPTERS[c]), "tag": ""}
                     for c in sorted({q.get("ch") for q in items if q.get("ch")})],
        "questions": [dict(q, id="choice_%d" % i, no=i) for i, q in enumerate(items, 1)],
        "warnings": ["选择题按章节整理；同题只留一份，答案/解析取最完整的副本"],
    }
    save(agg)

    # 单章卷
    for ch in sorted({q.get("ch") for q in items if q.get("ch")}):
        sub = [q for q in items if q.get("ch") == ch]
        save({
            "id": "bank_choice_ch%02d" % ch,
            "title": "选择题 · 第 %d 章 %s" % (ch, CHAPTERS[ch]),
            "subject": "Java语言程序设计III", "time": agg["time"], "kind": "choice",
            "chapters": [{"id": ch, "name": "第 %d 章 · %s" % (ch, CHAPTERS[ch]), "tag": ""}],
            "questions": [dict(q, id="c%02d_%d" % (ch, i), no=i)
                          for i, q in enumerate(sub, 1)],
            "warnings": ["选择题按章节拆分的单章卷"],
        })

    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()

    print("选择题拆卷完成（去重后 %d 道）：" % len(items))
    for bid, title, n in made:
        print("  %-20s %-30s %3d 题" % (bid, title, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
