# -*- coding: utf-8 -*-
"""把桌面主题的 CSS 注入到 index.html（可反复执行，不会叠加）。

index.html 里那段「/* === QS THEME === */ … /* === QS THEME END === */」就是产物，
真正的样式源文件是 desktop/theme-light.css。改完 CSS 跑一次本脚本即可。

    py -3 _dev/apply_theme.py
    py -3 _dev/apply_theme.py desktop/theme-light.css
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "index.html")
MARK = "/* === QS THEME === */"
END = "/* === QS THEME END === */"


def main():
    css_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "desktop", "theme-light.css")
    if not os.path.isabs(css_path):
        css_path = os.path.join(ROOT, css_path)
    if not os.path.exists(css_path):
        raise SystemExit("找不到主题文件：%s" % css_path)

    css = io.open(css_path, encoding="utf-8").read()
    html = io.open(HTML, encoding="utf-8").read()
    before = len(html)
    html = re.sub(r"\n?/\* === (?:QS|ARK) THEME === \*/.*?/\* === (?:QS|ARK) THEME END === \*/\n",
                  "\n", html, flags=re.S)
    i = html.rindex("</style>")
    html = html[:i] + "\n" + MARK + "\n" + css + "\n" + END + "\n" + html[i:]
    io.open(HTML, "w", encoding="utf-8").write(html)
    print("已注入 %s：CSS %d 字节，index.html %d → %d 字节" % (
        os.path.basename(css_path), len(css), before, len(html)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
