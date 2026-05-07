---
name: bidreview-review-workflow
description: 协调 bidreview 项目的 Codex skills。用户提出“生成 skill”“用哪个 skill”“先做角色识别再审查”“主审查后二次复核”“需要说明这些 skill 怎么放到 Codex 里使用”时使用。该 skill 负责根据任务选择 `bidreview-role-detection`、`bidreview-primary-review` 或 `bidreview-second-pass`，并说明哪些逻辑必须保留在 Python 运行时。
---

# Bidreview Review Workflow

把这个 skill 作为总入口。先判断任务属于哪个阶段，再切到对应 skill；不要在这里重复抄写所有业务规则，但要保持和当前 runtime 的分阶段审查口径一致。

## Workflow

1. 先读 [references/skill-map.md](references/skill-map.md)，确定应调用哪个 bidreview skill。
2. 如果任务只是在一组输入文件中判断哪个是招标文件、哪些是投标文件，切到 `$bidreview-role-detection`。
3. 如果任务是“招标文件 + 投标文件”的首次完整审查，切到 `$bidreview-primary-review`。
   当前首轮审查不是单个大提示词，而是按“requirements 提取 -> compliance/context/semantic 分层审查 -> 合并去重 -> summary.review_scope”来执行。
4. 如果任务是在已有首轮结果基础上补漏，只输出新增 finding，切到 `$bidreview-second-pass`。
   若 runtime 已按 profile 自动带二次复核，这个 skill 仍用于“单独做补漏”或“解释 second pass 规则”的场景。
5. 若用户问这些 skill 如何在 Codex 中使用，读 [references/placement.md](references/placement.md)。
6. 若你不确定某条逻辑应写进 skill 还是留在 Python 运行时，读 [references/runtime-boundaries.md](references/runtime-boundaries.md)。

## Guardrails

- 不要把这个 workflow skill 当成一个大而全的审查提示词。
- 不要把当前已经拆成多阶段的主审查，又退回成“读完两份文件后自由发挥”的旧式描述。
- 不要在这里复制所有角色识别、主审查、复核细节；这些应放在对应 skill。
- 不要把 review profile、OCR 预处理、completion retry、导出逻辑误搬进 skill 文档。
