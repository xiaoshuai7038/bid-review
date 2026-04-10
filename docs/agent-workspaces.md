# Agent Workspaces

## Purpose

当多个 agent 或多份并行实验同时运行时，优先隔离 worktree 和 runtime 目录，避免：

- `data/output` 混写
- `tmp/review-context` 互相污染
- 调试时难以追踪某次运行到底来自哪个工作副本

## Dry-Run Preview

先看计划路径，不改仓库：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\create-agent-worktree.ps1 -Name "demo-agent" -DryRun
```

## Create Worktree

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\create-agent-worktree.ps1 -Name "demo-agent" -CheckoutNewBranch
```

脚本会：

- 调用 `git worktree add`
- 为该 worktree 规划独立 `.runtime`
- 生成 `agent-env.ps1`

## Env Script

`agent-env.ps1` 默认会写入：

- `BID_REVIEW_RUNTIME_ROOT`
- `BID_REVIEW_RUN_CONTEXT_DIR`

进入该 worktree 后先执行：

```powershell
. .\agent-env.ps1
```

再跑 review / harness 命令，产物就会落到当前 worktree 对应 runtime 下。

## Notes

- 默认建议先 `-DryRun`
- 实际创建前确保目标目录不存在
- 该脚本只负责隔离工作目录与 runtime，不会处理凭证同步
