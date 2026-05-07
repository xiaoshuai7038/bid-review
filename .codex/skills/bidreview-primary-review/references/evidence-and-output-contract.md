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
      "source": "招标文件第X页 Lm-Ln：关键原文"
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
    "finding_count": 0,
    "review_scope": {
      "tender_total_pages_seen": 0,
      "tender_sections_reviewed": [],
      "bid_sections_reviewed": [],
      "docx_image_count_seen": 0,
      "docx_ocr_completed": false,
      "completion_check_passed": false
    }
  }
}
```

## Evidence Rules

- 招标证据和投标证据都要精确到行级。
- PDF 证据写法：
  - `招标文件第X页 Lm-Ln：关键原文`
  - `投标文件第X页 Lm-Ln：关键原文`
- Word 证据写法：
  - `投标文件《章节名》Lm-Ln：关键原文`
- OCR 图片证据写法：
  - `投标文件第X页图片OCR Lm-Ln：关键原文`
  - 或 `投标文件《章节名》图片OCR Lm-Ln：关键原文`
- 如果是同一主体字段冲突，`bid_evidence` 至少给出两处冲突位置。
- 如果证据来自图片，先读取图片中的文字，再引用关键原文；不要留下“需 OCR 验证”占位话。

## Writing Rules

- `issue` 要写完整句，不能用省略号。
- `recommendation` 面向标书编制人员，使用业务语言，不要写运行时术语。
- 同一事实只输出一条 finding；措辞变化但证据和事实相同，视为重复。
- requirement 和 finding 都不要输出 markdown 解释文字。
