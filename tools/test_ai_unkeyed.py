# -*- coding: utf-8 -*-
"""端到端验证：题库缺答案的选择题会不会被判「错误」。

流程和前端一致：POST /api/grade 传 pending 项（带 opts、unkeyed），
再轮询 /api/report 看 judge 是否拿到判定。

用法：py -3 tools/test_ai_unkeyed.py [题库id] [作答字母]
"""
import json
import sys
import time
import urllib.request

SERVER = "http://127.0.0.1:8770"
BANK = sys.argv[1] if len(sys.argv) > 1 else "bank_quiz_jb1"
ANSWER = sys.argv[2] if len(sys.argv) > 2 else "B"
COUNT = int(sys.argv[3]) if len(sys.argv) > 3 else 6


def get(path):
    with urllib.request.urlopen(SERVER + path, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, obj):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(SERVER + path, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    bank = get("/api/banks/" + BANK)["bank"]
    qs = bank["questions"][:COUNT]
    items = []
    for q in qs:
        ref = (q.get("answer") or "").strip()
        it = {"id": q["id"], "type": q["type"], "stem": q["stem"], "ref": ref,
              "user": ANSWER if q["type"] == "single" else "", "score": q.get("score") or 0}
        if q.get("options"):
            it["opts"] = " | ".join("%s.%s" % (o["k"], o["v"]) for o in q["options"])
        if not ref:
            it["unkeyed"] = True
        items.append(it)
    payload = {
        "title": bank["title"],
        "summary": {"总题数": len(qs), "已答": len([i for i in items if i["user"]]), "正确": 0,
                    "错误": 0, "半对": 0, "正确率": "0%"},
        "chapters": [],
        "wrong": [],
        "subjective": [i for i in items if i["user"]],
    }
    print("送判 %d 题（全部 unkeyed：%s）" % (len(payload["subjective"]),
                                       all(i.get("unkeyed") for i in payload["subjective"])))
    r = post("/api/grade", payload)
    print("POST /api/grade -> %s" % json.dumps(r, ensure_ascii=False))
    sid = r.get("sid")
    t0 = time.time()
    while time.time() - t0 < 300:
        time.sleep(5)
        j = get("/api/report?sid=%d" % sid)
        if j.get("status") == "pending":
            print("  ...%ds 仍在判" % int(time.time() - t0))
            continue
        judge = j.get("judge") or {}
        print("\n状态: %s  用时 %ss  通道 %s" % (j.get("status"), j.get("elapsed"), j.get("provider")))
        print("error: %s" % (j.get("error") or "（无）"))
        print("判定条数: %d / 送去 %d" % (len(judge), len(payload["subjective"])))
        for k, v in list(judge.items())[:6]:
            print("   %-24s %-5s %-20s %s" % (k, v.get("verdict"), v.get("comment", "")[:40],
                                              ""))
        print("\n诊断前 200 字:\n%s" % (j.get("review") or "")[:200])
        return 0
    print("超时未出结果")
    return 1


if __name__ == "__main__":
    sys.exit(main())
