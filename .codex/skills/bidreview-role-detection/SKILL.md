---
name: bidreview-role-detection
description: 识别输入文件中哪个是招标文件、哪个或哪些是投标文件。用户提到“自动识别招标/投标角色”“先判断文件身份”“一份招标多份投标”“只做角色识别，不做完整审查”时使用。输出必须是纯 JSON。
---

# Bidreview Role Detection

执行招标 / 投标文件角色识别，并只输出 JSON，不输出额外解释。

## Workflow

1. 先读 [references/role-detection-rules.md](references/role-detection-rules.md)。
2. 先根据文件名判断。
3. 若文件名不足以区分，再读取文件内容做最小必要确认。
4. 单招标单投标场景输出 `tender_id + bid_id`。
5. 一招标多投标场景输出 `tender_id + bid_ids`。
6. `reasoning` 只写一句话，说明最主要判断依据。

## Guardrails

- 只输出 JSON。
- 永远只返回 1 个招标文件。
- 不要在角色识别 skill 中提前执行完整审查。
