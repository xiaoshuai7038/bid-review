---
name: bidreview-role-detection
description: 识别输入文件中哪个是招标文件、哪个或哪些是投标文件。用户提到“自动识别招标/投标角色”“先判断文件身份”“一份招标多份投标”“只做角色识别，不做完整审查”时使用。输出必须是纯 JSON。
---

# Bidreview Role Detection

执行招标 / 投标文件角色识别，并只输出 JSON，不输出额外解释。

## Workflow

1. 先读 [references/role-detection-rules.md](references/role-detection-rules.md)。
2. 若调用方已经显式给出招标 / 投标角色，把它视为人工优先信息；这个 skill 只在自动识别场景下真正做判断。
3. 自动识别时先根据文件名和文件 stem 判断。
4. 只有在文件名不足以区分时，才读取文件内容做最小必要确认；不要提前进入完整审查。
5. 单招标单投标场景输出 `tender_id + bid_id`；一招标多投标场景输出 `tender_id + bid_ids`。
6. `reasoning` 只写一句话，说明最主要判断依据。
7. 如需确认哪些逻辑仍属于 runtime，读 [references/runtime-boundaries.md](references/runtime-boundaries.md)。

## Guardrails

- 只输出 JSON。
- 永远只返回 1 个招标文件。
- 不要在角色识别 skill 中提前执行完整审查。
- 不要引用历史审查产物或生成文件来判断角色。
