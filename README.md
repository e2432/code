# AFE 科学具身智能任务

本仓库保存一个面向科学具身智能的 AFE L1 任务包。任务主题是连续稀释与定量移液，Agent 需要在受限的模拟移液环境中完成四级连续稀释，并提交可审计的动作记录。

## 目录

```text
.
├── task_package/                         # 可运行的 AFE 任务包
│   ├── task.toml                         # 任务和运行配置
│   ├── instruction.md                    # Agent 读取的任务说明
│   ├── environment/                      # 解题环境和输入协议
│   └── tests/                             # 独立评分环境和评分程序
├── docs/
│   ├── Agent Frontier Exam 共建指南.pdf  # AFE 共建指南
│   ├── sources.md                        # 设计来源和材料说明
│   └── validation_record.md               # 当前验证记录
└── dist/
    └── afe-serial-dilution-pipetting-v0.1.0.zip
```

## 任务摘要

- 初始库存液浓度为 1000 µM
- 连续制备 500、250、125、62.5 µM 四级样品
- 每一级使用 500 µL 前一级样品和 500 µL 稀释液
- 评分器重建液体体积和溶质浓度
- 评分器检查体积守恒、浓度误差、样品来源、混匀、吸头复用和动作合法性

## 本地运行评分器

任务包遵循 AFE 1.0 目录结构。直接运行评分器时，可以用环境变量把工作目录和日志目录映射到用户可写路径：

```bash
AFE_WORKDIR=/path/to/work \
AFE_LOG_DIR=/path/to/logs \
python3 task_package/tests/score.py
```

标准接口结果写入 `afe_result.json` 和 `reward.json`。完整任务说明见 `task_package/instruction.md`。
