# Runtime Boundaries

以下内容保留在 runtime：

- 首轮和二次复核结果的最终合并
- second-pass 是否自动启用的 profile / 环境开关
- finding ID 重编
- dedupe 的最终兜底
- OCR 预处理、缓存复用和覆盖校验
- no-write / timeout / retry / JSON repair
- evidence enrichment

skill 文档负责：

- 说明什么是“新增 finding”
- 说明哪些遗漏项要重点复核
- 说明只允许复用已有 `requirement_id`
- 说明输出必须只包含 `additional_findings`
