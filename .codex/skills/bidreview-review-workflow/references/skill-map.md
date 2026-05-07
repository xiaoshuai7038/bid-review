# Skill Map

使用这组 skills 时，按下面的边界选择。对齐事实来源时，以当前 runtime 的实现为准：

- `app/ai/prompts/templates/review/*`
- `app/ai/prompts/templates/role_detection/*`
- `app/review/workflows/legacy_engine.py`
- `app/review/execution_policy.py`

- `$bidreview-role-detection`
  - 只负责识别招标 / 投标文件角色
  - 不做完整审查
- `$bidreview-primary-review`
  - 负责首轮完整审查
  - 输出 `requirements`、`findings`、`summary`
  - 内部按 4 个逻辑阶段理解：
    - `requirements`：只从招标文件提取 requirement
    - `compliance`：常规逐条合规问题
    - `context`：主体基线、角色/位置一致性、模板字段角色错位、跨全文冲突
    - `semantic`：字段标签和值类型不匹配
- `$bidreview-second-pass`
  - 负责基于已有首轮结果做补漏
  - 只输出 `additional_findings`
  - 只补新增事实，不重写整份首轮结果

默认推荐顺序：

1. 先做角色识别
2. 再做首轮审查
3. 最后在需要时做二次复核

如果用户没有明确说是哪一步，就先判断任务属于哪个阶段，再切换到对应 skill。

如果任务是“同步升级 skill 以匹配项目新逻辑”，优先检查：

1. 当前 prompt/source 文件路径是否已迁移
2. 首轮审查是否仍是分阶段口径
3. second pass 是否仍只允许复用已有 `requirement_id`
4. 哪些 guard 仍属于 runtime，而不是 skill
