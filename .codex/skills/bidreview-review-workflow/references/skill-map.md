# Skill Map

使用这组 skills 时，按下面的边界选择：

- `$bidreview-role-detection`
  - 只负责识别招标 / 投标文件角色
  - 不做完整审查
- `$bidreview-primary-review`
  - 负责首轮完整审查
  - 输出 `requirements`、`findings`、`summary`
- `$bidreview-second-pass`
  - 负责基于已有首轮结果做补漏
  - 只输出 `additional_findings`

默认推荐顺序：

1. 先做角色识别
2. 再做首轮审查
3. 最后在需要时做二次复核

如果用户没有明确说是哪一步，就先判断任务属于哪个阶段，再切换到对应 skill。
