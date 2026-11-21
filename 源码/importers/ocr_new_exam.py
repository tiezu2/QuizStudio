# -*- coding: utf-8 -*-
"""把 E:\\Desktop\\新题 里的截图 OCR 成题目，去重后插入题库（只加新题）。

    py -3 源码/importers/ocr_new_exam.py --dry        # 只 OCR + 统计，不写库
    py -3 源码/importers/ocr_new_exam.py

产物：
    _ocr_new.json      每张图的原始 OCR 文本（可复查/重解析）
    _ocr_new_qs.json   解析出来的题目（去重前/后都记）
"""
import base64
import glob
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
SRC_DIR = r"E:\Desktop\新题"
RAW_JSON = os.path.join(PROJ, "_ocr_new.json")
QS_JSON = os.path.join(PROJ, "_ocr_new_qs.json")
BANK_ID = "bank_new_20261121"
BANK_TITLE = "新题（万维平台截图）"

PROMPT = (
    "这是一张在线考试平台的题目截图。请把题目整理成 JSON，只输出 JSON，不要解释。\n"
    '格式：{"type":"单选|多选|判断|填空|简答|程序","stem":"题干原文",'
    '"options":[{"k":"A","v":"选项文字"}],"answer":"题目给出的答案，没有就留空"}\n'
    "要求：\n"
    "1. 题干逐字转录，包含给出的代码/表格（保留换行）；\n"
    "2. 选项只要 A/B/C/D 文字，去掉界面上的按钮文字；\n"
    "3. 单选题 type=单选；多选题 type=多选；判断题 type=判断（选项可能是 对/错）；\n"
    "4. 截图上没有答案就 answer 留空；\n"
    "5. 程序题/简答题 type=程序，stem 里带上题目要求和给出的代码。"
)


def api_key():
    with open(os.path.join(ROOT, "quiz_studio_llm.json"), encoding="utf-8") as f:
        return json.load(f)["api_key"]


def ocr_one(path, key, retries=2):
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    payload = {
        "model": "glm-4v-flash",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
            {"type": "text", "text": PROMPT},
        ]}],
        "max_tokens": 1024,
        "temperature": 0.1,
    }
    req = urllib.request.Request(
        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    last = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                j = json.loads(r.read().decode())
            return ((j.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 + attempt * 3)
    raise last


def parse_json_loose(txt):
    t = (txt or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        t = t[i:j + 1]
    try:
        return json.loads(t)
    except Exception:
        # 代码题里常有字符串内裸换行，strict=False 能容忍
        return json.loads(t, strict=False)


def type_cn_to_key(t):
    t = str(t or "")
    if "多选" in t:
        return "multi"
    if "判断" in t:
        return "judge"
    if "填空" in t:
        return "blank"
    if "程序" in t or "简答" in t or "论述" in t:
        return "code"
    return "single"


def norm(s):
    t = re.sub(r"\s+", "", str(s or ""))
    t = re.sub(r"[（(]\s*[)）]", "", t)
    return re.sub(r"第\s*\d+\s*题", "", t)


def main():
    dry = "--dry" in sys.argv
    imgs = sorted(glob.glob(os.path.join(SRC_DIR, "*.jpg")))
    print("图片 %d 张" % len(imgs))
    key = api_key()

    raw = {}
    if os.path.exists(RAW_JSON):
        raw = json.load(open(RAW_JSON, encoding="utf-8"))
    for idx, p in enumerate(imgs, 1):
        name = os.path.basename(p)
        if name in raw and raw[name].strip():
            continue
        try:
            txt = ocr_one(p, key)
            raw[name] = txt
            print("  [%2d/%2d] %s  %d 字" % (idx, len(imgs), name[-18:], len(txt)), flush=True)
        except Exception as exc:  # noqa: BLE001
            raw[name] = ""
            print("  [%2d/%2d] %s  失败 %s" % (idx, len(imgs), name[-18:], exc), flush=True)
        if idx % 5 == 0:
            json.dump(raw, open(RAW_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(raw, open(RAW_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    qs = []
    for name, txt in raw.items():
        if not txt.strip():
            continue
        try:
            obj = parse_json_loose(txt)
        except Exception:  # noqa: BLE001
            print("  解析失败：%s" % name[-20:])
            continue
        stem = str(obj.get("stem") or "").strip()
        if not stem:
            continue
        # 模型常把选项也塞进题干：从第一个 (A) / A. / A、 处截断
        stem = re.split(r"\s*[（(]?A\s*[)）.．、]", stem, maxsplit=1)[0].strip() or stem
        opts = []
        for o in obj.get("options") or []:
            k = str(o.get("k") or "").strip().upper()[:1]
            v = str(o.get("v") or "").strip()
            if k and v:
                opts.append({"k": k, "v": v})
        qs.append({"img": name, "type": type_cn_to_key(obj.get("type")), "stem": stem,
                   "options": opts, "answer": str(obj.get("answer") or "").strip()})
    json.dump(qs, open(QS_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n解析出题目 %d 道" % len(qs))

    # 去重（对全库）
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    pool = set()
    for r in con.execute("SELECT data FROM banks"):
        for q in json.loads(r["data"]).get("questions") or []:
            pool.add(norm(q.get("stem")))

    new = []
    for q in qs:
        key2 = norm(q["stem"])
        if not key2 or key2 in pool:
            continue
        pool.add(key2)
        new.append(q)
    print("其中新题 %d 道（已存在/重复 %d 道）" % (len(new), len(qs) - len(new)))

    if dry or not new:
        con.close()
        return 0

    now = time.time()
    old = con.execute("SELECT created FROM banks WHERE id=?", (BANK_ID,)).fetchone()
    prev = []
    if old:
        prev = json.loads(con.execute("SELECT data FROM banks WHERE id=?", (BANK_ID,)).fetchone()[0]).get("questions") or []
    have = {norm(q.get("stem")) for q in prev}
    questions = list(prev)
    for q in new:
        if norm(q["stem"]) in have:
            continue
        i = len(questions) + 1
        item = {"id": "new%d" % i, "no": i, "type": q["type"], "stem": q["stem"],
                "answer": q["answer"], "exp": "", "ch": 0, "score": 2,
                "chapter": "", "ref": "", "_src": "万维平台截图 · " + q["img"]}
        if q["options"]:
            item["options"] = q["options"]
        if q["type"] == "code":
            item["score"] = 10
        questions.append(item)
        have.add(norm(q["stem"]))

    bank = {
        "id": BANK_ID, "title": BANK_TITLE, "kind": "paper",
        "subject": "Java语言程序设计III", "time": time.strftime("%Y-%m-%d %H:%M"),
        "chapters": [], "questions": questions,
        "warnings": ["来自万维全自动网络考试平台的题目截图，答案多为空，需要补答案/解析"],
    }
    payload = json.dumps(bank, ensure_ascii=False)
    if old:
        con.execute("UPDATE banks SET title=?, time=?, n_questions=?, updated=?, data=? WHERE id=?",
                    (bank["title"], bank["time"], len(questions), now, payload, BANK_ID))
    else:
        con.execute("INSERT INTO banks(id,title,time,n_questions,created,updated,data) VALUES(?,?,?,?,?,?,?)",
                    (BANK_ID, bank["title"], bank["time"], len(questions), now, now, payload))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    print("已写入卷子「%s」：共 %d 题（本次新增 %d）" % (BANK_TITLE, len(questions), len(questions) - len(prev)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
