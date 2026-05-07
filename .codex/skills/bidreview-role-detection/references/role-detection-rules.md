# Role Detection Rules

## Goal

识别输入文件中哪个是招标文件，哪个或哪些是投标文件。

## Decision Order

1. 若用户或上游 runtime 已明确指定 `tender` / `bid` 角色，优先尊重人工指定。
2. 否则先看文件名和 stem。
3. 若文件名不够明确，再读取文档内容做最小必要确认。
4. 只能返回 1 个招标文件；可以返回 1 个或多个投标文件。

## Filename Heuristics

- 常见招标侧关键词：
  - `招标`
  - `招标文件`
  - `采购文件`
  - `磋商文件`
  - `竞争性谈判`
- 常见投标侧关键词：
  - `投标`
  - `投标文件`
  - `响应文件`
  - `报价文件`
  - `应答文件`

## Content Hints

- 招标侧常见内容：
  - `投标人须知`
  - `评标办法`
  - `招标文件格式`
  - `采购需求`
- 投标侧常见内容：
  - `投标函`
  - `资格审查申请书`
  - `报价一览表`
  - `授权委托书`
  - `营业执照`

## Output Contracts

单招标单投标：

```json
{
  "tender_id": "D1",
  "bid_id": "D2",
  "reasoning": "一句话说明依据"
}
```

一招标多投标：

```json
{
  "tender_id": "D1",
  "bid_ids": ["D2", "D3"],
  "reasoning": "一句话说明依据"
}
```

## Guardrails

- 只输出 JSON。
- `reasoning` 保持一句话。
- 只读取本次输入文件，不要读取 `review_result.json`、`batch_summary.json` 等派生产物。
- 如果自动识别存在歧义，仍要给出最合理判断，不要在这个 skill 中自行扩展成完整编排逻辑。
