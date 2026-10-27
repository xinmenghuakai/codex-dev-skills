# Review、接口交付与发布

SKILL.md“轻量方案维护”允许主 Agent 直接维护既有 plan。本文 Planner/Architect 的 plan 来源要求包含该例外：实际主写入者可提交 `selected_agent=main_agent` 的 `scope_contract` 来源，且只覆盖冻结的 `plan_manifest`；不得用于实现文件或辅助产物，不参与 Reviewer 路由，不豁免正式快照、覆盖与发布校验。

准备 Review、复审、接口交付、Git 发布或判断完整交付时读取本文件。

## 轻量修复边界

本文件的正式 artifact、Gate、结构化 report 和 release binding 只适用于 `whole|modular`。`targeted_fix/simple_fix` 不进入这些步骤：它们只做短范围锁定、一次必要验证和短 diff 核对；稳定传输契约下也不自动调用 `api-handoff`。若要 Git 发布，取得用户对准确目标的授权后直接按 `git-pr` 完成正常 Git 检查、tag（适用时）与远端读回。

`simple_fix` 可调整已有非敏感运行参数，但新增密钥、地址、依赖、协议字段、重试/并发策略或数据副作用时必须升级。轻量修复的代码、测试、配置、依赖和验证命令未变化时复用既有验证结果，不重复业务测试或 Review。目标分支前进时，先检查目标文件、直接依赖和 `go.mod/go.sum` 是否重叠；无重叠只重做 Git 集成检查，有重叠或合并语义变化才重新验证并升级适用审查。

## 正式 Gate 适用范围

先按下节核对 `review_reuse_verified`，再声明 `formal_gate_required`。`whole/modular` 已有完整有效审查且复用核验通过时，使用 `review_reuse_verified=true`、`formal_gate_required=false`，可支持已授权的 test 或 master 发布，风险等级保持原值。不能复用时，最终发布及高风险测试发布为 true；普通审查、普通风险测试发布和轻量修复为 false。此分流优先于引用文件或 Agent 中默认要求新 Gate 的表述。

false 时保持完整范围、计划覆盖、必要验证及发布前置项；首次审查仍由独立 Reviewer 按风险完成。复用成功则由主 Agent 做目标集成检查，不再派 Reviewer，不生成 provenance、no-plan 文件、snapshot、机器 report 或 binding。无复用依据的普通审查只支持相应审查或普通测试目标，不因此获得 master/tag 准入。未关闭的阻塞问题不能发布。

以下正式任务包和 Gate 协议只在 true 时适用；接口交付、migration、部署及授权按真实变动和目标核对。复用历史材料不等于旧 Gate 已绑定当前目标，不改旧 scope、指纹或结论来伪造新 Gate。

## 双向复用与发布检查

`test → master`、`master → test` 及同一代码再次发布适用同一规则。方向表示同份已审业务改动的传播，仍按用户明确的源分支合并，不把 test 独有提交一并带入 master。主 Agent 先核对：

1. 已有真实独立审查及可复核代码基线，覆盖当前完整需求、范围和相应风险维度；findings 已关闭、必要验证有效。普通审查记录和正式报告均可作为依据，不能只凭 tag、发布成功或“审过了”判定。
2. 逐仓映射已审 commit/tree 或未提交内容摘要到当前完整发布 diff，包含测试、配置、依赖、接口、migration 和相关调用链；目标独有提交及实际合并结果已核对，没有未覆盖的语义变化。提交 SHA、分支名、文件名相同都不能代替内容及集成检查。
3. 当前目标的环境差异、生产专有分支和外部依赖不会引入未审的权限、数据、失败或副作用语义。仅目标 ref、合并 SHA、环境构建产物或事实性验收记录变化，不使已证明有效的业务审查失效；同源码也不能自动证明运行语义相同。

全部成立才记 `review_reuse_verified=true`。高风险代码未变且相关语义已核验时同样复用，不能仅因继承高风险功能再造一套 Gate。当前回传或已有发布记录只补原审查引用、已审基线、当前源/目标提交、合并结果及差异/验证结论；原报告、来源和验证日志保留引用，不复制重写，也不为更换 scope 临时编写证据生成脚本或启动交接角色。

使用既有 Git 命令核对目标、冲突、暂存范围和远端读回；推送前若目标或候选继续变化，重查受影响的集成与验证，不能沿用过期核对。构建按当前目标环境执行：同输入同环境结果复用，测试包与生产包不能互用；环境构建和资源引用检查通过即可，不因产物哈希变化重审未变业务代码。

缺少覆盖或出现普通有界变化时，只补独立审查受影响范围及必要验证，再把增量结论与旧结论一起核验；高风险关键语义变化、重要冲突或影响面不明时完整复审。新发现的阻塞项不得以复用跳过。授权、冲突处理确认、生产 migration/配置前置项和部署边界继续按当前目标核对。首次完整审查与无法复用时的正式 Gate 仍走下文协议。

## 同批上线与跨窗口合版

提前明确同批上线、无需各自先行发布时，各窗口完成实现和安全定向验证后，回传“实现及验证完成，待合版审查”。由发起合版的主会话汇总完整候选、准确目标和已有验证，安排一次完整独立 Review，覆盖全部改动及合并交互；仍按最终风险覆盖规定维度。本规则优先于按窗口或模块实现结束就分别安排完整 Review 的默认时机。用户明确要求提前单独审查或独立发布时，按其范围执行。

若各窗口已审过后才决定合版，按 [审查事实复用](../../review/SKILL.md#审查事实复用) 汇总各自可核验基线、原始审查结论和有效验证，由一个独立 Reviewer 核对并补审新增改动、未覆盖范围与交叉影响。跨窗口本身不触发全量重审；缺少证据或风险变化按该规则处理。优先只读获取已有会话回传、证据路径和 Git 事实，就地汇总，不为普通合版新增交接角色或证据文件。

完整审查通过后，发布前执行候选/目标漂移、Git 和适用的正式 Gate/binding 校验；有效结果沿用。后续修复或候选变化仍按下节决定补审或完整复审，“一次”不限制必要纠错。仅声明同批发布不改变尚未知情窗口的执行状态；未确认其他窗口已采用该安排时，不声称其已暂停或取消审查。

## 审查与发布衔接

首轮按 [review 的审查事实复用规则](../../review/SKILL.md#审查事实复用) 留下可核对基线，单一审查来源优先复用原独立 Reviewer，多来源合版由一个独立 Reviewer 汇总。正式发布时先确认完整候选和准确目标，比较首轮基线；未变内容继承分析，普通且有界的变化补审受影响调用链和最终集成，高风险变化或无法界定影响面则完整复审。所有当前计划项和规定维度仍须覆盖。

发布范围已明确且候选稳定时，首轮可直接准备 `final_release` 审查，避免先做一轮普通审查再立即重启正式审查。最终接口材料、验证和适用构建先就绪，再冻结报告输入；待这些前置项完成前不提前启动发布 Agent 占用名额。候选中途变化时先重判复用，仅失效受影响的检查和构建结果；仍需正式 Gate 时才更新快照与 binding。

仅未走上述复用发布分流且 `formal_gate_required=true` 时，由实际 Reviewer 对当前完整冻结输入给出新 report，使用当前 `reviewed_release_fingerprint` 和 scope。既有 Gate 脚本照常校验；这不属于旧 report 的 scope promotion，使用 `--scope-promotion false --previous-gate-evidence none --release-diff-kind not_applicable --reused-passes none --delta-reviewed false`。这些 CLI 字段只控制旧报告的机械提升，不表示人类审查未复用事实。不得伪报已经重新审读的遍次，也不能靠更换指纹替代本轮核验。

验证日志在执行时保存命令、退出码和关键结果，原执行者就地记录；只需补事实或摘要时由主 Agent 核对原始结果后维护，不为抄录日志派 Test Specialist/Verifier。保持原始日志不变，缺失时如实说明，不能为补日志重跑未失效的测试。

## 正式 Gate 的 Vue 候选准备

仅在项目要求提交构建产物且本次 `formal_gate_required=true` 时，主 Agent 在 Reviewer/快照/binding 之前准备候选：先完成准确目标分支同步，再在开发分支或隔离的候选 worktree 上按目标环境的真实构建命令生成产物，将源码与产物共同纳入待审 diff。构建记录包含命令、环境、目标 ref/SHA、输入与产物范围；先完成已安排的安全定向测试，再构建，避免已知失败后重复打包。产物路径与哈希可由构建执行者批量枚举回传；Reviewer 核对真实源码、构建输入输出清单及资源引用，不把每个压缩 chunk 当成独立业务模块重复分析。仍冻结全部产物及实际构建来源，不假装执行了真实部署。

冻结候选必须已包含最新目标分支；Review 审查源码、构建配置/记录和产物范围，binding 绑定最终 candidate/merge tree。发布任务包声明 `reviewed_build_candidate=true` 并携带已冻结构建证据；Releaser 先核对候选、目标、构建输入和环境仍与该证据一致，再合并已审候选并复用构建结果，不在目标分支再创建产物提交。项目构建必须依赖目标分支名称等条件、无法在候选环境重现时，发布前报告具体限制并制定受控方案，不先推送再补审。

目标/候选/构建输入漂移或产物需重建时，在远端写入前返回主 Agent 重新准备候选及 Review/binding；不放宽 tree/父链校验。`formal_gate_required=false` 或项目不提交产物时，沿用 git-pr 既有构建规则。此流程不额外授权提交、推送或部署。

人工/主会话/其他既有实现的来源按 [接手既有实现的来源](plan-and-task-packages.md#接手既有实现的来源) 使用 schema v3，固定角色 v2 保持兼容；本文件后续“schema v2 provenance”同时接受这一 v3 扩展。未知模型独立性使用 `source_unknown`，不能冒认来源。

## Review 任务包与风险

任务包必须包含 `baseline_id`、`review_phase=initial|rereview`、`review_gate_scope=review_only|test_release|final_release`、`risk_level`、`required_passes`、固定 `pass_ids`、`sql_check_required=true|false`、`plan_coverage_required`、`expected_plan_manifest`、适用的 `expected_plan_item_ids`、`task_difficulty`、`selected_agent`、`selected_model`、`selection_evidence`、发布仓库外的 schema v2 `implementation-provenance.json` 绝对路径（作为 schema v4 `role=implementation_provenance` artifact），以及由 `"${CODEX_HOME:-$HOME/.codex}/skills/feature-delivery/scripts/implementation_provenance.py" --risk-level <small|normal|high>` 根据当前 `risk_level` 和已校验实现来源导出的路由 JSON。该命令 stdout 必须是**单个原始 JSON object**，例如 `{"implementation_model_families":["terra"],"review_independence":"independent","selected_reviewer":"feature_delivery_sol_reviewer"}`；主 Agent 只可解析该对象并映射：families 为空数组时给 Gate 的 `--implementation-model-families none`，否则按数组既有顺序以逗号连接；`selected_reviewer` 映射到 `--selected-reviewer`，`review_independence` 映射到 `--review-independence`。不得把 stdout 改写、要求 Reviewer 重述，或把 `implementation_model_families=...` 一类 `key=value` 伪装成脚本原始输出。`entry_type=scope_contract` 只保留仓内 plan 的实际修改来源审计，不参与 Reviewer 路由。主 Agent 先按真实范围确定风险，再使用脚本结果；不得自行汇总 family 或覆盖脚本选出的 Reviewer；“Review Gate 未经主 Agent 校验前禁止修复和发布”。

主 Agent 根据目标分支 merge-base 到当前工作区的完整发布 diff 判定风险。`whole/modular` 的普通风险使用 `normal/2`，高风险使用 `high/5`；`small/1` 只属于直接 `review` 的轻量审查，不作为 feature-delivery 的正式 Gate。

风险按真实状态和失败语义分级，不按关键词分级。同步串行、无队列/回调/重试/跨实例状态、不改持久数据或失败策略、只补外部协议排序元数据的消息顺序修复使用 `normal/2`。安全定向测试应覆盖请求体、顺序边界、零值/溢出和适用的部分失败；测试证据不足形成 finding 或验证阻塞，不自动升级风险。涉及持久状态竞争、幂等补偿、重复/丢失的不可接受副作用、资金权益或不可逆影响时才使用 `high/5`。正式风险只能 `normal -> high`。

## Review Gate

1. 主 Agent 先以 `python3 "${CODEX_HOME:-$HOME/.codex}/skills/feature-delivery/scripts/freeze_snapshot.py" --repo-target <绝对仓库>=<目标分支ref> --artifact <role>=<绝对路径> --output <发布仓库外绝对路径>` 创建 schema v4 基础快照。目标必须是可解析的分支/ref，不能传 `HEAD` 或裸 commit；脚本自行冻结 `target_ref,target_revision,candidate_ref,candidate_revision,base_revision=merge-base` 与当前工作树 diff。所有 artifact 都用 `--artifact <role>=<绝对路径>`，必须包含 `implementation_provenance`、一项 `plan_manifest|no_plan_contract` 和适用的 `validation_evidence|auxiliary`。`implementation_provenance`、`no_plan_contract`、`review_report` 和 `validation_evidence` 一律位于所有发布仓库外；`plan_manifest` 与 `auxiliary` 可在仓内或仓外。再执行 `python3 "${CODEX_HOME:-$HOME/.codex}/skills/feature-delivery/scripts/implementation_provenance.py" --risk-level <small|normal|high> --snapshot-manifest <绝对路径> --implementation-provenance <绝对路径> --scope-contract-artifact <plan 或 no-plan 的绝对路径，可重复> --expected-plan-item-ids <完整 ID 或 none>`，解析其原始 JSON 输出并按上节映射 Gate 参数；`--scope-contract-artifact` 只能是 role 为 `plan_manifest|no_plan_contract` 的 artifact，绝不接受 migration/API auxiliary。脚本按显式 `--risk-level` 选择 Reviewer，只有 `entry_type=implementation` 参与家族和独立性计算，scope_contract 条目只校验 plan 来源。风险升级后按新等级重新生成路由，Gate 将用报告与 CLI 中的实际风险交叉校验。输出哪个 Reviewer 就使用其 Agent TOML 的模型和档位。使用 `review` 审查完整改动；涉及查询、DDL、索引或 migration 时由已选 Reviewer 在同一阶段合并 `sql-check`，不得重新路由。
2. 基础快照 stdout 的 `review_input_sha256=<hex>` 是 report 顶层 `reviewed_release_fingerprint` 必须原样绑定的 review-input 指纹，不是快照中的 JSON 字段。完成全部适用遍次后，Reviewer 在回复中只输出一个由 `<!-- feature-delivery-review-report-v1:start -->` 与 `<!-- feature-delivery-review-report-v1:end -->` 包围的 JSON 区块；两个标记之间只能是一份 schema v1 JSON，且该 JSON 不能与人类可读 `Review Gate` 混排。主 Agent 只保存标记之间的原始 JSON bytes 到仓外 report 文件，不得代填、格式化、补字段或拼接人类输出。
3. `pass` 与 `findings` 都是“完整审查结论”：二者都必须有上述基础快照、provenance、scope contract、结构化 report 和第二份含 `role=review_report` 的快照。主 Agent 必须用完全相同的 release diff、contract、provenance 和验证材料重新运行 `python3 "${CODEX_HOME:-$HOME/.codex}/skills/feature-delivery/scripts/freeze_snapshot.py"`，并加入 `--artifact review_report=<报告绝对路径>`；report 本身被 review-input 指纹排除，因此第二份快照的 `review_input_sha256` 必须与基础快照相同。随后按 `review_gate.py --help` 对含 report 的第二份快照传入任务包预期与 report/Gate 实际值；scope 使用 `--expected-review-gate-scope` 和 `--review-gate-scope`。计划项分别传 `--expected-plan-item-ids`、`--gate-plan-item-ids`、`--reported-plan-item-ids`；finding 分别传 `--gate-finding-ids`、`--reported-finding-ids`，异常计划项分别传 `--gate-finding-plan-item-ids`、`--reported-finding-plan-item-ids`，并要求 report 嵌套 gate 原样签回三项 reported 集合。`gate=pass` 只能写 `--write-gate-evidence <发布仓库外新路径>`，且 `--write-review-evidence none`。`gate=findings` 必须传 `--write-gate-evidence none` 与 `--write-review-evidence <发布仓库外新路径>`；后者只会生成 `schema_version=1,evidence_kind=review_findings` 的不可复用审查证据，不能 scope 提升、复用为 pass 或启动接口交付/发布。
4. `blocked` 表示未完成全部适用遍次或关键材料/验证不能闭合：不得生成结构化 reviewer report，不得传 snapshot/provenance/scope contract/review report/release binding，且 `--write-gate-evidence none`、`--write-review-evidence none`；只如实列出已经完成的遍次、缺失材料和下一步。Reviewer 可升级风险，禁止降级。非 finding 的 Gate 错误按错误指纹向同一 Reviewer 最多补发一次；同指纹再次出现时以 `blocked` 收敛，不启动新 Reviewer。
5. Gate 为 `findings` 时，完成全部遍次后一次性返回实现阶段成批修复；不得边审边修。修复后先验证旧 finding，更新 baseline 并按上节优先由原独立 Reviewer 续审。`normal` 的有界变化复用未变事实；高风险内容变化或影响面不明时重做完整 2/5 遍。只有 `gate=pass` 且 `release_ready=true` 才能进入接口交付或发布。

   信任边界：Gate 只能校验冻结快照、report 与 provenance 的内容和一致性，不能证明本地 report 实际由独立 Reviewer 任务产出；不得把本地 report 当作平台级身份凭证。若运行平台未来提供可验证的签名 task receipt，Gate 应额外校验该 receipt 与审查任务、模型和 review-input 指纹的绑定；当前流程不假设、伪造或声称已支持 receipt。

   本机文件系统边界：Gate 的 fd/identity 校验用于防范普通路径软链或替换，但若同 UID 的恶意本机进程能在最终检查后任意 rename 输出目录或 release repo，纯用户态 CLI 无法原子证明文件仍在最终位置；不得将当前流程夸大为完全抵御本机攻击。生产级隔离需要受控、不可改的 evidence root 和操作系统权限边界。

6. 每个完整结论（`pass/findings`）都必须先冻结完整发布范围，并按 schema v4 角色冻结文件：有 plan 时为 `role=plan_manifest`；无 plan 时把已要求的内联契约落为发布仓库外、文件名严格为 `no-plan-contract.md` 的文件，必须包含 `# 无 plan 契约`、`## 目标`、`## 非目标`、`## 发布范围`、`## 验证`、`## 授权边界`，并标为 `role=no_plan_contract`；provenance 为仓库外的 `role=implementation_provenance`；审查 report 为仓库外的 `role=review_report`；验证材料为仓库外的 `role=validation_evidence`；接口、migration 或其他补充材料为 `role=auxiliary`。只有 plan/no-plan 可传给 `--scope-contract-artifact`，migration/API 文件绝不能充当 scope contract。`implementation-provenance.json`、snapshot、no-plan contract、review report、validation evidence、release binding 与 Gate/review evidence 都必须放在每个发布仓库外的会话证据目录；`plan_manifest` 与 `auxiliary` 可在仓内或仓外，但 plan 进入 release diff 时必须有实际 Planner/Architect 回传的一条或多条 `entry_type=scope_contract` contributor 来源。`review_only` 的 `pass` 在 Gate 中传 `--release-binding none`；`test_release/final_release` 的 `pass` 必须先运行 `python3 "${CODEX_HOME:-$HOME/.codex}/skills/feature-delivery/scripts/freeze_snapshot.py" --bind-release-snapshot <含report快照绝对路径> --output <发布仓库外新release-binding.json>`，再把该绝对路径传为 `--release-binding`。binding 会确认当前 target ref、HEAD、工作树和 index tree 仍匹配审查快照，并冻结 candidate tree 与目标分支合并后的 merge tree。Gate 会重算 Git diff、未跟踪文件和全部 artifact，并校验 provenance 覆盖完整发布文件；缺少适用 binding 或其验证失败均不能得到可发布 pass。

   binding 不规定“必须先提交”或“必须后提交”的单一时机：已提交且已审的 source branch 可以直接合并；仍在已审工作树中的内容也可先完整暂存、建立 binding，再在同一 source branch 创建**唯一一个** tree 与冻结 candidate tree 完全相同的提交后合并。两种路径都只允许冻结候选本身或其这一个直接子提交；binding 后混入第二个改动/提交、squash/rebase 或任何 tree 变化都会使后验校验失败。

   旧 Gate 的机械 scope promotion 仅兼容同输入、同测试目标的 `review_only -> test_release`，保留原 report bytes；严格条件见 [正式 Gate 协议](../../review/references/formal-gate.md#gate-作用域提升)。test/master 双向复用先走上文发布分流，不调用该提升命令，不要求把旧 report 改成新 scope。确需新正式 Gate 时使用 `--scope-promotion false`，绑定当前输入；Gate/review evidence 不得覆盖旧证据或冻结 artifact。

7. `dynamic_validation=completed` 只要求本次 scope 内必要、已授权且安全的验证全部完成。明确安排在测试部署后的真实环境人工验收，或本次不交付的平台生成工具，可作为非阻塞限制记录；scope 内必要验证缺失时才使用 `limited/blocked`，且不得与 `release_ready=true` 并存。

正式 Gate 路径中，Review 进行中、Gate 无效/为 `findings/blocked`，或修复后尚无新 pass Gate 时，禁止暂存、提交、推送、合并、打 tag 或启动 Releaser；已验证复用路径按入口的当前检查结论判断，历史 binding 失效本身不触发上述阻塞。

## 接口交付条件

发布任务包必须声明 `api_handoff_required=true|false`。接口契约和交付要求未变且已有材料可核验时，沿用原交付证据，不因 test/master 换目标重做 API 文档、来源清单或发布 checklist；只更新确有变化的目标环境事项及状态。

- 有前端或客户端可感知的接口新增、修改或删除时必须为 true，并按 `api-handoff` 的执行方式选择：符合小批 Markdown 连续交付条件时由当前主 Agent 先冻结契约再生成、核验；其余情况先委派 `api_handoff_agent` 冻结事实，再由 `api_handoff_executor` 生成、校验和执行已授权同步。实际执行者如实记录，模型和档位读取中央路由与对应 Agent TOML。
- 为 true 时，发布任务包还必须有 `api_handoff_completed=true` 和非空 `api_handoff_evidence_paths`。每个路径必须是绝对路径，正式 Gate 路径还需在相关快照中以 `role=auxiliary` 冻结，并能证明本次接口产物生成/校验/授权同步或明确未同步原因；`auxiliary` 可在仓内或仓外，但仅写“已同步 YApi”不构成证据。
- 为 false 时必须携带非空 `api_handoff_not_applicable_reason`，并由主 Agent 根据真实路由、req/res 与接口 diff 核验；仅写“内部改造”不够。
- true 时的交付模式只由冻结 API contract 决定：项目未明确启用且可核验 YApi 时默认只生成 Markdown；只有 `delivery_mode=yapi` 才生成 YApi JSON；Swagger/ApiPost 与独立前端变更表分别需要用户明确请求。写 YApi 需 `yapi_write_authorized`；ApiPost 新增/修改/删除需 `apipost_write_authorized`。测试库只读、uid 模拟认证、单次认证/业务请求分别需要本次独立授权，任何授权不隐含另一项。

## 发布

1. 仅 `formal_gate_required=true` 时要求 `review_gate_validated=true`、`review_gate_scope_validated=true`、`gate=pass`、`release_ready=true`，覆盖台账 `missing/blocked/external=none`，且接口交付条件满足时才组装发布任务包。发布任务包中的 scope 必须来自该次脚本校验成功的 Reviewer Gate，不得另行改写；`test_release` 只允许已授权的 push/test 和适用测试部署，正式发布需 `final_release`。确需委派时，发布包携带 `task_difficulty`、`selected_agent`、`selected_model`、`selection_evidence`，仅正式 Gate 路径附适用 binding 和校验结果；主 Agent 连续执行不创建自我交接包。
2. 仅正式 Gate 路径整理已有“验证冻结快照”：完整发布文件及摘要、Gate baseline/结果、release binding、测试/构建命令与结果。发布前内容完全一致且验证未中断时复用结果，不重复 Review、业务单测或构建；仍执行 `git diff --check`、暂存区/分支/远端检查和发布预检。`targeted_fix/simple_fix` 没有 Gate 快照，直接复用实现阶段准确记录的验证命令与结果。
3. 正式 Gate 的目标、候选或冻结输入漂移时，旧 binding 不再证明当前目标；先按“双向复用与发布检查”判断哪些结论有效。只重验受影响项，不能把绑定变化直接等同于全量重审或材料重建。必要验证失败、环境不明或新阻塞项未关闭时停止发布。
4. 单仓普通 Git 发布，以及同一功能、契约不变且无非代码上线依赖的普通前后端两仓发布，默认由主 Agent 连续完成 `git-pr`；两仓正式发布仍遵循 `release` 的顺序和每仓校验。需要并行处理其他工作或用户要求委派时，才把已准备就绪的发布任务交给 Releaser。超过两仓，或涉及 migration、cron、生产配置、跨服务协议与上线顺序时，在 `final_release` 使用 Release Coordinator 编排。执行者变化不豁免当前分流要求的检查、授权或远端读回。`test_release` 不调用 `release` 或 Release Coordinator，多仓测试由主 Agent 按仓执行或委派 `git-pr test`，测试部署单独授权。
5. migration 或 `.sql` 在 master 前必须有用户/DBA 提供的 `executed_confirmed` 或 `effect_verified` 人工执行/核验回执；Codex 不连接、不探测、不查询生产数据库；后者不能表述为证明了历史 SQL 文本/顺序。
6. 当前发布关口必须有 `push`、`test`、`master`、`merge <branch>` 或 `from <branch>` 的明确授权；会话中已有明确执行授权且目标与范围未变时直接沿用，不重复询问。计划阶段仅列出的目标不是发布授权，SSH 等逐次授权仍遵守适用 AGENTS.md。
7. 只暂存本需求文件。正式 Gate 路径要求：有正式 release binding 时，在本地目标合并完成、tag/push 之前运行 `python3 "${CODEX_HOME:-$HOME/.codex}/skills/feature-delivery/scripts/freeze_snapshot.py" --verify-release-binding <release-binding绝对路径> --release-commit <绝对仓库>=HEAD --per-repository --before-push`；该检查只证明本地合并 tree/父链匹配，允许远端跟踪 ref 仍是冻结旧目标，不能报告远端已发布。先 fetch 核对准确远端目标未漂移，校验失败不得推送。推送后 fetch/读回目标 ref，再去掉 `--before-push` 用准确发布 commit 运行同一校验，本仓两步均通过且远端 tag/分支一致才报告该仓完成；在开发分支回同步前完成后验。`--per-repository` 只证明本仓，主 Agent 必须汇总 binding 中全部仓库的前后校验及远端读回，不能用一仓结果报告整个发布完成。校验只接受冻结候选的 fast-forward 或标准 two-parent merge，squash/rebase、额外提交、错误 tree 均失败。Vue 先走“正式 Gate 的 Vue 候选准备”；需要重建产物时在远端写入前退回主 Agent 重新准备。Releaser 不解决合并冲突。
8. 仅正式 Gate 路径的无 plan 发布包必须显式携带 `无 plan`、`plan_coverage_required=false`、`expected_plan_manifest=none`、`plan_manifest=none`、`expected_plan_item_ids=none`、发布仓库外的 `--no-plan-contract <绝对路径>`，以及内联发布范围、执行顺序、非代码事项和完整 Gate 校验命令/成功结果；不得依赖上轮上下文暗示，也不得要求为 `whole` 发布临时创建 plan。

## 完成条件

先按 SKILL.md“需求完整性”确认用户当前有效需求未被 plan/任务包缩减；全部有效计划项（或无 plan 时的内联契约）有证据且无 `missing/blocked/external`；授权范围验证和 Review 完成；按入口分流，复用发布须有有效审查引用和当前目标检查结论；需正式 Gate 时必须有本次目标对应的 `gate=pass`、`release_ready=true`，正式发布 scope 为 `final_release`；严重问题关闭；`api_handoff_required=true` 时 `api_handoff_completed=true` 且交付证据有效（仅正式 Gate 路径要求冻结），为 false 时不适用依据已被真实接口 diff 证实；用户授权的发布目标完成，并报告仓库/分支/commit/tag/人工事项，才能说完整交付完成。

阶段 Agent 按“结论、文件/证据位置、命令与结果、风险/阻塞、需要主 Agent 的下一动作”回传；Reviewer 仅在 `formal_gate_required=true` 时额外输出固定 Review Gate；普通审查不增加 Gate 或机器报告。
