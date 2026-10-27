---
name: git-pr
description: 提交代码到远程仓库，支持五种模式：push（仅推送）、test（合并到测试分支）、master（合并到主分支并打tag）、merge（合并到指定分支）、from（将指定分支合并到当前分支）
---

# Git 提交与合并

## 模式

- `$git-pr`、`$git-pr push`：提交并推送当前分支。
- `$git-pr test`：推送当前分支并合并到 `test`。
- `$git-pr master [version|patch|minor|major]`：合并到 `master`、构建、打远程唯一 tag。
- `$git-pr merge <target>`：把当前分支合并到目标分支。
- `$git-pr from <source>`：把远程来源分支合并到当前分支。

参数不完整时只询问缺失的分支或版本意图，不自行选择发布目标。

用户只要求合回**本地开发分支**时，不套用会推送远端的 `merge/from` 模式；本地合并本身不触发发布 Gate，已有审查或验证阻塞仍须处理。核对源/目标提交、工作区和已完成的验证后完成本地合并并读回；存在其他窗口未提交的改动时保留现场，必要时使用隔离工作区。不自动推送、打 tag 或为合并重跑未失效的业务测试。

## 已审代码同步 test/master

test/master 双向发布及已发布代码同步测试分支，先按 [双向复用与发布检查](../feature-delivery/references/review-and-release.md#双向复用与发布检查) 核验已有审查、完整范围和目标集成。符合条件就复用结论及原材料，按本 Skill 完成 Git 检查、必要环境构建和远端读回，不重启 Reviewer、不为换目标生成新 Gate 套件，也不将旧目标的 binding 用于当前目标。未覆盖改动或关键语义变化按真实风险补审或复审。migration、冲突确认、发布与 SSH 授权仍按当前目标执行。

## 通用前置

1. 读取适用的 `AGENTS.md`，确认仓库发布、构建、产物和禁止项。
2. 记录仓库根、原分支和目标；拒绝 detached HEAD。`test`、`master`、`merge` 模式下当前分支等于目标分支时停止并询问，不进入同步、构建、推送或打 tag；确需在目标分支补构建或 tag 时必须改用单独的显式授权流程。
3. 检查 `git status --short`、未解决冲突和用户已有改动。只处理当前需求文件，不使用 `git add .`/`git add -A`。
4. 需要提交时先看完整 diff 和近期提交风格，按逻辑边界暂存具体文件；提交前必须核对完整 `git diff --cached`，发现用户原有或无关暂存内容时停止确认。确认暂存区只含本需求后，生成符合仓库风格的提交信息并执行 `git commit`，再核对新 commit 和暂存区；没有本需求改动时跳过。
5. 提交后仍有无关修改时，`push` 可在确认暂存区无关内容后继续；需要切分支或构建的模式若选择保留现场，就停止本次操作，只有用户确认精确 stash 或能提供干净构建工作区的隔离方案后才继续，不得默认 stash。恢复隔离修改发生冲突时停止并保留现场。
6. 执行 `git fetch origin`，再运行 `scripts/preflight.sh <repo> <target>`。
7. 当前分支仅 behind 时 `git merge --ff-only <upstream>`；ahead 与 behind 同时存在时展示远端独有提交，确认语义后 `git merge --no-ff <upstream>`。upstream、远端语义或冲突不清时停止。

禁止用未指定策略的 `git pull` 处理共享分支。任何模式执行后都要核对真实分支、commit、upstream、远端状态和 tag，而不是只转述命令成功。

## 按模式执行

### push

前置检查完成后执行 `git push origin <current>`，再确认本地与远端一致。

### test、merge、from

读取并严格执行 [references/branch-modes.md](references/branch-modes.md) 中对应模式；不要加载无关模式。检测到 Vue 项目且目标是 `test` 时，再读取 [references/vue-build.md](references/vue-build.md) 的测试构建部分。

### master

读取并严格执行 [references/master.md](references/master.md)。发现本次待上线提交包含 migration 或 `.sql` 文件时，必须先按 `release` 的“migration 执行验证与生产事实”完成代码审计和用户/DBA 人工核验回执检查；不能因为单仓而跳过，也不能把 Git 中存在 SQL 当作已执行。检测到 Vue 项目时，再读取 [references/vue-build.md](references/vue-build.md) 的线上构建部分。

## 冲突与失败

- 冲突时列出文件、分析两侧语义并给出建议，等待用户确认后才修改。
- `master` 最终合并仍冲突时优先 abort，回开发分支重新同步最新 `origin/master` 并解决；不在 master 直接决定业务冲突。
- Vue 产物冲突只有在源文件正确且重新构建通过后，才用新产物覆盖。
- 构建、测试、推送或 tag 失败时停在当前阶段；保留状态和证据，不跳过继续。
- 切换过分支的模式结束或中止时，明确当前分支；安全可行时切回原分支。

## 输出

报告模式、源/目标分支、提交、构建结果、推送结果、tag（如有）、最终所在分支及遗留状态。未执行或失败的步骤不得描述为完成。
