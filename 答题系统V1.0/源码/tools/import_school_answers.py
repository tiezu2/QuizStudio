# -*- coding: utf-8 -*-
"""把 school 项目里的作答写进题库对应大题的 exp（解析）字段。

原则：只写 exp，不动 answer —— 这些是**你的作答**，不是标准答案；
    AI 判分时 ref 仍为空，它会自己解题，不会被这份作答带偏。

用法：
    py -3 tools/import_school_answers.py --dry     只看会改哪些题
    py -3 tools/import_school_answers.py           真写（走 /api/banks 覆盖）
"""
import glob
import json
import os
import sys
import urllib.request

SERVER = "http://127.0.0.1:8770"
SRC = r"E:\桌面映射\Java\Java_oop\school\src"

# 文件 -> 用来在题干里定位的关键词
MAP = [
    ("school/work1/Test.java", ["findPremeter"], "Prog1 矩形周长"),
    ("school/work2/Test.java", ["calculateScore"], "Prog1 成绩"),
    ("school/work3/Test.java", ["输出图书基本信息"], "Prog1 图书"),
    ("school/work4/Fen.java", ["电风扇"], "Fan 电风扇"),
    ("school/work5/Teacher.java", ["课时当量"], "Teacher 课时费"),
    ("school/work6/Account.java", ["模拟银行账户"], "Account 银行账户"),
    ("extends1/Test.java", ["派生出子类Teacher"], "Teacher extends Person"),
    ("extends2/Test.java", ["派生出子类Student"], "Student extends Person"),
    ("extends3/Test.java", ["派生出子类Milk"], "Milk extends Goods"),
    ("extends4/Test.java", ["派生出子类Apple"], "Apple extends Goods"),
    ("extends5/Test.java", ["派生出子类Clothing"], "Clothing extends Goods"),
]


def api(path, method="GET", obj=None):
    data = None
    headers = {}
    if obj is not None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(SERVER + path, data=data, method=method, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    dry = "--dry" in sys.argv
    banks = api("/api/banks")["banks"]
    full = {}
    for b in banks:
        full[b["id"]] = api("/api/banks/" + b["id"])["bank"]

    changed = {bid: 0 for bid in full}
    for rel, keys, label in MAP:
        path = os.path.join(SRC, rel.replace("/", os.sep))
        if not os.path.exists(path):
            print("跳过（文件不存在）: %s" % rel)
            continue
        code = open(path, encoding="utf-8", errors="replace").read().rstrip()
        block = "【你的作答·school 项目】%s\n%s" % (rel, code)
        hit = 0
        for bid, bank in full.items():
            for q in bank["questions"]:
                stem = q.get("stem") or ""
                if all(k in stem for k in keys) and q.get("type") == "code":
                    q["exp"] = block
                    changed[bid] += 1
                    hit += 1
        print("%-42s %-22s 命中 %d 题" % (label, rel, hit))

    todo = {bid: n for bid, n in changed.items() if n}
    print("\n将修改的卷子: " + ("无" if not todo else ", ".join("%s(%d题)" % kv for kv in todo.items())))
    if dry:
        print("[dry] 没有写入")
        return 0
    for bid, n in todo.items():
        r = api("/api/banks", "POST", full[bid])
        print("写入 %-18s %d 题 -> %s" % (bid, n, json.dumps(r, ensure_ascii=False)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
