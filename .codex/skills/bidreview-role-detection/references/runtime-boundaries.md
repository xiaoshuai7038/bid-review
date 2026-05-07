# Runtime Boundaries

角色识别 skill 只负责给出角色判断和 JSON 输出。

以下内容保留在 runtime：

- 解析 CLI 输入形式
- 手工指定和自动识别的分支调度
- `len(inputs) == 2` 与“一招标多投标”的不同调用路径
- 文件名 fallback 的最终兜底实现
- 同路径冲突检查
- 将识别结果喂给后续 pipeline

skill 文档负责：

- 自动识别时的判断顺序
- filename/content 两级启发式
- 单招标单投标与一招标多投标的输出契约
- 一句话 `reasoning` 的约束
