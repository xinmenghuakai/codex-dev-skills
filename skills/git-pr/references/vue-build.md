# Vue 构建

只在项目根 `package.json` 的 dependencies 或 devDependencies 包含 Vue 时应用；仓库 `AGENTS.md` 和真实 scripts 优先。

## 已审构建候选

收到 `reviewed_build_candidate=true` 的正式 Gate 发布任务时，先核对 feature-delivery 已冻结的构建命令/环境/输入、候选 tree、最新目标 ref 和产物范围；一致则复用已审产物，不在 test/master 再构建或提交。任一漂移在推送前退回主 Agent 重新准备候选，不用额外产物提交绕过 release binding。项目依赖目标分支名称导致候选无法同环境构建时，必须在发布前解决。下文“在目标分支构建”仅适用于未提供该已审候选的普通 Git 路径。

`review_reuse_verified=true` 的双向发布按当前目标选构建命令；仅输入及环境均相同时复用产物，不能用测试包上线或将生产包当测试包。环境不同就构建一次并核对资源引用和实际环境，沿用原业务审查材料，不为新产物创建整套 Gate。旧目标的 `reviewed_build_candidate` 不能自动套到当前环境。

## 包管理器

同时核对 `package.json#packageManager`、锁文件和仓库历史：

1. 声明与单一锁文件一致时使用对应的 pnpm、yarn 或 npm；
2. 未声明时按单一 `pnpm-lock.yaml`、`yarn.lock`、`package-lock.json` 选择；
3. 声明与锁文件冲突、存在多种锁文件、使用未覆盖的包管理器，或没有足够证据时停止确认，不默认退回 npm。

仅在 `node_modules` 不存在且仓库规则允许时安装依赖。新增或更新依赖、锁文件不属于自动构建授权。

## test 目标

按 `package.json` 中真实存在的脚本选择：

1. `build:test`；
2. `build:stage`；
3. `build`。

在 test 分支执行。项目规定专用命令时不得使用兜底命令替代。

## master 目标

仓库规则或历史发布提交明确了专用生产命令时优先遵循；否则按真实脚本选择：

1. `build:prod`；
2. `build`。

严禁在 master 使用 `build:test` 或 `build:stage`。缺少 `build:prod` 且无法确认 `build` 是生产构建时停止，不用兜底命令猜测。产物目录及是否提交产物必须从 `AGENTS.md`、构建配置或最近发布提交确认，不默认一定是 `dist/`；无法确认时停止。

## 产物

构建失败时停止。产物冲突只有在源文件冲突已正确解决并重新构建通过后，才用新构建结果覆盖。只暂存实际产物目录，并以仓库既有提交风格提交。
