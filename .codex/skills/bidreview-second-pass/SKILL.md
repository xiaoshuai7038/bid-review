---
name: bidreview-second-pass
description: 执行 bidreview 的二次复核，只返回首轮遗漏的新增 finding。用户提到“二次复核”“补漏”“已有初审结果只找新增问题”“additional_findings”时使用。输出必须是只包含新增 finding 的 JSON。
---

# Bidreview Second Pass

执行二次复核，并只输出 `additional_findings` JSON。

## Workflow

1. 先读 [references/delta-review-rules.md](references/delta-review-rules.md)。
2. 再读 [references/evidence-and-output-contract.md](references/evidence-and-output-contract.md)。
3. 如需确认哪些逻辑必须留在 Python runtime，读 [references/runtime-boundaries.md](references/runtime-boundaries.md)。
4. 重新读取招标和投标文件，不要盲信首轮结果。
5. 只输出新增 finding，不重复首轮已覆盖事实。
6. `requirement_id` 只能复用首轮已有 requirement，不能新增 requirement 编号。
7. 如果没有新的、证据充分的遗漏项，返回空数组。

## Guardrails

- 只返回新增项。
- 不要把首轮同义改写、证据相同的重复问题当新增 finding。
- 不要把 second pass 变成整份首轮报告重写。
- 输出必须是 JSON，不要带 markdown。
