# -*- coding: utf-8 -*-
"""把同一道题（题干去重后相同）在所有卷子里的副本对齐成一份权威数据。

第 1 步 答案统一：优先用「官方答案」（没有 _aiAnswer 标记的），
  官方之间不一致就多数票；全都只有 AI 答案时取多数票，平票优先 bank_java3_253。
第 2 步 解析同步：优先用非 AI 写的解析；否则用「带逐选项行（含 ——）」的那份，
  再否则取最长的一份，复制给同组所有副本。

    py -3 tools/unify_duplicates.py --dry
    py -3 tools/unify_duplicates.py
"""
import json
import re
import sqlite3
import sys
import time
import collections
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "quiz_studio.db")
PREFERRED = "bank_java3_253"      # 总集，平票时优先


def norm(s):
    t = re.sub(r"\s+", "", str(s or ""))
    t = re.sub(r"[（(]\s*[)）]", "", t)
    t = re.sub(r"第\s*\d+\s*题", "", t)
    return t


def main():
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB)
    rows = [(r[0], json.loads(r[1])) for r in con.execute("SELECT id, data FROM banks")]
    print("卷子 %d 个" % len(rows))

    groups = collections.defaultdict(list)     # stem -> [(bank_id, q)]
    for bid, bank in rows:
        for q in bank.get("questions") or []:
            groups[(q.get("type"), norm(q.get("stem")))].append((bid, q))

    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    print("重复题组 %d 个（涉及副本 %d 条）" % (len(dup_groups), sum(len(v) for v in dup_groups.values())))

    ans_fixed = exp_fixed = 0
    ans_changed_groups = 0
    for key, items in dup_groups.items():
        # ---------- 第 1 步：答案 ----------
        official = [(b, q) for b, q in items if not q.get("_aiAnswer")]
        pool = official or items
        votes = collections.Counter(str(q.get("answer") or "").strip() for _b, q in pool)
        votes.pop("", None)
        if votes:
            best_n = max(votes.values())
            tops = [a for a, n in votes.items() if n == best_n]
            if len(tops) == 1:
                target = tops[0]
            else:
                pref = [str(q.get("answer") or "").strip() for b, q in items if b == PREFERRED]
                target = pref[0] if pref and pref[0] in tops else sorted(tops)[0]
            changed = False
            for _b, q in items:
                if str(q.get("answer") or "").strip() != target:
                    q["answer"] = target
                    q["_ansSynced"] = 1
                    ans_fixed += 1
                    changed = True
            if changed:
                ans_changed_groups += 1

        # ---------- 第 2 步：解析 ----------
        exps = [((q.get("exp") or "").strip(), q) for _b, q in items]
        exps = [(t, q) for t, q in exps if t]
        if not exps:
            continue
        official_exp = [(t, q) for t, q in exps if not q.get("_aiExp")]
        pool_exp = official_exp or exps
        with_opts = [(t, q) for t, q in pool_exp if "——" in t and re.search(r"(?m)^\s*[A-H]\s*[．.]", t)]
        pick_pool = with_opts or pool_exp
        best_exp, _src = max(pick_pool, key=lambda x: len(x[0]))
        for _b, q in items:
            if (q.get("exp") or "").strip() != best_exp:
                q["exp"] = best_exp
                q["_expSynced"] = 1
                if not q.get("_aiExp"):
                    q["_aiExp"] = 1
                exp_fixed += 1

    print("答案对齐：%d 条副本（%d 个组）" % (ans_fixed, ans_changed_groups))
    print("解析对齐：%d 条副本" % exp_fixed)

    if dry:
        print("[dry] 没有写库")
        con.close()
        return 0

    now = time.time()
    for bid, bank in rows:
        con.execute("UPDATE banks SET data=?, updated=? WHERE id=?",
                    (json.dumps(bank, ensure_ascii=False), now, bid))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    print("已写库")
    return 0


if __name__ == "__main__":
    sys.exit(main())
