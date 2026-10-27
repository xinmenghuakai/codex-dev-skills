# 平台交付与同步

仅用于已启用的 YApi 模式或明确请求的 ApiPost；事实提取、冻结契约、交付目录和脱敏要求先遵守 [API Handoff 主文件](../SKILL.md)。文中的 `<skill-dir>` 始终指 api-handoff 根目录。

## YApi JSON

仅在项目明确配置并启用 YApi 时执行。项目配置必须能确认目标项目标识、同步方式和凭据环境变量名；真实凭据不得进入生成物或对话。

写入 `<交付物根>/yapi/<版本或任务标识>/yapi_<主题>_<版本>_<端>.json`；项目另有明确命名规范时沿用项目规范。根节点是分类数组，每个分类包含 `name`、`desc`、`list`；接口至少包含：

- `title`、`path`、`method`、`status: "undone"`、`markdown`、`desc`；
- GET 或无 body 请求的 `req_query`（允许空数组，每项含 `name`、`desc`、`required: "0|1"`、`example`）；
- form 请求的 `req_headers`、`req_body_type: "form"`、`req_body_is_json_schema: false`、`req_body_form`（每项含 `name`、`type`、`desc`、`required: "0|1"`、`example`），或 JSON 请求对应的 `req_body_type: "json"` 与 `req_body_other`；
- 按真实 Controller 响应写 `res_body_type`：JSON/JSONC 使用 `"json"`，外部协议明确要求纯文本等原始响应时使用 `"raw"`；两者均写 `res_body_is_json_schema: false` 和字符串形式的 `res_body`。

分类说明写清该分类从真实代码确认的响应外层、公共参数和加密后逻辑结构，不得强套 `{code,msg,data}`；第三方回调按对方协议和 Controller 的真实应答生成。method 使用大写、path 以 `/` 开头；`req_body_other` 和 JSON `res_body` 使用 YApi 接受的 JSON/JSONC 字符串，raw `res_body` 使用非空原始字符串。字段顺序与 Go 一致且每个字段带来源明确的注释；敏感字段示例只能使用变量模板，其他示例才贴近真实类型。

生成后依次运行：

```bash
python3 -m json.tool <file>
python3 <skill-dir>/scripts/validate_yapi.py <file>
```

校验失败或仍有待补、待确认、TODO、TBD、FIXME 等占位事实时不得交付。修改存量 JSON 只动本次接口，保留其他条目。

## 本机 ApiPost 同步

仅在用户明确要求 ApiPost 时处理。YApi 模式按“YApi 已确认事实 → 稳定 ID 映射 → ApiPost 更新”的状态机交付；Markdown 模式可以从冻结契约生成脱敏 Swagger 2.0 JSON，但当前稳定映射依赖 YApi 项目与接口 ID，因此默认只交付文件和手工导入说明，不自动写入 ApiPost。只有项目另行配置了可核验的非 YApi 稳定映射方案时，才允许自动同步。

ApiPost 文件写入 `<交付物根>/apipost/<版本或任务标识>/`；生成文件不等于已经导入 ApiPost。仅在当前本机 ApiPost 版本已通过其 UI/API/MCP 或成功的非敏感本机样例确认支持 Swagger 2.0 时，才能称该文件“可导入”；否则交付格式核验步骤，明确不宣称可导入或已同步。以下自动同步状态机仅适用于已配置的 YApi 模式：

1. 将以下授权分别记录在本次任务中：`yapi_write_authorized`（仅 YApi 模式，新增/修改接口写入或更新 YApi）、`apipost_write_authorized`（创建/更新/禁用本机 ApiPost 项目、目录、接口及映射）、`test_db_read_authorized`（只读测试库）、`simulate_login_credential_authorized`（将真实 uid 写入本机私有环境）和 `single_request_authorized`（执行一个指定请求，认证请求也单独适用）。任一授权均不隐含另一项；默认只生成脱敏文件、禁用请求和手工步骤。高权限 `debug_key` 只保留变量名，由用户自行在已确认的本机私有环境填写；Agent 不得读取、复制、输出或写入该值。
2. 从已圈定接口所属的源码仓确定仓库身份，不从当前 CWD 或 linked worktree 目录名推导。`repo_key` 只使用规范化 `origin` 的稳定 `host/path`：移除凭据与 `.git` 后缀，并将等价的 SSH/HTTPS 写法归一；Git common-dir 仅用于确认当前 checkout 与取得本机锁，不得参与项目身份。没有可确认远端时停止并请用户确认。
3. 将映射保存在仅本机使用的 `~/.codex/apipost-project-map.json`，固定使用 `schema_version: 2`。结构必须以 `repositories[repo_key]` 为根：仓库记录保存已确认的展示名、`apipost_project{id,name,scope}` 和 `pending_operations`；其 `clients[client_scope]` 保存 `yapi{project_id,address,confirmed_at}`、分类和接口映射。分类键为 `<yapi_project_id>:<category_id>`，记录 `parent_category_id`、`ancestor_category_ids`、`apipost_folder_id`、`parent_apipost_folder_id`、`full_path` 与读回 revision；接口键为 `<yapi_project_id>:<interface_id>`，记录 `apipost_interface_id`、分类键、method、normalized_path、disabled 与读回 revision。映射不得保存密钥、uid 或测试业务数据。
4. 映射缺失时，只能把源码仓的已确认展示名作为待确认 ApiPost 项目名，取得 `apipost_write_authorized` 和用户确认后才创建或绑定；仅同名项目、团队空间、云端空间或归属不明项目一律不能自动复用。每次写入前按 `repo_key` 取得排他锁、重读映射，并通过 API/MCP/GUI 实时确认目标项目仍为当前用户可见的本机私有、非团队、非云同步空间；映射中的 `scope=local_only` 只是缓存。`schema_version` 缺失、不支持或字段不完整时，不得当作新项目/目录/接口创建：必须先实时核验旧目标、取得用户确认，再原子迁移映射；无法唯一迁移即停止。
5. 首次以 `(repo_key, client_scope)` 绑定 YApi 时，用户必须明确确认准确的 `project_id` 与地址；项目名、路由注解、Swagger tag 和旧导入文件只能列为候选或预填，即使只有一个候选也不得自动绑定。分类以稳定的 `(yapi_project_id, category_id)` 为主身份；分类改名/移动时先按已保存的父分类 ID 与祖先链解析目标父目录，确认 `parent_apipost_folder_id` 后移动同一个 `apipost_folder_id`。任一祖先缺失、不唯一或导入能力无法表达完整目录层级时停止，禁止创建同名平行目录。
6. 每个新增或修改接口都必须先以当前 YApi 为准核验：生成并校验 YApi JSON → YApi 与当前代码不一致时，在取得 `yapi_write_authorized` 后导入或更新 YApi → 从当前 YApi 读回 `project_id`、`category_id`、完整目录、`interface_id`、method、path 与 revision，并确认与代码一致 → 再在取得 `apipost_write_authorized` 后创建/更新 ApiPost。YApi 尚未落地、读回 ID/契约不一致，或 YApi 需要更新但未获授权时，只交付脱敏文件，明确“未写入 ApiPost”。
7. 以 `(yapi_project_id, yapi_interface_id) -> apipost_interface_id` 作为接口同步主身份；`(category_id, method, normalized_path)` 只作一致性核验。`normalized_path` 从已读回的 YApi `path` 统一计算：去掉 query/hash、保留大小写、补齐单个前导 `/`、除根路径外去除尾部 `/`，并将完整路径段形式的 `:参数名` 与 `{参数名}` 统一为 `{}`。已有映射时即使路径、method、标题或目录变化，也更新/移动同一个 ApiPost 接口；映射缺失但出现候选时必须由用户确认绑定，多个候选立即停止，零候选仅限已读回的新 YApi 接口才可创建。导入器没有可验证的查询/更新语义时，不得以再次导入代替同步。
8. 对每次创建、移动、更新或禁用，在锁内先原子写入 `pending_operations[operation_id]`，至少含 `phase=prepared`、操作类型、上述稳定目标 ID、期望父级/契约摘要和开始时 revision；远端成功后立即读回并把远端 ID/revision 写为 `remote_applied`，映射完成后才标为 `committed`。恢复时先按 operation 的稳定目标和摘要实时查询远端；只在能唯一确认已创建/已更新对象时补全映射。远端成功但本机未回写、对象不唯一或状态漂移时停止并交付人工绑定信息，绝不因映射缺失再次创建。
9. YApi 或 ApiPost 若提供 ETag、revision 或 `updated_at`，读取后写入必须携带对应前置条件；冲突后重新读取并停止重新规划，不得盲目重试或覆盖。若能力不提供版本条件，必须在每次远端写入前、后立即读回并比较稳定 ID、method、path、目录/父级、变量引用和 disabled 状态；发现外部并发漂移时停止。无法实时确认、锁内状态变化或映射回写不能原子完成时停止写入。
10. 源码 diff 或 YApi 明确显示已删除的接口，只在已有同步映射时处理：先验证当前 ApiPost 通道具备可持久化的禁用能力，再将对应请求禁用、记录 disabled/revision 并读回禁用状态与时间后才标记“已下线”；保留映射用于追溯。无法验证禁用能力或状态时只交付手工禁用清单，不能报告删除已同步。物理删除项目、目录或接口必须另获一次明确授权；无法唯一定位既有映射时不得猜测删除对象。
11. 生成 Swagger 2.0 时，包含 `swagger: "2.0"`、非空 `info.title/version`、以 `/` 开头的 `paths`、真实 method、参数、鉴权模板、Content-Type 和响应结构；新文件必须省略 `host`、`schemes` 和 `basePath`，不得把任何地址作为默认请求目标。当前 ApiPost 版本只有在经 UI/API/MCP 或非敏感本机样例确认能将该文件导入为相对路径，并在本机私有环境中用其已验证的变量机制绑定 `{{base_url}}` 时，才允许导入。生成后运行 `python3 -m json.tool <file>` 和 `python3 <skill-dir>/scripts/validate_apipost_swagger2.py <file>`；只有结构校验通过且当前导入能力可按项目/目录/接口 ID 查询与更新时，才可执行导入。写后逐个读回项目、目录、接口 ID、method、path、鉴权模板、变量引用和目标环境，不能只看导入成功提示或接口总数。
12. 读取测试库前先取得本次 `test_db_read_authorized`，并实时确认目标 ApiPost 环境为本机私有、非团队、非云同步，`base_url` 精确匹配当前项目白名单中的 scheme、host 和 port。远端测试环境只允许 HTTPS；仅明确的 loopback 本地地址可使用 HTTP。认证请求不得跟随重定向或降级协议；TLS、目标地址、数据库主机/端口/库名/schema、账号只读范围或私有范围无法确认时，不得连接测试库、创建真实数据临时物或发起登录。通过后才从当前仓库已确认的测试配置取得真实库名和最小必要数据；查询只取必要标量字段、使用确定条件和 `LIMIT 1`，带真实库名前缀，不得读取密码、令牌、手机号、证件、第三方凭据、完整用户资料或批量 uid。只有接口确需 uid 冒充时，才额外取得 `simulate_login_credential_authorized` 并将该真实 uid 写入本机私有环境。
13. `debug_key` 属于生产同样有效的高权限凭据，Agent 只生成 `X-Debug-Key: {{debug_key}}` 变量模板，绝不从代码、配置、数据库或外部系统读取、复制、输出或写入该值；用户如需模拟登录，必须自行在已验证的本机私有环境填写。所有请求默认只生成禁用模板，不自动发送；包括 GET、认证和可能写库、扣费、支付、短信/IM、上传、回调或第三方调用的接口。执行认证或业务请求前，必须取得本次 `single_request_authorized`，再次确认目标环境、对象和副作用；没有安全的模拟登录能力时不得为了取令牌自动调用真实登录。
14. 真实数据临时导入物必须位于所有 Git worktree 之外的唯一受限临时目录（目录 `0700`、文件 `0600`），在成功、失败、取消、超时或异常退出的 finally/清理路径中删除。GUI 或导入能力无法提供可判定的完成/取消信号时，不得生成含真实数据的文件，改为用户在已验证的本机私有环境中手工填写。`<交付物根>/apipost/<版本或任务标识>/` 下的文件只允许包含脱敏变量和非敏感示例；交付前以两类校验器确认工作区无真实测试数据、调试密钥或临时导入物。
15. 未获得对应授权、缺少实时 YApi/ApiPost 查询更新能力、格式校验失败或任何唯一性/安全核验失败时，只交付脱敏 Swagger 2.0 文件和手工配置清单，并明确标记“未写入 ApiPost”。自动写入完成后，报告本机映射的 schema 版本、项目/目录/接口 ID、YApi 完整目录、删除禁用读回、授权状态及未自动执行的请求；不得宣称已同步而没有逐项读回证据。
