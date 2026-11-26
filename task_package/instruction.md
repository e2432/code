# 连续稀释与定量移液 v0.4

## 任务目标

在仿真实验室中控制机械臂和移液工具，从 1000 µM 库存液制备 500、250、125 和 62.5 µM 四级样品。Agent 需要完成连续稀释、校准、空白对照、重复测量和质量报告，并处理仿真反馈中的移液失败、液体不足、混匀不足和吸头携带污染。

任务的科学价值在于检验 Agent 执行可复现实验流程、处理实验异常、估计测量不确定性和生成可审计质量记录的能力。任务属于 AFE L1，不要求科学突破。

## 仿真输入

协议位于 `/work/input/protocol.json`。库存液和 750 µM 标准样是固定参考溶液。协议包含稀释液、空白样品、目标管、移液器范围、重复测量次数、随机种子、故障计划、校准要求和实例配置。评测器可以用不同实例替换协议中的 seed、故障位置和库存液体积。

仿真环境应向 Agent 提供主相机、腕部相机、机械臂状态、容器状态和动作反馈。当前 AFE 版本通过文件反馈工具模拟这一接口，运行参考位于 `/work/input/references/`，包括协议笔记、Agent 完成清单和 AutoBio/MuJoCo 仿真教程。

## 工具和动作

```bash
python3 /work/tools/feedback.py --protocol /work/input/protocol.json --state /work/output/feedback_state.json --action /work/output/next_action.json
python3 /work/tools/check_submission.py /work/input/protocol.json /work/output/submission.json
```

允许的动作：

- `calibrate`，校准移液器，字段为 `pipette`、`reference_volume_ul`、`measured_volume_ul`。
- `transfer`，字段为 `action_id`、`source`、`dest`、`volume_ul`、`pipette`、`tip_id`。重试增加 `retry_of`。
- `mix`，字段为 `dest`、`volume_ul`、`cycles`。混匀质量由循环数和仿真器规则共同决定。
- `measure`，字段为 `target`、`measurement_id`。每个目标管、空白样和 750 µM 已知浓度标准样均至少测量三次。
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

- 每个目标管的三次测量值
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
2. 每个目标管、空白样和标准样完成三次测量。
3. 浓度误差不超过 1%，体积误差不超过 5 µL。浓度误差是主指标，体积误差是辅助指标。
4. 重复测量结果、平均值、标准差和报告字段一致。
5. 混匀质量达到最低要求，混匀发生在下一级转移前。
6. 失败动作不改变状态，重试动作引用正确的失败动作。
7. 液体不足会触发反馈，跨源吸头复用会产生携带污染记录。
8. 空白对照、校准、标准样、进度、暂停状态和 `finish` 记录完整。
9. `progress.json` 全部步骤完成，`run_state.json` 为 `completed`。

缺少输出文件或 JSON 无法解析时属于 `invalid_submission`。仿真评测使用固定 seed，多个 seed 用于隐藏实例。


## P1000、误差和仿真故障

所有转移动作必须使用 P1000，P200 不参与本任务。协议中的测量误差采用固定 seed 的正态分布，均值为 0 µL，标准差为 1 µL，并在 ±3 µL 处截断。正态分布表示误差围绕 0 对称，接近 0 的小误差出现概率高，较大的正负误差出现概率低。

仿真实例还会触发视觉识别失败、机械臂运动碰撞、容器位置不一致和液体标签误读。失败动作不改变实验状态，Agent 必须读取反馈并使用 `retry_of` 重试，或者在无法安全恢复时暂停并保存检查点。

## 评分权重

浓度误差是主指标，占最终分数的 80%。体积误差是辅助指标，占 10%。质量记录、校准、重复测量、空白标准样、故障恢复和进度收口占 10%。


## 新增标准样与视觉、运动故障

协议提供 750 µM 已知浓度标准样。Agent 必须对标准样和空白样各完成三次测量，并在质量报告中记录标准样浓度估计、空白测量和重复测量离散程度。

仿真实例会触发视觉标签误读、容器位置不一致和机械臂运动碰撞。失败动作可以是 `observe` 或 `move`，失败不会改变实验状态，Agent 必须通过反馈识别原因并提交带 `retry_of` 的重试动作。

## 测量误差模型

当前误差为固定 seed 的正态分布，均值为 0 µL，标准差为 1 µL，并在 ±3 µL 处截断。正态分布表示误差围绕 0 对称，小误差出现概率高，大误差出现概率低。同一 seed 会产生同一组误差，便于复现实验和比较 Agent 行为。

## 评分权重

浓度误差是主指标，占最终分数的 80%。体积误差是辅助指标，占 10%，验收阈值为 5 µL。重复测量、标准样、空白、校准、故障恢复、污染控制、进度和完成收口占 10%。

## 浓度误差的测定

对每个目标管，先对三次体积测量取平均值 `V_measured`。仿真器根据动作重建该管中的溶质量 `S_reconstructed`，再计算估计浓度：

```text
C_estimated = S_reconstructed / V_measured
concentration_error_fraction = |C_estimated - C_target| / C_target
```

评分器对四个目标管的浓度误差取平均，形成主指标。三次测量的标准差记录重复性。固定库存液和标准样用于检查移液、测量和浓度计算流程。空白样只用于检查背景信号和携带污染，不参与目标浓度主指标计算。
