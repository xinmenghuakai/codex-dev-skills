# 正式 Review Gate 协议

仅用于 feature-delivery 正式 Review 任务包；通用范围、风险、遍次和复审要求仍以 [Review 主文件](../SKILL.md) 为准。直接 Review 不加载本文件。

feature-delivery Review 开始前固定 `baseline_id`、`review_phase`、`review_gate_scope`、`risk_level`、`required_passes` 和 `pass_ids`。`review_gate_scope` 只能是 `review_only/test_release/final_release`，必须使用任务包明确给出的值并原样回传，不得由 Reviewer 自行升级或改写；`baseline_id` 仅使用字母、数字和 `._:/@+-`，例如 `api@abc123+worktree`。`direct_review` 只记录本轮可读范围、主要风险与检查限制，不创建 Gate scope、固定 pass IDs 或发布 baseline。任务包未给风险等级时自行判定；风险只能按 `small -> normal -> high` 升级，禁止降级，高风险不得宣布或执行“两遍审查”。

### Gate 作用域提升

本节只兼容既有 `formal_gate_required=true` 的机械 scope promotion。发布前先按 [双向复用与发布检查](../../feature-delivery/references/review-and-release.md#双向复用与发布检查) 分流；成立则不调用本协议、不生成新的正式材料。test/master 双向复用业务审查，不把旧 Gate、report 或 binding 改写为新目标。

旧脚本仅支持测试发布开始前、同一目标和完全相同冻结输入的 `review_only -> test_release`：上一 Gate 必须为已校验 pass，baseline、phase、risk、完整 pass、scope contract、provenance、validation evidence、report 和快照内容一致，目标独有提交与 merge 不改变语义。保留原 report bytes 和其中旧 scope；新 test scope 由 CLI 及新 Gate evidence 表达，首次 test binding 仍须验证。

仅该兼容操作使用 `--scope-promotion true --previous-gate-evidence <旧证据> --snapshot-manifest <当前快照> --release-diff-kind same --reused-passes <原pass> --delta-reviewed false`。脚本重算快照和旧证据，任一不符则拒绝；不能靠改字段或关闭校验通过。兼容操作失败后回入口按事实判断复用或必要补审，不为满足旧提升协议无条件重做全部工作。

确需新正式 Gate 时使用 `scope_promotion=false`，按 feature-delivery 正式流程绑定当前完整输入；普通审查和已验证复用发布均不生成本节 report。`review_only` scope 仅兼容历史证据，不使普通审查自动进入 Gate。

## Review Gate

feature-delivery Review 的最终人类可读结论必须携带下述 `Review Gate`；没有 Gate、字段与风险等级不一致、pass 数量不足或 pass ID 不完整时，结论无效。它是给用户和主 Agent 阅读的 `key=value` 摘要，**不是**可冻结的 JSON reviewer report。`direct_review` 不使用本 Gate：

```text
Review Gate
baseline_id=<任务包固定的无空白标识>
review_phase=<initial|rereview>
review_gate_scope=<review_only|test_release|final_release>
risk_level=<small|normal|high>
required_passes=<1|2|5>
completed_passes=<none|逗号分隔的固定 pass ID>
ledger_closed=<true|false>
sql_check_required=<true|false>
sql_check=<completed|not_applicable|blocked>
dynamic_validation=<completed|limited|blocked|not_applicable>
plan_coverage_required=<true|false>
plan_manifest=<plan绝对路径|none>
plan_item_ids=<none|逗号分隔的稳定计划交付项 ID>
reviewed_plan_item_ids=<none|逗号分隔的已核验 ID>
satisfied_plan_item_ids=<none|逗号分隔的已有交付证据 ID>
not_applicable_plan_item_ids=<none|逗号分隔的已确认不适用 ID>
missing_plan_item_ids=<none|逗号分隔的缺失 ID>
blocked_plan_item_ids=<none|逗号分隔的阻塞 ID>
external_plan_item_ids=<none|逗号分隔的外部待交付 ID>
findings_total=<非负整数>
finding_ids=<none|逗号分隔的唯一 F001 格式 ID>
finding_plan_item_ids=<none|所有 finding 关联的异常计划项 ID 并集>
origin_counts=<initial,baseline,fix_introduced,newly_exposed,unknown 五个非负整数>
gate=<pass|findings|blocked>
release_ready=<true|false>
```

- `pass`：全部 pass 和台账关闭、计划项集合与任务包完全一致、`missing/blocked/external` 为空、finding 为 0、必要专项检查未阻塞，且 `release_ready=true`。
- `findings`：全部 pass 和台账关闭、一次性汇总全部 finding；`missing/blocked/external` 必须在 finding 中说明，且 `release_ready=false`。
- `blocked`：审查材料或关键验证不足，无法完成全部适用遍次；`completed_passes` 只能是规定 pass 的有序前缀，不输出部分 finding，且 `release_ready=false`。交付项本身待外部处理但审查已完整时使用 `findings`，不能借此隐藏已确认问题。

当且仅当 feature-delivery Review 的 `gate=pass` 或 `gate=findings`（全部遍次已经完成）时，Reviewer 还必须在**所有人类可读内容之后**回传一份唯一、机器可提取的 schema v1 reviewer report。`direct_review` 禁止生成该 report。格式固定如下，开始/结束标记各只能出现一次，二者之间只能有一份原始 JSON，不加 Markdown fence、标题、解释或前后缀：

```text
<!-- feature-delivery-review-report-v1:start -->
{"schema_version":1,"reviewed_release_fingerprint":"...","selected_reviewer":"...","selected_model":"...","implementation_model_families":["..."],"review_independence":"...","gate":{},"validation_evidence_paths":[]}
<!-- feature-delivery-review-report-v1:end -->
```

顶层字段固定且只允许为 `schema_version=1`、`reviewed_release_fingerprint`、`selected_reviewer`、`selected_model`、`implementation_model_families`、`review_independence`、`gate` 和 `validation_evidence_paths`。`gate` 必须精确镜像本次 Gate 的 `baseline_id,risk_level,review_phase,review_gate_scope,required_passes,completed_passes,ledger_closed,plan_coverage_required,plan_manifest,plan_item_ids,reported_plan_item_ids,reviewed_plan_item_ids,satisfied_plan_item_ids,not_applicable_plan_item_ids,missing_plan_item_ids,blocked_plan_item_ids,external_plan_item_ids,sql_check_required,sql_check,dynamic_validation,findings,finding_ids,reported_finding_ids,finding_plan_item_ids,reported_finding_plan_item_ids,origins,gate,release_ready`；其中 origins 的键固定为 `initial,baseline,fix_introduced,newly_exposed,unknown`。`validation_evidence_paths` 可为空，非空项必须是发布仓库外、已冻结的 `role=validation_evidence` artifact。report 的 `reviewed_release_fingerprint` 必须等于主 Agent 已提供基础快照 stdout 的 `review_input_sha256` hex。Reviewer 只返回自己实际审出的 JSON 内容，不得声称已写入仓外文件；主 Agent 只能提取标记间原始 bytes、保存、冻结和交给 Gate，不能代填、格式化或改写其结论。`gate=blocked` 不得输出这对标记或伪造 report。

## 输出

feature-delivery Review 先输出人类可读 `Review Gate`，再输出紧凑的计划覆盖表（ID、状态、文件/提交/测试/交付证据），其 ID 必须与 Gate、plan 清单和任务包一致；随后按 P0（严重事故/广泛破坏）、P1（正常路径严重错误）、P2（真实边界缺陷）、P3（低概率但有证据）排序。每个 finding 以 Gate 中对应的 `[F001]` 唯一 ID 开头，标记 `plan_item_ids=<none|逗号分隔 ID>`，并包含标题、精确文件行号、触发场景、错误影响、来源和最小修复方向；所有 finding 的计划项并集必须完整覆盖 `missing/blocked/external`。没有问题时写 `finding_ids=none`、`finding_plan_item_ids=none`，说明未发现需要报告的问题并列出未覆盖验证。`pass/findings` 的全部人类内容结束后，再输出上述唯一机器 JSON 区块；`blocked` 只输出人类 Gate 和阻塞说明。`direct_review` 直接按同一严重性格式输出 findings、已完成遍次、验证与限制，不输出 Gate、计划覆盖表或机器 report。Gate 只能约束 feature-delivery 审查协议和报告自洽，不能声称数学上证明不存在尚未发现的问题。

审查默认只读；仅在用户明确要求修复，或 `feature-delivery` 已授权返回实现阶段时修改代码。
