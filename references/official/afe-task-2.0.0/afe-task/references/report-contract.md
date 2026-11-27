# 报告数据与统一输出

复制 `assets/assessment.template.json`，填写后交给 `scripts/render_report.py`。结构脚本的 `structure.json` 保留原始结果，不手工删掉负项；人工解释放在 `format_notes`。认为脚本误报时给出原文证据并反馈维护者，不为完成审核擅自修改 skill；获得修订授权后才更新规则并另存新结果。

必填字段：

| 字段 | 含义 |
| --- | --- |
| schema_version | assessment 固定字符串 `1.2`；结构脚本仍为 `1.0` |
| task_title / task_version / original_level | 可识别任务名、版本依据及来源 Level；未声明就明确写未声明，不猜测 |
| summary / recommendation | 简述主要科研产物、目标、拟新增贡献与关键质量发现；无法确认写待核实。给出下一步，不合成质量总分，不宣称已获入库或发布批准 |
| coverage.read / coverage.not_verified | 实际阅读范围和未核实范围，均为字符串数组；不声称读过未读取内容 |
| format_notes | 人工解释格式线索的数组；每项含 `check_id`、`disposition`、`evidence` 字符串数组、`reason`；无补充可空。disposition 简述已消歧、已确认问题、已有记录但待补证等处置，不覆盖原始工具状态 |
| content | 恰好 C1–C8 八项，每项含 `id`、`score`、`evidence`、`reason`、`action` |
| reference_solution | 可选资料的提供状态，见下文 |
| issues | 待处理问题数组，每项含 `id`、`title`、`evidence`、`action`；按重要性排序，关联维度引用同一问题编号 |

`score` 只能为整数 0、1、2、3，或 JSON `null`（渲染为待核实）。每项原因和建议必须是非空字符串；证据必须是非空字符串数组。缺文件/缺记录也是可定位的证据，要写“在所查范围未发现”，不虚构不存在的行号。达到基本要求也要说明依据，建议可写“本项无新增整改要求”。

`reference_solution` 只作资料记录：

- 未提供：仅填写 `{"provided": false}`，不生成负项、满分验收或作者确认要求。
- 已提供：填写 `provided: true`、`method`、`known_result`、`limitations` 非空字符串及 `evidence` 非空字符串数组。未执行或证据不足如实说明；未满分结果可以直接记录，不要求作者再次确认。
- 不接受旧版 status、task_success_status、full_score_status、author_confirmation 等字段，避免误把旧验收规则带入新报告。

证据尽量写成 `tests/check_outputs.py:40–68（源码）`、`task.toml:artifacts`、`authoring/evidence/run.json:任务版本与结果（已有记录）`，不粘贴答案、凭据或大段私有资料。

渲染器生成固定的任务信息、结果概览、F1–F7 工具状态及人工处置、包质量 C1–C8 内容表、可选参考资料（提供时）、需处理事项。题内 C1 等解答成绩另写，不与审核档位混用。保持摘要和每项理由简短；证据列优先放最能支持结论的少数定位，完整检查清单可保存在 JSON。它只验证数据完整性与基本一致性，不能替审核者证明科学判断。最终交付 `review.md`，人类不需阅读 JSON 才能理解结论。
