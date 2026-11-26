# 科学具身智能仿真环境搭建教程

## 1. 目标与范围

本教程说明如何参考 AutoBio 搭建连续稀释与定量移液的科学具身智能仿真环境，并将其接入 AFE L1 任务包。

环境中由 Agent 控制仿真机械臂完成：

1. 识别库存液、稀释液、目标管和吸头。
2. 选择吸头并完成定量吸液、移液、混匀和测量。
3. 根据执行反馈处理临时失败、液体不足和吸头污染。
4. 记录动作、观测、反馈、进度和终态质量报告。
5. 在满足验收条件后执行 `finish` 收口。

当前任务采用 MuJoCo 仿真，Agent 通过统一接口获取图像和状态，并调用机械臂动作工具。真实机械臂驱动、真实液体和湿实验设备不属于本版本的运行边界。

## 2. AutoBio 可以提供什么

AutoBio 的目录和运行方式可直接参考以下部分：

```text
autobio/
├── assets/       # 实验室和器材资源
├── model/        # MuJoCo MJCF 场景和模型
├── grasp/        # 抓取、运动学和姿态工具
├── packages/     # 推理服务和通信组件
├── task.py       # 任务抽象、管理器和场景入口
├── evaluator.py  # 观测、控制、评测循环
├── instrument.py # 实验仪器状态和行为
├── liquid.py     # 液体和容器状态
├── render.py     # 离线渲染
└── evaluate.py   # 多 episode 评测
```

AutoBio 的关键设计是把任务定义、仿真场景、机器人控制、仪器状态、液体状态、观测和评测循环组合起来。已有 `mani_pipette.py` 可作为吸液和移液动作的参考，`evaluator.py` 可作为观测、策略调用和成功判断的参考。

需要区分 AutoBio 原生能力和本任务的 AFE 科学扩展。AutoBio 原生液体模块主要维护容器液体积、液面几何、液面法向和液面距离。移液任务通过末端位置、吸头与液面的相对位置、控制动作和任务完成条件判断吸液是否成功。AutoBio 的评测重点是机械臂是否完成任务、轨迹是否有效、观测和控制是否能在多个 episode 中复现。

AutoBio 的公开文献和代码没有规定浓度测定、标准样、空白对照或化学分析仪器接口。当前任务中的固定库存液、750 µM 标准样、空白背景检查和浓度误差属于 AFE 科学流程层。接入 AutoBio 后，应将两层结果分开记录，AutoBio 层记录抓取、定位、吸液、排液、碰撞、液体积和轨迹，AFE 层根据已知溶质量和测量体积计算浓度误差并评价实验报告。

来源：

- https://github.com/autobio-bench/AutoBio
- https://arxiv.org/abs/2505.14030

## 3. 环境准备

AutoBio README 使用 Ubuntu 20.04 以上环境，推荐 Ubuntu 24.04、Python 3.11 和 MuJoCo 3.3.0。

```bash
git clone https://github.com/autobio-bench/AutoBio.git
cd AutoBio

conda create -n afe-autobio python=3.11 -y
conda activate afe-autobio

pip install \
  'mujoco==3.3.0' \
  numpy scipy jax[cpu] toppra trimesh shapely triangle \
  manifold3d sympy zstandard tqdm networkx usd-core \
  ffmpeg imageio[ffmpeg] matplotlib scikit-image
```

先确认 MuJoCo 可以加载一个已有任务：

```bash
python autobio/mani_pipette.py
```

如果图形环境不可用，先使用离屏渲染模式，并确认 `MUJOCO_GL` 或集群提供的 EGL 配置符合服务器环境。

## 4. 场景设计

### 4.1 场景对象

连续稀释任务至少需要：

- 一个 UR5e 或 ALOHA 机械臂
- 一个实验台
- 库存液容器
- 稀释液容器
- T1–T4 目标管
- 吸头架
- 可抓取的移液器和吸头
- 相机和腕部相机
- 可读的液面、容器标签和目标位置

建议先使用固定位置的容器完成最小任务，再增加位置随机化。

### 4.2 MJCF 模型

在 `model/` 下建立任务场景，例如：

```text
model/
└── serial_dilution.xml
```

场景中需要为关键对象设置稳定名称，便于任务代码获取状态：

```text
/World/stock_tube
/World/diluent_tube
/World/target_T1
/World/target_T2
/World/target_T3
/World/target_T4
/World/tip_rack
/World/pipette
/World/camera_main
/World/camera_wrist
```

每个容器需要有位置、容量、液面高度和可抓取区域。液体可以先使用几何液面表示，再通过 Python 状态管理浓度、体积和污染状态。

## 5. 任务类设计

参考 AutoBio 的 `task.py`，为连续稀释建立独立任务类：

```python
class SerialDilutionTask(Task):
    def reset(self, seed=None):
        # 重置场景、液体、吸头、进度和故障事件
        ...

    def step_and_log(self, action):
        # 推进 MuJoCo，更新液体和过程日志
        ...

    def check(self):
        # 检查终态体积、浓度、污染、进度和 finish 状态
        ...

    def finish(self):
        # 保存最终轨迹、质量报告和仿真状态
        ...
```

任务信息需要包含：

```python
task_info = {
    "prefix": "完成四级连续稀释并提交实验质量报告",
    "action_indices": action_indices,
    "state_indices": state_indices,
    "camera_mapping": {
        "image": "camera_main",
        "wrist_image": "camera_wrist"
    }
}
```

## 6. 观测接口

Agent 每次动作前至少获得：

```json
{
  "observation": {
    "image": "主相机图像",
    "wrist_image": "腕部相机图像",
    "robot_state": "关节位置、末端位姿和夹爪状态",
    "scene_state": {
      "visible_containers": ["stock", "diluent", "T1", "T2"],
      "tip_available": true
    },
    "experiment_state": {
      "step": 4,
      "current_progress": "T1 prepared",
      "paused": false
    }
  }
}
```

液体浓度和隐藏故障原因不直接暴露给 Agent。Agent 通过视觉、公开测量工具和执行反馈获取信息。

## 7. 动作和工具接口

建议把机械臂低层控制封装成稳定的高层工具：

```text
observe_scene()
move_to(target)
pick_tip(tip_id)
aspirate(source, volume_ul)
dispense(dest, volume_ul)
mix(dest, cycles)
measure(target)
release_tip()
checkpoint()
pause(reason)
resume()
finish()
```

每个工具返回统一反馈：

```json
{
  "status": "ok",
  "step": 12,
  "observation": {},
  "state_delta": {},
  "quality_flags": []
}
```

失败时返回：

```json
{
  "status": "failed",
  "reason": "temporary_pipette_failure",
  "retry_required": true,
  "safe_checkpoint": "after_T1_mix"
}
```

## 8. 液体和实验状态

建立独立的实验状态，不把浓度只放在最终评分器中：

```json
{
  "containers": {
    "stock": {"volume_ul": 1200.0, "concentration_um": 1000.0},
    "diluent": {"volume_ul": 2600.0, "concentration_um": 0.0},
    "T1": {"volume_ul": 0.0, "concentration_um": 0.0},
    "T2": {"volume_ul": 0.0, "concentration_um": 0.0},
    "T3": {"volume_ul": 0.0, "concentration_um": 0.0},
    "T4": {"volume_ul": 0.0, "concentration_um": 0.0}
  },
  "used_tips": {},
  "contamination_events": [],
  "measurement_events": [],
  "failure_events": []
}
```

仿真器每次成功转移后更新体积和溶质：

```text
solute_after = solute_before - transferred_volume × source_concentration
volume_after = volume_before - transferred_volume
```

目标容器接收同样的溶质和体积，并重新计算浓度。

## 9. 误差、失败和污染

### 9.1 可复现的测量误差

第一版可使用固定 seed 的伪随机误差：

```json
{
  "seed": 20261125,
  "measurement_error_distribution": "uniform",
  "measurement_error_range_ul": [-1.0, 1.0]
}
```

每个 episode 使用 seed 初始化随机数生成器，保证同一 seed 的结果可复现。多个 seed 用于隐藏评测实例。

### 9.2 临时移液失败

故障应在仿真器内部触发，不由 Agent 自己声明。失败动作：

- 不改变液体状态
- 写入 failure event
- 返回 retry_required
- 保存安全检查点

Agent 需要引用失败动作并重新执行：

```json
{
  "type": "transfer",
  "retry_of": "t2_sample_attempt1",
  "source": "T1",
  "dest": "T2",
  "volume_ul": 500
}
```

### 9.3 吸头污染

仿真器维护吸头到源容器的映射。一个吸头跨不同源容器使用时：

- 记录 contamination event
- 返回 contamination_risk
- 评分器扣除质量分

第一版可以采用确定性违规判定，后续再加入概率性污染模型。

## 10. 暂停、恢复和进度

仿真环境需要保存：

```text
/work/output/run_state.json
/work/output/progress.json
/work/output/events.jsonl
```

`run_state.json` 至少包含：

```json
{
  "status": "running",
  "step": 12,
  "last_safe_checkpoint": "after_T2_mix",
  "pause_reason": null,
  "robot_motion": "stopped"
}
```

`progress.json` 逐项记录：

```json
{
  "steps": [
    {"id": "prepare_T1", "status": "completed"},
    {"id": "prepare_T2", "status": "completed"},
    {"id": "prepare_T3", "status": "pending"},
    {"id": "prepare_T4", "status": "pending"},
    {"id": "measure_and_report", "status": "pending"}
  ]
}
```

Agent 遇到无法恢复的状态时执行 `pause(reason)`。评分器要求完成任务时所有步骤为 `completed`，并且存在 `finish` 事件。

## 11. 轨迹记录和渲染

AutoBio 的数据流程可以直接参考：

1. 运行任务定义文件生成轨迹。
2. 将每个 episode 保存到 `logs/<task_name>/<timestamp>/`。
3. 保存 MuJoCo 场景文件和状态轨迹。
4. 使用渲染脚本导出各相机视频或图像。
5. 将轨迹和质量报告交给评测器。

示例：

```bash
python autobio/serial_dilution.py
bash autobio/render.bash serial_dilution
```

每个 episode 建议保存：

```text
episode.json
trajectory.npz
scene.mjb
camera_main.mp4
camera_wrist.mp4
events.jsonl
progress.json
run_state.json
quality_report.json
```

## 12. 评测设计

仿真评测建议分成三层：

### 操作层

- 抓取和放置成功
- 吸头连接正确
- 末端轨迹无严重碰撞
- 吸液和排液动作完成
- 混匀动作达到指定次数

### 实验层

- 目标体积满足阈值
- 目标浓度满足阈值
- 液体守恒
- 污染事件为零或在允许范围内
- 失败动作被正确重试

### 记录层

- 进度文件完整
- 失败事件和恢复动作可追溯
- 测量误差和体积误差记录正确
- 质量报告与仿真状态一致
- `finish` 事件存在

多 episode 评测时，为每个 episode 使用固定 seed，并输出：

```json
{
  "status": "evaluated",
  "score": 87.5,
  "raw": {
    "episodes": 20,
    "success_rate": 0.85,
    "mean_concentration_error": 0.006,
    "contamination_rate": 0.05,
    "recovery_rate": 0.9
  }
}
```

## 13. 接入 AFE 任务包

仿真环境和 AFE 任务包分工如下：

```text
AutoBio/MuJoCo
  负责场景、机器人、观测、物理推进和轨迹记录

AFE task_package
  负责任务说明、资源配置、输出约定、独立评分和结果接口
```

任务包建议包含：

```text
task_package/
├── task.toml
├── instruction.md
├── environment/
│   ├── Dockerfile
│   ├── input/
│   └── tools/
└── tests/
    ├── Dockerfile
    ├── test.sh
    └── score.py
```

`task.toml` 中需要明确：

- Agent 超时
- MuJoCo 和渲染资源
- 是否需要 GPU
- artifacts 路径
- verifier 独立环境
- 评分结果路径

`instruction.md` 中需要明确：

- 仿真场景入口
- 观测格式
- 动作工具和返回反馈
- 暂停、恢复和检查点
- 输出文件
- 完成定义
- 评分所需证据

## 14. 建议的搭建顺序

1. 先运行 AutoBio 已有的 `mani_pipette.py`，确认环境、模型和渲染正常。
2. 复制一个已有移液任务，建立 `serial_dilution.py`。
3. 加入 T1–T4 容器和吸头架。
4. 接入液体体积和浓度状态。
5. 实现 `aspirate`、`dispense`、`mix` 和 `measure`。
6. 加入可复现测量误差和一次临时故障。
7. 加入 checkpoint、pause、resume 和 progress 文件。
8. 先用固定 seed 跑 1 个 episode。
9. 再用 3–5 个 seed 跑隐藏评测。
10. 将仿真输出映射到 AFE 评分结果。
11. 最后再考虑训练策略、LeRobot 数据转换和多模型评测。

## 15. 验收前检查清单

- [ ] MuJoCo 可以加载场景
- [ ] 主相机和腕部相机能输出观测
- [ ] 机械臂动作空间和控制频率已记录
- [ ] 液体体积和浓度状态可重建
- [ ] 失败动作不会改变液体状态
- [ ] 重试动作可以恢复任务
- [ ] 吸头跨源复用会生成污染事件
- [ ] 进度文件逐项更新
- [ ] 暂停状态可以恢复
- [ ] `finish` 会检查所有必要条件
- [ ] 轨迹、图像、事件和质量报告都能保存
- [ ] 多 seed 评测结果可复现
- [ ] AFE `afe_result.json` 和 `reward.json` 正确生成
