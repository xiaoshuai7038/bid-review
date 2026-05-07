# Runtime Boundaries

以下内容应保留在 Python runtime，而不是写死到 skill 文档里：

- backend 选择和可用性检查
- 输出目录创建和产物命名
- batch orchestration
- 进度回调与日志输出
- review profile（`fast` / `balanced` / `thorough`）及其对应的 second-pass/retry 策略
- OCR 预处理、提图过滤、缓存复用和“禁止重复批量提图/OCR”约束
- OCR 强制覆盖校验
- no-write 检测、工具白名单、超时拉长与重试
- JSON fallback / repair
- completion gate、requirements completion retry、precise-location retry
- finding / requirement 归一化与 dedupe
- 证据定位增强与稳定性兜底补齐
- markdown / json / docx 导出

skill 文档应保留的内容：

- 审查步骤和阶段边界
- 角色识别逻辑
- requirements 提取规则
- 主体一致性、字段语义、模板字段审查规则
- 证据书写和 finding 约束
