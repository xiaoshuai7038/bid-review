# Runtime Boundaries

## Python Runtime Owns

- CLI / GUI 参数解析
- 输入文件路径与运行目录隔离
- prompt 选择与阶段编排
- MCP 配置拼装
- 重试、完成度 gate、缓存和产物导出
- harness、CI、仓库文档、任务文档

## Model Runtime Owns

- 招标 / 投标角色判断
- requirements 提取
- findings 判断
- second pass 补漏

本地代码不负责重写这些业务判断标准。

## MCP Runtime Owns

- PDF 结构化读取
- Word 结构化读取
- Word 图片提取
- OCR 调用与缓存

## Harness Owns

- 离线可执行验证入口
- repo-native smoke cases
- 结果 manifest 和断言
- 为 CI 提供统一命令入口

## Out Of Scope For P0 Harness

- 需要在线模型凭证的默认 case
- 真实样本集的 golden-output 评估
- 外部日志平台、trace 平台或 metrics backend

## Practical Rule

如果某项能力决定“系统能不能稳定运行、能不能自动验证、能不能恢复上下文”，它应该优先留在 Python runtime 或 harness。

如果某项能力决定“这份标书是否符合条款”，它应继续由模型运行时负责。
