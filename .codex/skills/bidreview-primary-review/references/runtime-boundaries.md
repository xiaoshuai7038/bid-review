# Runtime Boundaries

以下内容保留在 runtime：

- review profile（`fast` / `balanced` / `thorough`）和对应的 second-pass 开关
- OCR 预处理、图片过滤、缓存与受控目录复用
- OCR 全量覆盖校验
- no-write 行为检测、工具白名单和超时控制
- JSON repair / fallback 解析
- requirements completion retry
- completion gate 与 precise-location retry
- finding / requirement ID 归一化
- findings 最终 dedupe 与稳定性兜底补齐
- 证据定位增强
- 输出文件导出

skill 文档只定义：

- requirements 提取范围和最低覆盖面
- `compliance` / `context` / `semantic` 的边界
- 主体基线与模板字段审查规则
- 证据书写和输出 JSON 契约
