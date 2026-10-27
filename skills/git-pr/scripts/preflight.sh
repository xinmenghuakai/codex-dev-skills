#!/usr/bin/env bash
set -euo pipefail

repo="${1:-.}"
target="${2:-master}"

git_cmd=(git -C "$repo")

if ! "${git_cmd[@]}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "FAIL 不是 Git 工作区: $repo"
  exit 1
fi

branch=$("${git_cmd[@]}" branch --show-current)
if [[ -z "$branch" ]]; then
  echo "FAIL 当前处于 detached HEAD"
  exit 1
fi

echo "repo=$("${git_cmd[@]}" rev-parse --show-toplevel)"
echo "branch=$branch"

if "${git_cmd[@]}" diff --name-only --diff-filter=U | grep -q .; then
  echo "FAIL 存在未解决冲突"
  "${git_cmd[@]}" diff --name-only --diff-filter=U
  exit 1
fi

echo "status:"
"${git_cmd[@]}" status --short

upstream=$("${git_cmd[@]}" rev-parse --abbrev-ref --symbolic-full-name "@{upstream}" 2>/dev/null || true)
echo "upstream=${upstream:-none}"

if [[ -n "$upstream" ]]; then
  counts=$("${git_cmd[@]}" rev-list --left-right --count "HEAD...$upstream")
  ahead=${counts%%[[:space:]]*}
  behind=${counts##*[[:space:]]}
  echo "ahead=$ahead behind=$behind"
  if [[ "$behind" -gt 0 ]]; then
    echo "remote-only commits:"
    "${git_cmd[@]}" log --oneline "HEAD..$upstream"
  fi
fi

target_ref="origin/$target"
if "${git_cmd[@]}" show-ref --verify --quiet "refs/remotes/$target_ref"; then
  echo "target=$target_ref"
  echo "commits to target:"
  "${git_cmd[@]}" log --oneline "$target_ref..HEAD"
else
  echo "WARN 远端目标分支尚未获取: $target_ref"
fi

latest_tag=$("${git_cmd[@]}" tag --list 'v[0-9]*.[0-9]*.[0-9]*' --sort=-version:refname | head -n 1)
echo "latest_local_tag=${latest_tag:-none}"
