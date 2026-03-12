# Runtime Boundaries

角色识别 skill 只负责给出角色判断和 JSON 输出。

以下内容保留在 runtime：

- 解析 CLI 输入形式
- 手工指定和自动识别的分支调度
- 文件名 fallback 的最终兜底实现
- 同路径冲突检查
- 将识别结果喂给后续 pipeline

如果 skill 无法可靠区分，应在 `reasoning` 中说明主要依据，而不是在 skill 中自行扩展成完整编排逻辑。
