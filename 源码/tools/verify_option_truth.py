# -*- coding: utf-8 -*-
"""「解析文字」与「选项真值」一致性校验。

对每道单选题：
  1) 先不看答案键，让模型独立判断每个选项本身说法对不对（true/false）；
  2) 用这份判断核对：
     a. 解析里每行写的「说法正确/说法错误」是否与判断一致；
     b. 题库答案是否落在「说法正确」的选项里（单选取其一）。
不一致的收集进报告，交人工裁决。

    py -3 源码/tools/verify_option_truth.py
产物：_option_truth.json / 选项真值校验报告.md
"""
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.path.isdir(os.path.join(PROJ, "源码")):
    PROJ = os.path.dirname(PROJ)
ROOT = os.path.join(PROJ, "程序") if os.path.isdir(os.path.join(PROJ, "程序")) else PROJ
DB = os.path.join(ROOT, "quiz_studio.db")
OUT = os.path.join(PROJ, "_option_truth.json")
REPORT = os.path.join(PROJ, "选项真值校验报告.md")

SYS = ("你是 Java 课程助教。只输出 JSON，不要解释。\n"
       '格式：{"A":"true|false","B":"true|false", ...}\n'
       "true = 该选项的说法本身是正确的；false = 说法本身有错。"
       "注意：不要考虑题目问的是什么，只判断每个选项的陈述真假。")

OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def key():
    return json.load(open(os.path.join(ROOT, "quiz_studio_llm.json"), encoding="utf-8"))["api_key"]


def ask(stem, opts, k):
    payload = {
        "model": "glm-4-flash",
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": "题干：%s\n选项：\n%s" % (
                         stem[:600], "\n".join("%s. %s" % (o["k"], (o["v"] or "")[:200]) for o in opts))}],
        "max_tokens": 400, "temperature": 0.1,
    }
    req = urllib.request.Request("https://open.bigmodel.cn/api/paas/v4/chat/completions",
                                 data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + k})
    with urllib.request.urlopen(req, timeout=120) as r:
        j = json.loads(r.read().decode())
    txt = ((j.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    i, j2 = txt.find("{"), txt.rfind("}")
    if i < 0 or j2 <= i:
        return {}
    data = json.loads(txt[i:j2 + 1])
    return {str(k2).strip().upper()[:1]: str(v).strip().lower().startswith("t") for k2, v in data.items()}


def norm(s):
    t = re.sub(r"\s+", "", str(s or ""))
    return re.sub(r"[（(）)：:，,。．、\"'`；;？?]", "", t)


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    banks = [(r["id"], json.loads(r["data"])) for r in con.execute("SELECT id, data FROM banks")]
    con.close()

    best = {}
    for bid, bank in banks:
        if bid.startswith(("bank_choice_ch", "bank_bigq_choice", "bank_prog_ch", "bank_bigq_prog",
                           "bank_fix_ch", "bank_bigq_fix", "bank_fill_ch", "bank_bigq_fill",
                           "bank_java3_253")):
            continue
        for q in bank.get("questions") or []:
            if q.get("type") not in ("single", "multi"):
                continue
            if len(q.get("options") or []) < 2:
                continue
            k = norm(q.get("stem"))
            if not k:
                continue
            score = len(q.get("exp") or "") + len(str(q.get("answer") or "")) * 3
            if k not in best or score > best[k][0]:
                best[k] = (score, q)

    items = [v[1] for v in best.values()]
    print("待校验 %d 道选择题" % len(items))
    k = key()
    results, done = {}, 0
    for q in items:
        try:
            truth = ask(q.get("stem") or "", q.get("options") or [], k)
        except Exception as exc:  # noqa: BLE001
            print("  失败 %s: %s" % (norm(q.get("stem"))[:16], exc), flush=True)
            continue
        if not truth:
            continue
        results[norm(q.get("stem"))] = {
            "stem": q.get("stem"), "answer": q.get("answer"), "truth": truth,
            "exp": q.get("exp") or "", "no": q.get("no")}
        done += 1
        if done % 20 == 0:
            print("  已判 %d/%d" % (done, len(items)), flush=True)
            json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    ans_bad, exp_bad = [], []
    for k2, r in results.items():
        truth = r["truth"]
        ans = str(r["answer"] or "").upper()
        letters = [c for c in ans if "A" <= c <= "H"]
        if letters:
            ok = all(truth.get(c, False) for c in letters)
            if not ok:
                ans_bad.append(r)
        for ln in (r["exp"] or "").splitlines():
            m = re.match(r"^\s*([A-H])\s*[．.、]", ln)
            if not m:
                continue
            letter = m.group(1)
            said_correct = "说法正确" in ln
            said_wrong = "说法错误" in ln
            if not (said_correct or said_wrong):
                continue
            real = truth.get(letter)
            if real is None:
                continue
            if (said_correct and not real) or (said_wrong and real):
                exp_bad.append((r, letter, real, ln.strip()))
                break

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("# 选项真值校验报告\n\n生成时间：%s\n\n" % time.strftime("%Y-%m-%d %H:%M"))
        f.write("- 校验题数：%d（单选题，已对全库去重）\n" % len(results))
        f.write("- 答案与真值冲突：**%d 道**\n" % len(ans_bad))
        f.write("- 解析里选项对错写反：**%d 道**\n\n" % len(exp_bad))
        f.write("## 一、答案可能存错（题库答案不在「说法正确」的选项里）\n\n")
        for r in ans_bad:
            f.write("### %s\n" % (r["stem"] or "").replace("\n", " ")[:80])
            f.write("- 题库答案：`%s`　模型判断正确项：%s\n" % (
                r["answer"], "、".join(k3 for k3, v in r["truth"].items() if v)))
            f.write("- 选项：\n")
            for ln in (r["exp"] or "").splitlines():
                pass
            f.write("\n")
        f.write("\n## 二、解析里选项对错写反\n\n")
        for r, letter, real, ln in exp_bad:
            f.write("- **%s**\n  - %s 实际说法：%s；解析写的是：%s\n" % (
                (r["stem"] or "").replace("\n", " ")[:60], letter,
                "正确" if real else "错误", ln[:70]))
    print("\n完成：答案冲突 %d 道，解析写反 %d 道" % (len(ans_bad), len(exp_bad)))
    print("报告：%s" % REPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
