// 科目/章节 纯函数单元测试：从 index.html 里切出 CHS + 章节辅助函数来跑
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const a = src.indexOf('var CHS = [');
const b = src.indexOf('function esc(');
if (a < 0 || b < 0 || b < a) { console.error('切片失败'); process.exit(2); }
const code = src.slice(a, b);
const f = new Function('esc', code + `
  return { CHS, bankChapters, chNameOf, chShortOf, chTagOf, ensureChapter, chapterFromStem, chapOptions };`);
const M = f((s) => String(s == null ? '' : s));

let fails = [];
function eq(got, want, name) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) fails.push(name + '：得到 ' + JSON.stringify(got) + ' 期望 ' + JSON.stringify(want));
  console.log((ok ? 'ok   ' : 'FAIL ') + name + ' -> ' + JSON.stringify(got));
}

/* 1. 老卷子（没有 chapters）回退 Java 13 章 */
const legacy = { questions: [] };
eq(M.bankChapters(legacy).length, 13, '老卷子回退 13 章');
eq(M.chNameOf(legacy, 10), '第 10 章 · 异常处理', '老卷子 chName');
eq(M.chShortOf(legacy, 10), '第 10 章', '老卷子 chShort');

/* 2. 新科目：自定义章节 */
const math = { subject: '高等数学', chapters: [{ id: 1, name: '第 1 章 · 极限', tag: '数列 / 函数' }], questions: [] };
eq(M.chNameOf(math, 1), '第 1 章 · 极限', '自定义章节名');
eq(M.chTagOf(math, 1), '数列 / 函数', '自定义 tag');
eq(M.chNameOf(math, 0), '其他 / 综合', '未分类名');
eq(M.chNameOf(math, 7), '第 7 章', '没有该章时的兜底');

/* 3. 新增章节是幂等的 */
const b2 = { chapters: [] };
const id1 = M.ensureChapter(b2, '第 1 章 · 极限');
const id1b = M.ensureChapter(b2, '第 1 章 · 极限');
const id2 = M.ensureChapter(b2, '第 2 章 · 导数');
eq([id1, id1b, id2], [1, 1, 2], 'ensureChapter 幂等 + 自增');
eq(b2.chapters.length, 2, '章节数');
eq(M.ensureChapter(b2, ''), 0, '空名返回 0');

/* 4. 从题干里读章节标注 */
eq(M.chapterFromStem('1. 求极限\n章节：第 1 章 · 极限'), '第 1 章 · 极限', '章节：标注');
eq(M.chapterFromStem('题目 第 3 章 分支结构 下面的说法'), '第 3 章 分支结构', '正文里的第N章');
eq(M.chapterFromStem('没有章节信息的题'), '', '没有标注');

/* 5. 下拉选项 */
const opts = M.chapOptions(math, 1);
eq(opts.indexOf('selected') > 0, true, '下拉里有选中项');
eq(opts.indexOf('__new') > 0, true, '下拉里有新建章节');

/* 6. 章节号超出 13 不再崩（老代码 CHS[k-1].tag 会抛） */
const far = { chapters: [{ id: 20, name: '第 20 章 · 深入', tag: 'x' }] };
eq(M.chTagOf(far, 20), 'x', '章节号 20 正常');
eq(M.chTagOf(legacy, 20), '', '老卷子查 20 不抛错');

console.log(fails.length ? ('\n失败 ' + fails.length + ' 项:\n' + fails.join('\n')) : '\n全部通过');
process.exit(fails.length ? 1 : 0);
