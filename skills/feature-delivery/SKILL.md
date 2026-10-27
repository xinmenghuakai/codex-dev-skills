---
name: feature-delivery
description: 以轻量行为修复、简单修复、整体实现或分模块实现四种模式编排研发交付。用于已有读逻辑的查询行为修复、小修复、完整需求和多模块实现；按需复用 go-test、review、sql-check、api-handoff、git-pr 和 release。
---

# 研发交付流程

以用户原始需求、后续明确纠正及已确认的范围调整为当前有效需求；plan 是执行记录，不能缩小或替代用户要求。结合真实代码和 Git 状态推进已授权阶段。

## 需求完整性

- 开始改动前，沿相关入口与调用链确认需求覆盖的行为、控制项和验收结果；“全部/统一/不再使用”等要求按实际职责核对，不能只匹配某种字段类型、命名或已有 diff。代码证明同一目标还需其他落点时补齐；不为满足轻量模式的文件/行数上限裁剪需求，应升级模式。
- 将必要的需求与落点、验收依据就地补进已有 plan 或内联范围；交接时保留会改变实现或验收的用户原话和纠正。无需新增表格、任务包字段、文件或确认步骤。发现 plan/任务包漏项时，按已授权原意修正并继续；只有真实业务歧义、范围新增或授权不足才询问。
- 收尾时反向对照当前有效需求检查完整实现，包括未改文件中的相关旧入口、默认值、配置读取和回退路径；验证应覆盖要求的结果及明确禁止的旧行为。测试、Review 或 Gate 通过不能替代此项核对。

## 复杂度与模型

本 Skill 只负责判定复杂度和选择阶段 Agent，不重复实现 Codex 已有的代码修改、测试、Review、Git 和发布能力。模型映射只维护在 [模型分级与 Agent 路由](references/model-routing.md) 与对应 Agent TOML；主 Agent 使用当前会话完成范围判断，只有实际阶段超过当前模型能力时才委派更高档 Agent，不为读取代码或普通范围判断强制切换模型。

进入阶段前简记 `task_difficulty`、`selected_agent`、`selected_model` 和 `selection_evidence`。按中央路由选择必要执行者；小修复与普通连续验证保留当前执行者，不因阶段切换升级模型或重复派发。产品速度模式由 Codex 管理。

新建子 Agent 默认显式使用 `fork_turns="none"`，由主 Agent 提供本阶段必要的业务决策、代码入口和授权边界；例外、增量交接及复用规则见 [子 Agent 上下文](references/model-routing.md#子-agent-上下文)。不因此改变模型分级或降低验证与审查要求。

## 轻量方案维护

用户只要求把已确认口径补进既有 plan，或回写已有实现、验证和验收事实时，由当前主 Agent 使用当前会话模型直接修改，不委派 Planner/Architect。先核对直接相关代码/证据，只改对应章节和必要的总览、交付清单；不重新讨论已确认决策。存在尚未确认的业务取舍、跨模块契约冲突或高风险设计判断时，退出此例外，按真实阶段难度路由；不能为满足 Agent 准入而把任务强行升为 L4。

这是文档维护例外，不是 `simple_fix` 实现资格，也不授权改代码、DDL、配置、接口平台或发布。保留权限、事务、数据安全及后续正式 Review 边界。仅维护文档时不创建阶段任务包、provenance 文件或 Gate，不运行无关业务测试；完成一次定向 diff 核对，有结构/交付项变更时运行 plan 审计。

本例外优先于本 Skill 及引用文件中的“plan 必须由 Planner/Architect 写入”要求。该 plan 后续进入正式发布时，主 Agent 如实补记自己的 `scope_contract` 来源（`selected_agent=main_agent`、`selected_model` 为实际会话的 model/effort），不得冒充 Planner 或认领业务实现；该来源不参与实现模型 family 和 Reviewer 路由。

## 交付模式

模式只决定需求如何拆分、实现和验证。用户未指定时检查完整发布范围后选择，并在首个实现任务包记录唯一 `delivery_mode`：

| 模式 | 值 | 执行 |
| --- | --- | --- |
| 轻量行为修复 | `targeted_fix` | 已有读逻辑的查询行为修复；见 [轻量行为修复](references/targeted-fix.md) |
| 简单修复模式 | `simple_fix` | 单仓、单根因、短 diff；业务实现最多 3 文件/80 行。测试文件和同一既有非敏感配置项在多环境文件中的机械同步不计入业务实现上限。允许调整已有模型名、超时等运行参数，但不得新增密钥、地址、依赖、协议字段、重试/并发策略或数据副作用。当前主 Agent 使用当前会话模型完成修改、一次安全定向验证和短 diff 核对 |
| 整体实现模式（默认） | `whole` | 单一完整链路，一个执行者连续实现；验证按下述分工，再做独立 `normal/high` Review |
| 分模块实现模式 | `modular` | 已确认 plan 下的多个可独立描述和验收模块；先冻结依赖、公共契约和写入范围，再决定串行或分波次并行，最后做跨模块测试和最终完整 Review |

技术方案按模块写不等于必须使用分模块实现。简单修复任一资格不满足立即升级；整体实现是默认；分模块必须有真实独立边界和已确认 plan。

使用 `modular` 或复核模式边界时，必须读取 [交付模式与分模块验收](references/modes-and-modules.md)。`targeted_fix`、`simple_fix` 与 `whole` 只能使用 `execution_lane=single`；`serial|parallel` 仅属于 `modular`。并行任务携带 `current_module_id`、`allowed_plan_item_ids`、`dependency_status=ready`、`write_scope`、`shared_contract_baseline`；主 Agent 独占 plan 变更决策、公共文件和跨模块契约修改权，仓内 plan 的实际写入仅委派 Planner/Architect。默认每波最多 3 个实现 Agent；并行只用于缩短墙钟时间，不视为节省 Token。

## Plan 与任务包

技术方案面向用户阅读时，先用通俗中文说明谁在什么情况下做什么、处理顺序及成功/失败结果，再在对应步骤补充完整表名、字段和读写操作。不要把状态名、缩写和数据库操作串成长句代替业务解释；具体写法见 [技术方案写作要求](references/plan-and-task-packages.md#技术方案写作要求)。此规则同样适用于轻量方案维护。

`targeted_fix/simple_fix` 使用短计划或当前回合的内联范围锁定，不因用户要求“先给计划”而升级模式、委派 Planner 或套完整模板；用户明确要求保存短计划时按约定位置写入，仅核对本次目标、落点、改法和验证，不触发完整 plan 审计。其余情况不新建 plan，也不创建 provenance、snapshot、report、binding 或 Gate 任务包。准备 `whole/modular` 的阶段任务包时读取 [Plan 与阶段任务包契约](references/plan-and-task-packages.md)；`whole` 可合法无 plan，`modular` 必须使用已确认 plan。

`simple_fix` 由当前主 Agent 完成必要的补测和一次安全定向验证，不因补测或执行命令固定派发 Agent。只有出现当前模型无法可靠处理的测试设计或失败诊断问题时，才按真实风险转测试专家；验证无法安全执行时说明阻塞，委派不能替代副作用审查或授权。已经成功且输入未变化的验证证据不得交给 Verifier 重跑。

## 起始阶段与确认关口

- 新需求/需求文档：从需求分析开始。
- 业务问题已回答：进入技术方案，不等于授权实现。
- 用户只要求计划：交付计划并等待实现授权；已授权实施中的事实性计划回写可继续，新增范围或实质业务取舍变化再确认。
- 计划或内联方案已确认、继续实现：先审计契约，合格后实现。
- 只要求测试、Review 或发布：从对应阶段开始并补齐前置证据。

业务口径确认、技术方案确认和发布授权互相独立。配置、依赖、表结构、model 字段和重要取舍统一按适用 `AGENTS.md` 的实际风险与已有授权判断，不因修改配置或 model 文件就重复确认。阶段任务包传递已授权的精确范围与依据；未获授权且需要确认的改动、范围扩大或实质改变方案时先确认。实施授权不自动包含真实 migration、线上配置操作或发布。需求、方案或实现证据变化时，有 plan 先同步原 plan；无 plan 更新内联契约与快照，业务取舍变化时重新确认。阶段 Agent 只回传事实、覆盖和验收证据，不直接改写 plan；需要回写仓内 plan 时，主 Agent 以定向的 Planner/Architect 任务完成事实性回写并取得该实际 writer 的 scope-contract 来源条目。

## 阶段流程

### 1. 需求与技术方案

读取适用 `AGENTS.md` 和本次相关的真实入口、调用链、数据与现有抽象；按实际风险扩展到 req/res、Service、DAO/Repository、Model、migration、配置和测试，明确目标、非目标、客户端、仓库、数据口径、兼容、发布范围和待确认项。技术方案、计划交付项、最小方案审计和运行 `python3 "${CODEX_HOME:-$HOME/.codex}/skills/feature-delivery/scripts/audit_plan.py" <plan绝对路径> --strict` 的要求以 [Plan 与阶段任务包契约](references/plan-and-task-packages.md) 为准；技术方案确认前不改业务代码。

### 2. 实现与验证

复核已确认契约和 Git 状态，按现有分层实现最小改动并保留无关工作区内容。实现证据推翻方案时先更新 plan/内联契约，改变业务取舍则暂停确认。

- `simple_fix`：当前主 Agent 使用当前会话模型连续完成范围圈定、低风险小修复、必要补测和一次安全定向验证，随后核对完整短 diff、直接调用边界和验证结果；默认不委派小修复 Implementer，不再启动独立 Reviewer、Verifier 或正式 Gate。资格失效时升级交付模式并按真实风险重新选模；明确能力缺口按上文或路由表处理，不为阶段切换而换模型。
- `whole`：L2 常规实现由能力足够的当前主 Agent 或一个 `feature_delivery_implementer` 连续完成；不因阶段名称切换执行者。契约已冻结但内部逻辑复杂时使用 `feature_delivery_deep_implementer`；存在高风险、公共基础修改或关键语义仍需判断时使用 `feature_delivery_critical_implementer`。页面视觉任务按中央路由按需选 Terra；其余委派按 Agent TOML。随后按下述规则验证，并由独立 Reviewer 审查。
- `modular`：按依赖图、写入边界和模块验收规则推进，每个模块独立分级和选模；不得因同属一个需求强制所有模块使用同一模型。详见 [交付模式与分模块验收](references/modes-and-modules.md)。

#### 验证执行方式

Go 改动使用 `go-test`；`simple_fix` 按上文执行，其余先复用有效证据：

- **普通整体实现连续验证**：`whole`、L2、普通风险且边界清晰时，原执行者连续补改现有测试、做安全定向验证和构建，可覆盖同一功能且契约不变的前后端两仓。执行前确认命令、收集范围、环境和副作用；仅编译也遵守测试安全要求。
- **专门验证**：独立环境、用户明确要求或确有并行收益时使用 Verifier；耗时本身不要求交接。L3/L4、高风险和 `modular` 保留原分工，不以单模块结果代替整体验证。视觉验收按中央路由选 Terra，复用有效截图。
- **失败处理**：原执行者修复原因明确且未扩面的失败，只重验受影响项；新夹具、复杂测试设计或原因不明时转 Test Specialist，保留失败证据，不追加猜测性命令。仍不能归因时按中央路由诊断。
- **证据复用**：代码、测试、配置、依赖、命令及环境未变时复用已有结果，只执行缺失或失效项；用户明确要求重跑时除外。
- **事实记录**：就地保存实际执行者、目录、命令、收集范围、环境/副作用审查、代码基线、退出码、关键输出及限制。主 Agent 可据此维护验证材料，不冒充执行者、不把局部结果称为全量通过。

独立 Reviewer、正式 Gate 和发布授权按下述规则执行；委派不豁免安全审查或授权。

### 3. Review

`targeted_fix/simple_fix` 不进入正式 Review Gate。`whole/modular` 安排审查前读取 [Review、接口交付与发布](references/review-and-release.md)：同批上线在合版后集中一次完整独立 Review，已有审查按跨窗口规则复用。按既有风险路由使用 `review`，涉及 SQL/GORM/DDL/索引/migration 时合并 `sql-check`。test/master 先核验双向复用；只有未能复用的最终发布或高风险测试发布才新建正式 Gate。

### 4. 接口交付与发布

`targeted_fix/simple_fix` 获得准确目标授权后直接按 `git-pr` 发布，复用未失效验证。目标前进但未触碰目标文件、直接依赖或 `go.mod/go.sum` 时只重做 Git 集成检查，否则核对影响。`whole/modular` 发布前必须读取 [Review、接口交付与发布](references/review-and-release.md)。

`whole/modular` 声明 `api_handoff_required=true|false`，按真实接口 diff 判断并遵循上述引用中的交付与证据要求。未核验启用 YApi 时默认 Markdown，其他额外交付物须有明确请求。普通 Git 发布默认主 Agent 连续执行；需协调非代码依赖时按引用分流。核对准确目标的有效授权，已有授权且范围未变时沿用；SSH 仍遵守逐次授权要求。Releaser 不解决合并冲突。

## 状态真实性与长任务

只有确有运行中的工具、命令或 Agent 才能说“正在执行”。追问、中断或失败时读取 [运行状态、上下文与收敛](references/runtime-and-recovery.md)，按真实状态恢复；不得虚构隔离环境、后台执行或自动合并。

## 完成标准

所有模式均先核对当前有效需求的完整覆盖，不能仅以计划项、改动文件或检查通过宣告完成。`targeted_fix/simple_fix` 在完整需求范围内完成一次必要验证和短 diff 核对，以及用户授权的 Git 目标读回；`whole/modular` 另需全部计划项或内联契约有证据、必要 Review/Gate 通过、严重问题关闭及接口交付条件满足，并完成用户授权的发布目标。原范围内发现遗漏时继续补齐与定向验证，不追加实现确认。结论简述已实现结果、验证依据和剩余项；尚有必要项未完成时明确部分完成或阻塞。只授权到某阶段时，只报告该阶段完成和下一关口。

阶段 Agent 简述结论、证据、验证、限制和下一动作，不粘贴完整日志、diff 或 plan。Reviewer 的普通结论与正式 Gate/report 输出按 Review 引用协议执行。
