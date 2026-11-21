# -*- coding: utf-8 -*-
"""把教材大题按章节并进现有的章节卷（ch07 / ch08 / ch09），然后删掉单独那份卷。

- 第 7 章 · 类与对象        -> bank_ch07
- 第 8 章 · 继承与多态      -> bank_ch08
- 第 9 章 · 抽象类与接口    -> bank_ch09
- 第 10 章 · 多态与综合     -> 按内容拆：继承/多态类进 ch08，接口/工厂类进 ch09
"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8770"
SRC = "bank_textbook_bigq"
TARGET = {"ch1": ("bank_ch07", 7), "ch2": ("bank_ch08", 8), "ch3": ("bank_ch09", 9)}

# 第 10 章那批按内容归类
CH4_TO_CH9 = ("Shape 接口", "图形绘制", "手机卡", "Sim", "汽车生产工厂", "工厂", "支付", "Payment")

op = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(path):
    with op.open(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, obj):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with op.open(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    dry = "--dry" in sys.argv
    src = get("/api/banks/" + SRC)["bank"]
    plan = {"bank_ch07": [], "bank_ch08": [], "bank_ch09": []}

    for q in src["questions"]:
        key = "ch%d" % q.get("ch", 0)
        if key in TARGET:
            plan[TARGET[key][0]].append((q, TARGET[key][1]))
        else:  # 第 10 章 · 多态与综合
            hay = q.get("stem") or ""
            to9 = any(k in hay for k in CH4_TO_CH9)
            plan["bank_ch09" if to9 else "bank_ch08"].append((q, 9 if to9 else 8))

    for bid, items in plan.items():
        bank = get("/api/banks/" + bid)["bank"]
        base_no = len(bank["questions"])
        for i, (q, ch) in enumerate(items, 1):
            new = dict(q)
            new["id"] = "q%d" % (base_no + i)
            new["no"] = base_no + i
            new["ch"] = ch
            new["_src"] = "教材大题 · %s" % src["title"]
            bank["questions"].append(new)
        print("%-12s +%2d 题  -> %d 题" % (bid, len(items), len(bank["questions"])))
        if not dry:
            post("/api/banks", bank)

    if dry:
        print("[dry] 没有写入")
        return 0

    post("/api/banks/delete", {"id": SRC})
    print("已删除单独的教材卷 %s" % SRC)
    for bid in plan:
        b = get("/api/banks/" + bid)["bank"]
        chs = sorted({q.get("ch") for q in b["questions"]})
        types = {}
        for q in b["questions"]:
            types[q["type"]] = types.get(q["type"], 0) + 1
        print("  %-12s 题数=%-4d 章节=%s 题型=%s" % (bid, len(b["questions"]), chs, types))
    return 0


if __name__ == "__main__":
    sys.exit(main())
