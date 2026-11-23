# -*- coding: utf-8 -*-
"""重建「大题」三类卷（编程 / 改错 / 填空）：

  · 每类一份总卷（按章节排序）
  · 每类按章节再拆成单章卷（编程题 · 第 7 章 …）
  · 每道题带 _from：它出现在哪些卷子里（显示「出自：…」）

    py -3 源码/tools/rebuild_bigq_all.py
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
KIND_CN = {"prog": "编程题", "fix": "改错题", "fill": "填空题"}
SKIP_PREFIX = ("bank_bigq_", "bank_prog_ch", "bank_fix_ch", "bank_fill_ch")

CH_RULES = [
    (9, ("抽象", "接口", "interface", "abstract", "implements")),
    (8, ("继承", "多态", "super", "覆盖", "override", "父类", "子类", "extends", "上转型")),
    (13, ("jdbc", "数据库", "sql", "connection", "resultset", "statement")),
    (12, ("集合", "arraylist", "hashmap", "list", "map")),
    (11, ("字符串", "string", "stringbuffer", "stringbuilder", "正则")),
    (10, ("异常", "try", "catch", "finally", "throw", "exception")),
    (6, ("数组", "[ ]", "[]")),
    (5, ("方法", "重载", "return")),
    (4, ("循环", "for(", "while", "do-while")),
    (3, ("if(", "switch", "分支")),
    (2, ("数据类型", "运算符", "变量")),
    (1, ("jdk", "jre", "jvm", "环境")),
]


def norm(s):
    t = re.sub(r"\s+", "", str(s or ""))
    t = re.sub(r"[（(）)：:，,。．、\"'`；;？?]", "", t)
    return re.sub(r"第\s*\d+\s*题", "", t)


def subtype(stem):
    s = stem or ""
    if "SPACE" in s or "[?]" in s or "【?】" in s:
        return "fill"
    if "FOUND" in s:
        return "fix"
    return "prog"


def guess_ch(q):
    if q.get("ch"):
        return q["ch"]
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

    best, sources = {}, {}
    for bid, bank in rows:
        if bid.startswith(SKIP_PREFIX):
            continue
        title = (bank.get("title") or bid).replace("Java语言程序设计III · ", "")
        for q in bank.get("questions") or []:
            if q.get("type") != "code":
                continue
            key = norm(q.get("stem"))
            if not key:
                continue
            sources.setdefault(key, [])
            if title not in sources[key]:
                sources[key].append(title)
            score = (len(q.get("exp") or "") + len(q.get("ref") or "") * 2
                     + len(q.get("answer") or "") * 3 + len(q.get("stem") or "") // 4)
            if key not in best or score > best[key][0]:
                best[key] = (score, q, bid)

    groups = {"prog": [], "fix": [], "fill": []}
    for key, (_score, q, _bid) in best.items():
        item = dict(q)
        item["ch"] = guess_ch(item)
        item["_from"] = sources.get(key, [])[:4]
        groups[subtype(item.get("stem"))].append(item)

    now = time.time()
    created = []
    for kind, items in groups.items():
        items.sort(key=lambda q: (q.get("ch") or 99, str(q.get("no") or "")))
        # 总卷
        agg_id = "bank_bigq_%s" % kind
        agg_title = "%s · 按章节" % KIND_CN[kind]
        agg = {
            "id": agg_id, "title": agg_title, "subject": "Java语言程序设计III",
            "time": time.strftime("%Y-%m-%d %H:%M"), "kind": kind,
            "chapters": [{"id": c, "name": "第 %d 章 · %s" % (c, CHAPTERS[c]), "tag": ""}
                         for c in sorted({q["ch"] for q in items if q.get("ch")})],
            "questions": [dict(q, id="%s_%d" % (kind, i), no=i) for i, q in enumerate(items, 1)],
            "warnings": ["同题只留一份；每题标注出自哪些卷子"],
        }
        # 单章卷
        parts = []
        for ch in sorted({q["ch"] for q in items if q.get("ch")}):
            sub = [q for q in items if q["ch"] == ch]
            bid = "bank_%s_ch%02d" % (kind, ch)
            parts.append({
                "id": bid, "title": "%s · 第 %d 章 %s" % (KIND_CN[kind], ch, CHAPTERS[ch]),
                "subject": "Java语言程序设计III", "time": agg["time"], "kind": kind,
                "chapters": [{"id": ch, "name": "第 %d 章 · %s" % (ch, CHAPTERS[ch]), "tag": ""}],
                "questions": [dict(q, id="%s%02d_%d" % (kind[0], ch, i), no=i)
                              for i, q in enumerate(sub, 1)],
                "warnings": ["%s按章节拆分的单章卷" % KIND_CN[kind]],
            })

        for bank in [agg] + parts:
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
            created.append((bank["id"], bank["title"], len(bank["questions"])))

    # 清掉旧的单章编程卷（命名已统一到 bank_prog_chNN）
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()

    print("重建完成：")
    for bid, title, n in created:
        print("  %-18s %-36s %3d 题" % (bid, title, n))
    print("合计 %d 卷（%d 道大题）" % (len(created), sum(len(v) for v in groups.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
