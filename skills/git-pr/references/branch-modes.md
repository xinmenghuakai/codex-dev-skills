# test、merge、from 模式

只执行用户选择的一个模式。所有模式开始前均完成 `SKILL.md` 的通用前置和当前分支同步。

## test：当前分支合并到测试分支

1. 推送当前分支：

   ```bash
   git push origin <current>
   ```

2. 更新并合并到 test：

   ```bash
   git fetch origin test
   git switch test
   git rev-list --left-right --count test...origin/test
   ```

   本地 test 与远端一致时直接继续；仅 behind 时执行 `git merge --ff-only origin/test`；ahead 或 diverged 时停止确认，不把未知本地提交带入测试分支。确认目标分支安全后执行：

   ```bash
   git merge --no-ff <current> -m "Merge <current>: <摘要>"
   ```

3. 如果是 Vue 项目，读取 `references/vue-build.md`；有 `reviewed_build_candidate=true` 时核对并复用已审产物，否则执行测试构建，产物有变化时只提交实际产物目录。
4. 推送并切回：

   有正式 release binding 时，在本地目标合并完成、tag/push 之前运行 `python3 "${CODEX_HOME:-$HOME/.codex}/skills/feature-delivery/scripts/freeze_snapshot.py" --verify-release-binding <release-binding绝对路径> --release-commit <绝对仓库>=HEAD --per-repository --before-push`；该检查只证明本地合并 tree/父链匹配，允许远端跟踪 ref 仍是冻结旧目标，不能报告远端已发布。先 fetch 核对准确远端目标未漂移，校验失败不得推送。推送后 fetch/读回目标 ref，再去掉 `--before-push` 用准确发布 commit 运行同一校验，本仓两步均通过且远端 tag/分支一致才报告该仓完成；在开发分支回同步前完成后验。`--per-repository` 只证明本仓，主 Agent 必须汇总 binding 中全部仓库的前后校验及远端读回，不能用一仓结果报告整个发布完成。

   ```bash
   git push origin test
   git switch <current>
   ```

5. 核对 `origin/test` 已包含合并提交，报告构建结果和最终分支。

## merge：当前分支合并到指定目标

1. 推送当前分支。
2. 更新目标并合并：

   ```bash
   git push origin <current>
   git fetch origin <target>
   git switch <target>
   git rev-list --left-right --count <target>...origin/<target>
   ```

   本地目标分支与远端一致时直接继续；仅 behind 时执行 `git merge --ff-only origin/<target>`；ahead 或 diverged 时停止确认。确认目标分支安全后执行：

   ```bash
   git merge --no-ff <current> -m "Merge <current>: <摘要>"
   git push origin <target>
   git switch <current>
   ```

3. 带正式 release binding 时，将上文 test 的推送前校验插在本地 merge 与 push 之间，推送后再执行目标读回校验。核对远端目标包含合并提交并报告最终分支。除非 `AGENTS.md` 或用户明确要求，普通 `merge` 不自行增加构建步骤。

## from：远程来源分支合并到当前分支

1. 当前分支保持为目标，只更新来源远端跟踪分支：

   ```bash
   git fetch origin <source>
   git log HEAD..origin/<source> --oneline
   ```

2. 列表为空时报告无新提交并结束。
3. 展示来源、当前目标和待并入提交；已有覆盖这些提交的准确授权时继续，仅在范围漂移或授权缺失时请求确认。
4. 合并并推送：

   ```bash
   git merge --no-ff origin/<source> -m "Merge <source> into <current>: <摘要>"
   git push origin <current>
   ```

5. 合并事实来源始终使用 `origin/<source>`；不要求改写本地同名来源分支。核对远端当前分支包含合并提交。
