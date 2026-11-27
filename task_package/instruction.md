# 连续稀释与定量移液 v0.5.1

## 任务目标

在仿真实验室中控制机械臂和移液工具，从固定的 1000 µM 库存液制备 500、250、125 和 62.5 µM 四级样品。Agent 需要完成连续稀释、P1000 校准、空白样和标准样的体积质控、重复测量和质量报告，并依据反馈处理移液失败、液体不足、混匀不足、视觉识别失败、运动碰撞和吸头携带污染。

任务属于 AFE L1，不要求科学突破。当前版本的标准样和空白样只有体积质控功能；独立浓度 assay 属于后续扩展。

## 仿真输入与实例固定

协议位于 `/work/input/protocol.json`。协议定义库存液、稀释液、空白样、标准样、目标管、P1000 范围、重复测量次数、随机种子、移液误差、校准要求、逻辑步骤和实例配置。

正式评测时，运行器应通过环境变量 `AFE_INSTANCE_ID` 注入实例。评分器会拒绝与该实例不一致的 `submission.instance_id`。本地调试未设置该变量时，才使用提交文件中的实例编号。

## 工具和动作

```bash
python3 /work/tools/feedback.py --protocol /work/input/protocol.json --state /work/output/feedback_state.json --action /work/output/next_action.json
python3 /work/tools/check_submission.py /work/input/protocol.json /work/output/submission.json
```

动作字段如下：

- `observe`、`move`：必须包含协议声明的 `step_id`、`action_id`，失败后可用 `retry_of` 重试；故障按 `step_id + attempt` 注入，与动作名称无关。
- `calibrate`：字段为 `pipette`、`reference_volume_ul`、`measured_volume_ul`。校准是流程质控记录，本版本不自动用校准值修正移液。
- `transfer`：字段为 `step_id`、`action_id`、`source`、`dest`、`volume_ul`、`pipette`、`tip_id`；重试增加 `retry_of`，且必须引用同一逻辑步骤的真实失败尝试。
- `mix`：字段为 `dest`、`volume_ul`、`cycles`；至少 3 圈，混匀体积必须不超过容器当前体积。
- `measure`：字段为 `target`、`measurement_id`；每个目标管、空白样和标准样至少测量三次。
- `pause`：记录无法安全继续的原因和最后安全检查点。
- `finish`：在所有目标、质控、进度和质量记录满足要求后收口。

失败动作不会改变液体状态。无效的 `retry_of` 不会执行转移。液体不足时，只有在收到对应的 `insufficient_source_volume` 反馈、填写暂停原因和最后安全检查点后，才算完成预期安全暂停。

## 最终交付

必须写出：

- `/work/output/submission.json`
- `/work/output/progress.json`
- `/work/output/run_state.json`
- `/work/output/events.jsonl`

`submission.json` 必须包含 `actions`、`report` 和 `instance_id`。报告数值至少保留 6 位小数；重复测量标准差使用总体标准差 `pstdev`。

每个目标管的报告至少包含三次原始测量值、平均测量体积、`volume_error_ul`、`measurement_error_ul`、`volume_sd_ul`、`estimated_concentration_um` 和 `estimated_concentration_error_fraction`。标准样和空白样报告三次测量值、平均体积和总体标准差。

## 验收标准

评分器会重放动作并检查：

1. P1000 校准通过；
2. 每个目标管、空白样和标准样完成三次测量；
3. 真实终态浓度误差不超过 1%；真实终态体积误差不超过 5 µL。体积误差是辅助指标，但超过阈值会使流程不合格；
4. 报告中的测量值、均值、标准差、终态体积误差、测量误差和 Agent 估计值与重放结果一致；
5. 混匀质量达到最低要求，且混匀发生在下一级转移前；
6. 失败动作不改变液体状态，重试引用同一逻辑步骤的实际失败尝试；
7. 液体不足会触发反馈，跨源吸头复用会改变污染状态并产生污染记录；
8. `progress.json` 必须包含协议要求的步骤 ID 集合，每个 ID 仅出现一次；完成实例的 `run_state.json` 必须为 `completed`，并存在 `finish` 事件；
9. `events.jsonl` 必须存在，每行是 JSON 对象，并且至少覆盖评分器事件中的每个带 `action_id` 的动作及其状态。

无证据暂停是 `evaluated` 失败，不是 `pending_review`。低库存实例的安全暂停使用 `outcome=safe_pause_expected`，当前分数上限由协议中的 `score_caps.safe_pause` 设置为 50。

## 误差模型

所有转移动作必须使用 P1000，P200 不参与本任务。实际转移体积为请求体积加固定 seed 派生的合成随机误差；当前误差均值为 0 µL、标准差为 1.0 µL，并在 ±3 个标准差处截断。该参数是 benchmark 模型，不代表具体 P1000 型号的实测规格。

测量误差为固定 seed 派生的正态误差，均值为 0 µL、标准差为 1 µL，并在 ±3 个标准差处截断。误差按目标管和重复序号派生，不使用 Agent 自选的 `measurement_id`。移液故障按协议 `step_id` 和尝试次数注入，不使用 Agent 自选的 `action_id`。

## 评分规则

评分区分完成门和原始指标：

- 无必要条件失败且所有目标、质控、记录和收口条件满足时，最终 `score=100`；
- 科学门失败（目标浓度、污染、移液顺序、混匀、校准、终态体积或未恢复故障）时，最高 50 分；
- 只有记录门失败时，最高 80 分；
- 50、80、100 是流程门控结果，不是等距科学量尺。连续浓度、体积、测量误差和重复性指标保存在 `raw` 中。

## 浓度、体积与质控指标

化学准确度由仿真真实状态计算：

```text
C_true = S_reconstructed / V_true
concentration_error_fraction = |C_true - C_target| / C_target
```

Agent 报告的是可观测估计：

```text
C_estimated = S_reconstructed / V_measured
estimated_concentration_error_fraction = |C_estimated - C_target| / C_target
```

其中 `volume_error_ul = V_true - V_target`，`measurement_error_ul = V_measured - V_true`。标准样和空白样在本版本只用于体积重复性和记录质控，不产生独立化学浓度或背景信号结果。
