# Evidence And Output Contract

## Output JSON

只输出 JSON：

```json
{
  "requirements": [
    {
      "id": "R001",
      "category": "资格资质|工期交付|报价税务|响应格式|技术要求|主体一致性|其他",
      "text": "硬性要求内容",
      "source": "章节/页码/原文定位"
    }
  ],
  "findings": [
    {
      "id": "F001",
      "requirement_id": "R001",
      "status": "non_compliant|risk|needs_manual",
      "issue": "问题描述",
      "tender_evidence": "招标证据",
      "bid_evidence": "投标证据",
      "recommendation": "整改建议"
    }
  ],
  "summary": {
    "requirement_count": 0,
    "finding_count": 0
  }
}
```

## Evidence Rules

- 招标证据和投标证据都要精确定位。
- 如果是同一主体字段冲突，`bid_evidence` 至少给出两处冲突位置。
- 对截图或图片证据，先读取图片中的文字，再引用关键原文。
- finding 要去重，同一事实不要重复输出。

## Writing Rules

- `issue` 要写完整句。
- `recommendation` 要面向标书编制人员，可执行。
- 不要把已有明确字段错误降级成泛化“需人工核验”。
