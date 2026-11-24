# -*- coding: utf-8 -*-
"""类名猜测回归测试。"""
import sys

sys.path.insert(0, r"E:\桌面映射\Java\QuizStudio答题系统")
import server  # noqa: E402

CASES = [
    ("题目：Prog1类与对象\n1) 属性：两个double成员变量", "Prog1"),
    ("题目：定义一个名为Prog1的类，属性有平时成绩", "Prog1"),
    ("题目：定义一个电风扇类Fan，要求如下", "Fan"),
    ("题目：设计一个描述二维平面上点的类Point，要求如下", "Point"),
    ("题目：设计一个模拟银行账户功能的类Account，要求如下", "Account"),
    ("题目：设计一个关于等边三角形的类Trival，要求如下", "Trival"),
    ("现有父类Person，在此基础上派生出子类Student，子类定义了自己的属性", "Student"),
    ("题目：定义一个教师类Teacher，要求如下", "Teacher"),
    ("使用 while 循环，求 1 到 100 连续自然数的和。", ""),
    ("【五星红旗高高飘扬】(1) 使用记事本编写一个 Java 应用程序", ""),
]

ok = 0
for text, want in CASES:
    got = server._guess_answer_class(text)
    good = got == want
    ok += good
    print("%s  %-44s -> %-10r 期望 %r" % ("ok  " if good else "FAIL", text[:40], got, want))
print("\n%d/%d 通过" % (ok, len(CASES)))
