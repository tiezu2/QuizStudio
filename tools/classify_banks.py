# -*- coding: utf-8 -*-
"""给每个卷子打上分类：kind = "chapter"（分章节）或 "paper"（原卷子）。

规则：
  · 标题以「第 N 章」开头，或标题里有「去重视图」 → chapter
  · 其余（全部题库 / 统一练习 / 统一试卷 / 卷B / 课堂测验 / 随堂测验 …） → paper

    py -3 tools/classify_banks.py --dry
    py -3 tools/classify_banks.py
"""
import json
import os
import re
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "quiz_studio.db")

CH = re.compile(r"^\s*第\s*\d+\s*章")
CH_WORDS = ("去重视图", "章节", "章 ·")


def classify(bank):
    title = str(bank.get("title") or "")
    if bank.get("id") == "bank_dedup_view":
        return "chapter"
    if CH.match(title) or any(w in title for w in CH_WORDS):
        return "chapter"
    return "paper"


def main():
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB)
    rows = [(r[0], json.loads(r[1])) for r in con.execute("SELECT id, data FROM banks")]
    changed = 0
    stat = {"chapter": 0, "paper": 0}
    for bid, bank in rows:
        kind = classify(bank)
        stat[kind] += 1
        if bank.get("kind") != kind:
            bank["kind"] = kind
            changed += 1
            print("  %-20s %-8s %s" % (bid, kind, (bank.get("title") or "")[:40]))
            if not dry:
                con.execute("UPDATE banks SET data=?, updated=? WHERE id=?",
                            (json.dumps(bank, ensure_ascii=False), time.time(), bid))
    if not dry:
        con.commit()
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    print("\n%s：分章节 %d 卷，原卷子 %d 卷，本次改动 %d 卷" % (
        "[dry] 会变成" if dry else "已分类", stat["chapter"], stat["paper"], changed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
