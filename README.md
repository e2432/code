# AFE 科学具身智能任务

本仓库保存一个面向科学具身智能的 AFE L1 任务包。任务主题是连续稀释与定量移液，Agent 需要在含测量误差和可恢复故障反馈的模拟环境中完成四级连续稀释，并提交可审计的实验质量记录。

## 当前进度

| 阶段 | 状态 | 说明 |
|---|---|---|
| AFE L1 任务定义 | 已完成 | 目标、输入、输出、资源约束和验收标准已写入任务包 |
| 抽象仿真器和评分器 | 已完成 | 支持多实例、重复测量、空白、校准、故障、混匀质量、污染和暂停复核 |
| 远程服务器验证 | 已完成 | 在 `ailogin001.ihep.ac.cn` 上运行，结果为 `score=100`、`reward=1` |
| 教师审阅材料 | 已完成 | 已提供任务说明、来源说明、验证记录和审阅版压缩包 |
| AutoBio/MuJoCo 场景接入 | 规划中 | 已完成搭建教程，尚未接入真实 MuJoCo 场景和机械臂观测 |

当前版本为 `v0.3.0`。可运行任务包已经完成，AutoBio 仿真接入属于下一阶段。

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
│   ├── validation_record.md               # 当前验证记录
│   ├── remote_validation_record.md       # 远程服务器验证记录
│   └── 仿真实验室搭建教程-AutoBio参考.md  # AutoBio/MuJoCo 接入教程
└── dist/
    ├── afe-serial-dilution-pipetting-v0.3.0.zip
    └── afe-serial-dilution-pipetting-v0.3.0-teacher-review.zip
```

## 任务摘要

- 初始库存液浓度为 1000 µM
- 连续制备 500、250、125、62.5 µM 四级样品
- 每一级使用 500 µL 前一级样品和 500 µL 稀释液
- 评分器重建液体体积和溶质浓度
- 评分器检查体积守恒、浓度误差、样品来源、混匀、吸头复用和动作合法性

当前抽象仿真器通过文件状态和反馈工具重放动作。下一阶段会将这些接口接入 AutoBio 的 MuJoCo 场景、机械臂控制、相机观测和多 seed episode 评测。

## 本地运行评分器

任务包遵循 AFE 1.0 目录结构。直接运行评分器时，可以用环境变量把工作目录和日志目录映射到用户可写路径：

```bash
AFE_WORKDIR=/path/to/work \
AFE_LOG_DIR=/path/to/logs \
python3 task_package/tests/score.py
```

标准接口结果写入 `afe_result.json` 和 `reward.json`。完整任务说明见 `task_package/instruction.md`。
