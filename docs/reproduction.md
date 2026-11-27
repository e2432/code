# 标准结果复现

标准 fixture 位于 `/tests/fixtures/`。在评测容器中执行：

```bash
mkdir -p /work/output
cp /tests/fixtures/valid_submission.json /work/output/submission.json
cp /tests/fixtures/valid_progress.json /work/output/progress.json
cp /tests/fixtures/valid_run_state.json /work/output/run_state.json
cp /tests/fixtures/events.jsonl /work/output/events.jsonl
AFE_WORKDIR=/work AFE_LOG_DIR=/logs/verifier python3 /tests/score.py
```

期望结果为 `status=evaluated`、`score=100`、`raw.outcome=completed` 和 `reward=1`。标准结果包含 36 条评分器事件。`check_submission.py` 对标准提交包含的 37 个动作通过。

## Docker 构建上下文

两个 Dockerfile 的预期构建上下文如下：

```bash
docker build -f task_package/environment/Dockerfile task_package/environment
docker build -f task_package/tests/Dockerfile task_package/tests
```

这两条命令只能确认给定上下文下的本地构建。Harbor 使用的实际构建上下文和 Harbor lint 仍需在目标环境确认。
