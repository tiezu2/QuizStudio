# -*- coding: utf-8 -*-
"""检查本地小模型（Ollama）是否可用，并实测一次判分调用。

用法：
    py -3 tools/test_local_model.py
    py -3 tools/test_local_model.py --model qwen2.5:7b
不依赖 server.py 的常驻进程，直接复用它的 ai_chat。
"""
import json
import os
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

BASE = "http://127.0.0.1:11434"


def http(path, timeout=10):
    req = urllib.request.Request(BASE + path, headers={"Accept": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    model_arg = ""
    if "--model" in sys.argv:
        i = sys.argv.index("--model")
        if i + 1 < len(sys.argv):
            model_arg = sys.argv[i + 1]

    print("--- Ollama 状态 ---")
    try:
        ver = http("/api/version")
        print("服务在跑：%s  版本 %s" % (BASE, ver.get("version")))
    except Exception as exc:  # noqa: BLE001
        print("连不上 %s：%s" % (BASE, exc))
        print("\n先装 Ollama 并启动：https://ollama.com/download")
        print("  安装后执行： ollama pull qwen2.5:3b")
        return 1

    try:
        tags = http("/api/tags")
        models = [m.get("name") for m in tags.get("models") or []]
        print("已下载模型：%s" % (", ".join(models) if models else "（一个都没有，先 ollama pull qwen2.5:3b）"))
    except Exception as exc:  # noqa: BLE001
        models = []
        print("列模型失败：%s" % exc)

    want = model_arg or "qwen2.5:3b"
    print("\n--- 用 %s 跑一次真实判分 ---" % want)
    server.load_ai_config()
    # 强制只走本地通道，避免测到云上去了
    server.PROVIDERS = [{"name": "local", "url": BASE + "/v1/chat/completions", "model": want}]
    server.MIN_AI_GAP = 0.0

    q = {
        "id": "q1",
        "type": "单选题",
        "stem": "以下关于继承的描述错误的是",
        "opts": "A.继承体现类与类之间的 is-a 关系 | B.子类可以直接访问父类中所有的属性和方法 | "
                "C.Java 中类的继承是单继承 | D.父类是子类共性的提取",
        "ref": "",
        "user": "A",
        "unkeyed": True,
    }
    t0 = time.time()
    try:
        judge, provider, asked = server.ai_judge([q])
    except Exception as exc:  # noqa: BLE001
        print("调用失败：%s" % exc)
        return 1
    dt = time.time() - t0
    print("通道 %s  送 %d 题  用时 %.1fs" % (provider, asked, dt))
    print("判定：%s" % json.dumps(judge, ensure_ascii=False))
    if not judge:
        print("（模型没返回可解析的 JSON，换个更大的模型试试：--model qwen2.5:7b）")
        return 1
    print("\n本地判分可用 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
