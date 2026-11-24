# -*- coding: utf-8 -*-
"""把「一卷一条 JSON」拆成「一卷一张表」的结构。

新结构（同一个 quiz_studio.db）：
    papers            卷子元信息（id/title/subject/kind/时间/题数/隐藏/警告）
    q_<卷id>          该卷的题目表（一题一行，列是结构化字段）
    banks             保留原表做备份，不删

    py -3 源码/tools/split_banks_to_tables.py
"""
import json
import os
import re
import sqlite3
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.path.isdir(os.path.join(PROJ, "源码")):
    PROJ = os.path.dirname(PROJ)
ROOT = PROJ
if not os.path.isdir(os.path.join(ROOT, "程序")):
    pass
DB = os.path.join(ROOT, "程序", "quiz_studio.db")
if not os.path.exists(DB):
    DB = os.path.join(PROJ, "本地开发版", "程序", "quiz_studio.db")

Q_COLS = [("no", "INTEGER"), ("qid", "TEXT"), ("type", "TEXT"), ("stem", "TEXT"),
          ("options", "TEXT"), ("answer", "TEXT"), ("exp", "TEXT"), ("ref", "TEXT"),
          ("ch", "INTEGER"), ("ch_name", "TEXT"), ("score", "REAL"), ("src", "TEXT"),
          ("from_banks", "TEXT"), ("extra", "TEXT")]


def table_name(bid):
    n = re.sub(r"[^a-z0-9_]", "_", bid.lower())
    return "q_" + n


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript("""
      CREATE TABLE IF NOT EXISTS papers(
        id TEXT PRIMARY KEY, title TEXT, subject TEXT, kind TEXT,
        time TEXT, created REAL, updated REAL, n_questions INTEGER,
        hidden INTEGER DEFAULT 0, warnings TEXT);
    """)
    rows = list(con.execute("SELECT id,title,time,n_questions,created,updated,data FROM banks"))
    made = 0
    for r in rows:
        b = json.loads(r["data"])
        con.execute(
            "INSERT OR REPLACE INTO papers(id,title,subject,kind,time,created,updated,n_questions,hidden,warnings) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (r["id"], r["title"], b.get("subject") or "", b.get("kind") or "paper",
             r["time"] or "", r["created"], r["updated"], len(b.get("questions") or []),
             1 if b.get("_hidden") else 0,
             json.dumps(b.get("warnings") or [], ensure_ascii=False)))
        tn = table_name(r["id"])
        con.execute("DROP TABLE IF EXISTS %s" % tn)
        con.execute("CREATE TABLE %s(%s)" % (tn, ", ".join("%s %s" % (c, t) for c, t in Q_COLS)))
        ins = "INSERT INTO %s(%s) VALUES(%s)" % (
            tn, ",".join(c for c, _t in Q_COLS), ",".join("?" * len(Q_COLS)))
        data = []
        for q in b.get("questions") or []:
            known = {"id": q.get("id"), "type": q.get("type"), "stem": q.get("stem"),
                     "options": json.dumps(q.get("options") or [], ensure_ascii=False),
                     "answer": q.get("answer") or "", "exp": q.get("exp") or "",
                     "ref": q.get("ref") or "", "ch": q.get("ch") or 0,
                     "ch_name": q.get("chName") or "", "score": q.get("score") or 0,
                     "src": q.get("_src") or q.get("src") or "",
                     "from_banks": json.dumps(q.get("_from") or [], ensure_ascii=False),
                     "no": q.get("no") or 0}
            extra = {k: v for k, v in q.items() if k not in
                     ("id", "type", "stem", "options", "answer", "exp", "ref", "ch", "chName",
                      "score", "src", "_src", "_from", "no")}
            vals = (known["no"], known["id"], known["type"], known["stem"], known["options"],
                    known["answer"], known["exp"], known["ref"], known["ch"], known["ch_name"],
                    known["score"], known["src"], known["from_banks"],
                    json.dumps(extra, ensure_ascii=False) if extra else "")
            data.append(vals)
        con.executemany(ins, data)
        made += 1
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    n = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'q\\_%' ESCAPE '\\'").fetchone()[0]
    tot = con.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    con.close()
    print("已生成 %d 张卷子表 + papers 元信息表（共 %d 卷）" % (n, tot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
