# Role Detection Rules

## Goal

识别输入文件中哪个是招标文件，哪个或哪些是投标文件。

## Heuristics

1. 先看文件名。
- 常见招标侧关键词：
  - `招标`
  - `招标文件`
  - `采购文件`
- 常见投标侧关键词：
  - `投标`
  - `投标文件`
  - `响应文件`
2. 若文件名不够明确，再读取文档内容做最小必要确认。
3. 只能返回 1 个招标文件。
4. 可以返回 1 个或多个投标文件。

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
- 如果用户已经显式指定 `--tender` / `--bid` 角色，则应优先尊重手工指定。
