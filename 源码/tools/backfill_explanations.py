# -*- coding: utf-8 -*-
"""给题库里没有解析的题用 AI 补解析（含每个选项的对错点）。

    py -3 tools/backfill_explanations.py --dry              # 只看要补多少
    py -3 tools/backfill_explanations.py                    # 全部补
    py -3 tools/backfill_explanations.py --limit 50         # 先补 50 道
    py -3 tools/backfill_explanations.py --bank bank_ch08   # 只补一卷
    py -3 tools/backfill_explanations.py --types single,blank

规则：
  · 只补 exp 为空的题，已有解析一律不覆盖；
  · 解析写进 exp，并打 _aiExp=1 标记；
  · 题型映射成中文交给模型（单选/多选/判断/填空/简答/编程）。
"""
import json
import os
import sys
import time
import urllib.request

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.path.isdir(os.path.join(PROJ, "源码")):            # 脚本在 源码\tools|importers 下时上跳
    PROJ = os.path.dirname(PROJ)
# 运行时文件（server.py / index.html / 数据库 / 配置）都在 PROJ\程序 下
ROOT = os.path.join(PROJ, "程序") if os.path.isdir(os.path.join(PROJ, "程序")) else PROJ
BASE = "http://127.0.0.1:8770"
TYPE_CN = {"single": "单选题", "multi": "多选题", "judge": "判断题", "blank": "填空题",
           "short": "简答题", "code": "编程题"}
SEND = 25           # 每次 HTTP 请求送几题（服务端按 5 题/批调模型）
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(path):
    with OP.open(BASE + path, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, obj, timeout=1800):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with OP.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    args = sys.argv
    dry = "--dry" in args
    only_bank = args[args.index("--bank") + 1] if "--bank" in args else ""
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 0
    types = set()
    if "--types" in args:
        types = {t.strip() for t in args[args.index("--types") + 1].split(",") if t.strip()}

    plan = []
    for b in get("/api/banks")["banks"]:
        if only_bank and b["id"] != only_bank:
            continue
        full = get("/api/banks/" + b["id"])["bank"]
        miss = [q for q in (full.get("questions") or [])
                if not str(q.get("exp") or "").strip() and (not types or q.get("type") in types)]
        if miss:
            plan.append((full, miss))

    total = sum(len(m) for _f, m in plan)
    print("待补解析：%d 卷 / %d 题%s" % (len(plan), total, "（--limit %d）" % limit if limit else ""))
    for full, miss in plan:
        print("  %-18s 缺 %3d 题" % (full["id"], len(miss)))
    if dry or not plan:
        return 0

    done = 0
    t0 = time.time()
    budget = limit
    for full, miss in plan:
        batch = miss if not budget else miss[:budget]
        if not batch:
            break
        tasks = [{"id": q["id"], "type": TYPE_CN.get(q.get("type"), q.get("type") or ""),
                  "stem": q.get("stem") or "",
                  "opts": " | ".join("%s.%s" % (o.get("k"), (o.get("v") or "").replace("\n", " "))
                                     for o in (q.get("options") or [])),
                  "answer": str(q.get("answer") or q.get("ref") or "")[:200]}
                 for q in batch]
        got, provider = {}, ""
        for i in range(0, len(tasks), SEND):
            chunk = tasks[i:i + SEND]
            try:
                r = post("/api/explanations", {"questions": chunk})
            except Exception as exc:  # noqa: BLE001
                print("  [x] %s 第 %d 批出错：%s" % (full["id"], i // SEND + 1, exc), flush=True)
                continue
            if r.get("ok"):
                got.update(r.get("map") or {})
                provider = r.get("provider") or provider
        n = 0
        for q in batch:
            exp = got.get(q["id"])
            if exp:
                q["exp"] = exp
                q["_aiExp"] = 1
                n += 1
        if n:
            post("/api/banks", full)
        done += n
        print("  %-18s 补 %3d / %3d 题（%s）累计 %d，用时 %.0fs" % (
            full["id"], n, len(batch), provider or "-", done, time.time() - t0), flush=True)
        if budget:
            budget -= len(batch)
            if budget <= 0:
                break

    print("\n完成：补解析 %d 题，用时 %.1f 分钟" % (done, (time.time() - t0) / 60.0))
    left = 0
    for b in get("/api/banks")["banks"]:
        full = get("/api/banks/" + b["id"])["bank"]
        left += sum(1 for q in (full.get("questions") or []) if not str(q.get("exp") or "").strip())
    print("库里仍缺解析：%d 题" % left)
    return 0


if __name__ == "__main__":
    sys.exit(main())
