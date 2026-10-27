# master 模式

目标是让业务冲突留在开发分支解决，master 只接收已同步、已验证的上线合并；tag 必须指向最终线上产物 commit。

## 1. 开发分支同步最新 master

开始同步前，检查 `origin/master..<current>` 是否包含 migration 或 `.sql` 文件。命中时，先完成 `release` Skill 的“migration 执行验证与生产事实”：每条 SQL 必须有 `executed_confirmed` 或 `effect_verified` 的只读线上证据；`pending_manual_confirmation`、`not_executed`、`inconclusive`、缺少本次用户/DBA 合格回执或无真实 schema 名称时停止，不得继续合并、tag 或推送。Codex 不连接、不探测、不查询生产数据库；无生产连接不构成额外阻断。`effect_verified` 只能说明最终效果在线上已具备，不能声称已证明历史 SQL 文本或执行顺序。

先完成当前分支与 upstream 的通用同步，再执行：

```bash
git fetch origin master
git merge --no-ff origin/master -m "Merge origin/master into <current>: 同步主分支"
```

发生冲突时留在开发分支，列出文件和建议，取得用户确认后解决并提交。随后验证并推送开发分支：

```bash
git push origin <current>
```

已经最新且没有 merge commit 时也要确认当前分支远端已同步。

## 2. 更新 master 并展示上线内容

```bash
git switch master
git fetch origin master
git rev-list --left-right --count master...origin/master
```

本地 master 仅 behind 时才 `git merge --ff-only origin/master`；ahead 或 diverged 时停止，不把未知本地提交带上线。完成同步后记录 `origin/master` commit，并基于远端主分支展示真实待上线提交：

```bash
git log origin/master..<current> --oneline
```

展示源/目标分支、待合并提交、验证结果和非代码前置项。若本次会话已有覆盖这些内容的准确 `master` 发布授权，且内容未漂移，直接继续；仅在新增范围、前置项、重要取舍或授权缺失时请求确认。此时不要提前计算或承诺版本号。

如果 master 在步骤 1 后被推进，切回开发分支重新同步 `origin/master`；不要在 master 上直接解决新业务冲突。

## 3. 合并开发分支

授权核对通过后再次 `git fetch origin master`。若 `origin/master` 已不同于展示时记录的 commit，切回开发分支重新同步、验证和展示；远端未变化才执行：

```bash
git merge --no-ff <current> -m "Merge <current>: <摘要>"
```

仍出现冲突时优先 `git merge --abort`，回开发分支同步并解决，再重新进入 master。

## 4. 构建

如果是 Vue 项目，读取 `references/vue-build.md`：有 `reviewed_build_candidate=true` 时核对并复用已审产物，不追加提交；否则按既有线上构建规则在 master 上构建并提交实际产物目录。非 Vue 项目执行 `AGENTS.md` 或仓库规定的发布前验证；不得自行扩大到未经副作用审查的全量测试。

## 推送前与远端读回校验

有正式 release binding 时，在本地目标合并完成、tag/push 之前运行 `python3 "${CODEX_HOME:-$HOME/.codex}/skills/feature-delivery/scripts/freeze_snapshot.py" --verify-release-binding <release-binding绝对路径> --release-commit <绝对仓库>=HEAD --per-repository --before-push`；该检查只证明本地合并 tree/父链匹配，允许远端跟踪 ref 仍是冻结旧目标，不能报告远端已发布。先 fetch 核对准确远端目标未漂移，校验失败不得推送。推送后 fetch/读回目标 ref，再去掉 `--before-push` 用准确发布 commit 运行同一校验，本仓两步均通过且远端 tag/分支一致才报告该仓完成；在开发分支回同步前完成后验。`--per-repository` 只证明本仓，主 Agent 必须汇总 binding 中全部仓库的前后校验及远端读回，不能用一仓结果报告整个发布完成。

## 5. 计算远程唯一 tag

合并和构建完成后：

```bash
git fetch origin --tags
git ls-remote --tags origin
```

从远程 tag 中按仓库既有 `v<major>.<minor>.<patch>` 规则找最新版本：

- 无参数或 `patch`：patch + 1；
- `minor`：minor + 1，patch 归零；
- `major`：major + 1，minor/patch 归零；
- 指定版本：直接使用，但必须确认远程不存在。

解析 annotated tag 时忽略 `^{}` 解引用重复行，只比较 `refs/tags/v<major>.<minor>.<patch>`，并按 major、minor、patch 数值比较，禁止按字符串排序；创建前再次确认候选 tag 在远端不存在。只看本地 tag 不算验证。仓库不是该版本格式时遵循真实远程格式；无法唯一映射 `patch/minor/major` 时停止确认，不擅自套用 semver。

## 6. 推送 master 与 tag

已审构建候选的 tag 打在合入目标的最终发布 commit（其 tree 已包含审查通过的产物）；普通 Vue 路径打在构建产物 commit；非 Vue 项目打在最终 merge/验证后的发布 commit：

```bash
git tag -a <version> -m "<version>: <摘要>"
git push --atomic origin master <version>
```

远端不支持原子推送时停止并说明风险，未经用户确认不退化为分两次推送。推送后用远端状态核对 master commit 和 tag 指向。

## 7. 回同步开发分支

```bash
git switch <current>
git rev-list --count <current>..master
```

若开发分支落后于 master：

```bash
git merge --no-ff master -m "Merge master into <current>: 同步主分支"
git push origin <current>
```

发生冲突时按通用冲突规则等待确认。最终报告 master、tag、开发分支回同步结果和当前分支。
