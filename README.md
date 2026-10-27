# codex-dev-skills

一套中文研发交付 Skills，覆盖需求实现、代码与 SQL 审查、Go 测试、接口交付及 Git 发布。适合已有 Go/Vue 等项目，具体命令和业务规则始终以项目真实代码、配置和 `AGENTS.md` 为准。

## 包含内容

| Skill | 用途 |
| --- | --- |
| `feature-delivery` | 按改动规模组织方案、实现、验证与审查 |
| `review` | 按风险审查代码、边界、兼容性和数据正确性 |
| `sql-check` | 检查 SQL/GORM 的安全性、语义与性能 |
| `go-test` | 沿现有模式补充并执行经过副作用检查的定向测试 |
| `api-handoff` | 从真实 Go 代码生成接口文档，按需使用 YApi 或 ApiPost |
| `git-pr` | 提交、推送及向测试/主分支合并 |
| `release` | 编排多仓正式发布及 migration 等非代码前置项 |

`skills/` 包含入口、按需读取的参考资料和本地校验脚本；`agents/` 包含 14 个配套角色。仓库不包含个人配置、凭据、聊天记录、业务源码、生产排障工具或私有历史。

## 安装与适配

需要支持 Skills 的 Codex 环境。需要委派的流程还要求当前运行时支持自定义 Agent 角色，并已正确加载 `agents/` 中的角色。脚本使用 Python 3.11+ 和 Git；使用 Unix 文件系统操作，Windows 未验证。

1. 下载或克隆本仓库，检查同名 Skill/Agent 是否已经存在，保留自己的修改。
2. 将需要的 Skill 目录放入 `${CODEX_HOME:-$HOME/.codex}/skills/`，将配套 Agent TOML 放入同一 Codex 根目录的 `agents/`。完整研发流程建议一起安装 7 个 Skill 和 14 个角色；各目录的位置关系是校验脚本的一部分。
3. 当前 Codex 从 `~/.codex/agents/` 读取独立的角色 TOML，以文件中的 `name` 识别角色，无需逐个添加角色注册项。使用自定义 `CODEX_HOME` 时保持同一根目录；安装后在新会话确认角色已被发现，且多 Agent 功能未被关闭。加载方式与版本差异以 [官方自定义 Agent 文档](https://learn.chatgpt.com/docs/agent-configuration/subagents#custom-agents) 为准。本仓库不覆盖个人 `config.toml`、全局 `AGENTS.md` 或认证文件。Agent TOML 中的 `sandbox_mode` 不会覆盖主会话权限，不能将其视为权限隔离保证。
4. 检查模型和思考档位是否由自己的账号与运行时支持。当前角色配置使用 Sol、Astra、Luna 系列；模型路由见 [model-routing.md](skills/feature-delivery/references/model-routing.md)。调整模型时同步 TOML 的 `model`、`model_reasoning_effort`、`developer_instructions` 中写明的 `selected_model`/回传型号，以及路由说明和任务包中的对应值；只改顶层型号会使角色拒绝不匹配的任务包。现有来源校验识别这些模型家族；采用其他家族时需要相应适配并验证，不能只替换型号字符串。
5. 在项目 `AGENTS.md` 中确认适用的分支、构建/测试方式、临时与交付目录及外部平台配置。文档中的 `<repo>`、`<task_tmp_root>`、`<delivery_root>` 等是待解析的路径占位符，执行前替换为当前任务的真实绝对路径。未明确启用平台时，接口交付默认只生成 Markdown。

不要直接覆盖现有同名文件，也不要把凭据或真实业务数据写进公开文档、任务包和测试样例。

## 使用示例

在对应项目中向 Codex 提出请求：

- “用 `$feature-delivery` 修复这个已有查询的排序问题。”
- “用 `$review` 审查当前需求的完整改动。”
- “用 `$api-handoff` 为这两个接口生成 Markdown 文档。”
- “用 `$git-pr` 把已审过的改动合入 test。”

任务应说明真实目标与边界；需要用户选择的业务口径及实际外部写入，仍按已有授权处理。

## 审查与发布约定

- 简单改动按轻量流程处理，不为每个步骤固定增加 Agent 或发布材料。
- 同批跨窗口合版只做一次覆盖完整范围的独立 Review。已审代码在 `test` 与 `master` 之间双向复用审查；先核对代码、语义和证据是否一致，代码没有变化就不重复完整 Review，也不重建整套材料。
- 新增改动、语义冲突或风险变化按实际范围补审。目标分支集成、构建、环境和 migration 前置条件仍需检查；代码审查不能替代上线事实。
- 测试前检查真实副作用；涉及生产数据库的 migration 由用户或 DBA 执行并确认。发布和平台写入需要覆盖实际动作的授权。

具体边界见 [审查与发布规则](skills/feature-delivery/references/review-and-release.md)。Skill 不能替代项目配置、运行时权限或人的业务判断。

## 维护校验

从仓库根目录运行以下本地脚本测试。测试使用隔离的临时仓库和虚构数据；先把 `TMPDIR` 设置为本任务允许使用的临时目录，避免产物混入项目。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/feature-delivery/scripts -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/api-handoff/scripts -p 'test_*.py'
```

修改目录、角色或模型后，需要重新验证引用和模型路由；结构校验通过并不代表真实业务任务已完成验收。

## 许可

[MIT License](LICENSE)。
