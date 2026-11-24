# `importers` — 东软智慧教育平台题库导入

平台是登录态 SPA，题目通过 `/web-api/` 的 JSON 接口下发。两条路都验证过：

| 方式 | 用于 | 说明 |
| --- | --- | --- |
| **接口直取**（推荐） | 所有测验/试卷 | 结构最干净，还带知识点 `ktPointList`，章节不用猜 |
| HTML 解析 | 兜底 | 只有渲染后的抽屉 HTML 时用，题干/选项靠正则+DOM 树还原 |

## 一、接口直取（现在用的这条路）

登录态在 `..\..\Github项目查询\_edge\`（Chrome 调试实例 + token），流程：

1. `_edge\list_tests.py` —— `POST /web-api/teachmanager/teach-course-res-stu/test/list`
   拿到课程下全部测验：`{id, dataId, name, resCtl.id, resCtl.openTimeStr, ...}`
2. `_edge\fetch_all_papers.py` —— 对每份卷子
   `GET /web-api/smartexam/test/student/paper?testId=<resCtl.id>`
   存到 `_edge\papers\<名称>.json`
3. `_edge\paper_to_bank.py` —— 转成 QuizStudio 题库并 `POST /api/banks`
   （题库落盘副本在 `_edge\banks\<题库id>.json`）

请求头必须带：`Authorization: Bearer <token>`、`tenant-id: 1843937598321012737`
（不是 `userIdentity` 的 5）。缺 tenant 会返回 `403 您无权访问该租户的数据`。

## 二、HTML 解析（兜底）

```powershell
cd 'E:\桌面映射\Java\QuizStudio答题系统'
py -3 importers\parse_tongyi.py "importers\统一练习1.html" "importers\统一练习1.json" `
  "bank_tongyi_1" "Java语言程序设计III · 统一练习-1（200 题 · 373 分）" [--no-chapter]
```

`统一练习1.html` 是最早那次粘贴的抽屉 HTML，`统一练习1.json` 是它的产物；
**已被接口版覆盖**（同一 id `bank_tongyi_1` 会被 upsert），保留仅作对照。

## 三、已入库的卷子

| 题库 id | 内容 | 题数 | 满分 | 章节来源 |
| --- | --- | --- | --- | --- |
| `bank_java3_253` | 全部题库（13 章 + 大题专项） | 253 | — | 手动 |
| `bank_tongyi_1` | 统一练习-1 | 200 | 373 | 知识点 |
| `bank_tongshi_2` | 统一试卷2 | 45 | 89 | 知识点 |
| `bank_quiz_jb1` | Java基础部分课堂测验1 | 5 | 5 | 知识点 |
| `bank_quiz_arr` | 数组部分随堂测验 | 5 | 12 | 知识点 |
| `bank_quiz_ext` | 继承部分课堂测验 | 8 | 40 | 知识点 |
| `bank_quiz_jb2` | Java基础部分课堂测验2 | 9 | 9 | 知识点 |

课程下没有「统一练习-2」，第二个「统一*」就是统一试卷2。

## 四、答案

平台的公布策略是「提交后自动公布」（`resCtl.answerPublishType=2`），
`paper` 接口里 272 题的 `standardAnswer` / `analysis` 全是 `null`，
试过的 result/answer/analysis 类端点一律 500。所以导入的题库 `answer` 为空：

- 统一练习-1 有 4 题题干自身印了字母（第 69/81/94/98 题），已回填并在 `exp` 注明「答案来自题干」
- 其余靠 QuizStudio 的 AI 判分或人工对答案

## 五、知识点 → 章节

`paper_to_bank.py` 里的 `KT_CH` 把 27 个知识点映射到课程 13 章，例如
`KT8_一维数组→6`、`KT17_类的继承→8`、`KT21_abstract修饰符→9`、`KT29_JDBC基础→13`。
272 题全部命中知识点，没有落到「未分类」。
