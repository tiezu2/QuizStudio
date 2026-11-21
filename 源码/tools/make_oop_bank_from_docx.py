# -*- coding: utf-8 -*-
"""用一份 docx 重建「面向对象大题」卷：只保留 docx 里的题。

题目的答案/解析/参考代码从题库现有副本里取（同题干最完整的那份）。

    py -3 源码/tools/make_oop_bank_from_docx.py
    py -3 源码/tools/make_oop_bank_from_docx.py --docx "C:\\path\\xxx.docx" --title 面向对象大题
"""
import json
import os
import re
import sqlite3
import sys
import time
import zipfile
from xml.etree import ElementTree as ET

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.path.isdir(os.path.join(PROJ, "源码")):
    PROJ = os.path.dirname(PROJ)
ROOT = os.path.join(PROJ, "程序") if os.path.isdir(os.path.join(PROJ, "程序")) else PROJ
DB = os.path.join(ROOT, "quiz_studio.db")

BANK_ID = "bank_oop_bigq"
DEFAULT_DOCX = (r"C:\Users\Deabpool\Documents\WXWork\1688855097980506"
                r"\Cache\File\2026-11\Java面向对象基础练习题.docx")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_questions(path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    paras = ["".join(x.text or "" for x in p.iter(W + "t")).strip() for p in root.iter(W + "p")]
    paras = [p for p in paras if p]
    out = []
    for i, p in enumerate(paras):
        if not p.startswith("题目："):
            continue
        body = p[3:].strip()
        code = ""
        if i + 1 < len(paras) and not paras[i + 1].startswith("题目：") and not re.match(r"^\d{2}$", paras[i + 1]):
            code = paras[i + 1]
        out.append((body, code))
    return out


def norm(s):
    t = re.sub(r"\s+", "", str(s or ""))
    t = re.sub(r"[（(）)：:，,。．、\"'`；;]", "", t)
    return re.sub(r"第\s*\d+\s*题", "", t)


def main():
    docx = DEFAULT_DOCX
    title = "面向对象大题"
    if "--docx" in sys.argv:
        docx = sys.argv[sys.argv.index("--docx") + 1]
    if "--title" in sys.argv:
        title = sys.argv[sys.argv.index("--title") + 1]

    doc_qs = docx_questions(docx)
    print("docx：%s" % os.path.basename(docx))
    print("  题目 %d 道（含代码框架 %d 道）" % (
        len(doc_qs), sum(1 for _b, c in doc_qs if c)))

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [(r["id"], json.loads(r["data"])) for r in con.execute("SELECT id, data FROM banks")]
    pool = []
    for bid, bank in rows:
        for q in bank.get("questions") or []:
            pool.append((bid, q))

    chapters = {}
    for _bid, bank in rows:
        for c in bank.get("chapters") or []:
            chapters.setdefault(c.get("id"), c.get("name"))

    picked, missing = [], []
    for body, code in doc_qs:
        probe = norm(body)[:26]
        best, best_score = None, -1
        for bid, q in pool:
            stem = norm(q.get("stem"))
            if not probe or probe not in stem:
                continue
            score = len(q.get("exp") or "") + len(q.get("ref") or "") * 2 + len(q.get("answer") or "") * 3
            if score > best_score:
                best, best_score = (bid, q), score
        if best:
            picked.append(dict(best[1]))
        else:
            missing.append(body[:50])

    print("  在题库里找到 %d 道，缺 %d 道" % (len(picked), len(missing)))
    for m in missing:
        print("    缺：%s" % m)
    if not picked:
        con.close()
        return 1

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
        "subject": "Java语言程序设计III",
        "time": time.strftime("%Y-%m-%d %H:%M"),
        "kind": "paper",
        "chapters": [{"id": k, "name": chapters.get(k) or ("第 %d 章" % k), "tag": ""} for k in ch_ids],
        "questions": questions,
        "warnings": ["本卷只包含 %s 里的 %d 道题" % (os.path.basename(docx), len(questions))],
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

    has_ans = sum(1 for q in questions if str(q.get("answer") or q.get("ref") or "").strip())
    has_exp = sum(1 for q in questions if str(q.get("exp") or "").strip())
    print("\n已重建「%s」：%d 题（答案 %d，解析 %d，章节 %d）" % (
        title, len(questions), has_ans, has_exp, len(bank["chapters"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
