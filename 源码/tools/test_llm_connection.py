# -*- coding: utf-8 -*-
"""一条命令自检 AI 通道：读 quiz_studio_llm.json，发一个最小请求，打印实际走的通道与耗时。

用法：
    py -3 tools/test_llm_connection.py
    py -3 tools/test_llm_connection.py "出一道 Java 选择题并给答案"

不依赖正在运行的 server.py，直接复用 server 里的配置与 ai_chat。
"""
import os
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.path.isdir(os.path.join(PROJ, "源码")):            # 脚本在 源码\tools|importers 下时上跳
    PROJ = os.path.dirname(PROJ)
# 运行时文件（server.py / index.html / 数据库 / 配置）都在 PROJ\程序 下
ROOT = os.path.join(PROJ, "程序") if os.path.isdir(os.path.join(PROJ, "程序")) else PROJ
sys.path.insert(0, ROOT)
import server  # noqa: E402

PROMPT = sys.argv[1] if len(sys.argv) > 1 else "用一句话说明 Java 里 ArrayList 和 LinkedList 的区别。"


def main():
    server.load_ai_config()
    print("--- 当前配置 ---")
    print("通道   : %s" % ", ".join("%s(%s)" % (p["name"], p["model"]) for p in server.PROVIDERS))
    print("地址   : %s" % server.PROVIDERS[0]["url"])
    print("Key    : %s" % ("已配置（%s…）" % server.API_KEY[:6] if server.API_KEY else "（空，走免费通道）"))
    print("间隔   : %.0fs   批量: %d 题 × %d 批   超时: %.0fs"
          % (server.MIN_AI_GAP, server.JUDGE_BATCH, server.MAX_JUDGE_CALLS, server.TIMEOUT))
    print("--- 发起一次真实调用 ---")
    t0 = time.time()
    try:
        txt, provider = server.ai_chat("你只回答一句话，不要任何前缀。", PROMPT, max_tokens=200)
    except Exception as exc:  # noqa: BLE001
        print("失败：%s" % exc)
        print("\n排查顺序：")
        print("  1) api_key 是否填了（智谱 Key 形如 xxxxxxxx.yyyyyyyy）")
        print("  2) 控制台里该模型是否已开通 / 免费额度是否用完")
        print("  3) base_url 是否为 https://open.bigmodel.cn/api/paas/v4")
        return 1
    print("成功 · 通道 %s · 用时 %.1fs" % (provider, time.time() - t0))
    print("回复：%s" % txt.strip()[:400])
    return 0


if __name__ == "__main__":
    sys.exit(main())
