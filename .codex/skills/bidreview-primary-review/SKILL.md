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
4. 把首轮审查看成一个分阶段流程，而不是单次自由发挥：
   - 先只从招标文件提取 requirements
   - 冻结 requirement 编号后，再对投标文件做 3 类 findings 检查
   - 最后合并、去重并补齐 `summary.review_scope`
5. 若调用方已经提供 OCR 预处理状态或受控图片结果，优先复用，不要重复做整批提图 / OCR。
6. 如任务其实是“已有首轮结果，只找遗漏项”，切换到 `$bidreview-second-pass`。

## Guardrails

- 输出必须是 JSON，不要带 markdown。
- 不要把 `context` / `semantic` 两类字段级问题又降回泛化的“需人工核验”。
- 不要自行补写 runtime 才负责的 retry、导出、ID 重编和稳定性兜底。
- 不要跳过 `summary.review_scope`；当前 runtime 明确依赖这部分来判断完成度。
