---
name: afe-task
description: 构建、修改或审核 AFE Harbor 科研任务包。帮助共建者明确科研目标与验收条件，使用随包模板制作任务，或只读校验已有任务并生成统一中文审核报告。
metadata:
  version: "2.0.0"
---

# AFE 任务包构建与审核

一个入口，两种模式，共用 AFE 协议 1.0、模板和评价标准。常规供题所需指南、模板、检查与报告工具均在本 skill 内，不依赖原控制板或飞书登录。

## 按用户意图选择模式

| 用户请求 | 模式 | 执行入口 |
| --- | --- | --- |
| 从研究问题/材料制作题包，或明确要求修改、修复、迁移题包 | 构建 | 阅读 [构建流程](references/authoring.md) 和 [共建指南](assets/task-template/共建指南.md)；按需选随包模板 |
| 审核、检查、自查已有题包是否合格 | 审核 | 阅读 [审核流程](references/review.md)，保持题包只读，生成 review.md |

意图明确就执行；只有无法判断是否要修改文件时才询问。审核发现问题不会自动获得改包授权。“构建并自查”先完成构建，再对最终文件调用审核流程；允许修正已授权范围内的缺陷，并刷新受影响的检查。自查不冒充独立审核。

## 共用原则

- 首版 L1 是限定目标的科研挑战，达成目标应产生此前研究与方法尚未实现的科学贡献。题型只是开放示例。Level、题包质量和解题成绩分别判断，不因困难或高成本自动改级。
- 科学目标、满分依据、必要条件和有效的核验方法由作者/领域专家确定。已有材料足够时直接采用；关键内容缺失时询问，继续不依赖答案的工作，不能编造阈值、证据或创新性结论。
- solution 和参考成绩可选，没有参考解或满分解本身不判负，也不要求作者再次确认。支撑本题科学主张必需的对照仍需落实。
- 主分为 0–100、100 封顶且表示全部必要科学条件与目标成立；映射由作者实现。raw、超目标标记和参考成绩按协议可选，不新增统一端点表或通用 evidence/summary 输出要求。
- 审核采用静态阅读和已有证据，不运行题包。构建默认做静态自查；轻量合成检查及运行验证按用户授权、资源条件和工作目录边界执行。未运行不写成通过或失败；本 skill 不代替解题，也不自动提交或发布。

## 配套资源

- [共建指南](assets/task-template/共建指南.md)：项目定位、Level、完整目录、字段、评分、validation 和提交说明。首次构建必读，审核按需查阅。
- [模板目录](assets/task-template/)：task_package/ 为普通文件交接模板；可选示例/ 中有二分类片段、参考方法和 validation_task；均为合成演示。
- [协议检查要点](references/afe-contract.md)、[格式检查规则](references/format-contract.md)：字段和文件交接；机器 Schema 在 assets/task-template/自查工具/schemas/。
- [质量档位](references/rubric.md)、[题型核验指引](references/task-type-checks.md)：C1–C8，每项 0–3 或待核实，不合总分。
- [报告约定](references/report-contract.md) 与 [报告数据模板](assets/assessment.template.json)：生成统一中文 Markdown。
- [人类使用说明](README.md)：安装、构建/审核请求示例及验证边界。

结构检查运行 scripts/check_structure.py；结果校验运行 scripts/afe_contract.py；报告生成运行 scripts/render_report.py。命令与退出码见对应流程。Python 3.11+ 可直接使用；Python 3.8–3.10 需已有 tomli。审核不要求安装 Harbor 或 Docker。
