#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QuizStudio 本地服务
------------------
职责只有两件事：
  1) 托管 index.html（同源，localStorage 稳定，且免去 file:// 的跨域麻烦）
  2) 提供 AI 判分代理：浏览器把主观题 + 错题统计发过来，服务端调用
     免费、免密钥的 Pollinations 文本接口，异步生成结果，页面轮询取回。

启动：双击 start_quiz_studio.cmd，或 python server.py
端口：8770（与 java_quiz 项目的 8765 不冲突）
"""
from __future__ import annotations

import glob
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "quiz_studio.db"
HOST = "127.0.0.1"
PORT = 8770
VERSION = "1.3.0"        # 1.1.0：清理过期占位解析；IDE 配置热加载；Eclipse 索引越界修复

# 免费、免密钥、免注册的文本接口（与 java_quiz 项目同源方案，实测可用）
PROVIDERS = [
    {"name": "pollinations", "url": "https://text.pollinations.ai/openai", "model": "openai"},
    {"name": "pollinations-fast", "url": "https://text.pollinations.ai/openai", "model": "openai-fast"},
]
AI_CONFIG = ROOT / "quiz_studio_llm.json"
API_KEY = ""
MODEL_OVERRIDE = ""
TIMEOUT = 95           # 单次请求
CALL_BUDGET = 480      # 整份卷子的 AI 总预算（秒）
MAX_JUDGE_CALLS = 2    # 免费通道：最多分 2 批判定（每批 <=14 题）
JUDGE_BATCH = 14

# AI 分章：一次送多少题、最多送几批（带 Key 时也能覆盖几百题）
CHAPTER_BATCH = 20
CHAPTER_CALLS = 10

# 免费通道的真实规则是「每 IP 每 45 秒只放行 1 次请求」（实测 402 报文：
# Free limit reached: 1 reply every 45 seconds per IP）。所以必须串行排队，
# 相邻两次请求至少隔 MIN_AI_GAP 秒，否则第二发必被 402 打回。
# 自己带 Key 接大模型时不需要这个闸门，load_ai_config() 会把 MIN_AI_GAP 降为 0、
# 并把单次判分批量放大（默认 20 题/批 × 20 批 = 400 题，够判完整份卷子）。
MIN_AI_GAP = 46.0
_AI_LOCK = threading.Lock()
_AI_LAST = 0.0


def load_ai_config():
    """可选：用 quiz_studio_llm.json 换成任意 OpenAI 兼容接口（带 Key 的付费/免费额度都行）。

    免费通道有匿名配额，用光时接口会返回 402 / 429；需要稳定就把自己的 Key 填进这个文件。

    可配项：
      api_key / base_url / model   自带 Key（base_url 默认 https://api.deepseek.com）
      providers[]                  完全自定义通道（每项 name/url/model），优先级高于 base_url
      timeout / budget             单次请求超时、整卷总预算（秒）
      min_gap                      相邻两次外呼的最小间隔；带 Key 时默认 0，免费通道默认 46
      judge_batch / max_judge_calls 单批判几题、最多几批；带 Key 时默认 20/20（=400 题）
    """
    global PROVIDERS, API_KEY, MODEL_OVERRIDE, TIMEOUT, CALL_BUDGET
    global MIN_AI_GAP, JUDGE_BATCH, MAX_JUDGE_CALLS
    if not AI_CONFIG.exists():
        return
    try:
        cfg = json.loads(AI_CONFIG.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print("[AI] 配置文件解析失败，继续用免费通道：%s" % exc)
        return
    if not isinstance(cfg, dict) or cfg.get("enabled") is False:
        return
    API_KEY = str(cfg.get("api_key") or "").strip()
    if not API_KEY:
        # 也可以不写进文件，改用环境变量（重启终端生效）
        for env_name in ("ZHIPU_API_KEY", "BIGMODEL_API_KEY", "OPENAI_API_KEY"):
            if os.environ.get(env_name, "").strip():
                API_KEY = os.environ[env_name].strip()
                print("[AI] 从环境变量 %s 读取 Key" % env_name)
                break
    MODEL_OVERRIDE = str(cfg.get("model") or "").strip()
    if cfg.get("timeout"):
        TIMEOUT = float(cfg["timeout"])
    if cfg.get("budget"):
        CALL_BUDGET = float(cfg["budget"])
    provs = [p for p in (cfg.get("providers") or []) if isinstance(p, dict) and p.get("url")]
    if provs:
        PROVIDERS = [{"name": p.get("name") or "custom", "url": str(p["url"]).rstrip("/"),
                      "model": p.get("model") or MODEL_OVERRIDE or "gpt-4o-mini"} for p in provs]
    elif API_KEY:
        base = str(cfg.get("base_url") or "https://api.deepseek.com").rstrip("/")
        if not base.endswith("/chat/completions"):
            base += "/chat/completions"
        PROVIDERS = [{"name": "custom", "url": base,
                      "model": MODEL_OVERRIDE or "deepseek-chat"}]
    # 自带 Key / 本地模型 / 自定义通道：默认关掉 45 秒闸门，并放大判分批量；
    # 免费匿名通道是「每 IP 每 45 秒 1 次」的硬限流，配置文件不能把闸门调小，否则必然 402
    has_local = any(("127.0.0.1" in (p.get("url") or "")) or ("localhost" in (p.get("url") or ""))
                    for p in PROVIDERS)
    paid = bool(API_KEY) or has_local
    if paid:
        MIN_AI_GAP = float(cfg["min_gap"]) if cfg.get("min_gap") is not None else 0.0
        JUDGE_BATCH = int(cfg["judge_batch"]) if cfg.get("judge_batch") else 20
        MAX_JUDGE_CALLS = int(cfg["max_judge_calls"]) if cfg.get("max_judge_calls") else 20
    else:
        MIN_AI_GAP, JUDGE_BATCH, MAX_JUDGE_CALLS = 46.0, 14, 2
    load_exp_config(cfg)
    print("[AI] 使用配置：%s（%s）｜间隔 %.0fs｜单批 %d 题 × %d 批" % (
        ", ".join(p["name"] for p in PROVIDERS),
        "本地模型" if has_local else ("带 Key" if API_KEY else "免费通道"),
        MIN_AI_GAP, JUDGE_BATCH, MAX_JUDGE_CALLS))

JUDGE_SYS = (
    "你是严谨的 Java 课程阅卷老师。只输出 JSON，不要任何解释或代码块标记。"
    '格式：{"results":[{"id":"题目id","verdict":"ok|part|bad","score":0.0,"comment":"不超过40字的中文点评"}]}'
    "verdict 含义：ok=完全正确，part=部分正确，bad=错误。score 是 0~1 的得分比例。"
    "判分要宽容：同义表述、变量名不同但逻辑正确、代码能编译且输出正确，都算 ok。"
    "注意：题目带 unkeyed=true 或「参考答案」为空，说明题库没有标准答案。"
    "这类题你必须先自己解出正确答案（选择题给出选项字母，填空题给出答案），"
    "再判断学生作答对错，并在 comment 里写清正确答案，例如「正确答案：B（子类继承非私有成员）」。"
    "每道题都必须给出判定，不能跳过。"
)

REVIEW_SYS = (
    "你是 Java 课程助教。根据给出的答题数据输出中文诊断，严格分三段，用「一、二、三、」开头："
    "一、错误点归纳：只归纳「错题」列表里的题，以及「主观题判定」里判定为「错误」或「部分正确」的题；"
    "判定为「正确」的题一律不要出现在这一节。客观题用「第X题」，主观题用「简答题·关键词」标注，"
    "不要混用两套题号。格式为「第X题：你答 B，正确 C —— 错因：……」，一条一行；"
    "错因必须指出「你把什么和什么搞混了 / 漏了哪条规则 / 哪个关键字用错」，"
    "禁止把概念定义或正确答案本身当成错因复述一遍；"
    "二、薄弱知识点：只从给出的章节统计里正确率低于 70% 的章节、以及错题涉及的考点中提炼，"
    "编号 1/2/3，每条写清楚知识点名称 + 一句话补强要点；"
    "三、三天复习安排：第1天/第2天/第3天各一行，要具体到看哪一章、做什么类型的题。"
    "第一节最多 5 条、每节最多 3 条，一律用短句，三段必须齐全，第三段绝对不能省。"
    "只输出纯文本和简短换行，不要表格、不要加粗、不要复述完整题干。"
    "绝对不要出现数据里没有的题号或考点，也不要空泛地说「多练习」。"
    "总字数控制在 350 字以内。"
)


# ---------------------------------------------------------------- 数据库
def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        try:
            conn.execute("PRAGMA journal_mode=WAL")   # 读写并发更稳
        except Exception:
            pass
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS submissions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created REAL, bank TEXT, summary TEXT);
            CREATE TABLE IF NOT EXISTS reports(
                sid INTEGER PRIMARY KEY,
                status TEXT, judge TEXT, review TEXT,
                engine TEXT, provider TEXT, elapsed REAL, error TEXT,
                updated REAL);
            CREATE TABLE IF NOT EXISTS banks(
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                time TEXT,
                n_questions INTEGER NOT NULL DEFAULT 0,
                created REAL NOT NULL,
                updated REAL NOT NULL,
                data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_banks_updated ON banks(updated DESC);
            """
        )
        # 进程死了还挂在 pending 的，标为 failed，页面就不会一直转圈
        conn.execute("UPDATE reports SET status='failed', error='服务重启，任务已中断' "
                     "WHERE status='pending'")


# ---------------------------------------------------------------- 题库（永久存储）
def _bank_row_to_obj(row, with_data=True):
    """数据库行 -> 前端认识的卷子对象（结构与 index.html 里的 bank 一致）。"""
    obj = {"id": row["id"], "title": row["title"], "time": row["time"],
           "n_questions": row["n_questions"], "created": row["created"],
           "updated": row["updated"]}
    if with_data:
        try:
            obj.update(json.loads(row["data"] or "{}"))
        except Exception:
            pass
        obj["id"] = row["id"]        # 以列为准，避免 data 里被改脏
        obj["title"] = row["title"]
    # 分类兜底：老数据/老客户端没有 kind 时按标题补上，页面两个标签才不会空
    if not obj.get("kind"):
        obj["kind"] = _guess_kind(obj.get("title") or "", obj.get("id") or "")
    return obj


KIND_CH_RE = re.compile(r"^\s*第\s*\d+\s*章")


def _guess_kind(title, bid=""):
    if bid == DEDUP_BANK_ID or "去重视图" in title or KIND_CH_RE.match(title):
        return "chapter"
    return "paper"


W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_to_text(raw):
    """从 .docx 二进制里提取正文纯文本：段落之间换行，表格逐格按段落输出。"""
    import io as _io
    import zipfile
    from xml.etree import ElementTree as ET

    with zipfile.ZipFile(_io.BytesIO(raw)) as z:
        names = z.namelist()
        if "word/document.xml" not in names:
            raise ValueError("不是有效的 .docx（缺少 word/document.xml）")
        xml = z.read("word/document.xml")

    root = ET.fromstring(xml)
    lines = []
    for p in root.iter(W_NS + "p"):
        buf = []
        for node in p.iter():
            tag = node.tag
            if tag == W_NS + "t":
                buf.append(node.text or "")
            elif tag == W_NS + "tab":
                buf.append("\t")
            elif tag in (W_NS + "br", W_NS + "cr"):
                buf.append("\n")
        lines.append("".join(buf).rstrip())

    out = []
    for ln in lines:
        if not ln.strip() and out and not out[-1].strip():
            continue
        out.append(ln)
    return "\n".join(out).strip()


def _norm_bank(raw):
    """校验并规整一份卷子；不合法返回 None。"""
    if not isinstance(raw, dict):
        return None
    bid = str(raw.get("id") or "").strip()
    title = str(raw.get("title") or "").strip()
    questions = raw.get("questions")
    if not bid or len(bid) > 64:
        return None
    if not title or len(title) > 200:
        return None
    if not isinstance(questions, list) or not questions:
        return None
    obj = dict(raw)
    obj["id"], obj["title"], obj["questions"] = bid, title, questions
    return obj


STALE_EXP_RE = re.compile(r"[（(]?\s*(?:本题)?平台未公布标准答案[，,]\s*自动判分会记为未答对\s*[)）]?")


def _strip_stale_exp(obj):
    """删掉早期导入时写进 exp 的过期占位句（这些题现在都有答案、判分正常）。"""
    for q in obj.get("questions") or []:
        if isinstance(q, dict) and q.get("exp"):
            cleaned = STALE_EXP_RE.sub("", q["exp"]).strip("　 \n")
            if cleaned != q["exp"]:
                q["exp"] = cleaned


def save_bank(obj, insert_only=False):
    """按 id 插入或更新一份卷子。返回 'created' / 'updated' / 'exists' / 'skipped'。"""
    # 派生视图（去重视图之类）不再入库：页面缓存推上来也直接忽略
    if isinstance(obj, dict) and (obj.get("_view") or obj.get("id") == DEDUP_BANK_ID):
        return "skipped"
    _strip_stale_exp(obj)
    now = time.time()
    payload = json.dumps(obj, ensure_ascii=False)
    with db() as conn:
        row = conn.execute("SELECT created FROM banks WHERE id=?", (obj["id"],)).fetchone()
        if row:
            if insert_only:
                return "exists"
            conn.execute(
                "UPDATE banks SET title=?, time=?, n_questions=?, updated=?, data=? WHERE id=?",
                (obj["title"], obj.get("time") or "", len(obj["questions"]), now, payload, obj["id"]))
            return "updated"
        conn.execute(
            "INSERT INTO banks(id,title,time,n_questions,created,updated,data) VALUES(?,?,?,?,?,?,?)",
            (obj["id"], obj["title"], obj.get("time") or "", len(obj["questions"]), now, now, payload))
        return "created"


# ---------------------------------------------------------------- 去重视图
DEDUP_BANK_ID = "bank_dedup_view"


def _norm_stem(s):
    """题干归一化：去空白、去空括号、去「第 N 题」，用来判定是不是同一道题。"""
    t = re.sub(r"\s+", "", str(s or ""))
    t = re.sub(r"[（(]\s*[)）]", "", t)
    return re.sub(r"第\s*\d+\s*题", "", t)


def build_dedup_bank():
    """把 21 个卷子里重复出现的题合并成一份「独立题目」卷（约 323 题）。

    同一道题取第一份的答案/解析（各卷已在前一步对齐过，取值一致），
    并记下它出现在哪些卷子里（_from），方便溯源。
    """
    with db() as conn:
        rows = [(r[0], json.loads(r[1])) for r in
                conn.execute("SELECT id, data FROM banks WHERE id != ?", (DEDUP_BANK_ID,))]
    order = {"bank_java3_253": 0}       # 总集优先作为"主版本"
    groups, seen = [], {}
    for bid, bank in sorted(rows, key=lambda x: order.get(x[0], 1)):
        for q in bank.get("questions") or []:
            key = (q.get("type"), _norm_stem(q.get("stem")))
            if key in seen:
                holder = seen[key]
                if bid not in holder["_from"]:
                    holder["_from"].append(bid)
                continue
            item = dict(q)
            item["_from"] = [bid]
            item["_no_orig"] = q.get("no")
            seen[key] = item
            groups.append(item)

    chapters = {}
    questions = []
    for i, q in enumerate(groups, 1):
        ch = q.get("ch") or 0
        if ch and ch not in chapters:
            cname = None
            for _bid, bank in rows:
                for c in bank.get("chapters") or []:
                    if c.get("id") == ch:
                        cname = c.get("name")
                        break
                if cname:
                    break
            chapters[ch] = cname or ("第 %d 章" % ch)
        nq = dict(q)
        nq["id"] = "d%d" % i
        nq["no"] = i
        questions.append(nq)

    bank = {
        "id": DEDUP_BANK_ID,
        "title": "去重视图 · 独立题目（%d 题）" % len(questions),
        "subject": (rows[0][1].get("subject") if rows else "") or "Java语言程序设计III",
        "time": time.strftime("%Y-%m-%d %H:%M"),
        "chapters": [{"id": k, "name": v, "tag": ""} for k, v in sorted(chapters.items())],
        "questions": questions,
        "warnings": ["这是自动生成的视图：同一道题只留一份，答案/解析已按官方版本对齐；"
                     "每次点「去重视图」都会重建"],
        "_view": "dedup",
    }
    save_bank(bank)
    return bank


# ---------------------------------------------------------------- IDE 集成
# 「大题」点一下就丢进 Eclipse：在工程的 src 下生成一个带题目注释的 .java，
# 用 eclipse.exe --launcher.openFile 打开；提交评分后前端调 /api/code/close 删掉。
# 配置在 quiz_studio_ide.json，已生成的文件记录在 _opened_code.json。
IDE_CONFIG = ROOT / "quiz_studio_ide.json"
OPENED_JSON = ROOT / "_opened_code.json"
_OPENED_LOCK = threading.Lock()
_IDE_CACHE = {}

DEFAULT_IDE = {
    "enabled": True,
    "eclipse_exe": "",
    "project_src": "",
    "package": "bank",
}


def _find_eclipse():
    """先看正在跑的 Eclipse（用户既然在用，直接拿它的路径最稳），再找常见安装位置。"""
    exe = shutil.which("eclipse")
    if exe:
        return exe
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process eclipse -ErrorAction SilentlyContinue | Select-Object -First 1).Path"],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        p = (out.stdout or "").strip()
        if p and os.path.exists(p):
            return p
    except Exception:  # noqa: BLE001
        pass
    for pat in (r"C:\*\eclipse\*\eclipse\eclipse.exe", r"D:\*\eclipse\*\eclipse\eclipse.exe",
                r"C:\eclipse\eclipse.exe", r"D:\eclipse\eclipse.exe",
                r"C:\Program Files\eclipse\eclipse.exe"):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    return ""


def load_ide_config(refresh=False):
    if _IDE_CACHE and not refresh:
        return _IDE_CACHE
    cfg = dict(DEFAULT_IDE)
    if IDE_CONFIG.exists():
        try:
            raw = json.loads(IDE_CONFIG.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update({k: v for k, v in raw.items() if not k.startswith("_")})
        except Exception as exc:  # noqa: BLE001
            print("[IDE] 配置解析失败：%s" % exc)
    if not cfg.get("eclipse_exe"):
        cfg["eclipse_exe"] = _find_eclipse()
    cfg["package"] = re.sub(r"[^A-Za-z0-9_.]", "", str(cfg.get("package") or "bank")) or "bank"
    _IDE_CACHE.clear()
    _IDE_CACHE.update(cfg)
    return cfg


def _opened_load():
    with _OPENED_LOCK:
        try:
            return json.loads(OPENED_JSON.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}


def _opened_save(obj):
    with _OPENED_LOCK:
        OPENED_JSON.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def _short(bank_id, no):
    short = re.sub(r"[^0-9A-Za-z]", "", str(bank_id).replace("bank_", "")) or "q"
    num = re.sub(r"[^0-9A-Za-z]", "", str(no)) or "1"
    return short.lower(), num


# 题干里「真正的代码」从哪里开始：class / package / /* FOUND 标记
_CODE_START = re.compile(
    r"^[ \t]*(?:(?:public|final|abstract|protected|private)\s+)*class\s+\w+"
    r"|^[ \t]*package\s+[\w.]+\s*;"
    r"|^[ \t]*/\*+[ \t]*\**[ \t]*FOUND",
    re.M)

# 从题目文字里猜「要写的那个类」
_ANSWER_HINTS = [
    r"派生出子类\s*([A-Z][A-Za-z0-9_]*)",
    r"子类\s*([A-Z][A-Za-z0-9_]*)",
    r"名为\s*([A-Z][A-Za-z0-9_]*)\s*的?类",              # 定义一个名为 Prog1 的类
    r"定义一个(?:名为)?\s*([A-Z][A-Za-z0-9_]*)\s*类",     # 定义一个电风扇类 Fan
    r"设计(?:一个)?(?:名为)?\s*([A-Z][A-Za-z0-9_]*)\s*类",
    r"的描述?[\u4e00-\u9fa5]*的?类\s*([A-Z][A-Za-z0-9_]*)",
    r"类\s*([A-Z][A-Za-z0-9_]*)\s*，要求",
    r"([A-Z][A-Za-z0-9_]*)\s*类与对象",                   # Prog1 类与对象
    r"class\s+([A-Z][A-Za-z0-9_]*)",
]

# 这些是 Java 关键字/常用类名，不是「要写的那个类」
_NOT_CLASS = {"Java", "JDK", "JVM", "JRE", "String", "Math", "Scanner", "System",
              "Object", "Class", "Interface", "API", "Hello", "World"}


def _split_stem(stem):
    """把题干拆成（说明文字, 附带的代码）。没有代码就返回原文字 + 空串。"""
    m = _CODE_START.search(stem or "")
    if not m:
        return (stem or "").strip(), ""
    cut = stem.rfind("\n", 0, m.start()) + 1
    return stem[:cut].strip(), stem[cut:].rstrip()


def _guess_answer_class(text, code=""):
    for pat in _ANSWER_HINTS:
        for m in re.finditer(pat, text or ""):
            name = m.group(1)
            if name not in _NOT_CLASS:
                return name
    m = re.search(r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s+extends\s+\w+", code or "")
    if m:
        return m.group(1)
    classes = re.findall(r"class\s+([A-Za-z_][A-Za-z0-9_]*)", code or "")
    return classes[-1] if classes else ""


_TYPE_WORDS = ("String", "int", "double", "float", "boolean", "char", "long", "short",
               "byte", "Integer", "Double", "Boolean")

# 中文类型说法 -> Java 类型
_CN_TYPES = {
    "字符串": "String", "整数": "int", "整型": "int", "浮点": "double", "浮点型": "double",
    "小数": "double", "双精度": "double", "布尔": "boolean", "布尔型": "boolean", "字符": "char",
}

# 题干里描述属性的几种写法：(正则, 名字在前?, 是中文类型?)
_FIELD_PATTERNS = [
    # String 类型的学号（studentID）
    (r"(%s)\s*类型的?[\u4e00-\u9fa5A-Za-z]*?\s*[（(]\s*([A-Za-z_]\w*)\s*[)）]" % "|".join(_TYPE_WORDS),
     False, False),
    # 型号 model（String类型）
    (r"([A-Za-z_]\w*)\s*[（(]\s*(%s)\s*类型?\s*[)）]" % "|".join(_TYPE_WORDS), True, False),
    # 姓名（name，String类型）
    (r"[（(]\s*([A-Za-z_]\w*)\s*[，,]\s*(%s)\s*类型?[)）]" % "|".join(_TYPE_WORDS), True, False),
    # 储户姓名（name，字符串类型）
    (r"[（(]\s*([A-Za-z_]\w*)\s*[，,]\s*(%s)" % "|".join(_CN_TYPES), True, True),
    # 属性：name(书名,String类型) —— 英文在前、类型在后
    (r"([A-Za-z_]\w*)\s*[（(][^)）]*?(%s)\s*类型" % "|".join(_TYPE_WORDS), True, False),
]

_ZERO = {"int": "0", "double": "0.0", "float": "0.0f", "long": "0L", "short": "(short) 0",
         "byte": "(byte) 0", "boolean": "false", "char": "' '"}


def _fields_from_text(text):
    """从题干里抠出「属性：String 类型的学号（studentID）」这类字段声明。"""
    found, seen = [], set()
    for pat, name_first, cn in _FIELD_PATTERNS:
        for m in re.finditer(pat, text or ""):
            a, b = m.group(1), m.group(2)
            name, typ = (a, b) if name_first else (b, a)
            if cn:
                typ = _CN_TYPES.get(typ, typ)
            if typ not in _TYPE_WORDS or not name or name in seen:
                continue
            if name in ("main", "args", "String"):
                continue
            seen.add(name)
            found.append((typ, name))
    return found


def _parent_info(code, parent):
    """从父类代码里找出：构造方法参数列表（None=有无参构造）、有哪些方法。"""
    params, methods = None, []
    if not parent or not code:
        return params, methods
    body = None
    m = re.search(r"class\s+%s\b[^{]*\{" % re.escape(parent), code)
    if m:
        i, depth = m.end(), 1
        while i < len(code) and depth:
            if code[i] == "{":
                depth += 1
            elif code[i] == "}":
                depth -= 1
            i += 1
        body = code[m.end():i - 1]
    if body is None:
        return params, methods
    ctors = re.findall(r"[\s{;]\s*%s\s*\(([^)]*)\)\s*\{" % re.escape(parent), body)
    if ctors:
        params = [p.strip() for p in ctors[0].split(",") if p.strip()]
    for mm in re.finditer(r"(?:public|protected|private)?\s*(?:static\s+)?"
                          r"(void|[A-Za-z_]\w*(?:\[\])?)\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*\{", body):
        ret, name, ps = mm.group(1), mm.group(2), mm.group(3).strip()
        if name == parent:
            continue
        methods.append((ret, name, ps))
    return params, methods


def _skeleton(cls, parent, fields=None, parent_params=None, parent_methods=None):
    """只给能编译的空壳，不加任何提示注释（字段/构造方法直接生成好，不用再去点 Eclipse 的生成功能）。"""
    fields = fields or []
    ext = (" extends " + parent) if parent else ""
    out = ["class %s%s {" % (cls, ext)]
    for typ, name in fields:
        out.append("    private %s %s;" % (typ, name))
    if fields:
        out.append("")

    need_super = bool(parent) and parent_params is not None
    if need_super or fields:
        out.append("    %s() {" % cls)
        if need_super:
            args = []
            for p in (parent_params or []):
                p = p.strip()
                typ = p.split()[0] if " " in p else p
                args.append(_ZERO.get(typ, "null"))
            out.append("        super(%s);" % ", ".join(args))
        out.append("    }")
        out.append("")

    for ret, name, ps in (parent_methods or []):
        if ret == "void" and name in ("print", "show"):
            out.append("    @Override")
            out.append("    void %s(%s) {" % (name, ps))
            out.append("        super.%s(%s);" % (
                name, ", ".join(p.split()[-1] for p in ps.split(",") if p.strip())))
            out.append("    }")
            out.append("")
    if out[-1] == "":
        out.pop()
    out.append("}")
    out.append("")
    return out


_SINGLE_NAME = "Playground"


def _depublic(code):
    """单文件模式下文件名固定，里面不能再有 public class（否则编译报文件名不符）。"""
    return re.sub(r"\bpublic\s+((?:final|abstract|static)\s+)?class\s", r"\1class ", code or "")


def _ide_file(cfg, bank, q, stamp):
    """生成「题目注释 + 父类代码 + 待写类」的整份文件，返回 (文件名, 内容)。

    单文件模式：包名固定为 cfg["package"]，文件名固定 Playground.java，
    所以里面所有类都不能是 public（会跟文件名冲突）。
    """
    short, num = _short(bank["id"], q.get("no"))
    text, code = _split_stem(q.get("stem") or "")
    fields = _fields_from_text(q.get("stem") or "")
    type_zh = {"code": "编程题", "short": "问答题", "blank": "填空题",
               "single": "单选题", "multi": "多选题", "judge": "判断题"}.get(q.get("type"), q.get("type"))

    is_fix = "FOUND" in (code or "") or "改错" in (q.get("stem") or "") or "改正" in (q.get("stem") or "")
    has_parent = bool(code) and bool(re.search(r"class\s+[A-Za-z_]\w*\s*\{", code))

    cls = "" if is_fix else _guess_answer_class(text, code)
    if not cls:
        cls = "Q_%s_%s" % (short, num)

    lines = []
    lines.append("package %s;" % cfg["package"])
    lines.append("")
    lines.append("/*")
    lines.append(" * ══════════ QuizStudio 题库 · 第 %s 题（%s · %s 分）══════════"
                 % (q.get("no"), type_zh, q.get("score")))
    lines.append(" * 卷子：%s" % (bank.get("title") or bank["id"]))
    lines.append(" * 生成：%s" % stamp)
    lines.append(" *")
    for ln in (text or "（题干为空）").splitlines():
        lines.append(" * " + ln.replace("*/", "* /").rstrip())
    lines.append(" */")
    lines.append("")

    # 文件里只放「题目注释 + 题目自带的类」，不给任何空壳（要写的类由你自己建）
    if code:
        lines.append(_depublic(code))
        lines.append("")

    return (_SINGLE_NAME + ".java", "\n".join(lines))


def _code_file_body(cfg, bank, q, stamp):
    return _ide_file(cfg, bank, q, stamp)[1]


def _ensure_eclipse_refresh(cfg):
    """让 Eclipse 自动发现外部新建的文件（否则编辑器里没有补全、也没有「生成构造方法」）。

    找 workspace 的 .metadata，往 org.eclipse.core.resources.prefs 里补 refresh.enabled。
    需要重启一次 Eclipse 才生效；没重启也可以在工程上按 F5 手动刷新。
    """
    src = str(cfg.get("project_src") or "").strip()
    if not src:
        return False
    ws = str(cfg.get("workspace") or "").strip()
    cands = []
    if ws:
        cands.append(ws)
    proj = os.path.dirname(os.path.abspath(src))          # .../school
    cands.append(os.path.dirname(proj))                   # .../Java_oop
    cands.append(proj)
    for w in cands:
        meta = os.path.join(w, ".metadata")
        if not os.path.isdir(meta):
            continue
        pdir = os.path.join(meta, ".plugins", "org.eclipse.core.runtime", ".settings")
        pf = os.path.join(pdir, "org.eclipse.core.resources.prefs")
        try:
            os.makedirs(pdir, exist_ok=True)
            text = open(pf, encoding="utf-8").read() if os.path.exists(pf) else \
                "eclipse.preferences.version=1\n"
            if "refresh.enabled=true" in text:
                return False
            add = []
            if "refresh.enabled" not in text:
                add.append("refresh.enabled=true")
            if "refresh.lightweight.enabled" not in text:
                add.append("refresh.lightweight.enabled=true")
            if not add:
                return False
            if not text.endswith("\n"):
                text += "\n"
            text += "\n".join(add) + "\n"
            with open(pf, "w", encoding="utf-8") as f:
                f.write(text)
            print("[IDE] 已开启 Eclipse 自动刷新：%s（重启 Eclipse 后生效）" % pf, flush=True)
            return True
        except OSError as exc:
            print("[IDE] 写刷新配置失败：%s" % exc, flush=True)
    return False


def code_open(bank_id, qid):
    """生成大题文件并用 Eclipse 打开。返回 (结果 dict, 错误信息)。"""
    cfg = load_ide_config(refresh=True)      # 改完 json 立刻生效，不用重启
    if not cfg.get("enabled", True):
        return None, ("Eclipse 联动是关的（enabled=false）。要打开就编辑这个文件：%s"
                      % IDE_CONFIG)
    src = str(cfg.get("project_src") or "").strip()
    if not src:
        return None, "没配 project_src（Eclipse 工程的 src 目录），配置文件：%s" % IDE_CONFIG
    if not os.path.isdir(src):
        return None, "project_src 不存在：%s" % src
    with db() as conn:
        row = conn.execute("SELECT data FROM banks WHERE id=?", (bank_id,)).fetchone()
    if not row:
        return None, "没有这份卷子：%s" % bank_id
    bank = json.loads(row[0])
    q = None
    for x in bank.get("questions") or []:
        if str(x.get("id")) == str(qid):
            q = x
            break
    if q is None:
        return None, "这份卷子里没有这道题：%s" % qid

    short, num = _short(bank_id, q.get("no"))
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    filename, body = _ide_file(cfg, bank, q, stamp)
    text0, code0 = _split_stem(q.get("stem") or "")
    cls = _guess_answer_class(text0, code0) or filename[:-5]
    # 单文件模式：永远只用同一个文件，内容整体覆盖
    outdir = os.path.join(src, cfg["package"])
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, filename)

    # 已经写过的内容比记录更大 → 说明你在里面写了代码，别覆盖；
    # 变小/清空了就重写，省得你拿到一个编译不过的文件
    state = _opened_load()
    prev = state.get("single") or {}
    # 只有「重新打开同一道题」才保留你写的内容；换了题就必须整体覆盖，
    # 否则上一题的代码会一直留在 Playground.java 里。
    same_question = (prev.get("path") == path
                     and str(prev.get("bankId")) == str(bank_id)
                     and str(prev.get("qid")) == str(qid))
    keep_existing = False
    if same_question and prev.get("size"):
        try:
            if os.path.getsize(path) > int(prev["size"]):
                keep_existing = True
        except (OSError, TypeError, ValueError):
            pass

    if not keep_existing:
        _atomic_write(path, body.encode("utf-8"))

    state["single"] = {
        "path": path, "class": cls, "no": q.get("no"), "at": stamp,
        "bankId": str(bank_id), "qid": str(qid),
        "size": os.path.getsize(path)}
    _opened_save(state)

    exe = str(cfg.get("eclipse_exe") or "")
    refresh_turned_on = _ensure_eclipse_refresh(cfg)
    if not exe or not os.path.exists(exe):
        return {"file": path, "class": cls, "launched": False,
                "note": "没找到 eclipse.exe，文件已生成，手动打开即可"}, None
    try:
        subprocess.Popen([exe, "--launcher.openFile", path],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:  # noqa: BLE001
        return {"file": path, "class": cls, "launched": False,
                "note": "调起 Eclipse 失败：%s" % exc}, None
    return {"file": path, "class": cls, "launched": True,
            "kept": keep_existing,
            "refresh_turned_on": refresh_turned_on,
            "note": ("文件里已经有你写的内容，这次没覆盖；要重置请先删掉文件再点"
                     if keep_existing else
                     ("已帮你在 Eclipse 里开启自动刷新，重启一次 Eclipse 后就不用再手动刷新了"
                      if refresh_turned_on else ""))}, None


_IDE_MARKERS = (
    "// ===== 题目给出的父类（原样保留，不要改）=====",
    "// ================== 只写这一个类 ==================",
    "// ===== 下面是题目给出的程序，直接在它上面改错 =====",
)


def _strip_ide_header(text):
    """把生成时加的东西去掉：题库头注释、几个分隔提示行，留下纯代码。"""
    s = re.sub(r"/\*\n \* ═+ QuizStudio 题库.*?\n \*/\s*", "", text or "", flags=re.S)
    out = []
    for ln in s.splitlines():
        if ln.strip() in _IDE_MARKERS:
            continue
        out.append(ln)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def _blank_unit(cfg):
    """清空但保留文件：package + 一行注释，Eclipse 里依然是合法编译单元。"""
    return ("package %s;\n\n// 上一次作答已提交，点「在 Eclipse 里作答」会重新生成题目\n"
            % cfg["package"]).encode("utf-8")


def _atomic_write(path, data):
    """先写临时文件再替换。

    直接 open(path,'wb') 会先把文件截断成 0 字节，Eclipse 如果正在这瞬间读它，
    就会报「访问编译单元时出错：索引值超出边界」。原子替换把窗口降到最小。
    """
    d = os.path.dirname(path) or "."
    tmp = os.path.join(d, ".qs_tmp_%d.java" % (int(time.time() * 1000) % 1000000))
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return len(data)


def code_harvest(bank_id):
    """把 Playground.java 里写好的代码读回来。

    默认**不再清空文件**：Eclipse 那时往往还挂着这个编译单元的模型，外部一改就容易报
    「访问编译单元时出错：索引值超出边界」。留着内容不影响使用，下次点「在 Eclipse 里作答」
    会把整份文件覆盖掉。想要老行为就把 quiz_studio_ide.json 的 clearOnSubmit 改成 true。
    """
    state = _opened_load()
    files = []
    single = state.get("single") or {}
    cfg = load_ide_config()
    if single and str(single.get("bankId")) == str(bank_id):
        p = single.get("path")
        qid = str(single.get("qid") or "")
        if p and os.path.exists(p):
            try:
                raw = open(p, "rb").read().decode("utf-8", "replace")
                size = os.path.getsize(p)
                body = _strip_ide_header(raw)
                touched = size != single.get("size")
                files.append({"qid": qid, "no": single.get("no"), "class": single.get("class"),
                              "path": p, "code": raw, "body": body,
                              "touched": bool(touched), "bytes": size})
                if cfg.get("clearOnSubmit"):
                    _atomic_write(p, _blank_unit(cfg))
                    single["size"] = os.path.getsize(p)
                single["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                single["cleared"] = 1 if cfg.get("clearOnSubmit") else 0
                state["single"] = single
            except OSError as exc:
                files.append({"qid": qid, "no": single.get("no"), "class": single.get("class"),
                              "path": p, "code": "", "body": "", "touched": False,
                              "error": "读不到：%s" % exc})

    # 兼容以前「每题一个文件」留下的记录：读回来顺手删掉
    bucket = state.get(str(bank_id)) or {}
    deleted = []
    for qid in list(bucket.keys()):
        info = bucket.get(qid) or {}
        p = info.get("path")
        if not p:
            bucket.pop(qid, None)
            continue
        if not os.path.exists(p):
            bucket.pop(qid, None)
            continue
        try:
            raw = open(p, "rb").read().decode("utf-8", "replace")
            size = os.path.getsize(p)
        except OSError:
            bucket.pop(qid, None)
            continue
        files.append({"qid": qid, "no": info.get("no"), "class": info.get("class"),
                      "path": p, "code": raw, "body": _strip_ide_header(raw),
                      "touched": size != info.get("size"), "bytes": size})
        try:
            os.remove(p)
            deleted.append(p)
            d = os.path.dirname(p)
            for _ in range(2):
                try:
                    if os.path.isdir(d) and not os.listdir(d):
                        os.rmdir(d)
                        d = os.path.dirname(d)
                    else:
                        break
                except OSError:
                    break
        except OSError:
            pass
        bucket.pop(qid, None)
    if bucket:
        state[str(bank_id)] = bucket
    else:
        state.pop(str(bank_id), None)
    _opened_save(state)
    return files, deleted


def code_close(bank_id, qid=None):
    """重置/关闭时清空 Playground.java（保留文件本身，Eclipse 里不会变成新文件）。

    只有 clearOnSubmit=true 才清空；默认保留内容，等下次生成时整体覆盖。
    """
    state = _opened_load()
    cleared, missing = [], []
    cfg = load_ide_config()
    single = state.get("single") or {}
    if single and (qid is None or str(single.get("qid")) == str(qid)):
        p = single.get("path")
        try:
            if p and os.path.exists(p) and cfg.get("clearOnSubmit"):
                _atomic_write(p, _blank_unit(cfg))
                cleared.append(p)
                single["size"] = os.path.getsize(p)
                state["single"] = single
            elif p:
                missing.append(p)
        except OSError as exc:
            missing.append("%s（%s）" % (p, exc))

    # 兼容旧的按题文件：直接删
    bucket = state.get(str(bank_id)) or {}
    keys = [str(qid)] if qid else list(bucket.keys())
    for k in keys:
        info = bucket.get(str(k)) or {}
        p = info.get("path")
        if p and os.path.exists(p):
            try:
                os.remove(p)
                cleared.append(p)
            except OSError:
                pass
        bucket.pop(str(k), None)
    if bucket:
        state[str(bank_id)] = bucket
    else:
        state.pop(str(bank_id), None)
    _opened_save(state)
    return {"cleared": cleared, "missing": missing, "deleted": cleared}


# ---------------------------------------------------------------- AI
def _http_json(url, body=None, timeout=TIMEOUT, headers=None):
    data = None
    hdrs = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 不走系统代理
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _retry_after(body, default=50):
    """从 402 报文里抠出「Retry after 37s」，扣不到就按默认值等。"""
    m = re.search(r"[Rr]etry after\s*(\d+)", body or "")
    sec = int(m.group(1)) if m else default
    return max(3, min(75, sec + 2))


def _fmt_http_err(code, body):
    b = (body or "").strip()
    if code in (402, 429):
        return "免费 AI 通道限流（每 IP 每 45 秒只放行 1 次请求）"
    if code == 400 and "token limit" in b:
        return "AI 输出 token 用尽（模型把预算花在内部推理上了），请重试"
    snippet = re.sub(r"\s+", " ", b)[:120]
    return "HTTP %s%s" % (code, (" " + snippet) if snippet else "")


def _ai_wait_turn():
    """限流闸门：串行排队，保证相邻两次外呼至少相隔 MIN_AI_GAP 秒。"""
    global _AI_LAST
    with _AI_LOCK:
        gap = time.time() - _AI_LAST
        if gap < MIN_AI_GAP:
            wait = MIN_AI_GAP - gap
            print("[AI] 限流窗口未到，等 %.0fs" % wait, flush=True)
            time.sleep(wait)
        _AI_LAST = time.time()


def ai_chat(system, user, max_tokens=800, timeout=None, providers=None):
    """按顺序尝试通道，返回 (文本, provider 名)。全部失败则抛异常。

    providers 传了就只用这批通道（例如解析单独指定另一个模型），不传则用全局 PROVIDERS。
    免费通道是「每 45 秒 1 次」的硬限流：这里先把请求排队，撞上 402 就按
    报文里的 Retry after 等一轮再试一次，而不是立刻放弃。
    """
    timeout = timeout or TIMEOUT
    last = None
    headers = {"Authorization": "Bearer " + API_KEY} if API_KEY else None
    for pv in (providers or PROVIDERS):
        payload = {
            "model": pv.get("model") or MODEL_OVERRIDE or "openai",
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "stream": False,
        }
        if not API_KEY:
            payload["referrer"] = "quizstudio"
        for attempt in (1, 2):
            _ai_wait_turn()
            try:
                r = _http_json(pv["url"], payload, timeout=timeout, headers=headers)
                txt = ((r.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                txt = txt.strip()
                if txt:
                    # 报告里要能看出用的是哪个模型，别只显示「custom」
                    label = "%s · %s" % (pv["name"], pv.get("model") or MODEL_OVERRIDE or "?")
                    return txt, label
                last = RuntimeError("AI 返回空内容")
                break
            except urllib.error.HTTPError as exc:
                try:
                    body = exc.read().decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    body = ""
                last = RuntimeError(_fmt_http_err(exc.code, body))
                if exc.code in (402, 429) and attempt == 1:
                    wait = _retry_after(body)
                    print("[AI] 命中限流，%ds 后重试同一通道" % wait, flush=True)
                    time.sleep(wait)
                    continue
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
                break
    raise last or RuntimeError("所有 AI 通道均失败")


def _strip_fence(txt):
    t = txt.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def parse_json_loose(txt):
    """模型偶尔会裹代码块或带前后说明，尽量把 JSON 抠出来。"""
    t = _strip_fence(txt)
    try:
        return json.loads(t)
    except Exception:
        pass
    for pat in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
        m = re.search(pat, t)
        if m:
            frag = m.group(0)
            try:
                return json.loads(frag)
            except Exception:
                frag2 = re.sub(r",\s*([}\]])", r"\1", frag)
                try:
                    return json.loads(frag2)
                except Exception:
                    continue
    return None


def _pick_letters(s):
    """只留 A-H 并大写，用来比较「你答 B / 正确 B」这类字母答案。"""
    return "".join(sorted(set(c for c in str(s or "").upper() if "A" <= c <= "H")))


EXP_SYS = (
    "你是 Java 课程助教，正在给题目写解析。只输出 JSON，不要代码块标记、不要多余解释。"
    '格式：{"results":[{"id":"题目id","exp":"解析文本"}]}'
    "\n解析写法（严格遵守，便于前端逐行显示）："
    "\n1. 选择题：题干给了几个选项，就必须写几行，一行都不能少（哪怕某选项明显不对也要写）。"
    "每行格式固定为「A．说法正确 —— 理由」或「A．说法错误 —— 理由」；"
    "写的是【该选项本身说法】对错，与题目问什么无关；若它就是本题答案，行尾加「【本题答案】」。"
    "\n2. 最后单独一行：「结论：本题选 X —— 一句话说明为什么」。"
    "\n3. 判断题：一行「说法正确/说法错误 —— 理由」，再一行「结论：本题判断为 对/错」。"
    "\n4. 填空题：按空逐行「第 k 空：答案 —— 理由」。"
    "\n5. 简答/编程题：3~5 行要点（思路、关键 API、常见错误），不要贴整段代码。"
    "\n6. 每行不超过 60 字；不要用 markdown 符号（* # `），不要用 emoji。"
    "\n\n必须照抄这个示例的格式（示例有 4 个选项就写了 4 行）："
    "\nA．说法正确 —— 继承描述的是 is-a 关系"
    "\nB．说法正确 —— Java 类只能单继承"
    "\nC．说法错误 —— 子类不能访问父类私有成员【本题答案】"
    "\nD．说法正确 —— 父类提取共性"
    "\n结论：本题选 C —— 私有成员不可被子类直接访问"
)

EXP_BATCH = 5       # 一次送几题写解析
EXP_CALLS = 25      # 最多几批

# 解析可以单独指定模型（判分要快、解析要细）
EXP_MODEL = "glm-4.5-flash"
EXP_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
EXP_MAX_TOKENS = 2000
EXP_PROVIDERS = []


def load_exp_config(cfg=None):
    """从 quiz_studio_llm.json 的 exp 段读解析专用模型，没配就用默认值。"""
    global EXP_MODEL, EXP_URL, EXP_MAX_TOKENS, EXP_PROVIDERS, EXP_PROVIDERS_HEAVY
    try:
        if cfg is None:
            cfg = json.loads(AI_CONFIG.read_text(encoding="utf-8")) if AI_CONFIG.exists() else {}
    except Exception:  # noqa: BLE001
        cfg = {}
    sec = cfg.get("exp") or {}
    if isinstance(sec, dict):
        EXP_MODEL = str(sec.get("model") or EXP_MODEL)
        EXP_URL = str(sec.get("url") or EXP_URL)
        try:
            EXP_MAX_TOKENS = int(sec.get("max_tokens") or EXP_MAX_TOKENS)
        except (TypeError, ValueError):
            pass
    if not EXP_URL.endswith("/chat/completions"):
        EXP_URL = EXP_URL.rstrip("/") + "/chat/completions"
    heavy = "glm-4.5-flash"
    if isinstance(sec, dict):
        heavy = str(sec.get("model_heavy") or heavy)
    EXP_PROVIDERS = [{"name": "exp", "url": EXP_URL, "model": EXP_MODEL}]
    EXP_PROVIDERS_HEAVY = [{"name": "exp-heavy", "url": EXP_URL, "model": heavy}]
    print("[AI] 解析用模型：客观题 %s ｜ 大题 %s" % (EXP_MODEL, heavy), flush=True)


def _exp_quality_ok(exp, qtype):
    """选择题必须真的逐个选项写了说明，否则算没写出来（触发单独重问）。"""
    qt = str(qtype or "")
    if qt in ("single", "multi") or qt.startswith("单选") or qt.startswith("多选"):
        return len(re.findall(r"(?m)^\s*[A-H]\s*[．.、]", exp or "")) >= 2
    return len((exp or "").strip()) >= 10


def _postprocess_exp(exp, ans, qtype):
    """模型经常把「说法对的选项」误标成【本题答案】。
    这里统一删掉模型自己加的标记，再按题库答案把标记补到正确的选项行上。"""
    text = str(exp or "").replace("【本题答案】", "").replace("（本题答案）", "").replace("(本题答案)", "")
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    letters = set(c for c in str(ans or "").upper() if "A" <= c <= "H")
    qt = str(qtype or "")
    is_choice = qt in ("single", "multi") or qt.startswith("单选") or qt.startswith("多选")
    is_judge = qt in ("judge",) or qt.startswith("判断")
    marked = False
    if is_choice and letters:
        out = []
        for ln in lines:
            head = ln.lstrip()[:1].upper()
            if head in letters and "——" in ln:
                ln = ln + " 【本题答案】"
                marked = True
            out.append(ln)
        lines = out
        if not marked:
            lines.append("本题答案：%s" % "".join(sorted(letters)))
    elif is_judge and ans:
        lines.append("本题答案：%s" % ans)
    return "\n".join(lines)


def _exp_chunk(chunk, providers=None):
    """给一批题生成解析，返回 ({qid: 解析文本}, provider)。

    providers 传了就用那套模型（大题走 glm-4.5-flash，客观题走 glm-4-flash）。
    """
    user = "请为下面每道题写解析（含每个选项的对错点）：\n" + json.dumps(
        [{"id": x["id"], "题型": x.get("type") or "未知", "题干": (x.get("stem") or "")[:600],
          "选项": (x.get("opts") or "")[:500], "正确答案": x.get("answer") or "（未提供）"}
         for x in chunk], ensure_ascii=False)
    txt, provider = ai_chat(EXP_SYS, user,
                            max_tokens=min(EXP_MAX_TOKENS, max(1200, 600 * len(chunk))),
                            timeout=max(TIMEOUT, 180),
                            providers=providers or EXP_PROVIDERS or None)
    data = parse_json_loose(txt)
    rows = data.get("results") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    by_id = {x["id"]: x for x in chunk}
    got = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        qid = str(r.get("id") or "").strip()
        exp = str(r.get("exp") or "").strip()
        if not qid or not exp:
            continue
        src = by_id.get(qid) or {}
        got[qid] = _postprocess_exp(exp, src.get("answer"), src.get("type"))[:2200]
    return got, provider
def _is_heavy(item):
    """大题/简答走更细的模型，客观题走快的模型。"""
    t = str(item.get("type") or "")
    return t in ("编程题", "简答题", "code", "short") or t.startswith("编程") or t.startswith("简答")


def ai_explanations(items):
    """给每道题写解析：大题用 glm-4.5-flash，客观题用 glm-4-flash。

    返回 ({qid: 解析}, provider 标签, 送去几题)。模型少答的题会对半补问。
    """
    out, labels = {}, []
    pending = items[: EXP_BATCH * EXP_CALLS]

    def ask(chunk, providers):
        if not chunk:
            return
        try:
            got, prov = _exp_chunk(chunk, providers)
        except Exception as exc:  # noqa: BLE001
            print("[AI] 解析批次失败：%s" % exc, flush=True)
            return
        if prov and prov not in labels:
            labels.append(prov)
        out.update(got)
        missing = [x for x in chunk if x["id"] not in got]
        if missing and len(chunk) > 4:
            half = max(1, len(missing) // 2)
            ask(missing[:half], providers)
            ask(missing[half:], providers)
        elif missing:
            for x in missing:
                try:
                    got2, prov2 = _exp_chunk([x], providers)
                    if prov2 and prov2 not in labels:
                        labels.append(prov2)
                    out.update(got2)
                except Exception:  # noqa: BLE001
                    pass

    heavy = [x for x in pending if _is_heavy(x)]
    light = [x for x in pending if not _is_heavy(x)]
    for group, providers in ((light, EXP_PROVIDERS), (heavy, EXP_PROVIDERS_HEAVY)):
        for i in range(0, len(group), EXP_BATCH):
            ask(group[i:i + EXP_BATCH], providers)
    return out, " / ".join(labels), len(pending)
SOLVE_SYS = (
    "你是 Java 课程助教，请给出每道题的正确答案。只输出 JSON，不要解释、不要代码块标记。"
    '格式：{"results":[{"id":"题目id","answer":"答案"}]}'
    "单选题：1 个大写字母；多选题：字母串如 ACD（按字母顺序）；判断题：对 或 错；"
    "填空题：按空的顺序用「；」连接，只写答案本身；简答/论述/编程题：给 5 行以内的参考答案。"
    "拿不准也必须给出最可能的答案，不许留空、不许写“不确定/无法判断”。"
)

SOLVE_BATCH = 20     # 一次送几题
SOLVE_CALLS = 20     # 最多几批（400 题）


def _solve_chunk(chunk):
    """问一批题的答案，返回 ({qid: answer}, provider)。"""
    user = "请给出下面每道题的正确答案：\n" + json.dumps(
        [{"id": x["id"], "题型": x.get("type") or "未知", "题干": (x.get("stem") or "")[:600],
          "选项": (x.get("opts") or "")[:400]} for x in chunk], ensure_ascii=False)
    txt, provider = ai_chat(SOLVE_SYS, user,
                            max_tokens=max(800, min(8000, 300 + 160 * len(chunk))))
    data = parse_json_loose(txt)
    rows = data.get("results") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    got = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        qid = str(r.get("id") or "").strip()
        ans = str(r.get("answer") or "").strip()
        if qid and ans:
            got[qid] = ans[:400]
    return got, provider


def ai_solve(items):
    """让模型给每道题作答。返回 ({qid: 答案文本}, provider, 送去几题)。

    模型偶尔会少答几题（长代码题把输出挤爆了），所以哪几题没回来就对半再问一次。
    """
    out, provider = {}, ""
    pending = items[: SOLVE_BATCH * SOLVE_CALLS]

    def ask(chunk):
        nonlocal provider
        if not chunk:
            return
        try:
            got, prov = _solve_chunk(chunk)
        except Exception as exc:  # noqa: BLE001
            print("[AI] 作答批次失败：%s" % exc, flush=True)
            return
        provider = prov or provider
        out.update(got)
        missing = [x for x in chunk if x["id"] not in got]
        if missing and len(chunk) > 4:
            half = max(1, len(missing) // 2)
            ask(missing[:half])
            ask(missing[half:])
        elif missing:
            for x in missing:          # 只剩几题了，单独补问
                try:
                    got2, prov2 = _solve_chunk([x])
                    provider = prov2 or provider
                    out.update(got2)
                except Exception:      # noqa: BLE001
                    pass

    for i in range(0, len(pending), SOLVE_BATCH):
        ask(pending[i:i + SOLVE_BATCH])
    return out, provider, len(pending)


CHAPTER_SYS = (
    "你是课程助教，负责给题目分章节。只输出 JSON，不要解释、不要代码块标记。"
    '格式：{"results":[{"id":"题目id","chapter":"第 3 章 · 分支结构"}]}'
    "规则：优先复用给出的现有章节名（一字不改照抄）；"
    "确实都不合适才新建，命名沿用同一套风格「第 N 章 · 四个字以内的关键词」；"
    "每道题都必须给出结论，不许跳过、不许给空值。"
)


def ai_chapters(subject, chapter_names, items):
    """把一批题目交给模型分章。返回 ({qid: 章节名}, provider, 送去几题)。

    items: [{id, stem, opts}]
    """
    out, provider = {}, ""
    pending = items[: CHAPTER_BATCH * CHAPTER_CALLS]
    names = [str(x) for x in (chapter_names or []) if str(x).strip()]
    for i in range(0, len(pending), CHAPTER_BATCH):
        chunk = pending[i:i + CHAPTER_BATCH]
        user = ("科目：%s\n现有章节（能对上就直接用这个名字）：%s\n请给下面每道题定一个章节。\n%s"
                % (subject or "未说明", "、".join(names) if names else "（暂无）",
                   json.dumps([{"id": x["id"], "题干": (x.get("stem") or "")[:300],
                                "选项": (x.get("opts") or "")[:200]} for x in chunk],
                              ensure_ascii=False)))
        try:
            txt, provider = ai_chat(CHAPTER_SYS, user,
                                    max_tokens=max(800, min(4000, 200 + 60 * len(chunk))))
        except Exception as exc:  # noqa: BLE001
            print("[AI] 分章批次失败：%s" % exc, flush=True)
            break
        data = parse_json_loose(txt)
        rows = []
        if isinstance(data, dict):
            rows = data.get("results") or data.get("data") or []
        elif isinstance(data, list):
            rows = data
        for r in rows:
            if not isinstance(r, dict):
                continue
            qid = str(r.get("id") or "").strip()
            name = str(r.get("chapter") or "").strip()
            if qid and name:
                out[qid] = name[:40]
    return out, provider, len(pending)


def ai_judge(items):
    """items: [{id,type,stem,ref,user,score,opts,unkeyed}]

    返回 (判定表 {qid: {verdict,score,comment}}, provider, 实际送去判的题数)。
    """
    out = {}
    pending = items[: JUDGE_BATCH * MAX_JUDGE_CALLS]
    by_id = {str(x["id"]): x.get("user") or "" for x in pending}
    provider = ""
    for i in range(0, len(pending), JUDGE_BATCH):
        chunk = pending[i:i + JUDGE_BATCH]
        user = "请逐题批改下面的作答，返回 JSON。参考答案为空的题请自行求解后再判。\n" + json.dumps(
            [{"id": x["id"], "类型": x.get("type"), "题干": x.get("stem", "")[:400],
              "选项": (x.get("opts") or "")[:400],
              "参考答案": (x.get("ref") or ""),
              "学生作答": (x.get("user") or "")[:800],
              "unkeyed": bool(x.get("unkeyed") or not (x.get("ref") or ""))}
             for x in chunk], ensure_ascii=False)
        try:
            # 一批题越多，输出 JSON 越长；带 Key 时按题数放大输出预算
            mt = 2000
            if API_KEY:
                mt = max(2000, min(8000, 380 + 200 * len(chunk)))
            txt, provider = ai_chat(JUDGE_SYS, user, max_tokens=mt)
        except Exception as exc:  # noqa: BLE001
            print("[AI] 判分批次失败：%s" % exc, flush=True)
            break
        data = parse_json_loose(txt)
        rows = []
        if isinstance(data, dict):
            rows = data.get("results") or data.get("data") or []
        elif isinstance(data, list):
            rows = data
        for r in rows:
            if not isinstance(r, dict):
                continue
            qid = str(r.get("id") or "").strip()
            v = str(r.get("verdict") or "").strip().lower()
            if v not in ("ok", "part", "bad"):
                continue
            try:
                sc = float(r.get("score"))
            except Exception:
                sc = {"ok": 1.0, "part": 0.5, "bad": 0.0}[v]
            sc = max(0.0, min(1.0, sc))
            cmt = str(r.get("comment") or "")[:200]
            if qid and v == "bad":
                # 模型偶尔自相矛盾：评语里写「正确答案：B」，学生答的也是 B 却判错。
                # 这种以它自己写出的答案为准，改判 ok，别让报告出现「你答 B / 正确 B / 错误」。
                mm = re.search(r"正确答案[：:]\s*([A-Ha-h])", cmt)
                ua = _pick_letters(by_id.get(qid, ""))
                if mm and ua and ua == _pick_letters(mm.group(1)):
                    v, sc = "ok", 1.0
            if qid:
                out[qid] = {"verdict": v, "score": sc, "comment": cmt}
    return out, provider, len(pending)


def _review_complete(txt):
    """三段式诊断至少要出现「二、」和「三、」，缺了就说明输出被截断了。"""
    t = txt or ""
    return (re.search(r"^\s*[二2][、.．]", t, re.M) is not None
            and re.search(r"^\s*[三3][、.．]", t, re.M) is not None)


def ai_review(payload, judge=None):
    subj = payload.get("subjective") or []
    brief = {
        "卷子": payload.get("title"),
        "总体": payload.get("summary"),
        "章节": payload.get("chapters"),
        "错题": [{"题号": w.get("no"), "章节": w.get("chName"), "题型": w.get("type"),
                  "题干": (w.get("stem") or "")[:110],
                  "你答": (w.get("yours") or "")[:60],
                  "正确": (w.get("correct") or "")[:60]}
                 for w in (payload.get("wrong") or [])[:16]],
        "主观题判定": [],
    }
    vmap = {"ok": "正确", "part": "部分正确", "bad": "错误"}
    for it in subj:
        v = (judge or {}).get(str(it.get("id"))) or {}
        ref = (it.get("ref") or it.get("answer") or "").strip()
        row = {"题型": it.get("type"), "题干": (it.get("stem") or "")[:90],
               "学生作答": (it.get("user") or "")[:140],
               "参考答案": ref[:160] if ref else "（题库没给标准答案，以上面的判定为准）"}
        if v:                                    # 并行跑时通常没有，靠参考答案自己看
            row["判定"] = vmap.get(v.get("verdict"), "未判")
            row["点评"] = v.get("comment") or ""
        brief["主观题判定"].append(row)
    txt, provider = ai_chat(REVIEW_SYS, json.dumps(brief, ensure_ascii=False),
                            max_tokens=6000, timeout=max(TIMEOUT, 200))
    return txt, provider


def run_job(sid, payload):
    """先判待判题（主观题 + 题库缺答案的客观题），再拿着判分结果生成诊断。

    两个请求串行：免费通道对同一 IP 有并发限制，并行会被限流（实测第二个请求直接空返回）。
    """
    t0 = time.time()
    judge, review, provider, err = {}, "", "", ""
    judge_warn = ""
    try:
        subj = payload.get("subjective") or []
        asked = 0
        if subj:
            judge, provider, asked = ai_judge(subj)
            if asked and not judge:
                judge_warn = ("AI 判分没有返回任何结果（免费通道繁忙或输出被截断），"
                              "可点「重新请求」重试")
            elif asked and len(subj) > asked:
                judge_warn = ("题量超过单次判分上限，本次只判了 %d 题，"
                              "其余可再点「重新请求」继续" % asked)
            elif len(judge) < asked:
                judge_warn = "AI 只判出 %d/%d 题，剩下的可再点「重新请求」" % (len(judge), asked)
        for attempt in (1, 2):
            try:
                review, pv2 = ai_review(payload, judge)
                provider = provider or pv2
                if not _review_complete(review):
                    # 模型偶尔写一半就被截断：还有预算就再排一个窗口重写一次
                    if attempt == 1 and time.time() - t0 < CALL_BUDGET - 120:
                        print("[AI] 诊断输出不完整，重写一次", flush=True)
                        err = ""
                        continue
                    review = (review or "").rstrip() + \
                        "\n\n（本次 AI 输出被截断，后两段没写完，可点「重新请求」再生成一次）"
                err = ""
                break
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                if "限流" in msg:
                    msg = ("免费 AI 通道限流（每 45 秒只放行 1 次请求），本次没等到窗口。"
                           "点「重新请求」再试即可；想更快可在 quiz_studio_llm.json 填自己的 API Key")
                err = "诊断文字生成失败：%s" % msg
                if attempt == 1 and time.time() - t0 < CALL_BUDGET - 90:
                    time.sleep(3)
                    err = ""
                else:
                    break
        # 判分那边的提醒不能因为诊断成功就被清掉
        if judge_warn:
            err = (err + "；" if err else "") + judge_warn
        if not review and not err:
            err = "诊断文字未生成（免费接口繁忙，可点「重新请求」重试）"
        status = "done" if (judge or review) else "failed"
        if status == "failed" and not err:
            err = "AI 未返回有效内容（免费接口繁忙，可稍后重试）"
    except Exception as exc:  # noqa: BLE001
        status, err = "failed", "%s" % exc
        traceback.print_exc()
    if time.time() - t0 > CALL_BUDGET:
        err = (err + " " if err else "") + "已超出时间预算，结果可能不完整"
    with db() as conn:
        conn.execute("UPDATE reports SET status=?, judge=?, review=?, engine=?, provider=?, "
                     "elapsed=?, error=?, updated=? WHERE sid=?",
                     (status, json.dumps(judge, ensure_ascii=False), review, "free",
                      provider, round(time.time() - t0, 1), err, time.time(), sid))


# ---------------------------------------------------------------- HTTP
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/demo-bank.txt": ("demo-bank.txt", "text/plain; charset=utf-8"),
    "/README.md": ("README.md", "text/plain; charset=utf-8"),
}

# 静态兜底只放行「页面/示例卷」这类文件；数据库、源码、带密钥的配置一律不出网
# （之前 /quiz_studio.db、/server.py、/quiz_studio_llm.json 都能直接下载）
STATIC_DENY_SUFFIX = (".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".py", ".pyc",
                      ".log", ".iml", ".sh", ".bat", ".ps1", ".cmd")
STATIC_DENY_NAMES = {"quiz_studio_llm.json"}
STATIC_DENY_DIRS = {"源码","tools","importers",".idea",".git","__pycache__","out","自用","分享","assets"}


def _static_allowed(rel):
    """rel 是相对 ROOT 的路径；返回 False 表示不许通过 HTTP 取。"""
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    if not parts:
        return False
    if any(p in STATIC_DENY_DIRS for p in parts[:-1]):
        return False
    name = parts[-1]
    low = name.lower()
    if name in STATIC_DENY_NAMES or low.startswith("."):
        return False
    if low.endswith(STATIC_DENY_SUFFIX) or ".bak" in low:
        return False
    if low.endswith(".json") and ("llm" in low or "secret" in low or "key" in low or "config" in low):
        return False
    return True


class Handler(BaseHTTPRequestHandler):
    server_version = "QuizStudio/1.0"
    protocol_version = "HTTP/1.1"

    # ---------- 基础工具 ----------
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def send_json(self, obj, code=200):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def body_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:
            n = 0
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw.decode("utf-8", "replace") or "{}")
        except Exception:
            return {}

    def log_message(self, fmt, *args):  # 安静点
        if "/api/" in str(args[0] if args else ""):
            sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    # ---------- 路由 ----------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        qs = parse_qs(u.query)
        if path == "/api/health":
            try:
                with db() as conn:
                    n_banks = conn.execute("SELECT COUNT(*) FROM banks").fetchone()[0]
            except Exception:
                n_banks = None
            return self.send_json({"ok": True, "service": "quizstudio", "version": VERSION, "port": PORT,
                                   "ai": {"enabled": True,
                                          "providers": [p["name"] for p in PROVIDERS],
                                          "key": bool(API_KEY), "model": MODEL_OVERRIDE or
                                          (PROVIDERS[0].get("model") if PROVIDERS else ""),
                                          "min_gap": MIN_AI_GAP, "judge_batch": JUDGE_BATCH,
                                          "max_judge_calls": MAX_JUDGE_CALLS},
                                   "db": DB_PATH.name, "banks": n_banks})
        if path == "/api/report":
            sid = qs.get("sid", ["0"])[0]
            with db() as conn:
                row = conn.execute("SELECT * FROM reports WHERE sid=?", (sid,)).fetchone()
            if not row:
                return self.send_json({"ok": False, "error": "没有这次提交"}, 404)
            return self.send_json({"ok": True, "sid": int(sid), "status": row["status"],
                                   "judge": json.loads(row["judge"] or "{}"),
                                   "review": row["review"] or "",
                                   "engine": row["engine"], "provider": row["provider"],
                                   "elapsed": row["elapsed"], "error": row["error"]})
        if path == "/api/history":
            with db() as conn:
                rows = conn.execute(
                    "SELECT id,created,bank,summary FROM submissions ORDER BY id DESC LIMIT 20"
                ).fetchall()
            return self.send_json({"ok": True, "items": [
                {"sid": r["id"], "time": time.strftime("%m-%d %H:%M", time.localtime(r["created"])),
                 "bank": r["bank"], "summary": json.loads(r["summary"] or "{}")} for r in rows]})
        if path == "/api/banks":
            with_data = (qs.get("full") or ["0"])[0] in ("1", "true", "yes")
            with db() as conn:
                rows = conn.execute(
                    "SELECT id,title,time,n_questions,created,updated,data "
                    "FROM banks ORDER BY updated DESC").fetchall()
            return self.send_json({"ok": True,
                                   "banks": [_bank_row_to_obj(r, with_data) for r in rows]})
        if path.startswith("/api/banks/"):
            bid = path[len("/api/banks/"):]
            with db() as conn:
                row = conn.execute(
                    "SELECT id,title,time,n_questions,created,updated,data "
                    "FROM banks WHERE id=?", (bid,)).fetchone()
            if not row:
                return self.send_json({"ok": False, "error": "没有这份卷子"}, 404)
            return self.send_json({"ok": True, "bank": _bank_row_to_obj(row, True)})
        if path == "/api/code/list":
            cfg = load_ide_config()
            return self.send_json({"ok": True, "opened": _opened_load(),
                                   "config": {"enabled": bool(cfg.get("enabled", True)),
                                              "eclipse_exe": cfg.get("eclipse_exe") or "",
                                              "project_src": cfg.get("project_src") or "",
                                              "package": cfg.get("package") or "bank"}})
        if path in STATIC:
            name, ctype = STATIC[path]
            f = ROOT / name
        else:
            # 兜底：本目录下的静态文件（导入用的示例卷等），危险文件一律拒绝
            rel = path.lstrip("/")
            if rel and ".." not in rel and not rel.startswith(".") and _static_allowed(rel):
                f = ROOT / rel
                ctype = (mimetypes.guess_type(str(f))[0] or "application/octet-stream")
                if ctype.startswith("text/") or ctype == "application/json":
                    ctype += "; charset=utf-8"
            else:
                f, ctype = None, None
        if f is not None and f.is_file():
            raw = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self._cors()
            self.end_headers()
            self.wfile.write(raw)
            return
        return self.send_json({"ok": False, "error": "文件不存在"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/grade":
            payload = self.body_json()
            summary = payload.get("summary") or {}
            bank = str(payload.get("title") or "未命名卷子")
            with db() as conn:
                cur = conn.execute(
                    "INSERT INTO submissions(created,bank,summary) VALUES(?,?,?)",
                    (time.time(), bank, json.dumps(summary, ensure_ascii=False)))
                sid = cur.lastrowid
                conn.execute(
                    "INSERT INTO reports(sid,status,judge,review,engine,updated) "
                    "VALUES(?,?,?,?,?,?)", (sid, "pending", "{}", "", "free", time.time()))
            threading.Thread(target=run_job, args=(sid, payload), daemon=True).start()
            return self.send_json({"ok": True, "sid": sid, "status": "pending"})
        if path == "/api/parse-docx":
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except Exception:
                n = 0
            raw = self.rfile.read(n) if n else b""
            if not raw:
                return self.send_json({"ok": False, "error": "没有收到文件内容"}, 400)
            try:
                text = docx_to_text(raw)
            except Exception as e:
                return self.send_json({"ok": False, "error": "docx 解析失败：%s" % e}, 400)
            if not text.strip():
                return self.send_json({"ok": False, "error": "这个 docx 里没有可提取的文字"}, 400)
            return self.send_json({"ok": True, "chars": len(text), "text": text})

        if path == "/api/banks":
            payload = self.body_json()
            bank = _norm_bank(payload)
            if bank is None:
                return self.send_json(
                    {"ok": False, "error": "卷子格式不对（需要非空 id / title / questions）"}, 400)
            result = save_bank(bank)
            print("[BANK] %s %s（%d 题）" % (result, bank["id"], len(bank["questions"])), flush=True)
            return self.send_json({"ok": True, "id": bank["id"], "result": result},
                                  201 if result == "created" else 200)
        if path == "/api/banks/delete":
            payload = self.body_json()
            bid = str(payload.get("id") or "").strip()
            if not bid:
                return self.send_json({"ok": False, "error": "缺少 id"}, 400)
            with db() as conn:
                cur = conn.execute("DELETE FROM banks WHERE id=?", (bid,))
            return self.send_json({"ok": True, "deleted": cur.rowcount})
        if path == "/api/banks/bulk":
            payload = self.body_json()
            banks = payload.get("banks")
            if not isinstance(banks, list):
                return self.send_json({"ok": False, "error": "banks 必须是数组"}, 400)
            stat = {"created": 0, "updated": 0, "exists": 0, "skipped": 0}
            for raw in banks:
                bank = _norm_bank(raw)
                if bank is None:
                    stat["skipped"] += 1
                    continue
                stat[save_bank(bank, insert_only=True)] += 1
            print("[BANK] bulk %s" % stat, flush=True)
            return self.send_json({"ok": True, "result": stat})
        if path == "/api/answers":
            payload = self.body_json()
            items = payload.get("questions") or []
            if not isinstance(items, list) or not items:
                return self.send_json({"ok": False, "error": "没有要作答的题"}, 400)
            clean = []
            for x in items[:400]:
                if not isinstance(x, dict) or not str(x.get("id") or "").strip():
                    continue
                clean.append({"id": str(x["id"]), "type": str(x.get("type") or ""),
                              "stem": str(x.get("stem") or "")[:700],
                              "opts": str(x.get("opts") or "")[:500]})
            if not clean:
                return self.send_json({"ok": False, "error": "题目字段不对"}, 400)
            mapping, provider, asked = ai_solve(clean)
            print("[AI] 作答：送 %d 题，给出答案 %d 题（%s）" % (asked, len(mapping), provider or "-"),
                  flush=True)
            return self.send_json({"ok": True, "asked": asked, "map": mapping, "provider": provider})
        if path == "/api/chapters":
            payload = self.body_json()
            items = payload.get("questions") or []
            if not isinstance(items, list) or not items:
                return self.send_json({"ok": False, "error": "没有要分的题"}, 400)
            clean = []
            for x in items[:400]:
                if not isinstance(x, dict) or not str(x.get("id") or "").strip():
                    continue
                clean.append({"id": str(x["id"]), "stem": str(x.get("stem") or "")[:400],
                              "opts": str(x.get("opts") or "")[:300]})
            if not clean:
                return self.send_json({"ok": False, "error": "题目字段不对"}, 400)
            mapping, provider, asked = ai_chapters(payload.get("subject") or "",
                                                   payload.get("chapters") or [], clean)
            print("[AI] 分章：送 %d 题，判出 %d 题（%s）" % (asked, len(mapping), provider or "-"),
                  flush=True)
            return self.send_json({"ok": True, "asked": asked, "map": mapping,
                                   "provider": provider})
        if path == "/api/banks/dedup":
            try:
                bank = build_dedup_bank()
            except Exception as exc:  # noqa: BLE001
                return self.send_json({"ok": False, "error": "生成失败：%s" % exc}, 500)
            print("[DEDUP] 去重视图：%d 题" % len(bank["questions"]), flush=True)
            return self.send_json({"ok": True, "id": bank["id"], "title": bank["title"],
                                   "n": len(bank["questions"])})
        if path == "/api/explanations":
            payload = self.body_json()
            items = payload.get("questions") or []
            if not isinstance(items, list) or not items:
                return self.send_json({"ok": False, "error": "没有要写解析的题"}, 400)
            clean = []
            for x in items[:300]:
                if not isinstance(x, dict) or not str(x.get("id") or "").strip():
                    continue
                clean.append({"id": str(x["id"]), "type": str(x.get("type") or ""),
                              "stem": str(x.get("stem") or "")[:700],
                              "opts": str(x.get("opts") or "")[:600],
                              "answer": str(x.get("answer") or "")[:120]})
            if not clean:
                return self.send_json({"ok": False, "error": "题目字段不对"}, 400)
            mapping, provider, asked = ai_explanations(clean)
            print("[AI] 解析：送 %d 题，写出 %d 题（%s）" % (asked, len(mapping), provider or "-"),
                  flush=True)
            return self.send_json({"ok": True, "asked": asked, "map": mapping, "provider": provider})
        if path == "/api/code/open":
            payload = self.body_json()
            bid = str(payload.get("bankId") or "").strip()
            qid = str(payload.get("qid") or "").strip()
            if not bid or not qid:
                return self.send_json({"ok": False, "error": "缺少 bankId / qid"}, 400)
            data, err = code_open(bid, qid)
            if err:
                return self.send_json({"ok": False, "error": err}, 400)
            print("[IDE] 生成 %s（%s）" % (data["file"], "已调起 Eclipse" if data["launched"] else "未调起"),
                  flush=True)
            return self.send_json(dict(data, ok=True))
        if path == "/api/code/harvest":
            payload = self.body_json()
            bid = str(payload.get("bankId") or "").strip()
            if not bid:
                return self.send_json({"ok": False, "error": "缺少 bankId"}, 400)
            files, deleted = code_harvest(bid)
            if files:
                print("[IDE] 回填 %d 个文件并删除" % len(files), flush=True)
            return self.send_json({"ok": True, "files": files, "deleted": deleted})
        if path == "/api/code/close":
            payload = self.body_json()
            bid = str(payload.get("bankId") or "").strip()
            if not bid:
                return self.send_json({"ok": False, "error": "缺少 bankId"}, 400)
            qid = str(payload.get("qid") or "").strip() or None
            res = code_close(bid, qid)
            if res["deleted"]:
                print("[IDE] 已删除 %d 个作答文件" % len(res["deleted"]), flush=True)
            return self.send_json(dict(res, ok=True))
        return self.send_json({"ok": False, "error": "未知路径"}, 404)


def main():
    load_ai_config()
    init_db()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    srv.daemon_threads = True
    print("=" * 58)
    print(" QuizStudio 已启动： http://%s:%d/" % (HOST, PORT))
    print(" AI 通道： " + " / ".join(p["name"] for p in PROVIDERS)
          + ("（自带 Key）" if API_KEY else "（免费、免密钥）"))
    print(" 判分批量： %d 题/批 × %d 批，间隔 %.0fs" % (JUDGE_BATCH, MAX_JUDGE_CALLS, MIN_AI_GAP))
    print(" 数据库： %s" % DB_PATH)
    print(" 关闭窗口或 Ctrl+C 结束服务")
    print("=" * 58)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
