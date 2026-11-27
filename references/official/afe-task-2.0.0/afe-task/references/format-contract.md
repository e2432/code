# 静态结构约定

规则版本：2.0.0。声明 metadata.afe.protocol_version="1.0" 的题包按 [AFE 协议](afe-contract.md) 检查；未声明的旧 ReX 包记录迁移事项。运行配置沿用 Harbor 0.25.0、schema_version 1.4。强制参考解、authoring/provenance 目录及包内重复团队／授权信息不适用。

| 组 | 内容 | 解释边界 |
| --- | --- | --- |
| F1 | task.toml、instruction.md、两侧 Dockerfile 或显式预构建镜像、tests/test.sh；评分实现候选 | 缺运行必需路径如实记结构缺口；提议仍可提交。评分器可内嵌 test.sh，不强制叫 check_outputs.py；solution 可选 |
| F2 | TOML、schema_version、afe/ 命名、主要段、资源值与 AFE 元信息 | 项目约定不满足不等于所有 Harbor 都不支持。未显式声明 task_id 时使用目录标识，不强令 task.name 等于目录 |
| F3 | separate、artifacts 路径或 source/service 对象、边界配置 | 支持从侧服务收集记录；配置正确不证明运行隔离，/app/、/root/ 可以是容器路径 |
| F4 | Docker COPY/ADD、脚本引用、资源地址、参考 info 和已有 AFE 结果 | 变量、多阶段、动态生成留待核实；输出字面量不证明实际结果，未附结果不要求当场运行 |
| F5 | 镜像 tag/digest、溯源与验证记录线索 | scratch、已定义构建阶段不要求镜像 tag；实际可用性需证据 |
| F6 | 缓存、开发机路径、可疑凭据、私有材料引用、链接/扫描限制 | 模式命中仅提醒，不打印凭据值。审核包中的 solution/tests 是预期材料 |
| F7 | 指定版本 Harbor lint | 本脚本不执行 lint；agent 核对工具与已有记录。缺命令或缺证据记待核实，不安装新版本 |

每条结果含规则编号、状态、证据与原因。组状态优先级：不通过、待核实、提醒、通过；组状态不能自动决定接收。

只读取预算内文本，不跟随目录链接，不读取包外链接目标或特殊文件；限制写入 coverage。已存在但无法读取与确认不存在分开。外部挂载/下载可作为声明的数据交付方式，不因当前机器无法访问就断言数据不存在。

`coverage.content_not_scanned` 列因文件类型未进入自动正文扫描的文件，含 CSV/CIF/log 等；`skipped` 列预算、链接、权限等原因。两者都不等于题包异常，但必须明确覆盖范围，按必要性补查元数据或小样本。

主 Dockerfile 默认上下文为 environment/、tests/；发现额外 Dockerfile 时可检查 FROM，但 COPY/ADD 不猜上下文。先阅读 Compose/构建声明，将其上下文换算为题包相对路径，再用 `--build-context environment/bridge/Dockerfile=environment` 这类参数指定。示例路径不要求所有题包存在。上下文在包外或仍不清楚时保留待核实；不执行 Compose 获取信息。`dockerfiles_checked` 保留实际使用的上下文。

验证候选优先列参考解、空提交、lint、部分提交的结果及版本绑定，完整候选列表保存在 `coverage.evidence_candidates`。排序只帮助定位，不代表最近版本或可信度，须实际阅读修订链。

核心配置：schema_version="1.4"；artifacts 仅列 verifier 需要的文件/目录；verifier.environment_mode="separate"；task.name 为 afe/ 科学名称；timeout_sec、build_timeout_sec、cpus、memory_mb、storage_mb 为有限正数，gpus 非负。模板里的具体数值不是所有题必须相同的常量。

no-network 是指南默认模板，私有 judge/服务场景需明确例外和失败处理，不把 public 自动认定为所有场景非法。元数据缺项/空值提示补充，不臆造为官方 parser 的硬约束。

目录只检查字符约定；存在显式 task_id 才核对一致性。task.name 的外部科学名称与内部目录可以不同，记录项目约定冲突。

可以复用当前版本已有记录，区别记录存在、作者声明和证据支持。solution 为可选资料，缺少参考解不产生格式负项。ReX 的补充材料/ 与 task_package/ 同级，按需提供；本脚本不自动越出任务根目录，agent 另行读取用户提供的材料。来源／验证记录未在任务目录内找到时保留待核实，不强制补建 authoring/。网页已填写的团队和授权无需重复入包，不能因未知网页内容就宣称来源不存在。
