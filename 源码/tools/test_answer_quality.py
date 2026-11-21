# -*- coding: utf-8 -*-
"""用题库里已有的标准答案当基准，实测「AI 逐题作答」的准确率和耗时。

用法：
    py -3 tools/test_answer_quality.py              # 默认 20 题
    py -3 tools/test_answer_quality.py --n 40
    py -3 tools/test_answer_quality.py --model glm-4-flash
"""
import json
import os
import random
import sys
import time
import urllib.request

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.path.isdir(os.path.join(PROJ, "源码")):            # 脚本在 源码\tools|importers 下时上跳
    PROJ = os.path.dirname(PROJ)
# 运行时文件（server.py / index.html / 数据库 / 配置）都在 PROJ\程序 下
ROOT = os.path.join(PROJ, "程序") if os.path.isdir(os.path.join(PROJ, "程序")) else PROJ
sys.path.insert(0, ROOT)
import server  # noqa: E402

BASE = "http://127.0.0.1:8770"
OBJ = ("single", "multi", "judge", "blank")


def get(path):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def norm(a):
    return "".join(sorted(str(a or "").upper().replace(" ", "").replace("，", ",").split(",")[0]))


def main():
    n = 20
    if "--n" in sys.argv:
        n = int(sys.argv[sys.argv.index("--n") + 1])
    model = ""
    if "--model" in sys.argv:
        model = sys.argv[sys.argv.index("--model") + 1]

    server.load_ai_config()
    if model:
        server.PROVIDERS = [{"name": "zhipu", "model": model,
                             "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions"}]
        server.MIN_AI_GAP = 0.0
    print("通道：%s" % ", ".join("%s(%s)" % (p["name"], p.get("model")) for p in server.PROVIDERS))

    banks = get("/api/banks")["banks"]
    random.seed(20261118)
    picked = []
    for b in banks:
        full = get("/api/banks/" + b["id"])["bank"]
        for q in full["questions"]:
            if q.get("type") in OBJ and str(q.get("answer") or "").strip():
                picked.append((b["title"], q))
    random.shuffle(picked)
    picked = picked[:n]
    print("抽到 %d 道有标准答案的题（单选/多选/判断/填空）\n" % len(picked))

    items = [{"id": "q%d" % i, "type": {"single": "单选题", "multi": "多选题",
                                        "judge": "判断题", "blank": "填空题"}[q["type"]],
              "stem": q["stem"],
              "opts": " | ".join("%s.%s" % (o["k"], o["v"]) for o in (q.get("options") or []))}
             for i, (_, q) in enumerate(picked)]

    t0 = time.time()
    mapping, provider, asked = server.ai_solve(items)
    dt = time.time() - t0
    print("送 %d 题，回来 %d 题，用时 %.1fs（%.1fs/题），通道 %s\n" % (
        asked, len(mapping), dt, dt / max(len(mapping), 1), provider))

    ok = bad = 0
    for i, (title, q) in enumerate(picked):
        want = q["answer"]
        got = mapping.get("q%d" % i, "")
        good = norm(got) == norm(want) if q["type"] in ("single", "multi") else \
            (str(got).strip() == str(want).strip())
        if good:
            ok += 1
        else:
            bad += 1
        print("%s 第%d题 [%s] 标准:%s  AI:%s  %s" % (
            "✓" if good else "✗", i + 1, q["type"], want, got or "(空)",
            (q["stem"] or "")[:46].replace("\n", " ")))
    print("\n准确率 %d/%d = %.1f%%" % (ok, ok + bad, 100.0 * ok / max(ok + bad, 1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
