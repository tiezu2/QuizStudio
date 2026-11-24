# -*- coding: utf-8 -*-
"""题库内容体检：跨卷重复、答案覆盖、选项完整性、章节越界。只读。"""
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "quiz_studio.db")
uri = "file:%s?mode=ro" % DB.replace("\\", "/").replace(" ", "%20")
con = sqlite3.connect(uri, uri=True)
con.row_factory = sqlite3.Row


def norm(s):
    return re.sub(r"[\s，。、（）()【】\[\]：:；;？?！!\"'“”‘’]", "", (s or "")).lower()


banks = {}
for r in con.execute("select id, title, data from banks"):
    obj = json.loads(r["data"])
    banks[r["id"]] = (r["title"], obj.get("questions") or [])

print("卷数: %d  题目总数: %d" % (len(banks), sum(len(q) for _t, q in banks.values())))

# 每卷质量
print("\n%-18s %5s %6s %6s %7s %7s  %s" % ("题库id", "题数", "有答案", "空答案", "缺选项", "章节异常", "章节分布"))
for bid, (title, qs) in sorted(banks.items()):
    with_ans = sum(1 for q in qs if (q.get("answer") or "").strip())
    miss_opt = sum(1 for q in qs if q.get("type") in ("single", "multi") and len(q.get("options") or []) < 2)
    bad_ch = sum(1 for q in qs if not isinstance(q.get("ch"), int) or q.get("ch") < 0 or q.get("ch") > 13)
    chs = Counter(q.get("ch") for q in qs)
    chs_s = " ".join("%s:%d" % (k, v) for k, v in sorted(chs.items(), key=lambda x: (x[0] is None, x[0])))
    print("%-18s %5d %6d %6d %7d %7d  %s" % (bid, len(qs), with_ans, len(qs) - with_ans,
                                             miss_opt, bad_ch, chs_s[:70]))

# 跨卷重复
owner = defaultdict(list)
for bid, (_t, qs) in banks.items():
    for q in qs:
        owner[norm(q.get("stem"))].append(bid)
dupe = {k: v for k, v in owner.items() if len(set(v)) > 1}
print("\n跨卷重复题干: %d 组（占全部题干 %.0f%%）" % (
    len(dupe), 100.0 * len(dupe) / max(1, len(owner))))
pair = Counter()
for k, v in dupe.items():
    ids = tuple(sorted(set(v)))
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            pair[(ids[i], ids[j])] += 1
for (a, b), n in pair.most_common(12):
    print("   %-18s <-> %-18s %d 题" % (a, b, n))

# 卷内重复
print("\n卷内重复题干:")
for bid, (_t, qs) in sorted(banks.items()):
    c = Counter(norm(q.get("stem")) for q in qs)
    d = sum(v - 1 for v in c.values() if v > 1)
    if d:
        print("   %-18s %d 处" % (bid, d))

# 答案覆盖总览
tot = sum(len(q) for _t, q in banks.values())
ans = sum(1 for _t, qs in banks.values() for q in qs if (q.get("answer") or "").strip())
print("\n全部题目 %d，有标准答案 %d（%.0f%%），空答案 %d" % (tot, ans, 100.0 * ans / tot, tot - ans))

# 题型分布
types = Counter(q.get("type") for _t, qs in banks.values() for q in qs)
print("题型分布: %s" % dict(types))
con.close()
