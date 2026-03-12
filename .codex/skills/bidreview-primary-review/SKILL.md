---
name: bidreview-primary-review
description: 执行 bidreview 的首轮完整审查。用户提到“主审查”“首次审查”“输出 requirements/findings/summary”“按招标文件逐条审查投标文件”“提取硬性要求并找出不符合项”时使用。输出必须是首轮审查 JSON。
---

# Bidreview Primary Review

执行首轮完整审查，并输出包含 `requirements`、`findings`、`summary` 的 JSON。

## Workflow

1. 先读 [references/domain-rules.md](references/domain-rules.md)。
2. 再读 [references/evidence-and-output-contract.md](references/evidence-and-output-contract.md)。
3. 如需确认哪些逻辑必须留在 Python runtime，读 [references/runtime-boundaries.md](references/runtime-boundaries.md)。
4. 按以下顺序执行：
- 读取招标文件关键章节
- 提取硬性要求
- 建立主体基线
- 逐条审查投标文件
- 输出标准 JSON
5. 如任务其实是“已有首轮结果，只找遗漏项”，切换到 `$bidreview-second-pass`。

## Guardrails

- 只读分析，不在分析过程中写本地中间文件。
- 对模板字段、主体一致性、证据定位要用字段级结论，不要泛化。
- 输出必须是 JSON，不要带 markdown。
