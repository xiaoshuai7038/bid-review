# Placement

当前这组 skills 以 Codex 可直接使用为第一目标。

推荐放置方式：

- repo-local：
  - `D:\code\bidreview\.codex\skills\`
  - 适合当前仓库内协作和迭代
- global：
  - 复制到 `$CODEX_HOME/skills`
  - 适合跨仓库复用

当前阶段默认以 repo-local 目录为准；如果后续需要同步到全局目录，再补安装或同步脚本。

验收重点不是“是否已经全局安装”，而是：

- skill 目录结构完整
- `SKILL.md` 可用
- `quick_validate.py` 通过
