# -*- coding: utf-8 -*-
"""把题库单独导出来（不含程序本体）。

    py -3 _dev/export_bank_package.py

产物：_export/题库导出-<时间>/
       ├─ 题库-完整备份.json     含科目/章节/答案/AI 标记，可再导回
       ├─ 题库-全部题目.csv       Excel 直接打开
       ├─ 题库-浏览.html          离线只读浏览（带搜索、按卷折叠）
       ├─ 题库汇总.md             统计与分布
       └─ 分卷/*.json             每卷一个文件
     _export/题库导出-<时间>.zip
"""
import csv
import html
import json
import os
import re
import sqlite3
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "quiz_studio.db")
STAMP = time.strftime("%Y%m%d-%H%M")
NAME = "题库导出-%s" % STAMP
OUT = os.path.join(ROOT, "_export", NAME)

TYPE_CN = {"single": "单选", "multi": "多选", "judge": "判断", "blank": "填空",
           "short": "简答", "code": "编程"}
CH_LEGACY = {1: "Java 语言概述与运行机制", 2: "数据类型与运算符", 3: "分支结构", 4: "循环结构",
             5: "方法", 6: "数组", 7: "类与对象", 8: "继承与多态", 9: "抽象类与接口",
             10: "异常处理", 11: "字符串与常用类", 12: "集合框架", 13: "JDBC 数据库编程"}


def load_banks():
    con = sqlite3.connect(DB)
    banks = [json.loads(r[0]) for r in con.execute("SELECT data FROM banks ORDER BY title")]
    con.close()
    for b in banks:
        if not b.get("chapters"):
            b["chapters"] = [{"id": k, "name": "第 %d 章 · %s" % (k, v), "tag": ""}
                             for k, v in CH_LEGACY.items()]
    return banks


def chap_name(bank, ch):
    for c in bank.get("chapters") or []:
        if c.get("id") == ch:
            return c.get("name") or ("第 %d 章" % ch)
    return "未分类" if not ch else "第 %d 章" % ch


def opts_text(q):
    return " | ".join("%s.%s" % (o.get("k"), (o.get("v") or "").replace("\n", " "))
                      for o in (q.get("options") or []))


def answer_text(q):
    a = str(q.get("answer") or "").strip()
    if q.get("type") == "judge":
        return {"T": "对", "F": "错"}.get(a, a)
    return a


def md_stats(banks, total, code_n, ai_n):
    by_subject, by_ch, by_type = {}, {}, {}
    for b in banks:
        s = b.get("subject") or "未分类"
        by_subject.setdefault(s, [0, 0])
        by_subject[s][0] += 1
        by_subject[s][1] += len(b.get("questions") or [])
        for q in b.get("questions") or []:
            by_type[q.get("type")] = by_type.get(q.get("type"), 0) + 1
            k = (s, chap_name(b, q.get("ch")))
            by_ch[k] = by_ch.get(k, 0) + 1
    L = ["# QuizStudio 题库导出", "", "导出时间：%s" % time.strftime("%Y-%m-%d %H:%M"), "",
         "- 卷子 **%d 卷**，题目 **%d 题**" % (len(banks), total),
         "- 编程题 %d 道；AI 补过答案的 %d 道" % (code_n, ai_n),
         "- 题型分布：%s" % "、".join("%s %d" % (TYPE_CN.get(k, k), v) for k, v in
                                    sorted(by_type.items(), key=lambda x: -x[1])), "",
         "## 按科目", "", "| 科目 | 卷子 | 题目 |", "| --- | --- | --- |"]
    for s, (nb, nq) in sorted(by_subject.items()):
        L.append("| %s | %d | %d |" % (s, nb, nq))
    L += ["", "## 按章节", "", "| 科目 | 章节 | 题目 |", "| --- | --- | --- |"]
    for (s, ch), n in sorted(by_ch.items(), key=lambda x: (x[0][0], x[1])):
        L.append("| %s | %s | %d |" % (s, ch, n))
    L += ["", "## 卷子清单", "", "| 卷子 ID | 标题 | 科目 | 题数 | 编程题 |", "| --- | --- | --- | --- | --- |"]
    for b in banks:
        qs = b.get("questions") or []
        L.append("| `%s` | %s | %s | %d | %d |" % (
            b.get("id"), (b.get("title") or "").replace("|", "／"), b.get("subject") or "未分类",
            len(qs), sum(1 for q in qs if q.get("type") == "code")))
    return "\n".join(L) + "\n"


def build_html(banks):
    parts = ["""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>QuizStudio 题库</title>
<style>
:root{--bg:#f5f7fa;--card:#fff;--line:#ebeef5;--tx:#303133;--tx2:#606266;--tx3:#909399;--brand:#409eff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.75 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid var(--line);padding:12px 20px;
  display:flex;gap:14px;align-items:center;flex-wrap:wrap;box-shadow:0 2px 10px rgba(0,0,0,.04)}
h1{font-size:17px;margin:0}
input{flex:1;min-width:220px;padding:8px 12px;border:1px solid #dcdfe6;border-radius:6px;font-size:14px;outline:none}
input:focus{border-color:var(--brand);box-shadow:0 0 0 3px rgba(64,158,255,.12)}
.wrap{max-width:1100px;margin:0 auto;padding:16px 20px 60px}
.bank{background:var(--card);border:1px solid var(--line);border-radius:10px;margin-bottom:14px;box-shadow:0 2px 10px rgba(0,0,0,.04)}
.bank>summary{cursor:pointer;padding:12px 16px;font-weight:600;display:flex;gap:10px;align-items:center}
.bank>summary::marker{color:var(--brand)}
.meta{font-weight:400;color:var(--tx3);font-size:13px;margin-left:auto}
.q{padding:12px 16px;border-top:1px solid #f0f2f5}
.qh{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:12.5px;color:var(--tx3);margin-bottom:6px}
.tag{background:#f4f4f5;border-radius:4px;padding:1px 8px}
.tag.b{background:#ecf5ff;color:var(--brand)}
.stem{white-space:pre-wrap}
.opt{color:var(--tx2);font-size:14px;margin-top:4px}
.ans{margin-top:6px;font-size:14px;color:#3b5c33;background:#f0f9eb;border-left:3px solid #67c23a;padding:6px 10px;border-radius:6px;white-space:pre-wrap}
.ref{margin-top:6px;font-size:13.5px;color:#33475b;background:#f7fbff;border-left:3px solid var(--brand);padding:6px 10px;border-radius:6px;white-space:pre-wrap;font-family:Consolas,monospace}
.hide{display:none}
small{color:var(--tx3)}
</style></head><body>
<header><h1>QuizStudio 题库</h1>
<input id="kw" placeholder="搜索题干 / 答案 / 选项（支持空格分词）">
<span id="cnt"></span></header><div class="wrap" id="wrap">
"""]
    for b in banks:
        qs = b.get("questions") or []
        parts.append('<details class="bank"><summary>%s<span class="meta">%s · %d 题 · %d 编程</span></summary>'
                     % (html.escape(b.get("title") or ""), html.escape(b.get("subject") or "未分类"),
                        len(qs), sum(1 for q in qs if q.get("type") == "code")))
        for q in qs:
            stem = html.escape(q.get("stem") or "")
            ans = answer_text(q)
            ref = str(q.get("ref") or "").strip()
            blob = " ".join([stem, ans, ref, opts_text(q), chap_name(b, q.get("ch"))])
            parts.append('<div class="q" data-k="%s">' % html.escape(blob.replace("\n", " "), quote=True))
            parts.append('<div class="qh"><b>第 %s 题</b><span class="tag b">%s</span>'
                         '<span class="tag">%s</span><span class="tag">%s 分</span>%s</div>' % (
                             q.get("no"), TYPE_CN.get(q.get("type"), q.get("type") or ""),
                             html.escape(chap_name(b, q.get("ch"))), q.get("score") or "",
                             '<span class="tag">AI 答案</span>' if q.get("_aiAnswer") else ""))
            parts.append('<div class="stem">%s</div>' % stem)
            ot = opts_text(q)
            if ot:
                parts.append('<div class="opt">%s</div>' % html.escape(ot))
            if ans:
                parts.append('<div class="ans">正确答案：%s</div>' % html.escape(ans))
            if ref and q.get("type") in ("code", "short"):
                parts.append('<div class="ref">参考答案：%s</div>' % html.escape(ref[:4000]))
            parts.append("</div>")
        parts.append("</details>")
    total = sum(len(b.get("questions") or []) for b in banks)
    parts.append("""</div><script>
const kw=document.getElementById('kw'),qs=[...document.querySelectorAll('.q')],cnt=document.getElementById('cnt');
function run(){const t=kw.value.trim().toLowerCase().split(/\\s+/).filter(Boolean);
 let n=0;qs.forEach(q=>{const k=(q.dataset.k||'').toLowerCase();
  const ok=t.every(w=>k.includes(w));q.classList.toggle('hide',!ok);if(ok)n++;});
 document.querySelectorAll('.bank').forEach(b=>{const any=[...b.querySelectorAll('.q')].some(q=>!q.classList.contains('hide'));
  b.classList.toggle('hide',!any);if(t.length) b.open=any;});
 cnt.textContent=t.length?('匹配 '+n+' / %d 题'):('共 %d 题');}
kw.addEventListener('input',run);run();
</script></body></html>""" % (total, total))
    return "".join(parts)


def main():
    os.makedirs(OUT, exist_ok=True)
    banks = load_banks()
    total = sum(len(b.get("questions") or []) for b in banks)
    code_n = sum(1 for b in banks for q in (b.get("questions") or []) if q.get("type") == "code")
    ai_n = sum(1 for b in banks for q in (b.get("questions") or []) if q.get("_aiAnswer"))

    with open(os.path.join(OUT, "题库-完整备份.json"), "w", encoding="utf-8") as f:
        json.dump(banks, f, ensure_ascii=False, indent=1)

    # CSV（UTF-8 BOM，Excel 直接打开不乱码）
    csv_path = os.path.join(OUT, "题库-全部题目.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["科目", "卷子", "题号", "题型", "章节", "分值", "题干", "选项",
                    "正确答案", "参考答案", "AI补答案"])
        for b in banks:
            for q in b.get("questions") or []:
                w.writerow([b.get("subject") or "", b.get("title") or "", q.get("no"),
                            TYPE_CN.get(q.get("type"), q.get("type") or ""),
                            chap_name(b, q.get("ch")), q.get("score") or "",
                            (q.get("stem") or "").replace("\r", ""),
                            opts_text(q), answer_text(q), (q.get("ref") or "")[:4000],
                            "是" if q.get("_aiAnswer") else ""])

    with open(os.path.join(OUT, "题库-浏览.html"), "w", encoding="utf-8") as f:
        f.write(build_html(banks))

    with open(os.path.join(OUT, "题库汇总.md"), "w", encoding="utf-8") as f:
        f.write(md_stats(banks, total, code_n, ai_n))

    per = os.path.join(OUT, "分卷")
    os.makedirs(per, exist_ok=True)
    for b in banks:
        safe = re.sub(r'[\\/:*?"<>|]', "_", (b.get("title") or b.get("id") or "bank"))[:60]
        with open(os.path.join(per, "%s__%s.json" % (b.get("id"), safe)), "w", encoding="utf-8") as f:
            json.dump(b, f, ensure_ascii=False, indent=1)

    zip_path = OUT + ".zip"
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for base, _d, files in os.walk(OUT):
            for fn in files:
                full = os.path.join(base, fn)
                z.write(full, os.path.join(NAME, os.path.relpath(full, OUT)))

    print("目录：%s" % OUT)
    print("压缩包：%s（%.1f MB）" % (zip_path, os.path.getsize(zip_path) / 1024 / 1024))
    print("题库：%d 卷 / %d 题（编程 %d，AI 补答案 %d）" % (len(banks), total, code_n, ai_n))
    for base, _d, files in os.walk(OUT):
        rel = os.path.relpath(base, OUT)
        for fn in sorted(files)[:6]:
            p = os.path.join(base, fn)
            print("  %-46s %9.1f KB" % (fn if rel == "." else os.path.join(rel, fn),
                                        os.path.getsize(p) / 1024))
        if len(files) > 6:
            print("  %-46s …共 %d 个" % (rel + os.sep, len(files)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
