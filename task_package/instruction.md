# 连续稀释与定量移液 v0.2

## 科研目标

在模拟移液台上，从 1000 µM 库存液制备 500、250、125 和 62.5 µM 四级样品。实验采用连续 1:2 稀释，每一级加入 500 µL 前一级溶液和 500 µL 稀释液并混匀，再向下一级转移 500 µL。流程结束时，T1、T2、T3 各保留 500 µL，T4 保留 1000 µL。

任务要求 Agent 根据操作反馈处理一次可恢复的移液失败，识别有限的体积测量误差，避免吸头跨源复用，并提交可审计的实验质量记录。这是 L1 科学流程执行任务，不要求科学突破。

## 输入与约束

实验协议位于 `/work/input/protocol.json`。协议包含库存和稀释液体积、目标浓度、移液器范围、测量误差模式、失败事件和重试上限。不得假定协议文件之外存在额外输入。

每次 `transfer` 使用一个吸头。吸头不得在不同源容器之间复用。每个目标管在两次加液之后必须混匀，混匀循环至少为 3。不得从当前液体不足的容器中吸取液体。

协议中的失败事件会按 `action_id` 触发。失败动作不会改变容器状态，Agent 必须读取反馈并在允许的重试次数内提交带 `retry_of` 的重试动作。

## 可用工具

容器内提供：

```bash
python3 /work/tools/check_submission.py /work/input/protocol.json /work/output/submission.json
python3 /work/tools/feedback.py --protocol /work/input/protocol.json --state /work/output/feedback_state.json --action /work/output/next_action.json
```

`feedback.py` 用于逐步执行动作并返回状态、失败原因、测量值或重试提示。它不会替代独立评分器。

## 动作格式

`submission.json` 必须包含按实际执行顺序排列的 `actions`，动作类型包括：

- `transfer`，字段为 `action_id`、`source`、`dest`、`volume_ul`、`pipette`、`tip_id`。重试动作增加 `retry_of`。
- `mix`，字段为 `dest`、`volume_ul`、`cycles`、`pipette`、`tip_id`。
- `measure`，字段为 `target`、`measurement_id`。测量结果由反馈工具生成。

失败动作及其重试必须保留在动作记录中。不得删除失败动作来伪造无故障流程。

## 最终交付

必须写出 `/work/output/submission.json`。除 `actions` 外，还必须包含 `report`：

```json
{
  "actions": [],
  "report": {
    "samples": [
      {
        "name": "T1",
        "measured_volume_ul": 500.8,
        "volume_error_ul": 0.8,
        "estimated_concentration_um": 500.0,
        "concentration_error_fraction": 0.0,
        "quality_flags": ["measurement_uncertainty"]
      }
    ],
    "events": [
      {"action_id": "t2_sample_attempt1", "status": "failed", "reason": "temporary_pipette_failure"}
    ],
    "quality_flags": ["measurement_uncertainty", "retry_performed", "no_cross_source_tip_reuse"]
  }
}
```

`report.samples` 必须覆盖 T1–T4。测量值、体积误差、估计浓度和浓度误差必须与评分器重建结果一致。`report.events` 必须记录失败动作和重试事实。

## 验收标准

独立评分器会重放动作并检查：

1. 终态体积与目标值误差不超过 1 µL。
2. 目标浓度误差不超过 1%。
3. 失败动作没有改变容器状态，重试动作引用正确的失败动作。
4. 操作顺序、液体守恒、移液器范围、混匀和吸头来源规则满足协议。
5. `report.samples` 的测量值、体积误差、浓度和浓度误差与重放结果一致。
6. 质量记录包含测量不确定性、失败重试和吸头污染控制信息。
7. 输出 JSON 可解析，动作记录完整。

关键科学条件未满足时会扣分。缺少输出文件或 JSON 无法解析时属于 `invalid_submission`。
