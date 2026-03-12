# Runtime Boundaries

以下内容应保留在 Python runtime，而不是写死到 skill 文档里：

- backend 选择和可用性检查
- 输出目录创建和产物命名
- batch orchestration
- 进度回调与日志输出
- OCR 强制覆盖校验
- no-write 检测与重试
- JSON fallback 解析
- finding / requirement 归一化与 dedupe
- 证据定位增强
- markdown / json / docx 导出

skill 文档应保留的内容：

- 审查步骤
- 角色识别逻辑
- 主体一致性和模板字段审查规则
- 证据书写和 finding 约束
