# 来源与材料说明

## 规范来源

- AFE 共建指南 v1.0，文件为 `docs/Agent Frontier Exam 共建指南.pdf`。它确定 AFE L1 任务包的目录结构、解题环境与评分环境隔离、交付接口和结果文件要求。
- AFE task package template 1.0.1，协议版本为 1.0，Harbor 目标版本为 0.25.0。版本信息记录在 `references/official/AFE_task_package_template_v1.0.1/AFE_task_package_template/MANIFEST.json`。它影响 `task.toml`、Dockerfile、`tests/` 和 `environment/` 的组织方式。
- `afe-task` skill 2.0.0，版本信息记录在 `references/official/afe-task-2.0.0/afe-task/MANIFEST.json`。它提供当前使用的结构自查工具和 AFE 契约检查规则。

以上材料在 2026-11-27 核对。任务包中的评分模型、连续稀释协议、故障实例和报告字段由本项目自行设计。

## 概念参考

- [AutoBio](https://github.com/autobio-bench/AutoBio) 参考科学实验室环境、机器人操作和轨迹记录的组织方式。
- [LabUtopia](https://github.com/Rui-li023/LabUtopia) 参考实验室仿真、设备控制和科学 Agent 任务的组织方式。

这些项目只作为设计参考，没有复用其代码、模型权重、数据集或运行时依赖，也没有作为当前任务包的外部代码依赖。

## 外部材料边界

当前提交包不包含外部数据集、模型权重或外部代码。标准库存液、移液误差、测量误差和故障计划均由 `protocol.json` 明确定义，用于可复现的合成仿真。
