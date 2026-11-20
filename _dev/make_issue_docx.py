# -*- coding: utf-8 -*-
"""把题库里「有问题的题」导出成一份 Word 文档（另附同名 .md）。

分三部分：
  一、必须人工修：编程题参考答案 javac 编不过 / 参考答案不像代码 / 填空题空数与答案段数不匹配
  二、可能有问题：参考答案过短、与题干高度重复、编译过但被标 weak 的
  三、AI 补答案全清单（按卷子分组，供抽查复核）

用法：
    py -3 _dev/make_issue_docx.py
    py -3 _dev/make_issue_docx.py --all-ai     # 第三部分包含全部 AI 补的题（默认就是全部）
"""
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Cm

BASE = "http://127.0.0.1:8770"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DOCX = os.path.join(ROOT, "题库问题清单.docx")
OUT_MD = os.path.join(ROOT, "题库问题清单.md")
TYPE_CN = {"single": "单选", "multi": "多选", "judge": "判断", "blank": "填空",
           "short": "简答", "code": "编程"}
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(path):
    with OP.open(BASE + path, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def depublic(t):
    return re.sub(r"(?m)^(\s*)public(\s+(?:abstract\s+|final\s+)?(?:class|interface|enum)\s+)", r"\1\2", t)


def compiles(code):
    if "{" not in code or code.count("{") != code.count("}"):
        return False
    d = tempfile.mkdtemp()
    try:
        f = os.path.join(d, "Main.java")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(depublic(code))
        r = subprocess.run(["javac", "-encoding", "UTF-8", "-nowarn", "-d", d, f],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.returncode == 0
    except FileNotFoundError:
        return None
    finally:
        shutil.rmtree(d, ignore_errors=True)


def short(t, n=90):
    t = re.sub(r"\s+", " ", str(t or "")).strip()
    return t if len(t) <= n else t[:n] + "…"


def collect():
    must, maybe, ai_list = [], [], []
    for b in get("/api/banks")["banks"]:
        full = get("/api/banks/" + b["id"])["bank"]
        for q in full["questions"]:
            ans = str(q.get("answer") or "").strip()
            ref = str(q.get("ref") or "").strip()
            typ = q.get("type")
            opts = q.get("options") or []
            rec = {"bank": full["id"], "title": full.get("title") or "", "qid": q.get("id"),
                   "no": q.get("no"), "type": typ, "stem": q.get("stem") or "",
                   "answer": ans, "ref": ref, "ai": q.get("_aiAnswer"),
                   "code": q.get("_aiCode"), "weak": q.get("_aiCodeWeak"),
                   "nopts": len(opts)}
            problems = []
            if typ == "code":
                body = ref or ans
                if body and "{" in body:
                    ok = compiles(body)
                    if ok is False:
                        problems.append("参考答案 javac 编不过")
                elif body and not re.search(r"\b(class|interface)\s+\w+", body):
                    problems.append("参考答案不是代码（只有一句话/复述题干）")
                if body and len(body) < 90:
                    problems.append("参考答案过短（%d 字）" % len(body))
                if body and difflib.SequenceMatcher(None, short(body, 200), short(rec["stem"], 200)).ratio() > 0.6:
                    problems.append("参考答案与题干高度重复")
            elif typ == "blank":
                nblank = len(re.findall(r"_{2,}|＿{2,}|（\s*）|\(\s*\)", rec["stem"]))
                npart = len([x for x in re.split(r"[;；]", ans) if x.strip()])
                if ans and nblank >= 2 and npart == 1:
                    problems.append("题干有 %d 个空，答案只有 1 段" % nblank)
                if ans and nblank == 1 and npart >= 3:
                    problems.append("题干只有 1 个空，答案有 %d 段" % npart)
            elif typ in ("single", "multi"):
                letters = "".join(sorted(set(re.findall(r"[A-H]", ans.upper()))))
                if ans and not letters:
                    problems.append("答案里没有选项字母")
                if letters and opts and max(ord(c) - 65 for c in letters) >= len(opts):
                    problems.append("答案字母超出选项范围（共 %d 个选项）" % len(opts))
                if typ == "single" and len(letters) > 1:
                    problems.append("单选题给了多个字母")
                if typ == "multi" and len(letters) == 1 and re.search(r"哪些|多选|多项|至少", rec["stem"]):
                    problems.append("看着是多选，答案只有一个字母")
            elif typ == "judge":
                if ans and ans not in ("T", "F"):
                    problems.append("判断题答案不是 T/F")
            if not ans and not ref:
                problems.append("完全没有答案")
            hard = [p for p in problems if not p.startswith(("参考答案过短", "参考答案与题干高度重复"))]
            rec["problems"] = problems
            if hard:
                must.append(rec)
            elif problems:
                maybe.append(rec)
            if rec["ai"]:
                ai_list.append(rec)
    return must, maybe, ai_list


def set_cjk(run, name="微软雅黑"):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def h(doc, text, level=1):
    p = doc.add_heading(level=level)
    r = p.add_run(text)
    set_cjk(r)
    return p


def para(doc, text, size=10.5, bold=False, color=None, space=2):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space)
    r = p.add_run(text)
    r.font.size = Pt(size)
    r.bold = bold
    if color:
        r.font.color.rgb = RGBColor(*color)
    set_cjk(r)
    return p


def build(must, maybe, ai_list):
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)   # A4
    sec.left_margin = sec.right_margin = Cm(2.0)
    sec.top_margin = sec.bottom_margin = Cm(2.2)

    t = doc.add_heading(level=0)
    tr = t.add_run("QuizStudio 题库 · 问题题清单")
    set_cjk(tr)
    tr.font.size = Pt(22)

    para(doc, "生成时间：%s　|　题库：%d 卷 / %d 题" % (
        time.strftime("%Y-%m-%d %H:%M"), len({x["bank"] for x in must + maybe + ai_list}),
        sum(len(get("/api/banks/%s" % b["id"])["bank"]["questions"])
            for b in get("/api/banks")["banks"])), 10, color=(0x66, 0x66, 0x66))

    # 统计
    h(doc, "一、统计", 1)
    tbl = doc.add_table(rows=1, cols=2)
    tbl.style = "Light Grid Accent 1"
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl.rows[0].cells[0].text = "类别"
    tbl.rows[0].cells[1].text = "数量"
    for label, n in (("必须人工修", len(must)), ("可能有问题（参考答案过短/重复）", len(maybe)),
                     ("AI 补过答案的题（建议抽查）", len(ai_list))):
        row = tbl.add_row().cells
        row[0].text = label
        row[1].text = str(n)
    para(doc, "")

    # 一、必须修
    h(doc, "二、必须人工修（%d 道）" % len(must), 1)
    if not must:
        para(doc, "没有。")
    cur = None
    for r in sorted(must, key=lambda x: (x["bank"], x["no"] or 0)):
        if r["bank"] != cur:
            cur = r["bank"]
            para(doc, "【%s】%s" % (cur, short(r["title"], 40)), 11, bold=True, space=4)
        para(doc, "第 %s 题 [%s]　%s" % (r["no"], TYPE_CN.get(r["type"], r["type"]), short(r["stem"])),
             10, space=0)
        para(doc, "　问题：%s" % "；".join(r["problems"]), 10, color=(0xB5, 0x2A, 0x2A), space=0)
        body = short(r["ref"] or r["answer"], 160)
        if body:
            para(doc, "　当前答案：%s" % body, 9, color=(0x55, 0x55, 0x55), space=6)
        else:
            para(doc, "　当前答案：（空）", 9, color=(0x55, 0x55, 0x55), space=6)

    # 二、可能有问题
    h(doc, "三、可能有问题（%d 道）" % len(maybe), 1)
    para(doc, "这些题目答案能编译/能解析，但参考答案很短或和题干重复，复习价值低，先列出来供你判断。", 10,
         color=(0x66, 0x66, 0x66))
    cur = None
    for r in sorted(maybe, key=lambda x: (x["bank"], x["no"] or 0)):
        if r["bank"] != cur:
            cur = r["bank"]
            para(doc, "【%s】" % cur, 11, bold=True, space=4)
        para(doc, "第 %s 题 [%s]　%s" % (r["no"], TYPE_CN.get(r["type"], r["type"]), short(r["stem"], 70)),
             10, space=0)
        para(doc, "　%s　→　%s" % ("；".join(r["problems"]), short(r["ref"] or r["answer"], 90)),
             9, color=(0x55, 0x55, 0x55), space=5)

    # 三、AI 清单
    h(doc, "四、AI 补过答案的题（%d 道，按卷子分组）" % len(ai_list), 1)
    para(doc, "实测客观题答案约 65% 准，代码推演类最容易错。发现「答对被判错」时，照着这里的卷子/题号把 "
              "answer 改掉即可；带「代码✔」标记的表示参考答案能 javac 通过。", 10, color=(0x66, 0x66, 0x66))
    cur = None
    for r in sorted(ai_list, key=lambda x: (x["bank"], x["no"] or 0)):
        if r["bank"] != cur:
            cur = r["bank"]
            para(doc, "【%s】%s" % (cur, short(r["title"], 40)), 11, bold=True, space=4)
        mark = ""
        if r["type"] == "code":
            mark = " [代码✔]" if r["code"] and not r["weak"] else (" [代码✗]" if r["weak"] else "")
        para(doc, "第 %s 题 [%s%s] %s → %s" % (
            r["no"], TYPE_CN.get(r["type"], r["type"]), mark, short(r["stem"], 64),
            short(r["answer"] or r["ref"], 60)), 9, space=1)

    doc.save(OUT_DOCX)

    # 同步一份 Markdown
    lines = ["# QuizStudio 题库 · 问题题清单", "",
             "生成时间：%s" % time.strftime("%Y-%m-%d %H:%M"), "",
             "| 类别 | 数量 |", "| --- | --- |",
             "| 必须人工修 | %d |" % len(must),
             "| 可能有问题 | %d |" % len(maybe),
             "| AI 补过答案 | %d |" % len(ai_list), "",
             "## 二、必须人工修（%d 道）" % len(must), ""]
    cur = None
    for r in sorted(must, key=lambda x: (x["bank"], x["no"] or 0)):
        if r["bank"] != cur:
            cur = r["bank"]
            lines += ["### %s · %s" % (cur, r["title"]), ""]
        lines += ["- **第 %s 题 [%s]** %s" % (r["no"], TYPE_CN.get(r["type"], r["type"]), short(r["stem"])),
                  "  - 问题：%s" % "；".join(r["problems"]),
                  "  - 当前答案：%s" % (short(r["ref"] or r["answer"], 160) or "（空）")]
    lines += ["", "## 三、可能有问题（%d 道）" % len(maybe), ""]
    cur = None
    for r in sorted(maybe, key=lambda x: (x["bank"], x["no"] or 0)):
        if r["bank"] != cur:
            cur = r["bank"]
            lines += ["### %s" % cur, ""]
        lines += ["- 第 %s 题 [%s] %s → %s（%s）" % (
            r["no"], TYPE_CN.get(r["type"], r["type"]), short(r["stem"], 70),
            short(r["ref"] or r["answer"], 90), "；".join(r["problems"]))]
    lines += ["", "## 四、AI 补过答案的题（%d 道）" % len(ai_list), ""]
    cur = None
    for r in sorted(ai_list, key=lambda x: (x["bank"], x["no"] or 0)):
        if r["bank"] != cur:
            cur = r["bank"]
            lines += ["### %s · %s" % (cur, r["title"]), ""]
        mark = ""
        if r["type"] == "code":
            mark = " [代码✔]" if r["code"] and not r["weak"] else (" [代码✗]" if r["weak"] else "")
        lines += ["- 第 %s 题 [%s%s] %s → %s" % (
            r["no"], TYPE_CN.get(r["type"], r["type"]), mark, short(r["stem"], 64),
            short(r["answer"] or r["ref"], 60))]
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    return len(must), len(maybe), len(ai_list)


if __name__ == "__main__":
    m, mb, ai = collect()
    n1, n2, n3 = build(m, mb, ai)
    print("已生成：\n  %s\n  %s" % (OUT_DOCX, OUT_MD))
    print("必须修 %d 道 / 可能有问题 %d 道 / AI 补答案 %d 道" % (n1, n2, n3))
