# Runtime Boundaries

以下内容保留在 runtime：

- 首轮和二次复核结果的最终合并
- finding ID 重编
- dedupe 的最终兜底
- evidence enrichment
- retry / timeout / OCR enforce

skill 文档负责：

- 说明什么是“新增 finding”
- 说明哪些遗漏项要重点复核
- 说明输出必须只包含 `additional_findings`
