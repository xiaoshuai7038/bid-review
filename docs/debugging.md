# Debugging

## Purpose

仓库内排障入口要优先走机器可读产物，而不是直接手翻整批 `json/txt`。

## First Step

对任意 harness run 或 review run，先执行：

```powershell
uv run python scripts/triage_run.py "<run-dir-or-manifest>"
```

常见输入：

- `data/output/run-*/`
- `data/output/run-*/batch_summary.json`
- `tmp/harness-runs/run-*/`
- `tmp/harness-runs/run-*/run_manifest.json`

## Run Types

- `kind: harness`
  - 看 `failed_count`
  - 看 `failed_cases`
  - 看每个 case 的 `stdout/stderr/result.json`
- `kind: review`
  - 看 `status`
  - 看 `failed_stage`
  - 看 `missing_artifact_count`
  - 看 `batch_summary.json`、`run_manifest.json`、`run_metrics.json`

## Key Files

- `run_manifest.json`
  - harness: 默认 harness runner 的总清单
  - review: pipeline 输入、后端、隔离运行目录、阶段状态和每个 bid 的产物路径
- `batch_summary.json`
  - review 批量结果入口
- `claude_raw_output.txt`
  - 解析/格式问题优先查看
- `run_metrics.json`
  - review 阶段 metrics

## Suggested Flow

1. 先跑 `scripts/triage_run.py`
2. 如果是 harness 失败，定位失败 case 的 `stdout/stderr/result.json`
3. 如果是 review 失败，先看 `failed_stage`
4. 再打开对应 `claude_raw_output.txt` 或 report artifact

## Fixture References

仓库内自带最小 triage fixture，便于离线验证：

- `harness/fixtures/sample-harness-run`
- `harness/fixtures/sample-review-run`
