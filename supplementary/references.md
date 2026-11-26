# 参考文献与来源

## AFE 规范

- Agent Frontier Exam 共建指南，仓库 `docs/Agent Frontier Exam 共建指南.pdf`。用于任务包目录、L1 定义、结果接口、评分和提交边界。

## AutoBio

- AutoBio GitHub: https://github.com/autobio-bench/AutoBio
- AutoBio 论文: https://arxiv.org/abs/2505.14030
- AutoBio README 和公开代码中的 `mani_pipette.py`、`liquid.py`、`evaluator.py`、`evaluate.py`。用于仿真场景、液面几何、吸液条件、相机观测、轨迹记录和多 episode 评测的设计参考。

AutoBio 原生公开接口主要评价机械臂执行和液体体积状态。浓度误差、固定库存液、标准样和空白背景检查属于本任务的 AFE 科学评价扩展。

## LabUtopia

- LabUtopia GitHub: https://github.com/Rui-li023/LabUtopia
- LabUtopia 论文: https://arxiv.org/abs/2505.22634

LabUtopia 用于参考科学实验室场景、任务层级、机器人控制、观测和任务成功条件的组织方式。

## 数据和代码边界

本任务没有直接打包外部数据集、私有实验数据或外部模型权重。协议数值、模拟误差和评分逻辑由任务作者设计。
