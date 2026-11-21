# -*- coding: utf-8 -*-
"""验证 quiz_studio_llm.json 的解析：免费 vs 自带 Key 两套默认值。

做法：把真配置临时挪走 → 写一份测试配置 → 调 load_ai_config() → 读回全局量 → 还原。
不联网，只验证配置逻辑。
"""
import json
import os
import shutil
import sys
import tempfile

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.path.isdir(os.path.join(PROJ, "源码")):            # 脚本在 源码\tools|importers 下时上跳
    PROJ = os.path.dirname(PROJ)
# 运行时文件（server.py / index.html / 数据库 / 配置）都在 PROJ\程序 下
ROOT = os.path.join(PROJ, "程序") if os.path.isdir(os.path.join(PROJ, "程序")) else PROJ
sys.path.insert(0, ROOT)
CFG = os.path.join(ROOT, "quiz_studio_llm.json")
BACKUP = CFG + ".test-backup"


def run(name, cfg, expect):
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False)
    # 每次重新加载模块，避免全局量互相污染
    for m in list(sys.modules):
        if m == "server":
            del sys.modules[m]
    import server
    server.load_ai_config()
    got = {
        "key": bool(server.API_KEY),
        "gap": server.MIN_AI_GAP,
        "batch": server.JUDGE_BATCH,
        "calls": server.MAX_JUDGE_CALLS,
        "url": server.PROVIDERS[0]["url"],
        "model": server.PROVIDERS[0]["model"],
    }
    ok = all(got[k] == v for k, v in expect.items())
    print("%s %-22s %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, ensure_ascii=False)))
    if not ok:
        print("     期望: %s" % json.dumps(expect, ensure_ascii=False))
    return ok


def main():
    if os.path.exists(CFG):
        shutil.copy2(CFG, BACKUP)
    fails = 0
    try:
        fails += not run("免费通道（默认）", {"enabled": True, "api_key": ""},
                         {"key": False, "gap": 46.0, "batch": 14, "calls": 2,
                          "url": "https://text.pollinations.ai/openai"})
        fails += not run("带 Key（默认放大）", {"enabled": True, "api_key": "sk-test",
                                           "model": "deepseek-chat"},
                         {"key": True, "gap": 0.0, "batch": 20, "calls": 20,
                          "url": "https://api.deepseek.com/chat/completions",
                          "model": "deepseek-chat"})
        fails += not run("带 Key + 自定义 base", {"enabled": True, "api_key": "sk-test",
                                              "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                                              "model": "qwen-plus"},
                         {"key": True,
                          "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                          "model": "qwen-plus"})
        fails += not run("providers 优先", {"enabled": True, "api_key": "sk-test",
                                         "providers": [{"name": "本地", "url": "http://127.0.0.1:11434/v1/chat/completions",
                                                        "model": "qwen2.5:7b"}]},
                         {"key": True, "url": "http://127.0.0.1:11434/v1/chat/completions",
                          "model": "qwen2.5:7b"})
        fails += not run("自定义闸门/批量", {"enabled": True, "api_key": "sk-test",
                                      "min_gap": 3, "judge_batch": 8, "max_judge_calls": 5},
                         {"gap": 3.0, "batch": 8, "calls": 5})
        fails += not run("enabled=false 忽略", {"enabled": False, "api_key": "sk-test"},
                         {"key": False, "gap": 46.0})
    finally:
        if os.path.exists(BACKUP):
            shutil.move(BACKUP, CFG)
    print("\n%s" % ("全部通过" if not fails else "%d 项失败" % fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
