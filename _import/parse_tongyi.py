#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「东软智慧教育平台」统一练习抽屉的 HTML 解析成 QuizStudio 题库 JSON。

用法：
    py -3 _import/parse_tongyi.py <输入.html> <输出.json> [bank_id] [标题]

只用标准库。解析失败会打印原因而不是抛栈。
"""
import json
import re
import sys
from html.parser import HTMLParser

VOID = {"br", "img", "input", "hr", "meta", "link", "col", "area", "base",
        "embed", "source", "track", "wbr"}
BLOCK = {"p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5",
         "h6", "pre", "ul", "ol", "table", "section", "blockquote"}

TYPE_MAP = {"单选题": "single", "多选题": "multi", "填空题": "blank",
            "判断题": "single", "问答题": "short", "简答题": "short"}

# 章节关键词：每条 pattern 命中一次就加分（不按出现次数累加），
# 免得代码片段里一堆 for/if 把题目拽到循环/分支章。
# 格式：章号 -> (章节名, [(权重, 正则), ...])
CH_KEYWORDS = {
    1: ("Java 语言概述与运行机制", [
        (3, r"\bJDK\b|\bJVM\b|\bJRE\b|字节码|源文件"),
        (1, r"\bmain\s*\(|编译|\bclass\b")]),
    2: ("数据类型与运算符", [
        (3, r"数据类型|强制(类型)?转换|运算符|运算符优先级"),
        (1, r"\+\+|--|>>|<<|\bchar\b|\bboolean\b|\bdouble\b|\bfloat\b|\blong\b")]),
    3: ("分支结构", [
        (3, r"\bswitch\b|\bcase\b|分支结构|三目"),
        (1, r"\bif\s*\(|\belse\b")]),
    4: ("循环结构", [
        (3, r"\bwhile\s*\(|\bdo\s*\{|循环"),
        (1, r"\bfor\s*\(|\bcontinue\b|\bbreak\b")]),
    5: ("方法", [
        (3, r"方法重载|重载|递归|形参|实参|返回值|方法定义"),
        (1, r"\breturn\b|\bvoid\b")]),
    6: ("数组", [
        (3, r"数组|二维|\.length(?!\s*\()"),
        (1, r"\w+\s*\[\s*\]")]),
    7: ("类与对象", [
        (3, r"构造方法|封装|类与对象|成员变量|访问权限|\bstatic\b|\bthis\b"),
        (1, r"\bnew\b|对象")]),
    8: ("继承与多态", [
        (3, r"继承|父类|子类|\bextends\b|\bsuper\b|多态|覆盖|重写|向上转型|instanceof")]),
    9: ("抽象类与接口", [
        (3, r"接口|抽象|\babstract\b|\binterface\b|\bimplements\b")]),
    10: ("异常处理", [
        (3, r"异常|\bException\b|\btry\b|\bcatch\b|\bfinally\b|\bthrow\b|\bthrows\b")]),
    11: ("字符串与常用类", [
        (3, r"\bString\b|StringBuffer|StringBuilder|包装类|Math\.|Integer\."),
        (1, r"equals|toString|长度")]),
    12: ("集合框架", [
        (3, r"集合|ArrayList|HashMap|LinkedList|HashSet|TreeMap|泛型|Iterator|Collection|List<|Map<|Set<")]),
    13: ("JDBC 数据库编程", [
        (3, r"JDBC|Connection|ResultSet|DriverManager|\bSQL\b|Statement")]),
}
# 同分时的取舍顺序：先看 Java 三大特征，再往前面的基础章退
CH_PRIORITY = [8, 9, 10, 12, 11, 13, 7, 6, 5, 4, 3, 2, 1]
CH_MIN_SCORE = 3


class Node(object):
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []

    @property
    def cls(self):
        return (self.attrs.get("class") or "").split()

    def has(self, name):
        return name in self.cls

    def iter(self):
        for c in self.children:
            if isinstance(c, Node):
                yield c
                for x in c.iter():
                    yield x

    def find_all(self, name):
        return [n for n in self.iter() if n.has(name)]

    def find(self, name):
        for n in self.iter():
            if n.has(name):
                return n
        return None


class TreeBuilder(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.root = Node("#root", [])
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def render_text(node):
    """把子树渲染成纯文本：块级元素换行，<br> 换行，压缩多余空白。"""
    if node is None:
        return ""
    parts = []

    def walk(n):
        for c in n.children:
            if isinstance(c, str):
                parts.append(c)
            elif c.tag == "br":
                parts.append("\n")
            elif c.tag == "img":
                parts.append("［图］")
            else:
                blk = c.tag in BLOCK
                if blk and parts and not parts[-1].endswith("\n"):
                    parts.append("\n")
                walk(c)
                if blk:
                    parts.append("\n")

    walk(node)
    t = "".join(parts).replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("\xa0", " ").replace("\u3000", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{2,}", "\n", t)
    return t.strip()


def read_html(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def classify(stem, options):
    """按关键词猜章节；猜不出来返回 0（前端归到「其他 / 综合」）。

    同分时先看题干本身的命中分（题干比选项更能代表考点），再按 CH_PRIORITY。
    """
    opt_text = " ".join(o.get("v", "") for o in options)
    # main(String[] args) 这种样板签名会把所有代码题误判成「字符串」
    strip_main = lambda s: re.sub(r"String\s*\[\s*\]\s*\w+", " ", s)
    stem_c = strip_main(stem)
    hay = stem_c + " " + strip_main(opt_text)

    total, in_stem = {}, {}
    for ch, (_name, pats) in CH_KEYWORDS.items():
        s = s2 = 0
        for w, pat in pats:
            if re.search(pat, hay):
                s += w
                if re.search(pat, stem_c):
                    s2 += w
        if s:
            total[ch] = s
            in_stem[ch] = s2
    if not total:
        return 0, ""
    best = max(total.values())
    if best < CH_MIN_SCORE:
        return 0, ""
    cands = [ch for ch in total if total[ch] == best]
    if len(cands) > 1:
        top_stem = max(in_stem[ch] for ch in cands)
        cands = [ch for ch in cands if in_stem[ch] == top_stem]
    for ch in CH_PRIORITY:
        if ch in cands:
            return ch, CH_KEYWORDS[ch][0]
    return 0, ""


def parse_question(block):
    num_el = block.find("num-box")
    m = re.search(r"\d+", render_text(num_el))
    no = int(m.group(0)) if m else 0

    tag_el = block.find("el-tag__content")
    type_zh = render_text(tag_el).strip() or "单选题"
    qtype = TYPE_MAP.get(type_zh, "single")

    type_el = block.find("question-type")
    ms = re.search(r"(\d+)\s*分", render_text(type_el))
    score = int(ms.group(1)) if ms else 0

    info = block.find("qusetion-info")
    stem = ""
    options = []
    if info is not None:
        stem_el = None
        for item in info.find_all("info-item"):
            val = item.find("value")
            if val is not None and "!w100%" in val.cls:
                stem_el = val
                break
        if stem_el is None:  # 兜底：第一个 value
            val = info.find("value")
            stem_el = val
        stem = render_text(stem_el)

        for n, ch in enumerate(info.find_all("choices")):
            lab = render_text(ch.find("choices-label")).strip()
            key = re.sub(r"[^A-Za-z0-9]", "", lab) or chr(65 + n)
            txt = render_text(ch.find("choices-html"))
            options.append({"k": key.upper(), "v": txt})

    return {"no": no, "type": qtype, "type_zh": type_zh, "score": score,
            "stem": stem, "options": options}


def main(argv):
    if len(argv) < 3:
        print("usage: parse_tongyi.py <in.html> <out.json> [bank_id] [title]")
        return 2
    src, dst = argv[1], argv[2]
    bid = argv[3] if len(argv) > 3 else "bank_tongyi_1"
    title = argv[4] if len(argv) > 4 else "统一练习-1"

    html = read_html(src)
    start = html.find('class="item-box mb-4 pt-9"')
    if start < 0:
        print("ERROR: 没找到题目块（class=\"item-box mb-4 pt-9\"）")
        return 1
    end = html.find('class="right-box"', start)
    region = html[start:end if end > start else len(html)]
    # 用 id 边界切块
    heads = [m.start() for m in re.finditer(r'id="question-pre-', region)]
    print("题目块: %d" % len(heads))
    blocks = [region[heads[i]: (heads[i + 1] if i + 1 < len(heads) else len(region))]
              for i in range(len(heads))]

    # 卷头：满分 / 题量（先剥标签，取题目区之前最后一处，避免命中列表里的其他练习）
    head_plain = re.sub(r"<[^>]+>", "", html[:start])
    man = cnt = None
    for m in re.finditer(r"满分[：:]\s*(\d+)\s*分", head_plain):
        man = m
    for m in re.finditer(r"题量[：:]\s*(\d+)\s*题", head_plain):
        cnt = m
    total_score = int(man.group(1)) if man else None
    total_cnt = int(cnt.group(1)) if cnt else None

    # 平台不公布答案（「提交后自动公布」）。只有极少数题干里印着正确选项，
    # 形如「（ B ）」；这类才回填 answer，并在 exp 里注明来源。
    leak_pat = re.compile(r"[（(]\s*([A-Da-d])\s*[)）]")
    leaked = {}

    questions = []
    warnings = []
    stats = {"single": 0, "blank": 0, "short": 0, "multi": 0, "other": 0}
    score_sum = 0
    seen = {}
    use_chapter = "--no-chapter" not in argv
    ch_stat = {}
    for b in blocks:
        tree = TreeBuilder()
        tree.feed(b)
        q = parse_question(tree.root)
        if not q["stem"]:
            warnings.append("第 %d 题题干为空，已跳过" % q["no"])
            continue
        stats[q["type"] if q["type"] in stats else "other"] += 1
        score_sum += q["score"]
        ch_no, ch_name = classify(q["stem"], q["options"]) if use_chapter else (0, "")
        ch_stat[ch_no] = ch_stat.get(ch_no, 0) + 1
        ans, exp = "", ""
        if q["type"] == "single":
            hits = set(m.group(1).upper() for m in leak_pat.finditer(q["stem"]))
            keys = [o["k"] for o in q["options"]]
            if len(hits) == 1:
                cand = hits.pop()
                if cand in keys:
                    ans = cand
                    exp = "答案来自题干：题干中直接写出了「%s」。平台未公布官方答案键，此选项为按题干推断。" % cand
        item = {
            "type": q["type"],
            "stem": q["stem"],
            "options": q["options"],
            "answer": ans,
            "exp": exp,
            "ch": ch_no,
            "score": q["score"],
            "_src": "%s · 第 %d 题（%s）" % (title, q["no"], q["type_zh"]),
            "_ch": ch_no,
            "_cname": ch_name or (title + " · 未分章"),
        }
        questions.append(item)
        key = re.sub(r"\s+", "", q["stem"])
        if key in seen:
            warnings.append("第 %d 题与第 %d 题题干重复" % (q["no"], seen[key]))
        else:
            seen[key] = q["no"]

    if total_cnt and total_cnt != len(questions):
        warnings.append("题量标注 %d，解析出 %d" % (total_cnt, len(questions)))
    if total_score and total_score != score_sum:
        warnings.append("满分标注 %d，解析分值合计 %d" % (total_score, score_sum))

    bank = {
        "id": bid,
        "title": title,
        "time": "",
        "totalScore": total_score,
        "questions": questions,
        "warnings": warnings,
    }
    with open(dst, "wb") as f:
        f.write(json.dumps(bank, ensure_ascii=False, indent=1).encode("utf-8"))

    print("题数: %d" % len(questions))
    print("类型: %s" % json.dumps(stats, ensure_ascii=False))
    print("分值合计: %d（标注 %s）" % (score_sum, total_score))
    print("有答案: %d" % sum(1 for q in questions if q["answer"]))
    if use_chapter:
        parts = []
        for ch in sorted(ch_stat, key=lambda c: (c == 0, c)):
            nm = CH_KEYWORDS[ch][0] if ch else "未分类"
            parts.append("%s=%d" % (nm, ch_stat[ch]))
        print("章节分布: " + "，".join(parts))
    print("重复/异常提示: %d" % len(warnings))
    for w in warnings[:20]:
        print("  - " + w)
    print("写出: %s" % dst)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
