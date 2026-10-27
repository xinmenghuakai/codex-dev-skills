# 模型分级与 Agent 路由

进入需求判断、方案、实现、测试、Review、SQL 审查、接口交付或发布阶段前读取本文件。需要新委派时，模型选择以“能可靠完成该阶段的最低档位”为准。`simple_fix` 和 api-handoff 小批 Markdown 连续交付保留当前主会话模型，普通整体实现的连续验证沿用原执行者；不为单次机械步骤切换模型。本文件是唯一的人类可读路由说明，对应 Agent TOML 是机器执行配置；专项 Skill 不再复制具体模型或档位。Codex 自带的速度与会话模型功能由产品自身管理，本流程不重复实现。

本文 `Sol` 当前对应 `gpt-6.1-sol`；方案规划与架构设计使用 Sol/xhigh，其他固定 Agent 保留现有模型和思考档位。具体型号与档位以对应 Agent TOML 为准。

已确认口径的小范围 plan 增补和事实性回写先走 SKILL.md 的“轻量方案维护”，使用当前主会话模型，不派方案 Agent。下文 Planner/Architect 独占 plan 来源的要求对此例外不适用；真实主写入者以 `main_agent` 留下 `scope_contract` 来源，不影响任何实现/Review 模型配置。

## 子 Agent 上下文

所有引用本路由的研发阶段新建子 Agent 时，运行时支持则显式传入 `fork_turns="none"`，不依赖默认值继承整段会话；此设置只控制历史传递，不改变上述模型、思考档位或审查标准。

主 Agent 交接本阶段目标、当前有效业务决策（包括影响实现的用户原始要求与后续纠正，不能只给 plan 或任务包的归纳）、仓库与分支、代码入口或 plan 对应章节、允许修改范围、授权和副作用边界、有效验证结果及验收要求。以简短任务说明和精确文件引用传递，不复制整段聊天、整份 plan 或无关 Skill；子 Agent 仍须读取适用 AGENTS.md 与本阶段 Skill，并核对真实代码。具体任务包沿用 [最小任务包](plan-and-task-packages.md#最小任务包)，不额外引入交接文件或审批。

仅用户明确要求继承历史，或必要的历史语义无法可靠压缩交接时，才使用 `fork_turns="all"` 并简述原因；任务复杂本身不是全量继承的理由。材料不足时定向补充缺失事实，不默认重传完整历史。同一职责的后续工作优先复用原 Agent 并传入增量变化；复用不能代替所需的独立审查。

## 难度分级

| 难度 | 判定边界 | 默认执行模型 |
| --- | --- | --- |
| `L0` 机械执行 | 输入、目标和命令已冻结，只需按固定步骤运行、格式化、生成或读回；不需要解释业务语义 | Luna/medium |
| `L1` 简单实现 | 单一根因、边界清晰、低风险、短 diff，能从现有模式直接类比；允许同步修改同一既有非敏感配置项或调整已有模型名、超时等运行参数，但不新增密钥、地址、依赖、协议字段、重试/并发策略或数据副作用 | Luna/high；`simple_fix` 使用当前会话模型 |
| `L2` 常规工程 | 需要读代码和理解现有分层，存在多个边界或跨层改动，但契约明确、风险可控 | Sol/high |
| `L3` 深度实现 | 契约已经冻结，但内部算法、状态组合、性能或多文件实现复杂，需要更长推理；不负责重新定义业务契约 | Sol/max |
| `L4` 关键实现 | 高风险数据、权限、资金权益、并发事务、异步一致性、公共基础设施或实现期间仍需关键语义判断 | Astra/medium |
| `L5` 架构判断 | 多模块依赖、跨仓公共契约、重要数据模型、重大兼容/安全取舍或高不确定性的整体设计 | Sol/xhigh |

“消息、异步、乱序”不自动等于 `L4`。若真实调用同步串行、没有队列/回调/重试/跨实例共享状态、不改持久数据或业务失败语义，只按外部服务明确协议补排序元数据，则按 `L2` 常规工程处理；安全定向测试不足是验证 finding/阻塞，不改变实现复杂度。涉及持久状态竞争、幂等补偿、重复/丢失的不可接受副作用时才使用 `L4`。

研发主会话使用当前会话模型和思考档位，任务内手动选择优先于全局配置；方案规划和架构设计默认使用 `gpt-6.1-sol/xhigh`，L4 关键实现和高风险 Review 默认使用 `gpt-6-astra/medium`。使用 Astra/medium 的阶段取得必要证据后仍无法收敛关键不确定性时，说明具体缺口并建议升到 high；升级必须与实际执行配置一致，不得只改任务包或伪报档位。线上诊断流程继续使用 Sol/high 和 Sol/xhigh，不自动升到 Sol/max。

`delivery_mode=targeted_fix` 是 L1 的更窄执行分流：先按其专用准入条件读取直接代码和 Git 边界，条件成立时由当前主 Agent 原地完成，不要求为模型/Agent 切换停顿。它只省略仪式，不降低 L1 的代码判断要求；一旦出现传输契约或其他升级项，立即回到本文件的普通路由。

`delivery_mode=simple_fix` 满足现有准入条件时，由当前主 Agent 使用当前会话模型和思考档位连续完成实现、必要补测、一次安全定向验证和短 diff 核对；不为匹配 L1 默认档位切换模型或固定派发 Implementer/Verifier。资格失效时升级交付模式并重新分级；只有明确能力缺口时才按专项职责委派。`feature_delivery_simple_implementer` 的现有配置保留，供用户明确指定时使用，不再作为小修复的默认路由。

## Terra 页面与视觉任务（按需）

有设计稿还原、布局/样式/响应式调整、图片裁切或截图对照需求，且存在独立视觉任务的明确收益或用户明确要求时，才使用下述角色；不因涉及前端就固定委派，不为换模型拆任务或升级交付模式。`targeted_fix/simple_fix` 默认仍由当前主 Agent 连续实现与验证；用户明确要求独立视觉验收时可只委派只读验收，不升级模式。

- **页面实现**：`feature_delivery_ui_implementer` 使用 Terra/medium，仅接收 L2、已确认页面行为与接口契约下的 `whole/modular` 视觉实现。纯页面 `whole` 由它连续实现和必要验证；混合业务逻辑的 `whole` 继续由原 Sol/Astra 执行者负责，需要时只委派视觉验收。已有独立模块才按现有 `modular` 边界分工。不得修改鉴权、支付、业务状态、接口/持久化契约；发现这些问题回主 Agent 按原风险处理。
- **视觉验收**：`feature_delivery_visual_verifier` 使用 Terra/medium，读取设计参考与实际页面/截图，检查约定视口及页面状态下的布局、间距、字体、裁切、溢出和响应式差异，只回传问题位置、截图证据及未覆盖/阻塞项；不修改业务或测试文件。没有实际页面/截图证据不能报告验收通过。浏览器操作仍先核对环境与副作用，不执行未经授权的提交、发送、上传或交易。
- **任务输入**：复用当前模式已有任务包或小修复内联契约，只补设计稿/图片的精确引用、页面路由及代码基线、待验视口与状态、允许修改范围（实现）和本任务已有的证据目录。只读验收不要求实现来源、快照或新增 Gate 包；已有 plan 就引用对应项，无 plan 不补建。实现角色按现有 schema v2 回传真实写入来源；视觉验收只回传证据，不认领 implementation 文件。
- **证据复用与独立性**：代码、资源、设计基线、视口/状态、依赖和环境均未变化时复用已有截图及结论，仅补缺失或失效项；用户明确要求重跑时除外。需要独立视觉验收时，使用不同于实现者的 Agent 实例（可以同为 Terra），不把实现者自检称为独立验收。视觉结论只覆盖实际观察范围，不替代功能验证或代码 Review。
- **审查与发布**：视觉验收不是新增 Review 阶段或发布门槛。同批上线仍集中一次完整独立代码 Review，test/master 与跨窗口仍复用有效审查和材料；仅增加视觉任务或截图，不重建 provenance/snapshot/report/binding，不因换模型重跑有效业务验证。实际页面代码新增/变化仍按现有规则记录来源、核对风险并补审变化；正式 Gate 是否需要完全沿用原发布规则。

两个角色默认固定 Terra/medium。复杂视觉任务若需要 high，先由主 Agent 明确能力缺口并核对真实执行配置；固定角色 TOML 锁定的档位不能用 spawn 参数或任务包覆盖。改用明确配置的 Terra/high 执行者时如实记录来源，不把它冒报为固定 medium 角色；不默认使用 max。

## 研发测试失败升级

测试专家一轮后仍无法区分实现 bug、测试错误和环境问题时，由主 Agent 委派通用子 Agent 继续只读诊断，显式设置 `model=gpt-6-astra`、`reasoning_effort=medium`、`fork_turns=none`。任务只传入原范围、准确失败输出、已排除假设、相关代码位置和已审查的安全验证命令；不修改业务代码、测试、配置或外部状态，不扩大测试范围，不派生子 Agent。缺少必要权限或环境证据时报告具体阻塞，不能靠重试或更换模型绕过。

只读诊断不生成实现来源记录，也不因升级模型把普通任务强行定为 L4。根因确认后回传证据，由主 Agent 按原授权和真实风险转入对应修复流程；实际无法使用指定模型时如实报告，不以 Sol 或当前低档位冒充。此分支不调用线上诊断 Agent，也不改变它们的模型配置。

## 分级证据

每个阶段任务包必须记录：

- `task_difficulty=L0|L1|L2|L3|L4|L5`
- `selected_agent=<自定义 Agent 名>`
- `selected_model=<model/effort>`
- `selection_evidence=<为什么该任务需要且只需要此档位>`

每个会写入发布范围的 Implementer 或 Test Specialist 完成后，回传 schema v2 来源记录：`entry_type=implementation`、自己的 `task_id`、`module_id`、`selected_agent`、`selected_model`、关联计划项和实际写入的仓库相对路径。只有 Planner/Architect 实际改写了位于发布仓库内、且进入 release diff 的 `plan_manifest`，才回传 `entry_type=scope_contract`；该条目只证明该次 plan 修改的真实 writer，不能认领业务实现文件。一个 plan 在方案、模块验收和最终验收的多次事实回写可有多条 Planner/Architect contributor 条目；Implementer、Tester、Reviewer、Releaser 只回传事实，绝不自行认领或写入该 plan。主 Agent 将实际回传条目写入发布仓库外的 `implementation-provenance.json`，并在 schema v4 基础快照后按 Review 契约运行 `python3 "${CODEX_HOME:-$HOME/.codex}/skills/feature-delivery/scripts/implementation_provenance.py" --risk-level <small|normal|high>`。脚本 stdout 是单个 JSON object；只可解析其中的 `implementation_model_families`、`selected_reviewer` 与 `review_independence` 作为 Gate CLI 输入，不得把它伪造成 `key=value` 回传或人工覆盖。任务扩大、风险升级或契约重新打开时必须重新分级，只能基于新证据升降，不能为节省额度继续沿用不足模型。

## 阶段路由

| 职责 | Agent | 模型 | 适用范围 |
| --- | --- | --- | --- |
| 主 Agent 范围判断 | 当前主 Agent | 当前会话模型 | 读需求、代码入口和 Git 状态，判断 L0-L3 模式与是否需要阶段 Agent；普通范围判断不强制切换模型 |
| 主 Agent 架构判断 | 当前主 Agent | 当前会话模型 | 识别 `L5` 依赖图、跨仓公共契约和重大取舍后，委派下述架构设计 Agent |
| 轻量行为修复 | 当前主 Agent | 当前会话模型 | 已通过 `targeted_fix` 专用准入的 `L1`；不派 Agent，资格失效立即进入普通路由 |
| 方案规划 | `feature_delivery_planner` | Sol/xhigh | L4 的关键方案、数据/权限/并发取舍；L1-L3 由当前主 Agent按真实代码形成最小方案 |
| 架构设计 | `feature_delivery_architect` | Sol/xhigh | `L5` 架构、依赖和高风险边界 |
| 简单实现 | 当前主 Agent | 当前会话模型 | `L1` 且满足 `simple_fix`；连续实现、验证和短 diff 核对 |
| 常规实现 | `feature_delivery_implementer` | Sol/high | `L2` 需要委派时使用；当前主 Agent 能可靠完成时可连续实施，补测与验证按主文件 |
| 页面视觉实现（按需） | `feature_delivery_ui_implementer` | Terra/medium | L2，已确认契约的页面视觉范围；不因前端自动委派 |
| 截图/视觉验收（按需） | `feature_delivery_visual_verifier` | Terra/medium | 只读对照页面和设计参考，复用有效截图，不替代代码 Review |
| 深度实现 | `feature_delivery_deep_implementer` | Sol/max | `L3`，契约必须已冻结 |
| 关键实现 | `feature_delivery_critical_implementer` | Astra/medium | `L4` |
| 测试设计/诊断 | `feature_delivery_test_specialist` | Sol/high | 复杂测试设计、新夹具或首次不明确失败归因；普通 L2 的现有测试补改由原执行者连续完成 |
| 命令验证 | `feature_delivery_verifier` | Luna/medium | `L0`，有并行收益、独立环境或明确要求独立执行的安全命令，以及 L3/L4、modular 的专门验证；普通命令按主文件连续执行，有效结果不重跑 |
| 普通风险审查 | `feature_delivery_reviewer` | Sol/high | `whole/modular` 的 `normal/2` Review；`simple_fix` 不派 Reviewer |
| 高风险审查 | `feature_delivery_sol_reviewer` | Astra/medium | 资金、权限、生产数据、持久并发/事务/幂等、重大兼容等 `high/5` Review |
| 独立 SQL/GORM 专项审查 | `feature_delivery_reviewer` | Sol/high | 用户直接调用 `sql-check`，且不属于一次已选 Reviewer 的完整 Review |
| Review 内 SQL/GORM 检查 | 当前已选 Reviewer | 继承 Reviewer | 在同一审查阶段合并 `sql-check`，不得因 SQL 再改派模型或 Reviewer |
| 小批 Markdown 接口交付 | 当前主 Agent | 当前会话模型 | 满足 api-handoff 的连续交付条件时，先冻结事实再生成单份 Markdown |
| 接口事实提取 | `api_handoff_agent` | Sol/high | 超出小批 Markdown 连续交付条件时，从真实代码冻结接口契约 |
| 接口材料执行 | `api_handoff_executor` | Luna/medium | 只消费已冻结契约，生成、校验和授权同步 |
| 单仓 Git 发布 | `feature_delivery_releaser` | Luna/medium | 需要委派且已就绪的单仓发布；普通 Git 发布默认主 Agent 连续执行 |
| 复杂上线编排 | `feature_delivery_release_coordinator` | Sol/high | 超过两仓或涉及 migration、cron、生产配置、跨服务上线顺序；普通前后端两仓由主 Agent 编排 |

当前主 Agent负责范围判断和 L1-L3 的收敛，不因读取代码、拆一个任务或执行普通发布而自动升高思考档位。只有证据已经达到 L4/L5，或当前模型无法可靠关闭关键不确定性时，才委派对应高档 Agent。

## 直接调用回退

用户直接调用专项 Skill 时使用当前会话能力；只有任务风险明显超过当前模型且无法委派对应 Agent 时才说明缺口并请用户决定，不为常规任务反复要求 `/model`。直接 `$review` 若没有 feature-delivery 的正式发布任务包，使用 `direct_review`，只输出 findings 与验证限制，不生成或声称具备正式 Review Gate、机器 report 或发布就绪证据。

正式来源记录接手人工/主会话/其他已完成代码时，按 [接手既有实现的来源](plan-and-task-packages.md#接手既有实现的来源) 使用 schema v3；固定 Agent 的 v2 回传继续有效。未知模型返回 `source_unknown` 而非声称异构，不因此自动提高或降低审查风险。

## Review 路由

Reviewer 按审查风险选择，不再为了模型家族异构把常规 L2 Review 强制升级到 Astra：

- `targeted_fix/simple_fix`：主 Agent完成一次短 diff 核对，不派 Reviewer，不进入正式 Gate。
- `normal/2`：使用 `feature_delivery_reviewer`（Sol/high）。
- `high/5`：使用 `feature_delivery_sol_reviewer`（Astra/medium）。

正式 Gate 的 provenance 仍用于证明实现文件来源，但不作为提高 Reviewer 档位的理由。独立任务上下文本身提供复核视角；同模型家族时如实标记 `same_family_unavoidable`，不得伪称异构。

`feature_delivery_sol_reviewer` 保留为兼容既有任务包和 Gate 的内部角色名，实际模型以其 TOML 为准，当前为 Astra/medium；名称中的 sol 不代表仍执行 Sol。模型或档位变更前的来源记录与 report 不得直接冒充新模型证据，正式 Gate 按当前配置重新核验。
