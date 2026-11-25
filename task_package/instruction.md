# 连续稀释与定量移液 v0.3

## 任务目标

在仿真实验室中控制机械臂和移液工具，从 1000 µM 库存液制备 500、250、125 和 62.5 µM 四级样品。Agent 需要完成连续稀释、校准、空白对照、重复测量和质量报告，并处理仿真反馈中的移液失败、液体不足、混匀不足和吸头携带污染。

任务的科学价值在于检验 Agent 执行可复现实验流程、处理实验异常、估计测量不确定性和生成可审计质量记录的能力。任务属于 AFE L1，不要求科学突破。

## 仿真输入

协议位于 `/work/input/protocol.json`。协议包含库存液、稀释液、空白样品、目标管、移液器范围、重复测量次数、随机种子、故障计划、校准要求和实例配置。评测器可以用不同实例替换协议中的 seed、故障位置和库存液体积。

仿真环境应向 Agent 提供主相机、腕部相机、机械臂状态、容器状态和动作反馈。当前 AFE 版本通过文件反馈工具模拟这一接口，AutoBio/MuJoCo 接入教程见仓库 `docs/仿真实验室搭建教程-AutoBio参考.md`。

## 工具和动作

```bash
python3 /work/tools/feedback.py --protocol /work/input/protocol.json --state /work/output/feedback_state.json --action /work/output/next_action.json
python3 /work/tools/check_submission.py /work/input/protocol.json /work/output/submission.json
```

允许的动作：

- `calibrate`，校准移液器，字段为 `pipette`、`reference_volume_ul`、`measured_volume_ul`。
- `transfer`，字段为 `action_id`、`source`、`dest`、`volume_ul`、`pipette`、`tip_id`。重试增加 `retry_of`。
- `mix`，字段为 `dest`、`volume_ul`、`cycles`。混匀质量由循环数和仿真器规则共同决定。
- `measure`，字段为 `target`、`measurement_id`。每个目标管至少测量两次，空白也至少测量两次。
- `pause`，记录无法安全继续的原因和最后安全检查点。
- `finish`，在所有目标、对照、进度和质量记录满足要求后收口。

失败动作不会改变液体状态。Agent 必须记录失败事件，并在允许次数内提交带 `retry_of` 的重试动作。液体不足时应暂停或提交可行的恢复动作，不能继续执行无效转移。

## 最终交付

必须写出：

- `/work/output/submission.json`
- `/work/output/progress.json`
- `/work/output/run_state.json`
- `/work/output/events.jsonl`

`submission.json` 必须包含 `actions`、`report` 和 `instance_id`。质量报告至少包含：

- 每个目标管的两次以上测量值
- 平均体积和体积误差
- 估计浓度和浓度误差
- 体积测量标准差
- 空白对照结果
- 校准结果
- 失败、重试、暂停和污染事件
- `finish` 事件

## 验收标准

评分器会重放动作，并检查：

1. 校准通过，移液器测量误差在协议阈值内。
2. 每个目标管和空白样品完成至少两次测量。
3. 终态体积误差不超过 1 µL，浓度误差不超过 1%。
4. 重复测量结果、平均值、标准差和报告字段一致。
5. 混匀质量达到最低要求，混匀发生在下一级转移前。
6. 失败动作不改变状态，重试动作引用正确的失败动作。
7. 液体不足会触发反馈，跨源吸头复用会产生携带污染记录。
8. 空白对照、校准、进度、暂停状态和 `finish` 记录完整。
9. `progress.json` 全部步骤完成，`run_state.json` 为 `completed`。

缺少输出文件或 JSON 无法解析时属于 `invalid_submission`。仿真评测使用固定 seed，多个 seed 用于隐藏实例。
