# Plan 与阶段任务包契约

新建/修改技术方案、存在 plan，或准备 `whole|modular` 的 Implementer、Verifier、Reviewer、Releaser 任务包时读取本文件。先按实际范围与风险判断详略：满足 `targeted_fix/simple_fix` 资格的计划只需目标与边界、真实落点、最小改法、验证和必要待确认项，默认内联；用户明确要求保存时可以写短计划文件，不因文件存在而进入本文件的完整模板、交付项清单、审计脚本、阶段任务包、provenance 或快照要求。`whole/modular` 的完整方案、交付项覆盖和相应审计要求继续保留；升级模式时补齐，不能把复杂或高风险需求称为短计划来跳过契约。

## 轻量方案维护例外

先应用 SKILL.md 的“轻量方案维护”：已确认口径的局部增补和有证据的事实性回写由当前主 Agent 直接完成，不进入本文件的阶段任务包/冻结流程。下文仅允许 Planner/Architect 写 plan 的限制不适用于该例外。后续正式发布需要来源记录时，实际主写入者使用 `entry_type=scope_contract`、`selected_agent=main_agent` 和真实 model/effort，只认领冻结为 `plan_manifest` 的文件；不得填 `current/default` 冒充具体模型。其模型是会话事实记录，不是 TOML 已校验声明，不参与实现 family 或 Reviewer 路由；其余来源覆盖和 Gate 校验不变。

## 普通审查与测试发布

准备 Review/Releaser 任务包前，先按 [Review、接口交付与发布](review-and-release.md#正式-gate-适用范围) 判定 `formal_gate_required`。false 时仅传范围、真实目标分支 diff、风险、有效方案或计划项、授权与验证证据；有 `review_reuse_verified=true` 时引用已有独立审查和本次目标检查，不再派 Reviewer 或补造材料，否则完成必要独立审查。两种路径均覆盖计划。下文 provenance、no-plan 文件、冻结快照、机器 report 和 Gate 字段仅适用于 true；普通任务不为准备未来可能的正式发布提前生成这些文件。同一主 Agent 连续执行时就地记录范围、验证和授权，不创建自我交接任务包；进入正式 Gate 仍须补齐对应材料，主 Agent 的真实实现来源使用下文 schema v3。实现者可在正常回传中保留实际写入事实，后续正式发布需要时再整理来源。

## 最小任务包

新建子 Agent 默认显式使用 `fork_turns="none"`；例外与交接原则见 [子 Agent 上下文](model-routing.md#子-agent-上下文)。主 Agent 将当前有效决策整理成可独立执行的任务包，不假定子 Agent 看过聊天历史。任务包只包含：

1. 阶段目标、已授权范围、完成门槛；其中保留影响本阶段的用户原始要求及后续纠正，并依 SKILL.md“需求完整性”核对 plan/任务包，不能只传递缩水后的计划摘要；`delivery_mode=targeted_fix|simple_fix|whole|modular`、`execution_lane=single|serial|parallel`、`task_difficulty=L0|L1|L2|L3|L4|L5`、`selected_agent`、`selected_model` 和 `selection_evidence`。
2. 有 plan 时给绝对路径及必须读取的真实标题/精确行范围，要求禁止全文扩读、材料不足时返回补包；无 plan 时明确“无 plan”，内联当前有效需求、业务口径、方案/发布契约和授权边界。
3. 当前执行快照、有效决策和未解决问题。
4. 仓库、分支、Git 状态、目标文件或完整发布 diff。
5. 测试/生产副作用、配置、依赖、表结构和发布边界。
6. 本阶段专项 Skill、模型、回传格式。

`targeted_fix/simple_fix` 不产生本节所称任务包；仅在当前回合保留目标、传输契约不变量、允许/禁止改动、目标文件、行数和验证命令的短范围锁定。`simple_fix` 额外记录允许修改的既有配置项及禁止变化。已有 plan 只在明示了被修正的旧行为时改动那一处，不能因为它存在就触发全局 plan 审计或覆盖台账。

`whole` 没有 plan 时，每一个 Implementer、Verifier、Reviewer 和 Releaser 任务包都必须原样写出 `无 plan`、`plan_coverage_required=false`、`expected_plan_manifest=none`、`plan_manifest=none`；Review/发布任务再写 `expected_plan_item_ids=none`。其中 `expected_plan_manifest` 是任务包期望值，`plan_manifest` 是阶段回传/Gate 实际值；两者在无 plan 时都必须为 `none`。这些字段不能只靠“内联契约”或上轮上下文暗示。内联材料按阶段至少包含：

- Implementer：目标、非目标、业务顺序、失败语义和授权边界。
- Verifier：验证目标、精确命令、收集范围、副作用审查和期望结果分类。
- Reviewer：当前有效方案、完整发布 diff、直接调用边界、验证证据和风险分级依据。
- Releaser：完整发布范围、Git/部署执行顺序、非代码事项、Gate 校验命令与包含 scope 的成功结果。

`whole` 的无 plan 是合法契约，不得要求主 Agent 凭空创建 plan，也不得仅因 `delivery_mode=whole` 返回缺包；只有上述显式字段或对应内联材料确实缺失时才请求补包。`modular` 依赖计划交付项拆分，缺少已确认 plan 时必须返回缺包并停止分模块派发。轻量模式资格不满足时必须升级，不能靠补任务包维持原模式。

实现阶段结束后，本流程新增写入的 Implementer 或 Test Specialist 必须回传一条 `entry_type=implementation` 来源记录：`task_id`、`module_id`、`selected_agent`、`selected_model`、`plan_item_ids` 与实际写入的 `{repo, path}` 文件清单。只有 Planner/Architect 实际修改了位于发布仓库内、且进入 release diff 的 `plan_manifest`，才如实回传一条 `entry_type=scope_contract` 来源记录；字段同样包含任务、模型、计划项和实际 `{repo, path}`，但不得认领业务实现文件。一个 plan 的方案确认、模块验收和最终验收可由多个 Planner/Architect 分阶段事实性回写，因而允许同一 plan 文件有多条 contributor 来源记录；Implementer、Tester、Reviewer、Releaser 只能回传事实，不能改 plan 或制造 scope-contract 来源。主 Agent 只可将实际回传条目合并为 schema v2、位于发布仓库外的 `implementation-provenance.json`，不得手填 family；随后由 `"${CODEX_HOME:-$HOME/.codex}/skills/feature-delivery/scripts/implementation_provenance.py" --risk-level <small|normal|high>` 在 schema v4 快照中校验范围和来源链，并按明确的审查风险选择 Reviewer，implementation 家族只用于独立性计算。该命令的唯一 stdout 是 JSON object，主 Agent 只能解析 `implementation_model_families`、`selected_reviewer` 与 `review_independence` 来组装 Gate CLI：空 families 映射为 `none`，非空数组按原序逗号连接；不得把原输出改写为 `key=value` 或要求 Reviewer 复述。实际范围、风险或契约状态变化时，主 Agent 按 [模型分级与 Agent 路由](model-routing.md) 重新分级和派发；不得因最初任务包选过某模型就固定沿用。

## 接手既有实现的来源

正式 Gate 允许接手人工、主会话及其他 Agent 已完成的代码。此时使用 provenance `schema_version=3`，保留原七个 entry 字段；`entry_type=implementation` 的非固定执行者增加 `source_evidence=<绝对路径>`：主会话用 `selected_agent=main_agent` 与真实 model/effort，人工用 `human`、`selected_model=none`，其他 Agent 用 `external_agent` 与真实 model/effort（未知填 `unknown`），作者也无法确认时用 `unknown_source`、`selected_model=unknown`。固定角色旧 schema v2 仍兼容，不能冒填成后来负责复核的 Implementer。

source_evidence 必须是随同快照冻结的非空 `role=auxiliary` 文本，记录用户声明/会话记录/Git commit 或当前工作树来源、对应文件和无法核验项；证据不含凭据或业务敏感数据。脚本校验冻结内容和完整文件覆盖，不能证明声明者真实身份。Reviewer 必须读取证据并独立审查全部接手改动，未知模型返回 family `unknown`、`review_independence=source_unknown`，不得声称已证明模型异构；主会话已知 family 仍参与同家族判断。来源不明不替代缺失的代码、验证或发布授权。

## Review 证据文件

准备任何可能得到完整结论（`gate=pass|findings`）的 Review 前，主 Agent 必须在本会话证据目录按 schema v4 准备并冻结以下材料。`gate=blocked` 不进入本节的完整证据链。所有脚本都用绝对路径调用，不得依赖当前工作目录：

1. 位于发布仓库外的 `implementation-provenance.json`：schema 为兼容的 `schema_version=2|3` 与 `entries[]`，作为 schema v4 快照的 `role=implementation_provenance` artifact。 `entry_type=implementation` 记录实际写入者；固定角色用 v2，人工/主会话/其他既有实现按上文使用 v3；`entry_type=scope_contract` 仅记录位于发布仓库内且进入 release diff 的 `plan_manifest`，必须由实际修改它的 Planner/Architect 回传。两类条目共同证明完整来源覆盖，但模型 family 和 Reviewer 只从 implementation 条目导出。
2. scope contract 仅有两类且互斥：有 plan 时使用 `plan_manifest`；无 plan 时使用发布仓库外、文件名严格为 `no-plan-contract.md` 的契约。该文件必须包含 `# 无 plan 契约`、`## 目标`、`## 非目标`、`## 发布范围`、`## 验证`、`## 授权边界` 六个标题；无 plan 时 `--no-plan-contract` 传该绝对路径，有 plan 时该参数必须为 `none`。只有这两类 artifact 可传给 `--scope-contract-artifact`，同一次 Gate 不得同时使用二者。
3. 接口交付物、migration/DDL 说明、YApi/ApiPost 读回和其他冻结材料只能以 `role=auxiliary` 加入快照，绝不是 scope contract。migration 或 API 文件若进入 release diff，仍必须由 implementation 条目认领；不得用 Planner/Architect 的 scope-contract 条目替代真实实现来源。
4. 基础快照用 `python3 "${CODEX_HOME:-$HOME/.codex}/skills/feature-delivery/scripts/freeze_snapshot.py" --repo-target <绝对仓库>=<目标分支ref>` 冻结所有仓库 release diff、scope contract、`role=implementation_provenance` 和适用的 `role=validation_evidence|auxiliary`。目标必须为分支/ref，不能是 `HEAD` 或裸 commit；脚本冻结 target/candidate/base revision。`implementation_provenance`、`no_plan_contract`、`review_report` 和 `validation_evidence` 必须在所有发布仓库外；`plan_manifest` 与 `auxiliary` 可以在仓内或仓外。调用统一使用 `--artifact <role>=<绝对路径>`，例如 `--artifact plan_manifest=<plan绝对路径>` 或 `--artifact no_plan_contract=<仓库外绝对路径>`；旧的无 role artifact 只属于 auxiliary，不能作为 v4 完整结论的 scope contract。

先运行 `python3 "${CODEX_HOME:-$HOME/.codex}/skills/feature-delivery/scripts/implementation_provenance.py" --risk-level <small|normal|high>` 获取唯一 JSON 路由对象，再派 Reviewer；脚本按当前 risk_level 路由，只从 implementation 条目计算家族和独立性，scope_contract 条目只保留 plan 的审计链。先冻结不含 report 的基础快照，并把 stdout 的 `review_input_sha256=<hex>` 原样给 Reviewer；这是 report 顶层 `reviewed_release_fingerprint` 必须绑定的 review-input 指纹，不是快照 JSON 字段。完成全部审查遍次的 Reviewer 必须以 `<!-- feature-delivery-review-report-v1:start -->` / `<!-- feature-delivery-review-report-v1:end -->` 输出唯一 schema v1 JSON report；标记间只允许 JSON，顶层必须精确为 `schema_version,reviewed_release_fingerprint,selected_reviewer,selected_model,implementation_model_families,review_independence,gate,validation_evidence_paths`；嵌套 `gate` 还必须写自身上报集合 `reported_plan_item_ids,reported_finding_ids,reported_finding_plan_item_ids`，不能只复述 Gate 侧集合。主 Agent 只保存该区块原始 bytes，随后以同一 release diff、同一 contract/provenance/验证材料重新冻结并加入 `role=review_report`；`review_input_sha256` 刻意排除该 role，故应与基础快照相同。`review_gate.py` 的 `pass/findings` 只能使用含 report 的后一个快照，且必须传 `--review-report <绝对路径>` 与 scope contract/provenance；`pass` 写新的 `--write-gate-evidence`，`findings` 写新的 `--write-review-evidence`，二者另一个输出均为 `none`。`blocked` 不创建 report 或调用 Gate，也不携带这条完整证据链。Gate/review evidence 必须是发布仓库外、尚不存在的新绝对路径，不得覆盖 snapshot、任一冻结 artifact 或上一证据。无 plan 不等于免除 contract；它只免除完整 plan。

`simple_fix` 固定 `execution_lane=single`，使用内联范围锁定。当前主 Agent 使用当前会话模型完成实现、必要补测、一次安全定向验证和短 diff 核对；验证成功后，只要代码、测试、配置、依赖和命令未变化，后续发布阶段直接复用，不再派 Verifier 或 Reviewer。尚未执行的安全定向命令也由当前主 Agent 执行；只有明确的测试设计或失败诊断能力缺口时才转 Test Specialist，验证无法安全执行时说明阻塞。

`whole` 固定 `execution_lane=single`。符合主文件“普通整体实现连续验证”时，由原执行者连续补测、验证和构建；委派时在原任务包附精确命令、测试收集范围、环境、副作用审查和期望结果分类，主 Agent 原地执行则就地记录，不创建自我交接或额外 Verifier 任务包。转入专门验证时只交接未完成或失效的命令及原有证据；能力缺口、环境阻塞和授权不足分别说明。`modular` 的 Implementer、会补改测试的 Test Specialist 和 Verifier 都额外携带 `wave_id`、`current_module_id`、`allowed_plan_item_ids`、`dependency_status`、`write_scope`、`shared_contract_baseline`；串行模块还须携带直接前置模块验证状态。共享测试、跨模块集成测试或公共夹具只能在当前实现波次全部停止后，以 `execution_lane=serial` 单独派发，不能与实现模块并行写入。

## 计划交付项清单

`whole` 或 `modular` 有 plan 时，维护唯一 `## 计划交付项清单`。表头固定为：

`交付项 ID | 范围状态 | 来源章节 | 交付内容 | 责任端/仓库 | 不适用依据`

- 同一模块的后端、前端/App、数据、任务和非代码事项分别一行。
- ID 只用字母、数字和 `._:/@+-`；状态只能为 `required/not_applicable`；来源章节必须是真实标题。
- `not_applicable` 只记录已确认排除依据。运行 `python3 "${CODEX_HOME:-$HOME/.codex}/skills/feature-delivery/scripts/plan_manifest.py" <plan绝对路径>` 取得完整 ID，不得另行缩减；旧 plan 缺清单时返回方案阶段补齐并重新确认。
- 实现、测试和 `normal/high` Review 共用覆盖状态：`satisfied/not_applicable/missing/blocked/external`。有关联 finding、验证或依赖阻塞时必须为 `blocked`；零 diff 项不得省略。

## Plan 定向读取

先运行 `python3 "${CODEX_HOME:-$HOME/.codex}/skills/feature-delivery/scripts/plan_context.py" <plan绝对路径> --list`，再用 `--line <标题起始行>` 提取章节；标题过多时 `--find <关键词>`。列表上限 120 个标题，正文上限 400 行/12000 字符；超长叶子章节用升序且互不重叠的 `--range <起始行>:<结束行>` 分段。任务包不得只给路径让 Agent 全文查找。

默认章节：

| 阶段 | 必需章节 |
| --- | --- |
| 方案 | 范围、业务口径、整体数据流、相关功能模块、计划交付项清单、待确认项 |
| 实现 | 当前执行快照、授权范围、计划交付项清单及覆盖台账、改动汇总、验证范围 |
| 测试 | 当前执行快照、计划交付项清单及覆盖台账、验证矩阵/记录 |
| Review | `small` 用内联修复契约、完整发布 diff、直接调用边界和定向验证；`normal/high` 读快照、范围/非目标、清单、全部来源模块、改动与验证记录、已废弃边界 |
| 发布 | 当前执行快照、计划项覆盖台账、改动汇总、验证/Review、发布步骤和非代码事项 |

阶段 Agent 默认不得全文扩读 plan。只有新建/整体修订 plan 的 Planner 可读取当前完整 plan。`normal/high` Reviewer 必须交叉检查清单与全部来源章节；`small` 不读整份 plan，但发布 diff 必须只包含本次修复。

## 技术方案写作要求

技术方案先让用户读懂业务，再提供实现所需的细节。新建、整体修订和局部维护均遵守：

- 每段先说明“谁、什么情况下、做什么、结果是什么”。执行流程按实际顺序分步写，成功、失败、重复请求和并发分支分别解释，避免压进一个长句。
- 在通俗解释后，就地补充技术操作：完整接口路径、完整表名、字段及其取值、事务和唯一约束。可用“数据操作：……”补充，不能只列字段或伪代码让用户自行推断业务。
- 每张字段表前明确“现有改造/拟新增”、完整表名、一条记录代表什么、谁写谁读；正文不要只用表名后缀指代存储对象。
- 首次使用必要术语时解释含义。优先写“当前任务的执行者”“结束当前任务”“防止重复处理”，避免用内部缩写代替主要解释。时间和并发边界用简短例子说明。
- 通俗表达不省略技术契约；机器要求的交付项、字段类型、索引与校验记录仍保留在对应表格或独立记录中。结构审计通过不代表表达清楚，交付前人工检查用户能否不读代码就理解每一步。

示例：

> 同一请求已经创建过任务时，返回已有任务的状态，不重复创建。首次请求创建一条待处理记录；并发请求通过唯一约束防止重复。
>
> 数据操作：按 `request_key` 查询示例表 `example_app.job_requests`；不存在时插入 `status=pending` 的记录，`request_key` 使用唯一索引。发生唯一键冲突时重新查询并返回已有记录。

示例表名和规则均为虚构，仅说明表达方式；实际设计以当前项目的真实契约为准。

## 技术方案逐模块闭环

每个 `模块X` 在同一章节写清：

1. 模块职责及不负责范围。
2. 调用方式、调用方、触发时机；区分新接口、现有接口/回调、内部 Service、外部调度和一次性发布动作，前端无感时写 C 端无需新增调用。
3. 接口/内部方法的参数、顺序、读写对象、外部依赖、成功与失败响应。
4. 表、字段、类型、默认值、备注、索引、唯一约束、逻辑删除和查询方式；不落库逐项说明。
5. 事务、幂等、并发与失败处理；不涉及时说明依据。
6. 真实代码落点及“现有改造/直接复用/拟新增”。
7. 正常、边界、重复、并发、失败和兼容中的适用验证。

全局总览只能导航，不能承载模块缺失的唯一契约。主 Agent 逐模块人工复核；`python3 "${CODEX_HOME:-$HOME/.codex}/skills/feature-delivery/scripts/audit_plan.py" <plan绝对路径> --strict` 不能替代人工复核。

技术方案要让不打开代码的负责人独立读懂：每个入口使用完整路径/方法名和中文用途；表首次出现说明其业务事实、谁写谁读；字段说明业务含义、口径和读写位置；新增表/字段/索引/Redis key 就地关联到具体执行步骤。不得只用 A01/P03 等编号或“见上文”代替语义。

## 需求与技术方案阶段

1. 读取适用 `AGENTS.md`、真实路由、Controller/Handler、req/res、Service、DAO/Repository、Model、migration、配置和测试。
2. 明确目标、非目标、客户端、仓库、数据口径、兼容和发布范围，以及必须由用户决定的问题。
3. 先交付最小主业务闭环。每个新增接口、表、字段、任务、状态、索引、缓存键、锁、`request_id` 或补偿必须对应明确需求、真实缺口或已证实风险；已有 SQL/Redis/状态可满足时不得新增持久化结构。
4. 新表只在必须跨请求可靠恢复、审计或条件查询，且现有表、SQL 与 Redis 均不能满足时提出。幂等记录、重试、补偿和异步状态只在真实重试/回调或重复执行会导致不可接受副作用时设计。
5. 用户要求计划但未给路径且无可复用 plan 时，按 `AGENTS.md` 先确认位置。
6. 实际修改 plan 后运行 `python3 "${CODEX_HOME:-$HOME/.codex}/skills/feature-delivery/scripts/audit_plan.py" <plan绝对路径> --strict`；无 plan 时按相同门槛人工核对。仍有阻塞待确认项时继续完善。
7. 汇总改动量、数据设计、风险与取舍，等待技术方案确认；确认前不改业务代码。
