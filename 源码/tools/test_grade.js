// gradeOne 单元测试：直接跑 index.html 里的判分函数（纯函数，无 DOM）
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const start = src.indexOf('function normLetters');
const end = src.indexOf('function computeReport');
if (start < 0 || end < 0) { console.error('切片失败'); process.exit(2); }
const code = src.slice(start, end);
const mod = { exports: {} };
new Function('module', code + '\nmodule.exports={gradeOne, normLetters};')(mod);
const { gradeOne } = mod.exports;

const cases = [
  // [标题, 题目, 用户作答, 期望 verdict, 期望 comment 包含]
  ['单选有答案答对', { type: 'single', answer: 'B' }, 'B', 'ok', ''],
  ['单选有答案答错', { type: 'single', answer: 'B' }, 'A', 'bad', '正确答案：B'],
  ['单选缺答案（原来是 bad）', { type: 'single', answer: '' }, 'B', 'pending', '题库缺标准答案'],
  ['多选缺答案', { type: 'multi', answer: '' }, 'AB', 'pending', '题库缺标准答案'],
  ['未作答', { type: 'single', answer: 'B' }, '  ', 'na', ''],
  ['判断缺答案', { type: 'judge', answer: '' }, 'T', 'na', ''],
  ['填空缺答案', { type: 'blank', answer: '' }, 'abc', 'na', ''],
];

let fail = 0;
for (const [name, q, user, wantV, wantC] of cases) {
  const g = gradeOne(q, user);
  const okV = g.verdict === wantV;
  const okC = !wantC || String(g.comment).includes(wantC);
  if (!okV || !okC) {
    fail++;
    console.log('FAIL  %s -> %s  期望 %s / 注释含「%s」', name, JSON.stringify(g), wantV, wantC);
  } else {
    console.log('ok    %s -> verdict=%s comment=%j', name, g.verdict, g.comment);
  }
}
console.log(fail ? ('\n%d 条失败' % fail) : '\n全部通过（' + cases.length + ' 条）');
process.exit(fail ? 1 : 0);
