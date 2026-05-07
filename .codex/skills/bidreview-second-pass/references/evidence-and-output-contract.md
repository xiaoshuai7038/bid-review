# Evidence And Output Contract

只输出 JSON：

```json
{
  "additional_findings": [
    {
      "requirement_id": "R001",
      "status": "non_compliant|risk|needs_manual",
      "issue": "问题描述",
      "tender_evidence": "招标证据",
      "bid_evidence": "投标证据",
      "recommendation": "建议"
    }
  ]
}
```

约束：

- 只返回新增 finding。
- 不重复首轮已覆盖的同一事实。
- 证据必须精确到行级。
- 若为同一字段前后冲突，`bid_evidence` 至少写两处冲突位置。
- recommendation 要可执行，并使用业务语言。
- 没有新增项时返回空数组，不要输出解释文本。
