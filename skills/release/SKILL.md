---
name: release
description: 多仓库上线编排:扫调试标记、migration 对线上库核对、按序合并 master 打 tag(Go/Vue)、输出非代码项 checklist。用于一次需求涉及多个仓库的正式上线。
---

# 多仓正式上线

编排多个仓库的上线依赖、migration 和非代码事项；单仓 Git 细节交给 `git-pr`。正式发布前取得覆盖目标仓库、顺序、分支/tag 和非代码前置项的准确授权；同一份已确认且未漂移的发布包可覆盖全部仓库，migration 与生产动作仍按各自授权执行。

同份已审代码从 test 上线 master 时，逐仓先按 [双向复用与发布检查](../feature-delivery/references/review-and-release.md#双向复用与发布检查) 核验。已有审查和材料有效则只补当前目标及非代码前置项检查，不重建 report、provenance、快照和 binding；migration/配置的生产事实及执行授权仍须独立确认。

## 输入与项目线索

- 无参数：从 plan 和当前需求圈定仓库；仍不明确时询问。
- 指定仓库：仍要核对 plan 是否存在遗漏依赖。
- 可附 `patch`、`minor`、`major` 或指定版本意图。

从各仓库的实际文件确认语言、构建脚本、产物目录、migration 约定和目标 schema，不预置业务仓库映射。tag 以远程为准，前端构建脚本看 `package.json`，产物目录看项目 `AGENTS.md`、配置或最近构建提交。

## 0. 范围与状态确认

对每个仓库检查：

- 当前分支、`git status --short`、目标分支和待合并提交；
- feature 与 upstream 的 ahead/behind 及远端独有提交；
- 远程 tag、仓库验证命令、构建产物和非代码依赖。

远端 feature 有本地未包含的提交时先合并并验证，不能直接合 master。工作区不干净时区分本需求与用户其他改动。输出“仓库、源/目标分支、提交数、当前 tag、版本意图、验证/非代码项”总表。范围或顺序存在未授权取舍时先确认；已有准确授权且总表一致时继续完成发布前检查。

## 1. 调试标记

在每个仓库定向搜索：

```bash
git -C <repo> grep -n -E "TODO 调试临时|待上线前恢复|待恢复|临时调试" -- ':!*.md'
```

有命中时逐项说明，等待用户选择恢复或明确带上线。恢复后重新验证并提交；不要因为文本像调试代码就擅自删除。

## 2. migration 执行验证与生产事实

先从仓库实际 SQL 目录（如 `migration/`、`migrations/`、`sql/`）和变更中的 `.sql` 文件圈定候选；`git diff <target> --name-status` 只用于发现候选，不能当执行清单。 已有代码侧审计、候选 SQL 和人工检查清单与当前范围一致时直接引用，只补变化；当前生产前置事实和用户/DBA 回执仍须核对。

对每个候选 SQL，在任何 `master` 合并、tag 或部署前完成代码侧审计并等待用户或 DBA 手工确认；Codex 不连接、不探测、不查询生产数据库：

1. 从真实连接配置确认 schema，提取 CREATE/ALTER/INSERT/UPDATE 涉及的表、列、索引、`AFTER` 依赖、数据口径和执行顺序；配置无法确认真实库名时停止，不猜测。
2. 生成带真实库名前缀的候选 migration、只读核验 SQL和人工检查项，说明锁表、兼容、回滚/前滚及重复执行风险；只交给用户或 DBA，不由 Codex 在生产库执行。
3. 初始状态标记 `pending_manual_confirmation`。只有用户或 DBA 明确提供执行回执、审计记录或人工核验结论后，才按证据标记 `executed_confirmed` 或 `effect_verified`；不得从代码存在、历史记忆或无法读库推断已执行。
4. 回执表明效果缺失时标记 `not_executed`；DML/回填或证据不足时标记 `inconclusive`。`pending_manual_confirmation`、`not_executed` 和 `inconclusive` 均阻塞正式发布。
5. 输出每条 SQL 的状态、待人工执行/核验 SQL、证据来源、确认人和时间。历史总体授权、连续模式或本机已有数据库/SSH 凭据都不替代本次人工确认。

默认建议兼容性 DDL 先于依赖它的新代码生效；若本次 DDL 对旧代码不兼容，单独设计发布顺序。

## 3. 逐仓发布

按被依赖者优先排序，通常后端先于前端。每个仓库：

1. 复核适用 `AGENTS.md`、待合并提交、验证结果、migration/配置前置项和版本意图。
2. 核对本仓仍在已授权范围内；远端漂移先重查受影响的集成与验证，仅引入新增范围、前置项或实质取舍时再确认，无关且核验通过的目标前进沿用原授权。
3. 使用 `git-pr master` 完成同步、合并、构建、远程 tag、推送和回同步。
4. 独立核对真实分支、commit、tag 和远端状态后再进入下一仓。

冲突、尚未核验的远端漂移、验证失败、任一 migration 状态为 `pending_manual_confirmation`/`not_executed`/`inconclusive` 或 tag 竞争时停在当前仓，不继续发布下游。

## 4. 非代码清单

无论代码是否全部完成，都汇总状态：

- SQL：文件、`pending_manual_confirmation`/`executed_confirmed`/`effect_verified`/`not_executed`/`inconclusive` 状态、人工确认方及证据；
- cron/任务：从本次真实路由 diff 提取 URL、参数、调用方、频率和扫描对象；区分 5/6 位 cron；
- 外部仓库：依赖的回调、任务或服务是否上线；
- 后台配置：商品、开关、菜单、权限及操作方；
- 接口文档：需要的 `api-handoff`、YApi 导入和前端通知；
- plan：回写仓库、commit、tag、日期、验证结果和遗留事项。

## 输出

给出仓库发布表（仓库、commit、tag、远端状态、验证）和待人工 checklist。只有所有已授权仓库及必需前置项完成时才报告上线完成；否则准确标记已完成、阻塞和未授权部分。
