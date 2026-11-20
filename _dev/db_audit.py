# -*- coding: utf-8 -*-
"""QuizStudio 数据库体检（只读）。

用法：py -3 _dev/db_audit.py [db路径]
不写库、不加锁：用 file:...?mode=ro 打开，服务端在跑也能读。
"""
import json
import os
import sqlite3
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "quiz_studio.db")


def con():
    uri = "file:%s?mode=ro" % DB.replace("\\", "/").replace(" ", "%20")
    c = sqlite3.connect(uri, uri=True)
    c.row_factory = sqlite3.Row
    return c


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit)
        n /= 1024.0


def section(t):
    print("\n=== %s ===" % t)


def main():
    print("数据库: %s" % DB)
    if not os.path.exists(DB):
        print("文件不存在")
        return 1
    section("文件")
    for suffix in ("", "-wal", "-shm"):
        p = DB + suffix
        if os.path.exists(p):
            print("  %-8s %10s  %s" % (suffix or "(main)", human(os.path.getsize(p)),
                                       __import__("time").strftime("%Y-%m-%d %H:%M:%S",
                                                                   __import__("time").localtime(os.path.getmtime(p)))))
    c = con()

    section("运行参数")
    for k in ("journal_mode", "page_size", "page_count", "freelist_count", "user_version",
              "foreign_keys", "integrity_check", "encoding", "auto_vacuum"):
        try:
            v = c.execute("PRAGMA %s" % k).fetchone()[0]
        except sqlite3.Error as e:
            v = "ERR %s" % e
        print("  %-16s %s" % (k, v))
    try:
        print("  %-16s %s" % ("quick_check", c.execute("PRAGMA quick_check").fetchone()[0]))
    except sqlite3.Error as e:
        print("  quick_check      ERR %s" % e)

    section("表与索引")
    rows = c.execute("select type, name, tbl_name, sql from sqlite_master order by type, name").fetchall()
    for r in rows:
        if r["type"] == "table":
            print("  [table] %-22s" % r["name"])
        elif r["type"] == "index":
            print("  [index] %-22s on %s" % (r["name"], r["tbl_name"]))
    for r in rows:
        if r["type"] == "table":
            cols = c.execute("PRAGMA table_info(%s)" % r["name"]).fetchall()
            print("    %-14s %s" % (r["name"], ", ".join(
                "%s %s%s" % (x["name"], x["type"], " PK" if x["pk"] else "") for x in cols)))

    tables = [r["name"] for r in rows if r["type"] == "table" and not r["name"].startswith("sqlite_")]
    section("行数")
    for t in tables:
        n = c.execute("select count(*) from %s" % t).fetchone()[0]
        print("  %-16s %d" % (t, n))

    if "banks" in tables:
        section("题库（banks）")
        bs = c.execute("select id, title, time, n_questions, created, updated, length(data) as bytes "
                       "from banks order by updated").fetchall()
        total_q = 0
        for b in bs:
            try:
                obj = json.loads(c.execute("select data from banks where id=?", (b["id"],)).fetchone()[0])
                real = len(obj.get("questions") or [])
                ok = "OK" if real == b["n_questions"] else "不一致!"
            except Exception as e:
                real, ok = -1, "JSON 坏了: %s" % e
            total_q += max(real, 0)
            print("  %-16s n=%-4s(%s) %8s  %s" % (b["id"], b["n_questions"], ok,
                                                  human(b["bytes"]), (b["title"] or "")[:44]))
        print("  合计题目: %d" % total_q)
        dup = c.execute("select id, count(*) c from banks group by id having c>1").fetchall()
        print("  重复 id: %d" % len(dup))

    if "submissions" in tables:
        section("提交（submissions）")
        cols = [x["name"] for x in c.execute("PRAGMA table_info(submissions)").fetchall()]
        print("  列: " + ", ".join(cols))
        rows = c.execute("select * from submissions order by rowid desc limit 5").fetchall()
        for r in rows:
            brief = {k: (str(r[k])[:40] if r[k] is not None else None) for k in cols}
            print("   ", json.dumps(brief, ensure_ascii=False)[:220])
        empty = c.execute("select count(*) from submissions where answers is null or answers=''").fetchone()[0] \
            if "answers" in cols else "无 answers 列"
        print("  空答案行: %s" % empty)

    if "reports" in tables:
        section("判分报告（reports）")
        cols = [x["name"] for x in c.execute("PRAGMA table_info(reports)").fetchall()]
        print("  列: " + ", ".join(cols))
        if "status" in cols:
            for r in c.execute("select status, count(*) c from reports group by status"):
                print("  status=%-10s %d" % (r["status"], r["c"]))
        if "sid" in cols and "submissions" in tables:
            orphan = c.execute("select count(*) from reports r where r.sid not in "
                               "(select sid from submissions)").fetchone()[0]
            print("  找不到对应 submission 的报告: %d" % orphan)
        if "created" in cols:
            r = c.execute("select min(created), max(created) from reports").fetchone()
            print("  时间范围: %s ~ %s" % (r[0], r[1]))
        if "error" in cols:
            n = c.execute("select count(*) from reports where error is not null and error<>''").fetchone()[0]
            print("  带错误信息的报告: %d" % n)
            for r in c.execute("select sid, substr(error,1,90) from reports where error is not null "
                               "and error<>'' order by rowid desc limit 3"):
                print("     sid=%s  %s" % (r[0], r[1]))
        if "judged" in cols and "total" in cols:
            for r in c.execute("select sid, judged, total, status from reports order by rowid desc limit 3"):
                print("     最近: sid=%s judged=%s/%s status=%s" % (r[0], r[1], r[2], r[3]))

    section("外键检查")
    try:
        fk = c.execute("PRAGMA foreign_key_check").fetchall()
        print("  违规: %d" % len(fk))
        for r in fk[:5]:
            print("   ", dict(r))
    except sqlite3.Error as e:
        print("  ERR %s" % e)
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
