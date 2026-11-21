# -*- coding: utf-8 -*-
"""QuizStudio 桌面版启动器。

打包成 exe 之后：
  · 双击就起一个本地服务（127.0.0.1，端口被占用会自动换），弹一个小窗口；
  · 「打开题库」用默认浏览器打开界面；
  · 题库数据放在 %LOCALAPPDATA%\\QuizStudio\\quiz_studio.db，首次运行从安装包里的模板复制一份，
    之后新增/修改的卷子都留在那，升级 exe 不会丢。
"""
import os
import shutil
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

APP_NAME = "QuizStudio"
TITLE = "QuizStudio 答题系统"


def res_dir():
    """打包后是临时解包目录，源码运行时是项目根目录。"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def pick_port(preferred=8770):
    for port in (preferred, 8769, 8768, 8771, 8772, 0):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            port = s.getsockname()[1]
            s.close()
            return port
        except OSError:
            s.close()
            continue
    return preferred


def seed_data(res, dat):
    """首次运行把模板数据库/配置复制到用户目录。"""
    db_dst = os.path.join(dat, "quiz_studio.db")
    if not os.path.exists(db_dst):
        src = os.path.join(res, "quiz_studio.db")
        if os.path.exists(src):
            shutil.copy2(src, db_dst)
    cfg_dst = os.path.join(dat, "quiz_studio_llm.json")
    if not os.path.exists(cfg_dst):
        src = os.path.join(res, "quiz_studio_llm.json")
        if os.path.exists(src):
            shutil.copy2(src, cfg_dst)
    # 桌面版默认不开 Eclipse 联动（对方机器不一定装了 Eclipse）
    ide_dst = os.path.join(dat, "quiz_studio_ide.json")
    if not os.path.exists(ide_dst):
        src = os.path.join(res, "quiz_studio_ide.json")
        if os.path.exists(src):
            shutil.copy2(src, ide_dst)
    return db_dst


def redirect_io(dat):
    """--windowed 打包后 sys.stdout/stderr 是 None，服务端的日志 print 会抛异常把请求打断，
    所以这里把它们接到用户目录的日志文件上（排查问题也方便）。"""
    log_path = os.path.join(dat, "quizstudio.log")
    if sys.stdout is None or sys.stderr is None:
        try:
            fh = open(log_path, "a", encoding="utf-8", buffering=1)
        except Exception:  # noqa: BLE001
            return None
        if sys.stdout is None:
            sys.stdout = fh
        if sys.stderr is None:
            sys.stderr = fh
        return fh
    return None


class Backend(threading.Thread):
    daemon = True

    def __init__(self, res, dat, port):
        super().__init__(name="quizstudio-server")
        self.res, self.dat, self.port = res, dat, port
        self.server = None
        self.error = None

    def run(self):
        try:
            sys.path.insert(0, self.res)
            import server
            from pathlib import Path
            # 静态资源（index.html）从安装包里读，数据/配置写到用户目录
            server.ROOT = Path(self.res)
            server.DB_PATH = Path(self.dat) / "quiz_studio.db"
            server.AI_CONFIG = Path(self.dat) / "quiz_studio_llm.json"
            server.IDE_CONFIG = Path(self.dat) / "quiz_studio_ide.json"
            server.OPENED_JSON = Path(self.dat) / "_opened_code.json"
            server.HOST = "127.0.0.1"
            server.PORT = self.port
            server.load_ai_config()
            server.load_ide_config()
            server.init_db()
            import http.server
            self.server = http.server.ThreadingHTTPServer((server.HOST, server.PORT), server.Handler)
            self.server.daemon_threads = True
            self.server.serve_forever()
        except Exception as exc:  # noqa: BLE001
            self.error = exc
            import traceback
            traceback.print_exc()

    def stop(self):
        if self.server:
            try:
                self.server.shutdown()
            except Exception:  # noqa: BLE001
                pass


def wait_ready(port, timeout=25):
    url = "http://127.0.0.1:%d/api/health" % port
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    return False


def main():
    res, dat = res_dir(), data_dir()
    redirect_io(dat)
    seed_data(res, dat)
    port = pick_port()

    be = Backend(res, dat, port)
    be.start()
    ok = wait_ready(port)
    url = "http://127.0.0.1:%d/" % port

    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except Exception:  # noqa: BLE001
        webbrowser.open(url)
        if not ok:
            print("服务启动失败：%s" % be.error)
            return 1
        try:
            while be.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        be.stop()
        return 0

    root = tk.Tk()
    root.title(TITLE)
    root.geometry("460x260")
    root.resizable(False, False)
    try:
        ico = os.path.join(res, "icon.ico")
        if os.path.exists(ico):
            root.iconbitmap(ico)
    except Exception:  # noqa: BLE001
        pass

    pad = {"padx": 18, "pady": 6}
    tk.Label(root, text=TITLE, font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w", **pad)
    tip = tk.Label(root, text="本地服务已启动，题库数据保存在：" + dat,
                   font=("Microsoft YaHei UI", 9), fg="#666", wraplength=420, justify="left")
    tip.pack(anchor="w", padx=18)

    stats = tk.StringVar(value="正在统计…")
    tk.Label(root, textvariable=stats, font=("Microsoft YaHei UI", 10), fg="#14785a").pack(
        anchor="w", padx=18, pady=(8, 4))

    def refresh_stats():
        try:
            import json
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                    "http://127.0.0.1:%d/api/health" % port, timeout=3) as r:
                j = json.loads(r.read().decode())
            n_banks = j.get("banks") or 0
            stats.set("题库：%d 卷    数据：%s" % (n_banks, os.path.basename(j.get("db") or "")))
        except Exception:  # noqa: BLE001
            stats.set("服务未就绪" if not ok else "统计失败")

    row = tk.Frame(root)
    row.pack(fill="x", padx=18, pady=12)

    def open_ui():
        webbrowser.open(url)

    ttk.Button(row, text="打开题库", command=open_ui).pack(side="left")
    ttk.Button(row, text="刷新统计", command=refresh_stats).pack(side="left", padx=8)
    ttk.Button(row, text="打开数据目录",
               command=lambda: os.startfile(dat) if hasattr(os, "startfile") else None).pack(side="left")

    addr = tk.Entry(row, width=22, font=("Consolas", 9))
    addr.insert(0, url)
    addr.configure(state="readonly")
    addr.pack(side="right")

    def on_close():
        if messagebox.askokcancel("退出", "退出后本地服务会关闭，题库数据已保存。确定退出？"):
            be.stop()
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    if not ok:
        messagebox.showerror("启动失败", "本地服务没起来：\n%s" % (be.error or "未知错误"))
    refresh_stats()
    open_ui()
    root.after(4000, refresh_stats)
    root.mainloop()
    be.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
