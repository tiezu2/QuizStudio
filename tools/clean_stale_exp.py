# -*- coding: utf-8 -*-
"""清理题库里过期的占位解析。

早期从东软平台导入时，平台没给答案的题会在 exp 里写一句
「（本题平台未公布标准答案，自动判分会记为未答对）」。
现在这些题都已有答案（多数是 AI 补的），判分正常，这句就变成误导信息了，要删掉。

    py -3 tools/clean_stale_exp.py --dry
    py -3 tools/clean_stale_exp.py
"""
import json
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "quiz_studio.db")

# 要删的句子（括号可有可无）
PATTERNS = [
    r"[（(]?\s*本题平台未公布标准答案[，,]\s*自动判分会记为未答对\s*[)）]?",
    r"[（(]?\s*平台未公布标准答案[，,]\s*自动判分会记为未答对\s*[)）]?",
]


def clean_exp(text):
    t = str(text or "")
    for p in PATTERNS:
        t = re.sub(p, "", t)
    # 清理删除后残留的全角空格 / 换行
    t = re.sub(r"[　\s]*\n\s*", "\n", t).strip("　 \n")
    return t


def main():
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB)
    rows = list(con.execute("SELECT id, data FROM banks"))
    changed_banks = changed_q = 0
    for bid, data in rows:
        bank = json.loads(data)
        dirty = False
        for q in bank.get("questions") or []:
            before = q.get("exp") or ""
            after = clean_exp(before)
            if after != before:
                q["exp"] = after
                changed_q += 1
                dirty = True
        if dirty:
            changed_banks += 1
            if not dry:
                con.execute("UPDATE banks SET data=?, updated=? WHERE id=?",
                            (json.dumps(bank, ensure_ascii=False), __import__("time").time(), bid))
    if not dry:
        con.commit()
    con.close()
    print("%s清理题目 %d 道，涉及卷子 %d 个" % ("[dry] 会" if dry else "已", changed_q, changed_banks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
