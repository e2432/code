# AFE 任务包协议 1.0 检查要点

用于静态审核。只检查已交材料和可读代码，不运行测试来补证。

## 元信息与题文

task.toml 的 Harbor schema_version 为 "1.4"，AFE 扩展放 metadata.afe：

- protocol_version="1.0"；level 非空，首版 L1。
- domains 为既定 11 科学领域的非空列表：生命、化学、材料、物理、天文、地球、能源、信息、神经科学、医学、数学。
- supports_over_target 是布尔值。
- score_mapping 包含 url、description，不额外结构化映射端点。
- reference_urls 可选；validation 的 command、description 可选，提供该表时两项要完整。

包内地址相对任务根目录；外部用 HTTPS。参考地址定位方法目录或 info.json。评分实现仍需实际进入评分环境，填 URL 不等于部署完成。

题文覆盖研究目标/贡献、输入、工具、约束、交付和验收；有 validation 才补调用/预算。不强制标题，不要求 Agent 知道分数映射。

## 结果

原生入口 tests/test.sh；输出 /logs/verifier/afe_result.json，有最终成绩时同时写 reward.json。作者内部实现自由，不要求特定 helper 或 score.py 文件名。

| status | score | error | raw / target_exceeded |
| --- | --- | --- | --- |
| evaluated | 有限 0–100 | 不出现 | 可选 |
| invalid_submission | 0 | 必需 code、message | 省略 |
| evaluation_error | null | 必需 code、message | 省略 |
| pending_review | null | 不出现 | 省略；仅必要人工复核可用 |

status/score 始终出现；notes 可选字符串。raw 为对象，内层按题目定义。超目标为可选布尔：true 要求 evaluated、score=100、声明支持且实际超目标。省略不等于 false。

同义状态复用规范名称；不同语义可扩展，说明字段和是否最终结果。未知状态提示待接入，不直接算科学失败，也不增加必填扩展注册表。错误细分使用 error.code。

主分100仅在所有必要条件成立时产生，归一映射和精度不能把未达标结果变成100。reward 对 evaluated 的100取1、其余 evaluated 及 invalid_submission取0。未决/评分故障/未知状态不输出假0；平台读取 AFE结果处理，原生Harbor不会自动理解这些状态。

已有结果可用脚本检查：

```sh
python3 <skill_dir>/scripts/afe_contract.py result <afe_result.json> --supports-over-target true
```

选择与题目相同的 true/false。静态审核只调用 result/reference 等读取检查模式；write_result 与 collect 是模板/平台的输出辅助，不用于执行题包。

## 可选参考

每个正式参考方法一个目录和 info.json：name、proposed_at、description、source_urls；可选 raw、score、notes。方法日期不强制精确到日，不要求 as_of/result_note。未测 raw/score 可省略或 null，不填0冒充。可以只有 info，没有代码或 solve.sh；没有参考不扣分。

核对方法的准确描述、来源以及是否为相关条件下的最佳参考。不能将不可比的文献数字伪装成本题实测分数；不强求重新运行方法。

## 实际交接与可选服务

instruction 的产物路径/格式 → artifacts 收集 → tests 读取必须一致。environment 文件由 Dockerfile 复制，workdir 不是复制规则。支持原生 artifacts 对象的 source/service，不误报其格式无效。

有 validation 时检查工具实际可用、Compose 服务启动、反馈/预算和 collect 导出记录；评分依赖的记录从服务侧收集。服务快照缺失归因于评测侧，不冒充 Agent 未查询。未验证运行行为标待核实。

harness 是按需给平台的适配材料，无自动调用约定；不要求普通题提供。额外 Dockerfile 上下文根据 Compose 确认后传给结构脚本。
