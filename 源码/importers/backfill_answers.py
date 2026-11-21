# -*- coding: utf-8 -*-
"""给题库里所有「没有标准答案」的题跑一遍 AI 作答，并把答案写回数据库。

    py -3 importers/backfill_answers.py --dry            # 只看要补多少题
    py -3 importers/backfill_answers.py                  # 全部补
    py -3 importers/backfill_answers.py --bank bank_ch08 # 只补一卷
    py -3 importers/backfill_answers.py --limit 50       # 只补前 50 题（试水）

规则跟前端 index.html 的 applyAiAnswer 保持一致：
  单选/多选 -> 只留 A-H 字母（多选排序去重；题型是猜的且题干像多选时自动纠正为多选）
  判断     -> T / F
  填空     -> 写 answer 和 ref
  简答/编程 -> 写 ref（参考答案）
每道被补的题打 _aiAnswer = 1，原题有答案的一律不碰。
"""
import json
import re
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8770"
SEND_PER_CALL = 200          # /api/answers 单次最多 400，这里留余量
TYPE_CN = {"single": "单选题", "multi": "多选题", "judge": "判断题", "blank": "填空题",
           "short": "简答题", "code": "编程题"}
MULTI_HINT = re.compile(r"哪些|多选|多项|至少|正确的有|全部|哪些是|哪几个")
JUDGE_T = re.compile(r"^(对|正确|√|✓|是|T|TRUE|Y|YES)$", re.I)
JUDGE_F = re.compile(r"^(错|错误|×|✗|否|F|FALSE|N|NO)$", re.I)

op = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(path):
    with op.open(BASE + path, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, obj):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with op.open(req, timeout=900) as r:
        return json.loads(r.read().decode("utf-8"))


def has_answer(q):
    return bool(str(q.get("answer") or "").strip() or str(q.get("ref") or "").strip())


def apply_answer(q, raw):
    t = str(raw or "").strip()
    if not t:
        return False
    typ = q.get("type")
    if typ in ("single", "multi"):
        letters = "".join(sorted(set(re.findall(r"[A-H]", t.upper()))))
        if not letters:
            return False
        if len(letters) > 1 and typ == "single" and MULTI_HINT.search(q.get("stem") or ""):
            q["type"] = "multi"
            typ = "multi"
        q["answer"] = letters if typ == "multi" else letters[:1]
    elif typ == "judge":
        if JUDGE_T.match(t):
            q["answer"] = "T"
        elif JUDGE_F.match(t):
            q["answer"] = "F"
        else:
            return False
    elif typ == "blank":
        q["answer"] = t
        if not str(q.get("ref") or "").strip():
            q["ref"] = t
    else:
        q["ref"] = t
        q["answer"] = str(q.get("answer") or "")
    q["_aiAnswer"] = 1
    return True


def main():
    dry = "--dry" in sys.argv
    only = ""
    if "--bank" in sys.argv:
        only = sys.argv[sys.argv.index("--bank") + 1]
    limit = 0
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    banks = get("/api/banks")["banks"]
    plan = []
    for b in banks:
        if only and b["id"] != only:
            continue
        full = get("/api/banks/" + b["id"])["bank"]
        miss = [q for q in full["questions"] if not has_answer(q)]
        if miss:
            plan.append((full, miss))

    want = sum(len(m) for _, m in plan)
    print("待补答案：%d 卷 / %d 题" % (len(plan), min(want, limit) if limit else want))
    for full, miss in plan:
        print("  %-18s 缺 %3d 题" % (full["id"], len(miss)))
    if dry or not plan:
        return 0

    filled_total = skipped_total = 0
    t_start = time.time()
    budget = limit
    for full, miss in plan:
        batch = miss if not budget else miss[:budget]
        if not batch:
            break
        tasks = [{"id": q["id"], "type": TYPE_CN.get(q["type"], q.get("type") or ""),
                  "stem": q.get("stem") or "",
                  "opts": " | ".join("%s.%s" % (o.get("k"), o.get("v")) for o in (q.get("options") or []))}
                 for q in batch]
        got, provider = {}, ""
        for i in range(0, len(tasks), SEND_PER_CALL):
            chunk = tasks[i:i + SEND_PER_CALL]
            try:
                r = post("/api/answers", {"questions": chunk})
            except Exception as exc:  # noqa: BLE001
                print("  [x] %s 第 %d 批出错：%s" % (full["id"], i // SEND_PER_CALL + 1, exc))
                continue
            if r.get("ok"):
                got.update(r.get("map") or {})
                provider = r.get("provider") or provider
        n = 0
        for q in batch:
            if apply_answer(q, got.get(q["id"])):
                n += 1
        filled_total += n
        skipped_total += len(batch) - n
        if n:
            post("/api/banks", full)
        print("  %-18s 补 %3d / %3d 题（%s）累计 %d，用时 %.0fs" % (
            full["id"], n, len(batch), provider or "-", filled_total, time.time() - t_start),
            flush=True)
        if budget:
            budget -= len(batch)
            if budget <= 0:
                break

    print("\n完成：补了 %d 题，没判出来 %d 题，总用时 %.1f 分钟" % (
        filled_total, skipped_total, (time.time() - t_start) / 60.0))
    # 汇总复查
    left = 0
    for b in get("/api/banks")["banks"]:
        full = get("/api/banks/" + b["id"])["bank"]
        left += sum(1 for q in full["questions"] if not has_answer(q))
    print("库里仍缺答案：%d 题" % left)
    return 0


if __name__ == "__main__":
    sys.exit(main())
