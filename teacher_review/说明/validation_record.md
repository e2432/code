# 验证记录

## 当前版本

任务包版本为 `0.5.1`，任务等级为 L1。

## 已完成检查

- `task.toml` 可由 Python 3.11 的 TOML 解析器读取。
- `protocol.json` 可解析。
- `tests/score.py`、`environment/tools/check_submission.py` 和 `environment/tools/feedback.py` 可通过 Python 语法检查。
- 标准连续稀释动作通过公开格式检查。
- 标准连续稀释动作由评分器重建为四个目标浓度。
- 标准动作 fixture 随任务包交付于 `task_package/tests/fixtures/`，用评分器重放得到 `status=evaluated`、`score=100` 和 `reward=1`。
- v0.5.1 增加可复现的移液误差、按容器和重复序号派生的测量误差、真实体积化学准确度与测量精密度分离、语义步骤故障注入、实例固定和严格重试引用。
- v0.5.1 本地回归确认：默认、failure_t3、vision_motion 和 position_label_error 的正确解均为 `score=100`；低库存实例的有证据安全暂停为 `score=50`。缺校准和错误校准均不超过 50 分；重命名 Agent 自选 ID 不改变移液和测量噪声；语义故障在改名后仍触发；改变请求体积而保留原 `step_id` 会被拒绝；实例不匹配会被拒绝；低库存无证据暂停为 `score=0`，带预期证据的安全暂停为 50 分。
- 进度步骤按唯一 ID 集合校验，`events.jsonl` 与评分器生成的带 `action_id` 事件交叉核对，混匀体积越界进入科学门而不会触发结构性归零；安全暂停只有记录产物完整时才给 50 分。记录缺失时保留真实记录惩罚，不追加 `pause_without_evidence`。
- 官方原版结构自查工具未修改；当前包在 Windows 本地官方检查结果为 34 通过、6 待核实、2 提醒、0 失败；提醒来自检查器对 `test.sh` 内嵌评分入口和扫描覆盖范围的提示。
- Windows 本地使用官方原版工具的结果为 34 通过、6 待核实、2 提醒、0 失败。Linux 预期会因路径分隔符识别正常而增加 F1.scorer 和 F4.reward 两项通过，预期为 36 通过、5 待核实、1 提醒、0 失败，尚未在 Linux 实机执行。
- `F4.build_context` 需要 Harbor 或目标运行器确认真实构建上下文。`F7.lint` 需要在 Harbor 环境执行指定版本 lint。两项均尚未执行。
- 来源版本、复现命令和外部材料边界记录在 `docs/sources.md` 与 `docs/reproduction.md`。标准 fixture、`afe_result.json`、`reward.json` 和官方结构报告随补充材料交付。
- `afe_contract.py` 检查标准 fixture 的 `afe_result.json` 得到 `valid=true`；非法提交结果使用 `status=invalid_submission`、`score=0` 和 `error`，省略 `raw`，同样得到 `valid=true`。

## 验证范围

当前记录包含本地合成输入、标准动作和关键缺陷变体验证。标准样和空白样在本版本仅作体积质控；独立浓度 assay 尚未实现。真实 Docker 构建和 Harbor 运行器联调仍需在相应运行器中执行。

## 远程服务器验证

v0.4.0 曾在 `ailogin001.ihep.ac.cn` 上使用 Python 3.9.25 运行公开格式检查和独立评分器，标准动作得到 `status=evaluated`、`score=100` 和 `reward=1`。v0.5.1 已完成本地回归，尚未在远程服务器重跑；不能把 v0.4.0 的远程结果当作 v0.5.1 的远程证据。

## 标准 fixture 复现

在评测容器中执行以下命令可复现标准结果。

```bash
cp /tests/fixtures/valid_submission.json /work/output/submission.json
cp /tests/fixtures/valid_progress.json /work/output/progress.json
cp /tests/fixtures/valid_run_state.json /work/output/run_state.json
cp /tests/fixtures/events.jsonl /work/output/events.jsonl
AFE_WORKDIR=/work AFE_LOG_DIR=/logs/verifier python3 /tests/score.py
```

期望结果为 `status=evaluated`、`score=100`，并在 `reward.json` 中得到 `reward=1`。
