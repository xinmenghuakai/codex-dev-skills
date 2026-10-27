#!/usr/bin/env python3
"""冻结并校验发布范围的 Git/契约快照。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import subprocess


SNAPSHOT_SCHEMA_VERSION = 4
RELEASE_BINDING_SCHEMA_VERSION = 1
ARTIFACT_ROLES = (
    "plan_manifest",
    "no_plan_contract",
    "implementation_provenance",
    "review_report",
    "validation_evidence",
    "auxiliary",
)
SCOPE_CONTRACT_ROLES = ("plan_manifest", "no_plan_contract")
NO_PLAN_CONTRACT_REQUIRED_HEADINGS = (
    "# 无 plan 契约",
    "## 目标",
    "## 非目标",
    "## 发布范围",
    "## 验证",
    "## 授权边界",
)
FILE_KINDS = ("regular", "symlink", "deleted")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40,64}")
TARGET_REF_PATTERN = re.compile(r"refs/(?:heads|remotes)/[^\x00\s]+")


def parse_absolute_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("must be an absolute path")
    return path.resolve()


def parse_absolute_literal_path(value: str) -> Path:
    """保留证据输出的字面绝对路径，交由 openat 链拒绝任何符号链接。"""
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("must be an absolute path")
    if (
        "\x00" in value
        or any(component in ("", ".", "..") for component in value.split("/")[1:])
    ):
        raise argparse.ArgumentTypeError(
            "evidence output path must not contain empty, . or .. components"
        )
    return path


def parse_repo_target(value: str) -> tuple[Path, str]:
    """解析 `<repo>=<target-ref>`，而不是调用方自报的 merge-base。

    Review 工作树的基线只能由当前候选 HEAD 与这个目标分支 ref 重新计算；
    允许把 `--repo-base` 当作兼容别名传入，但其右侧含义已经是 target ref。
    """
    try:
        raw_path, revision = value.rsplit("=", 1)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be <absolute-repo>=<target-ref>") from error
    if not revision or any(character.isspace() for character in revision):
        raise argparse.ArgumentTypeError("target ref must be a non-empty token")
    if revision in {"HEAD", "@"} or COMMIT_PATTERN.fullmatch(revision):
        raise argparse.ArgumentTypeError(
            "target ref must name a local or remote branch, not HEAD or an immutable commit"
        )
    return parse_absolute_path(raw_path), revision


# 保留给其他本地脚本的导入兼容性；新 CLI/文档一律称 repo-target。
parse_repo_base = parse_repo_target


def parse_repo_commit(value: str) -> tuple[Path, str]:
    try:
        raw_path, revision = value.rsplit("=", 1)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be <absolute-repo>=<commit>") from error
    if not revision or any(character.isspace() for character in revision):
        raise argparse.ArgumentTypeError("release commit must be a non-empty token")
    return parse_absolute_path(raw_path), revision


def parse_artifact(value: str) -> tuple[Path, str]:
    """解析 `role=<absolute-path>`；裸绝对路径仅作为 auxiliary 保留。"""
    for role in ARTIFACT_ROLES:
        prefix = f"{role}="
        if value.startswith(prefix):
            return parse_absolute_path(value[len(prefix) :]), role
    if "=" in value and not Path(value).is_absolute():
        raise argparse.ArgumentTypeError(
            "artifact must be an absolute path or <role>=<absolute-path>"
        )
    return parse_absolute_path(value), "auxiliary"


def is_path_within(path: Path, parent: Path) -> bool:
    """避免快照输出写进发布仓库后反过来污染其自身的 Git diff。"""
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_relative_path(value: str) -> str:
    """限制证据中的仓库内文件名，避免把绝对路径混入可比较范围。"""
    candidate = PurePosixPath(value)
    if (
        not value
        or "\x00" in value
        or candidate.is_absolute()
        or any(part in ("", ".", "..") for part in candidate.parts)
    ):
        raise ValueError("snapshot path must be a non-empty relative file path")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    """确保包含非 UTF-8 Git 文件名的快照仍能稳定写入 JSON。"""
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def git_bytes(repo: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = (
            error.stderr.decode("utf-8", errors="replace").strip()
            if isinstance(error, subprocess.CalledProcessError)
            else str(error)
        )
        raise ValueError(f"cannot read Git snapshot for {repo}: {detail}") from error
    return result.stdout


def git_worktree_root(repo: Path) -> Path:
    if not repo.is_dir():
        raise ValueError(f"snapshot repository does not exist: {repo}")
    inside = git_bytes(repo, "rev-parse", "--is-inside-work-tree").decode(
        "utf-8", errors="replace"
    ).strip()
    if inside != "true":
        raise ValueError(f"snapshot repository is not a Git worktree: {repo}")
    root = Path(
        git_bytes(repo, "rev-parse", "--show-toplevel").decode(
            "utf-8", errors="surrogateescape"
        ).strip()
    ).resolve()
    if root != repo:
        raise ValueError(
            f"snapshot repository must be the Git worktree root: {repo} (root: {root})"
        )
    return root


def resolve_base_commit(repo: Path, revision: str) -> str:
    commit = git_bytes(repo, "rev-parse", "--verify", f"{revision}^{{commit}}").decode(
        "ascii", errors="strict"
    ).strip()
    if not COMMIT_PATTERN.fullmatch(commit):
        raise ValueError(f"cannot resolve immutable Git base commit for {repo}: {revision}")
    return commit


def resolve_target_ref(repo: Path, revision: str) -> tuple[str, str]:
    """把可变目标分支名冻结为 canonical ref 与不可变 commit。

    目标必须是真实本地/远端 branch ref；调用者不能把当前 HEAD 或一段 SHA
    伪装成基线，从而漏掉 feature branch 上已提交但尚未发布的改动。
    """
    if revision in {"HEAD", "@"} or COMMIT_PATTERN.fullmatch(revision):
        raise ValueError(
            "release target must name a local or remote branch, not HEAD or an immutable commit"
        )
    try:
        target_ref = git_bytes(
            repo,
            "rev-parse",
            "--symbolic-full-name",
            "--verify",
            revision,
        ).decode("utf-8", errors="surrogateescape").strip()
    except ValueError as error:
        raise ValueError(f"cannot resolve release target ref for {repo}: {revision}") from error
    if not TARGET_REF_PATTERN.fullmatch(target_ref):
        raise ValueError(
            "release target must resolve to refs/heads/* or refs/remotes/*: "
            f"{revision}"
        )
    return target_ref, resolve_base_commit(repo, target_ref)


def resolve_candidate_ref(repo: Path) -> tuple[str, str]:
    """冻结当前候选分支身份，供合入后区分真实 source 与同树 squash。"""
    try:
        candidate_ref = git_bytes(repo, "symbolic-ref", "-q", "HEAD").decode(
            "utf-8", errors="surrogateescape"
        ).strip()
    except ValueError as error:
        raise ValueError(
            f"release review candidate must be on a local branch, not detached HEAD: {repo}"
        ) from error
    if not candidate_ref.startswith("refs/heads/") or not TARGET_REF_PATTERN.fullmatch(
        candidate_ref
    ):
        raise ValueError(f"release review candidate is not a local branch: {repo}")
    return candidate_ref, resolve_base_commit(repo, candidate_ref)


def resolve_merge_base(repo: Path, left_commit: str, right_commit: str) -> str:
    merge_base = git_bytes(repo, "merge-base", left_commit, right_commit).decode(
        "ascii", errors="strict"
    ).strip()
    if not COMMIT_PATTERN.fullmatch(merge_base):
        raise ValueError(
            f"cannot resolve immutable merge-base for {repo}: {left_commit}, {right_commit}"
        )
    return merge_base


def resolve_commit_tree(repo: Path, revision: str) -> str:
    tree = git_bytes(repo, "rev-parse", "--verify", f"{revision}^{{tree}}").decode(
        "ascii", errors="strict"
    ).strip()
    if not COMMIT_PATTERN.fullmatch(tree):
        raise ValueError(f"cannot resolve Git tree for {repo}: {revision}")
    return tree


def resolve_index_tree(repo: Path) -> str:
    tree = git_bytes(repo, "write-tree").decode("ascii", errors="strict").strip()
    if not COMMIT_PATTERN.fullmatch(tree):
        raise ValueError(f"cannot write Git index tree for {repo}")
    return tree


def git_path_list(repo: Path, *arguments: str) -> list[str]:
    raw_paths = git_bytes(repo, *arguments).decode(
        "utf-8", errors="surrogateescape"
    ).split("\0")
    return sorted(validate_relative_path(value) for value in raw_paths if value)


def _mode_for_regular_file(file_stat: os.stat_result) -> str:
    return "100755" if file_stat.st_mode & stat.S_IXUSR else "100644"


def read_regular_file(path: Path) -> bytes:
    """不跟随符号链接读取一个普通文件，避免校验路径后被替换。"""
    try:
        initial_stat = os.lstat(path)
    except OSError as error:
        raise ValueError(f"cannot stat regular file: {path}: {error}") from error
    if not stat.S_ISREG(initial_stat.st_mode):
        raise ValueError(f"expected a regular file: {path}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError(f"cannot safely open regular file: {path}: {error}") from error
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"expected a regular file: {path}")
        blocks: list[bytes] = []
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            blocks.append(block)
        return b"".join(blocks)
    except OSError as error:
        raise ValueError(f"cannot read regular file: {path}: {error}") from error
    finally:
        os.close(descriptor)


def capture_release_file(repo: Path, relative_path: str) -> dict[str, object]:
    """捕获最终工作树语义，不依赖文件当前是否已 git add。"""
    target = repo / relative_path
    try:
        file_stat = os.lstat(target)
    except FileNotFoundError:
        return {"path": relative_path, "kind": "deleted", "mode": None, "sha256": None}
    except OSError as error:
        raise ValueError(f"cannot stat snapshot file: {target}: {error}") from error
    try:
        if stat.S_ISREG(file_stat.st_mode):
            return {
                "path": relative_path,
                "kind": "regular",
                "mode": _mode_for_regular_file(file_stat),
                "sha256": sha256_bytes(read_regular_file(target)),
            }
        if stat.S_ISLNK(file_stat.st_mode):
            # Git 提交的是 link target 文本，而不是外部目标文件的内容。
            return {
                "path": relative_path,
                "kind": "symlink",
                "mode": "120000",
                "sha256": sha256_bytes(os.fsencode(os.readlink(target))),
            }
    except OSError as error:
        raise ValueError(f"cannot read snapshot file: {target}: {error}") from error
    raise ValueError(f"snapshot entry must be a regular file or symlink: {target}")


def capture_worktree_range(repo: Path, base_revision: str) -> list[dict[str, object]]:
    """捕获 review 阶段的最终工作树；此时不要求或修改 Git index。"""
    changed_paths = set(
        git_path_list(
            repo,
            "diff",
            "--name-only",
            "--no-ext-diff",
            "--no-renames",
            "-z",
            base_revision,
            "--",
        )
    )
    # 已暂存新增和未跟踪新增均按最终工作树文件建模，故仅 git add 不会失效。
    changed_paths.update(
        git_path_list(repo, "ls-files", "--others", "--exclude-standard", "-z")
    )
    return [capture_release_file(repo, relative_path) for relative_path in sorted(changed_paths)]


def capture_tree_file(repo: Path, tree: str, relative_path: str) -> dict[str, object]:
    """按 Git tree 捕获将提交的语义，绝不回读工作树或 index 文件内容。"""
    raw = git_bytes(repo, "ls-tree", "-z", tree, "--", relative_path)
    if not raw:
        return {"path": relative_path, "kind": "deleted", "mode": None, "sha256": None}
    entry, separator, encoded_path = raw.rstrip(b"\0").partition(b"\t")
    if not separator:
        raise ValueError(f"cannot parse Git tree entry for {repo}: {relative_path}")
    try:
        mode, object_type, object_id = entry.decode("ascii", errors="strict").split(" ")
    except ValueError as error:
        raise ValueError(f"cannot parse Git tree entry for {repo}: {relative_path}") from error
    if object_type != "blob" or not COMMIT_PATTERN.fullmatch(object_id):
        raise ValueError(f"release tree entry must be a blob: {repo}: {relative_path}")
    decoded_path = encoded_path.decode("utf-8", errors="surrogateescape")
    if decoded_path != relative_path:
        raise ValueError(f"release tree path changed while reading: {repo}: {relative_path}")
    if mode == "120000":
        kind = "symlink"
    elif mode in ("100644", "100755"):
        kind = "regular"
    else:
        raise ValueError(f"release tree file mode is unsupported: {repo}: {relative_path}")
    return {
        "path": relative_path,
        "kind": kind,
        "mode": mode,
        "sha256": sha256_bytes(git_bytes(repo, "cat-file", "blob", object_id)),
    }


def capture_tree_range(
    repo: Path, base_revision: str, tree: str
) -> list[dict[str, object]]:
    """捕获 base..tree 的完整提交候选范围。"""
    changed_paths = git_path_list(
        repo,
        "diff",
        "--name-only",
        "--no-ext-diff",
        "--no-renames",
        "-z",
        base_revision,
        tree,
        "--",
    )
    return [capture_tree_file(repo, tree, relative_path) for relative_path in changed_paths]


def capture_repository(repo: Path, target_input: str) -> dict[str, object]:
    """冻结候选 HEAD 对真实目标分支 merge-base 的工作树范围。"""
    root = git_worktree_root(repo)
    target_ref, target_revision = resolve_target_ref(root, target_input)
    candidate_ref, candidate_revision = resolve_candidate_ref(root)
    base_revision = resolve_merge_base(root, candidate_revision, target_revision)
    files = capture_worktree_range(root, base_revision)
    return {
        "path": str(root),
        "target_ref": target_ref,
        "target_revision": target_revision,
        "candidate_ref": candidate_ref,
        "candidate_revision": candidate_revision,
        "base_revision": base_revision,
        "diff_sha256": sha256_bytes(canonical_json_bytes(files)),
        "files": files,
    }


def validate_no_plan_contract(path: Path, data: bytes) -> None:
    if path.name != "no-plan-contract.md":
        raise ValueError("no_plan_contract artifact must be named no-plan-contract.md")
    try:
        text = data.decode("utf-8")
    except UnicodeError as error:
        raise ValueError(f"cannot read no_plan_contract artifact: {path}: {error}") from error
    missing = [heading for heading in NO_PLAN_CONTRACT_REQUIRED_HEADINGS if heading not in text]
    if missing:
        raise ValueError(
            "no_plan_contract artifact is missing required headings: " + ", ".join(missing)
        )


def validate_artifact_role(path: Path, role: str, data: bytes) -> None:
    if role not in ARTIFACT_ROLES:
        raise ValueError(f"snapshot artifact has an unknown role: {role}")
    if role == "plan_manifest":
        try:
            from plan_manifest import PlanManifestError, parse_plan_manifest

            parse_plan_manifest(data.decode("utf-8"))
        except (UnicodeError, PlanManifestError) as error:
            raise ValueError(f"plan_manifest artifact is invalid: {error}") from error
    elif role == "no_plan_contract":
        validate_no_plan_contract(path, data)


def capture_artifact(path: Path, role: str) -> dict[str, str]:
    data = read_regular_file(path)
    validate_artifact_role(path, role, data)
    return {"path": str(path), "role": role, "sha256": sha256_bytes(data)}


def canonical_fingerprint(snapshot: dict[str, object]) -> str:
    return sha256_bytes(canonical_json_bytes(snapshot))


def review_input_fingerprint(snapshot: dict[str, object]) -> str:
    """给 Reviewer 的稳定范围指纹；刻意排除其随后生成的 report。"""
    validate_snapshot_structure(snapshot)
    return sha256_bytes(
        canonical_json_bytes(
            {
                "schema_version": snapshot["schema_version"],
                "repositories": snapshot["repositories"],
                "artifacts": [
                    item for item in snapshot["artifacts"] if item["role"] != "review_report"
                ],
            }
        )
    )


def build_snapshot(
    repositories: tuple[tuple[Path, str], ...], artifacts: tuple[tuple[Path, str], ...]
) -> dict[str, object]:
    if not repositories:
        raise ValueError("snapshot requires at least one repository")
    normalized_repositories = sorted(
        ((git_worktree_root(path), target_ref) for path, target_ref in repositories),
        key=lambda item: str(item[0]),
    )
    normalized_artifacts = sorted(artifacts, key=lambda item: str(item[0]))
    repository_paths = [str(path) for path, _ in normalized_repositories]
    artifact_paths = [str(path) for path, _ in normalized_artifacts]
    if len(set(repository_paths)) != len(repository_paths):
        raise ValueError("snapshot repository paths must be unique")
    if len(set(artifact_paths)) != len(artifact_paths):
        raise ValueError("snapshot artifact paths must be unique")
    for artifact, role in normalized_artifacts:
        if role in {
            "no_plan_contract",
            "implementation_provenance",
            "review_report",
            "validation_evidence",
        } and any(is_path_within(artifact, repository) for repository, _ in normalized_repositories):
            raise ValueError(f"{role} artifact must stay outside release repositories: {artifact}")
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "repositories": [
            capture_repository(path, target_ref)
            for path, target_ref in normalized_repositories
        ],
        "artifacts": [capture_artifact(path, role) for path, role in normalized_artifacts],
    }


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _validate_release_file_entries(entries: object) -> None:
    if not isinstance(entries, list):
        raise ValueError("snapshot repository files must be a list")
    paths: set[str] = set()
    for item in entries:
        if not isinstance(item, dict) or set(item) != {"path", "kind", "mode", "sha256"}:
            raise ValueError("snapshot repository file entry has an unexpected schema")
        if not isinstance(item["path"], str) or item["kind"] not in FILE_KINDS:
            raise ValueError("snapshot repository file entry has invalid fields")
        try:
            path = validate_relative_path(item["path"])
        except ValueError as error:
            raise ValueError("snapshot repository file entry has an invalid path") from error
        if path in paths:
            raise ValueError("snapshot repository file paths must be unique")
        paths.add(path)
        if item["kind"] == "deleted":
            if item["mode"] is not None or item["sha256"] is not None:
                raise ValueError("deleted snapshot file must not have mode or digest")
        else:
            if item["kind"] == "symlink" and item["mode"] != "120000":
                raise ValueError("symlink snapshot file must use mode 120000")
            if item["kind"] == "regular" and item["mode"] not in ("100644", "100755"):
                raise ValueError("regular snapshot file has an invalid mode")
            if not _is_digest(item["sha256"]):
                raise ValueError("snapshot repository file has an invalid digest")


def validate_snapshot_structure(raw: object) -> dict[str, object]:
    """校验已冻结的 JSON 结构；不读取当前工作区。"""
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "repositories", "artifacts"}:
        raise ValueError("snapshot manifest has an unexpected schema")
    if raw["schema_version"] != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError(f"snapshot manifest schema_version must be {SNAPSHOT_SCHEMA_VERSION}")
    if not isinstance(raw["repositories"], list) or not isinstance(raw["artifacts"], list):
        raise ValueError("snapshot manifest repositories and artifacts must be lists")

    repository_paths: set[str] = set()
    for item in raw["repositories"]:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "target_ref",
            "target_revision",
            "candidate_ref",
            "candidate_revision",
            "base_revision",
            "diff_sha256",
            "files",
        }:
            raise ValueError("snapshot repository entry has an unexpected schema")
        if not all(
            isinstance(item[key], str)
            for key in (
                "path",
                "target_ref",
                "target_revision",
                "candidate_ref",
                "candidate_revision",
                "base_revision",
            )
        ):
            raise ValueError("snapshot repository entry has invalid identity fields")
        try:
            repo = parse_absolute_path(item["path"])
        except argparse.ArgumentTypeError as error:
            raise ValueError("snapshot repository entry has an invalid absolute path") from error
        if str(repo) in repository_paths:
            raise ValueError("snapshot repository paths must be unique")
        repository_paths.add(str(repo))
        if not TARGET_REF_PATTERN.fullmatch(item["target_ref"]):
            raise ValueError("snapshot repository entry target_ref must be a branch ref")
        if not item["candidate_ref"].startswith("refs/heads/") or not TARGET_REF_PATTERN.fullmatch(
            item["candidate_ref"]
        ):
            raise ValueError("snapshot repository entry candidate_ref must be a local branch ref")
        for key in ("target_revision", "candidate_revision", "base_revision"):
            if not COMMIT_PATTERN.fullmatch(item[key]):
                raise ValueError(
                    f"snapshot repository entry {key} must be an immutable commit"
                )
        if not isinstance(item["diff_sha256"], str) or not _is_digest(item["diff_sha256"]):
            raise ValueError("snapshot repository entry has an invalid diff_sha256")
        _validate_release_file_entries(item["files"])
        if item["diff_sha256"] != sha256_bytes(canonical_json_bytes(item["files"])):
            raise ValueError("snapshot repository diff_sha256 does not match files")

    artifact_paths: set[str] = set()
    for item in raw["artifacts"]:
        if not isinstance(item, dict) or set(item) != {"path", "role", "sha256"}:
            raise ValueError("snapshot artifact entry has an unexpected schema")
        if (
            not isinstance(item["path"], str)
            or not isinstance(item["role"], str)
            or not isinstance(item["sha256"], str)
        ):
            raise ValueError("snapshot artifact entry has invalid path, role or sha256")
        try:
            artifact = parse_absolute_path(item["path"])
        except argparse.ArgumentTypeError as error:
            raise ValueError("snapshot artifact entry has an invalid absolute path") from error
        if str(artifact) in artifact_paths:
            raise ValueError("snapshot artifact paths must be unique")
        artifact_paths.add(str(artifact))
        if item["role"] not in ARTIFACT_ROLES:
            raise ValueError("snapshot artifact entry has an unknown role")
        if item["role"] in {
            "no_plan_contract",
            "implementation_provenance",
            "review_report",
            "validation_evidence",
        } and any(is_path_within(artifact, Path(repository)) for repository in repository_paths):
            raise ValueError("snapshot evidence artifact must stay outside release repositories")
        if not _is_digest(item["sha256"]):
            raise ValueError("snapshot artifact entry has an invalid sha256")
    return raw


def snapshot_artifact_paths(snapshot: dict[str, object]) -> set[str]:
    validate_snapshot_structure(snapshot)
    return {item["path"] for item in snapshot["artifacts"]}


def snapshot_artifact_entry(snapshot: dict[str, object], path: Path) -> dict[str, str]:
    """按绝对路径获取已冻结 artefact 的角色和摘要。"""
    validate_snapshot_structure(snapshot)
    normalized = str(parse_absolute_path(str(path)))
    for item in snapshot["artifacts"]:
        if item["path"] == normalized:
            return item
    raise ValueError(f"artifact is not included in the snapshot: {normalized}")


def read_verified_artifact(snapshot: dict[str, object], path: Path) -> bytes:
    """在解析前读取并核对 artefact；避免 Gate 在校验后再次从磁盘取值。"""
    item = snapshot_artifact_entry(snapshot, path)
    try:
        data = read_regular_file(path)
    except ValueError as error:
        raise ValueError(f"cannot read frozen artifact: {path}: {error}") from error
    if sha256_bytes(data) != item["sha256"]:
        raise ValueError(f"frozen artifact no longer matches the snapshot: {path}")
    return data


def snapshot_file_paths(snapshot: dict[str, object]) -> set[tuple[str, str]]:
    """返回快照中所有需 Review 的仓库文件。"""
    validate_snapshot_structure(snapshot)
    return {
        (repository["path"], entry["path"])
        for repository in snapshot["repositories"]
        for entry in repository["files"]
    }


def _snapshot_repositories(snapshot: dict[str, object]) -> tuple[tuple[Path, str], ...]:
    return tuple(
        (parse_absolute_path(item["path"]), item["target_ref"])
        for item in snapshot["repositories"]
    )


def _snapshot_artifacts(snapshot: dict[str, object]) -> tuple[tuple[Path, str], ...]:
    return tuple(
        (parse_absolute_path(item["path"]), item["role"])
        for item in snapshot["artifacts"]
    )


def verify_snapshot_current(snapshot: dict[str, object]) -> None:
    """重新读取 Git、工作树和 artifact，拒绝冻结后任意范围漂移。"""
    validate_snapshot_structure(snapshot)
    expected = build_snapshot(_snapshot_repositories(snapshot), _snapshot_artifacts(snapshot))
    if snapshot != expected:
        raise ValueError("snapshot manifest no longer matches the current release range")


def load_and_verify_snapshot(path: Path) -> tuple[dict[str, object], str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read snapshot manifest: {error}") from error
    snapshot = validate_snapshot_structure(raw)
    verify_snapshot_current(snapshot)
    return snapshot, canonical_fingerprint(snapshot)


def _git_with_input(
    repo: Path,
    arguments: tuple[str, ...],
    *,
    input_data: bytes = b"",
    environment: dict[str, str] | None = None,
) -> bytes:
    env = None if environment is None else {**os.environ, **environment}
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *arguments],
            input=input_data,
            check=True,
            capture_output=True,
            env=env,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = (
            error.stderr.decode("utf-8", errors="replace").strip()
            if isinstance(error, subprocess.CalledProcessError)
            else str(error)
        )
        raise ValueError(f"cannot build release binding for {repo}: {detail}") from error
    return result.stdout


def _temporary_commit_for_tree(repo: Path, tree: str, parent: str) -> str:
    """创建无 ref 的短命候选 commit，仅用于 Git 的真实三方 merge 计算。

    `git merge-tree --write-tree` 需要 commit-ish；index 只有 tree。这个对象不更新
    分支、index 或工作树，且只使用固定身份/日期保证环境不依赖本机 Git 配置。
    """
    output = _git_with_input(
        repo,
        ("commit-tree", tree, "-p", parent),
        input_data=b"feature-delivery release binding candidate\n",
        environment={
            "GIT_AUTHOR_NAME": "feature-delivery",
            "GIT_AUTHOR_EMAIL": "feature-delivery@invalid",
            "GIT_COMMITTER_NAME": "feature-delivery",
            "GIT_COMMITTER_EMAIL": "feature-delivery@invalid",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00 +0000",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00 +0000",
        },
    ).decode("ascii", errors="strict").strip()
    if not COMMIT_PATTERN.fullmatch(output):
        raise ValueError(f"cannot create release binding candidate commit for {repo}")
    return output


def _merge_tree_for_commits(repo: Path, target: str, candidate: str) -> str:
    """让 Git 本身计算 target 与候选的 merge tree；冲突即不可复用。"""
    output = _git_with_input(
        repo,
        ("merge-tree", "--write-tree", target, candidate),
    ).decode("ascii", errors="strict").strip().splitlines()
    if not output or not COMMIT_PATTERN.fullmatch(output[0]):
        raise ValueError(f"cannot calculate clean candidate merge tree for {repo}")
    return output[0]


def _release_binding_repository(snapshot_repository: dict[str, object]) -> dict[str, str]:
    root = git_worktree_root(parse_absolute_path(snapshot_repository["path"]))
    candidate_tree = resolve_index_tree(root)
    release_files = capture_tree_range(
        root, snapshot_repository["base_revision"], candidate_tree
    )
    if release_files != snapshot_repository["files"]:
        raise ValueError(
            "release index tree does not exactly match the frozen review diff: "
            f"{root}"
        )
    if sha256_bytes(canonical_json_bytes(release_files)) != snapshot_repository["diff_sha256"]:
        raise ValueError(f"release index tree digest does not match frozen review diff: {root}")
    candidate_commit = _temporary_commit_for_tree(
        root, candidate_tree, snapshot_repository["candidate_revision"]
    )
    merge_base = resolve_merge_base(
        root, snapshot_repository["target_revision"], candidate_commit
    )
    if merge_base != snapshot_repository["base_revision"]:
        raise ValueError(f"release candidate merge-base changed since review: {root}")
    merge_tree = _merge_tree_for_commits(
        root, snapshot_repository["target_revision"], candidate_commit
    )
    return {
        "path": str(root),
        "target_ref": snapshot_repository["target_ref"],
        "target_revision": snapshot_repository["target_revision"],
        "candidate_ref": snapshot_repository["candidate_ref"],
        "candidate_revision": snapshot_repository["candidate_revision"],
        "base_revision": snapshot_repository["base_revision"],
        "candidate_tree": candidate_tree,
        "merge_tree": merge_tree,
    }


def build_release_binding(snapshot: dict[str, object]) -> dict[str, object]:
    """把已经审过的工作树精确绑定到当前 index 与目标分支 merge 结果。"""
    validate_snapshot_structure(snapshot)
    verify_snapshot_current(snapshot)
    return {
        "schema_version": RELEASE_BINDING_SCHEMA_VERSION,
        "review_snapshot_fingerprint": canonical_fingerprint(snapshot),
        "review_input_fingerprint": review_input_fingerprint(snapshot),
        "repositories": [
            _release_binding_repository(repository)
            for repository in snapshot["repositories"]
        ],
    }


def _validate_release_binding_repository(
    item: object, snapshot_repository: dict[str, object] | None = None
) -> None:
    required = {
        "path",
        "target_ref",
        "target_revision",
        "candidate_ref",
        "candidate_revision",
        "base_revision",
        "candidate_tree",
        "merge_tree",
    }
    if not isinstance(item, dict) or set(item) != required:
        raise ValueError("release binding repository has an unexpected schema")
    if not all(isinstance(item[key], str) for key in ("path", "target_ref", "candidate_ref")):
        raise ValueError("release binding repository has invalid identity fields")
    try:
        parse_absolute_path(item["path"])
    except argparse.ArgumentTypeError as error:
        raise ValueError("release binding repository has an invalid path") from error
    if not TARGET_REF_PATTERN.fullmatch(item["target_ref"]):
        raise ValueError("release binding repository target_ref must be a branch ref")
    if not item["candidate_ref"].startswith("refs/heads/") or not TARGET_REF_PATTERN.fullmatch(
        item["candidate_ref"]
    ):
        raise ValueError("release binding repository candidate_ref must be a local branch ref")
    for key in (
        "target_revision",
        "candidate_revision",
        "base_revision",
        "candidate_tree",
        "merge_tree",
    ):
        if not isinstance(item[key], str) or not COMMIT_PATTERN.fullmatch(item[key]):
            raise ValueError(f"release binding repository has an invalid {key}")
    if snapshot_repository is not None:
        for key in (
            "path",
            "target_ref",
            "target_revision",
            "candidate_ref",
            "candidate_revision",
            "base_revision",
        ):
            if item[key] != snapshot_repository[key]:
                raise ValueError("release binding repository does not match its frozen snapshot")


def validate_release_binding_structure(
    raw: object, snapshot: dict[str, object] | None = None
) -> dict[str, object]:
    required = {
        "schema_version",
        "review_snapshot_fingerprint",
        "review_input_fingerprint",
        "repositories",
    }
    if not isinstance(raw, dict) or set(raw) != required:
        raise ValueError("release binding has an unexpected schema")
    if raw["schema_version"] != RELEASE_BINDING_SCHEMA_VERSION:
        raise ValueError(
            f"release binding schema_version must be {RELEASE_BINDING_SCHEMA_VERSION}"
        )
    if not all(
        isinstance(raw[key], str) and _is_digest(raw[key])
        for key in ("review_snapshot_fingerprint", "review_input_fingerprint")
    ):
        raise ValueError("release binding has invalid review fingerprints")
    if not isinstance(raw["repositories"], list) or not raw["repositories"]:
        raise ValueError("release binding repositories must be a non-empty list")
    paths: set[str] = set()
    snapshot_by_path: dict[str, dict[str, object]] = {}
    if snapshot is not None:
        validate_snapshot_structure(snapshot)
        if raw["review_snapshot_fingerprint"] != canonical_fingerprint(snapshot):
            raise ValueError("release binding does not bind the Gate snapshot")
        if raw["review_input_fingerprint"] != review_input_fingerprint(snapshot):
            raise ValueError("release binding does not bind the frozen review input")
        snapshot_by_path = {item["path"]: item for item in snapshot["repositories"]}
    for item in raw["repositories"]:
        path = item.get("path") if isinstance(item, dict) else None
        if not isinstance(path, str) or path in paths:
            raise ValueError("release binding repository paths must be unique")
        paths.add(path)
        _validate_release_binding_repository(item, snapshot_by_path.get(path))
    if snapshot is not None and paths != set(snapshot_by_path):
        raise ValueError("release binding repositories do not match the Gate snapshot")
    return raw


def canonical_release_binding_fingerprint(binding: dict[str, object]) -> str:
    validate_release_binding_structure(binding)
    return sha256_bytes(canonical_json_bytes(binding))


def load_release_binding(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(read_regular_file(path).decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read release binding: {error}") from error
    return validate_release_binding_structure(raw)


def load_and_verify_release_binding(
    path: Path, snapshot: dict[str, object]
) -> tuple[dict[str, object], str]:
    """读取 binding 后重算真实 index/target/merge tree，防止只信任 JSON 自报。"""
    binding = load_release_binding(path)
    binding = validate_release_binding_structure(binding, snapshot)
    expected = build_release_binding(snapshot)
    if binding != expected:
        raise ValueError("release binding no longer matches the current target or candidate merge tree")
    return binding, canonical_release_binding_fingerprint(binding)


def resolve_commit_parents(repo: Path, commit: str) -> tuple[str, ...]:
    raw = git_bytes(repo, "rev-list", "--parents", "-n", "1", commit).decode(
        "ascii", errors="strict"
    ).strip().split()
    if not raw or raw[0] != commit or any(not COMMIT_PATTERN.fullmatch(item) for item in raw):
        raise ValueError(f"cannot resolve commit parents for {repo}: {commit}")
    return tuple(raw[1:])


def _is_bound_candidate_commit(repo: Path, commit: str, item: dict[str, object]) -> bool:
    """候选必须正是冻结 source branch 的当前 HEAD，不能夹入后续提交。

    允许两种发布前状态：审查时改动已经是 ``candidate_revision``，或把已审
    工作树暂存并在 binding 后创建唯一一个以它为 parent 的提交。若 source
    branch 在 binding 后继续前进，即使有人构造出同一棵 merge tree，也不能再把
    较早提交当作该 branch 的可发布候选。
    """
    if resolve_commit_tree(repo, commit) != item["candidate_tree"]:
        return False
    if commit == item["candidate_revision"]:
        structurally_bound = True
    else:
        structurally_bound = resolve_commit_parents(repo, commit) == (
            item["candidate_revision"],
        )
    if not structurally_bound:
        return False
    candidate_ref = item["candidate_ref"]
    if not isinstance(candidate_ref, str) or not candidate_ref.startswith("refs/heads/"):
        return False
    try:
        candidate_head = resolve_base_commit(repo, candidate_ref)
    except ValueError:
        return False
    return candidate_head == commit


def verify_release_binding_commits(
    binding: dict[str, object], release_commits: tuple[tuple[Path, str], ...],
    *, before_push: bool = False, per_repository: bool = False,
) -> None:
    """在合入后校验目标 HEAD 确由冻结 target/candidate 产生。

    只接受可精确证明的两种 git-pr 结果：fast-forward，或 first-parent 为
    冻结 target 的双亲 merge。squash/rebase/额外提交虽可能得到相同文本，
    但不能从父链证明为已审候选，故明确拒绝。推送前允许远端跟踪 ref 仍指
    冻结的旧目标，但校验对象必须是当前本地 HEAD；推送后仍要求目标 ref 已读回。
    """
    binding = validate_release_binding_structure(binding)
    supplied: dict[str, str] = {}
    for repo, revision in release_commits:
        root = git_worktree_root(repo)
        if str(root) in supplied:
            raise ValueError("release commit repositories must be unique")
        supplied[str(root)] = revision
    expected_paths = {item["path"] for item in binding["repositories"]}
    if per_repository:
        # 逐仓发布只证明当前一仓，绝不隐含其余仓库已经合并或通过。
        if len(supplied) != 1 or not set(supplied).issubset(expected_paths):
            raise ValueError("per-repository verification requires exactly one bound repository")
    elif set(supplied) != expected_paths:
        raise ValueError("release commits must exactly cover every binding repository")
    for item in binding["repositories"]:
        if per_repository and item["path"] not in supplied:
            continue
        root = Path(item["path"])
        target_ref, target_head = resolve_target_ref(root, item["target_ref"])
        if target_ref != item["target_ref"]:
            raise ValueError(f"release target ref changed identity since binding: {root}")
        release_commit = resolve_base_commit(root, supplied[str(root)])
        if before_push:
            # 本地 merge 完成后先检查，再允许远端写入；目标第三方推进仍要阻断。
            if release_commit != resolve_base_commit(root, "HEAD"):
                raise ValueError(f"before-push release commit must equal local HEAD: {root}")
            if target_head not in (item["target_revision"], release_commit):
                raise ValueError(f"release target drifted before push: {root}")
        elif release_commit != target_head:
            raise ValueError(
                f"release commit must equal the current bound target HEAD: {root}"
            )
        if resolve_commit_tree(root, release_commit) != item["merge_tree"]:
            raise ValueError(f"release target tree does not match bound merge tree: {root}")
        parents = resolve_commit_parents(root, release_commit)
        if len(parents) == 1:
            # fast-forward：目标 HEAD 就是已审候选（或基于 review HEAD 的那个提交）。
            if not _is_bound_candidate_commit(root, release_commit, item):
                raise ValueError(
                    f"fast-forward release commit is not the bound candidate: {root}"
                )
            if resolve_merge_base(root, item["target_revision"], release_commit) != item[
                "target_revision"
            ]:
                raise ValueError(
                    f"fast-forward release does not descend from the bound target: {root}"
                )
            if item["candidate_tree"] != item["merge_tree"]:
                raise ValueError(
                    f"fast-forward release unexpectedly differs from bound candidate tree: {root}"
                )
        elif len(parents) == 2:
            # 标准 --no-ff merge：first-parent 必须就是冻结时的目标；第二父为候选。
            if parents[0] != item["target_revision"]:
                raise ValueError(
                    f"merge release first parent does not match bound target: {root}"
                )
            if not _is_bound_candidate_commit(root, parents[1], item):
                raise ValueError(
                    f"merge release second parent is not the bound candidate: {root}"
                )
        else:
            raise ValueError(
                f"release commit must be a fast-forward or two-parent merge: {root}"
            )


def _directory_open_flags(*, no_follow: bool = True) -> int:
    """构造只打开目录的 flags；路径组件必须逐个 no-follow 固定。"""
    directory_flag = getattr(os, "O_DIRECTORY", None)
    no_follow_flag = getattr(os, "O_NOFOLLOW", None)
    if not isinstance(directory_flag, int) or not isinstance(no_follow_flag, int):
        raise ValueError(
            "secure evidence output requires O_DIRECTORY and O_NOFOLLOW support"
        )
    flags = os.O_RDONLY
    flags |= directory_flag
    if no_follow:
        flags |= no_follow_flag
    return flags


def _expand_trusted_root_alias(components: tuple[str, ...]) -> tuple[str, ...]:
    """只展开 `/` 下由 root 固定的系统别名（macOS 的 /var、/tmp 等）。

    用户可控的中间路径绝不在这里跟随软链；展开后仍交由逐段 O_NOFOLLOW
    的 openat 链验证。这样既不让 `.resolve()` 吞掉攻击者软链，也能使用
    macOS 的历史系统绝对路径。
    """
    expanded = components
    for _ in range(8):
        if not expanded:
            return expanded
        try:
            root_descriptor = os.open(os.path.sep, _directory_open_flags())
        except OSError as error:
            raise ValueError(f"cannot safely open filesystem root: {error}") from error
        try:
            root_stat = os.fstat(root_descriptor)
            first_stat = os.stat(
                expanded[0], dir_fd=root_descriptor, follow_symlinks=False
            )
            if not stat.S_ISLNK(first_stat.st_mode):
                return expanded
            if (
                root_stat.st_uid != 0
                or root_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                or first_stat.st_uid != 0
            ):
                # 非系统受控的根级软链也由下方 O_NOFOLLOW 明确拒绝。
                return expanded
            target = os.readlink(expanded[0], dir_fd=root_descriptor)
        except OSError as error:
            raise ValueError(
                f"cannot safely inspect filesystem-root path component {expanded[0]}: {error}"
            ) from error
        finally:
            os.close(root_descriptor)
        target_components = tuple(
            target.split("/")[1:] if target.startswith("/") else target.split("/")
        )
        if not target_components or any(
            component in ("", ".", "..") for component in target_components
        ):
            raise ValueError(
                f"trusted filesystem-root alias has an unsafe target: {expanded[0]}"
            )
        expanded = target_components + expanded[1:]
    raise ValueError("too many filesystem-root alias expansions for evidence output")


def _open_safe_directory(path: Path, *, label: str) -> int:
    """从根目录逐级 openat 一个绝对目录，避免中间祖先被符号链接替换。"""
    if not path.is_absolute() or path.anchor != os.path.sep:
        raise ValueError(f"{label} must be an absolute POSIX directory: {path}")
    components = path.parts[1:]
    if any(component in ("", ".", "..") for component in components):
        raise ValueError(f"{label} contains an unsafe path component: {path}")
    components = _expand_trusted_root_alias(components)
    try:
        descriptor = os.open(path.anchor, _directory_open_flags())
    except OSError as error:
        raise ValueError(f"cannot safely open {label}: {path}: {error}") from error
    try:
        for component in components:
            try:
                child_descriptor = os.open(
                    component,
                    _directory_open_flags(),
                    dir_fd=descriptor,
                )
            except OSError as error:
                raise ValueError(
                    f"cannot safely open {label}: {path}: {error}"
                ) from error
            try:
                if not stat.S_ISDIR(os.fstat(child_descriptor).st_mode):
                    raise ValueError(f"{label} is not a directory: {path}")
            except BaseException:
                os.close(child_descriptor)
                raise
            os.close(descriptor)
            descriptor = child_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_safe_output_parent(path: Path) -> int:
    """固定证据父目录；所有祖先目录均通过已固定的 dir_fd 打开。"""
    return _open_safe_directory(path.parent, label="evidence output parent")


def _directory_identity(descriptor: int) -> tuple[int, int]:
    file_stat = os.fstat(descriptor)
    if not stat.S_ISDIR(file_stat.st_mode):
        raise ValueError("expected an open directory descriptor")
    return file_stat.st_dev, file_stat.st_ino


def _open_directory_is_within(directory_descriptor: int, ancestor_descriptor: int) -> bool:
    """用 inode 链判断已打开的输出目录是否位于已打开的发布仓库内。"""
    ancestor_identity = _directory_identity(ancestor_descriptor)
    try:
        current_descriptor = os.dup(directory_descriptor)
    except OSError as error:
        raise ValueError(f"cannot duplicate evidence output directory: {error}") from error
    seen: set[tuple[int, int]] = set()
    try:
        while True:
            current_identity = _directory_identity(current_descriptor)
            if current_identity == ancestor_identity:
                return True
            if current_identity in seen:
                raise ValueError("cannot determine evidence output directory ancestry")
            seen.add(current_identity)
            try:
                parent_descriptor = os.open(
                    "..",
                    _directory_open_flags(no_follow=False),
                    dir_fd=current_descriptor,
                )
            except OSError as error:
                raise ValueError(
                    f"cannot determine evidence output directory ancestry: {error}"
                ) from error
            try:
                parent_identity = _directory_identity(parent_descriptor)
            except BaseException:
                os.close(parent_descriptor)
                raise
            if parent_identity == current_identity:
                os.close(parent_descriptor)
                return False
            os.close(current_descriptor)
            current_descriptor = parent_descriptor
    finally:
        os.close(current_descriptor)


def _assert_output_parent_outside_release_repositories(
    parent_descriptor: int,
    output_path: Path,
    forbidden_root_descriptors: tuple[int, ...],
) -> None:
    """在输出目录已固定后，按真实 inode 祖先再次拒绝落入发布仓库。"""
    for root_descriptor in forbidden_root_descriptors:
        if _open_directory_is_within(parent_descriptor, root_descriptor):
            raise ValueError(
                f"evidence output must stay outside release repositories: {output_path}"
            )


def _open_forbidden_root_descriptors(forbidden_roots: tuple[Path, ...]) -> tuple[int, ...]:
    """一次性固定发布仓库 inode，避免两次 containment 复核重开了不同目录对象。"""
    descriptors: list[int] = []
    try:
        for root in forbidden_roots:
            descriptors.append(
                _open_safe_directory(root, label="release repository root")
            )
        return tuple(descriptors)
    except BaseException:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


def _current_file_matches_identity(
    parent_descriptor: int, output_name: str, expected_identity: tuple[int, int]
) -> bool:
    """判断目录项仍是否指向本次已打开文件的 inode，而不跟随同名软链。"""
    try:
        current_stat = os.stat(
            output_name, dir_fd=parent_descriptor, follow_symlinks=False
        )
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return (current_stat.st_dev, current_stat.st_ino) == expected_identity


def write_new_text(
    path: Path, text: str, *, forbidden_roots: tuple[Path, ...] = ()
) -> None:
    """在已固定且仓外的目录中以硬链接发布新证据，永不覆盖已有文件。"""
    if not path.is_absolute() or path.name in ("", ".", ".."):
        raise ValueError("evidence output must be an absolute file path")
    forbidden_root_descriptors = _open_forbidden_root_descriptors(forbidden_roots)
    parent_descriptor: int | None = None
    temporary_name = f".{path.name}.{secrets.token_hex(12)}.tmp"
    temporary_descriptor: int | None = None
    temporary_identity: tuple[int, int] | None = None
    published = False
    published_identity: tuple[int, int] | None = None
    try:
        parent_descriptor = _open_safe_output_parent(path)
        _assert_output_parent_outside_release_repositories(
            parent_descriptor, path, forbidden_root_descriptors
        )
        try:
            os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError(f"evidence output already exists and will not be overwritten: {path}")
        temporary_descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=parent_descriptor,
        )
        temporary_stat = os.fstat(temporary_descriptor)
        temporary_identity = temporary_stat.st_dev, temporary_stat.st_ino
        with os.fdopen(temporary_descriptor, "w", encoding="utf-8", closefd=False) as output:
            output.write(text)
            output.flush()
            os.fsync(temporary_descriptor)
        if not _current_file_matches_identity(
            parent_descriptor, temporary_name, temporary_identity
        ):
            raise ValueError("evidence temporary file changed while publishing")
        os.link(
            temporary_name,
            path.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        published = True
        published_identity = temporary_identity
        if not _current_file_matches_identity(
            parent_descriptor, path.name, published_identity
        ):
            raise ValueError("evidence output changed while publishing")
        # 防御父目录在创建前后被并发移动到发布仓库；若发生则失败并保留文件，
        # 因为 check-then-unlink 无法证明同名路径仍属于本次写入。
        _assert_output_parent_outside_release_repositories(
            parent_descriptor, path, forbidden_root_descriptors
        )
        if not _current_file_matches_identity(
            parent_descriptor, path.name, published_identity
        ):
            raise ValueError("evidence output changed while publishing")
    except FileExistsError as error:
        raise ValueError(f"evidence output already exists and will not be overwritten: {path}") from error
    except ValueError as error:
        # POSIX 没有“仅当目录项仍指向这个 inode 才 unlink”的原子 API。校验后
        # 再 unlink 仍可能删除并发写入者刚替换的同名文件，故失败时宁可保留本次
        # 临时/已发布文件；Gate 不会把失败调用的输出当作有效证据，人工可安全清理。
        if published:
            raise ValueError(
                f"{error}; published evidence was intentionally left in place after "
                "a concurrent-write safety failure"
            ) from error
        raise
    except OSError as error:
        raise ValueError(f"cannot safely write evidence output: {path}: {error}") from error
    finally:
        if parent_descriptor is not None:
            if temporary_descriptor is not None:
                try:
                    os.close(temporary_descriptor)
                except OSError:
                    pass
            # 同理，不对随机临时名做 check-then-unlink；保留的 0600 临时文件
            # 不会被 Gate 读取，也不会覆盖任何证据输出。
            os.close(parent_descriptor)
        for descriptor in reversed(forbidden_root_descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def write_new_json(
    path: Path, value: object, *, forbidden_roots: tuple[Path, ...] = ()
) -> None:
    write_new_text(
        path,
        canonical_json_bytes(value).decode("utf-8") + "\n",
        forbidden_roots=forbidden_roots,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-target",
        type=parse_repo_target,
        action="append",
        dest="repo_targets",
        default=[],
        help="<absolute-repo>=<target branch ref>; merge-base is calculated by the script",
    )
    parser.add_argument(
        "--repo-base",
        type=parse_repo_target,
        action="append",
        dest="repo_targets",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--artifact", type=parse_artifact, action="append", default=[])
    parser.add_argument("--output", type=parse_absolute_literal_path)
    parser.add_argument(
        "--bind-release-snapshot",
        type=parse_absolute_path,
        help="freeze a commit-bound index/merge-tree binding for a verified review snapshot",
    )
    parser.add_argument(
        "--verify-release-binding",
        type=parse_absolute_path,
        help="verify post-commit tree(s) against a previously frozen release binding",
    )
    parser.add_argument("--release-commit", type=parse_repo_commit, action="append", default=[])
    parser.add_argument("--before-push", action="store_true", help="verify the local merged HEAD before publishing; does not prove remote delivery")
    parser.add_argument("--per-repository", action="store_true", help="verify exactly one supplied bound repository; does not verify the other repositories")
    args = parser.parse_args()
    selected_modes = sum(
        (
            bool(args.repo_targets or args.artifact),
            args.bind_release_snapshot is not None,
            args.verify_release_binding is not None,
        )
    )
    if selected_modes != 1:
        parser.error(
            "choose exactly one mode: review snapshot (--repo-target), "
            "--bind-release-snapshot, or --verify-release-binding"
        )
    if args.verify_release_binding is not None:
        if args.output is not None or args.repo_targets or args.artifact:
            parser.error("verify-release-binding does not accept --output, --repo-target or --artifact")
        if not args.release_commit:
            parser.error("verify-release-binding requires at least one --release-commit")
        try:
            binding = load_release_binding(args.verify_release_binding)
            verify_release_binding_commits(binding, tuple(args.release_commit), before_push=args.before_push, per_repository=args.per_repository)
        except ValueError as error:
            parser.error(str(error))
        phase = "before push (local only)" if args.before_push else "after target readback"
        scope = f"repository only={args.release_commit[0][0]}" if args.per_repository else "all bound repositories"
        print(f"release binding verified {phase}; {scope}: {args.verify_release_binding}")
        return 0

    if args.before_push:
        parser.error("before-push requires --verify-release-binding")
    if args.per_repository:
        parser.error("per-repository requires --verify-release-binding")
    if args.output is None:
        parser.error("review snapshot and bind-release-snapshot require --output")
    if args.bind_release_snapshot is not None:
        if args.repo_targets or args.artifact or args.release_commit:
            parser.error(
                "bind-release-snapshot does not accept --repo-target, --artifact or --release-commit"
            )
        try:
            snapshot, _ = load_and_verify_snapshot(args.bind_release_snapshot)
            binding = build_release_binding(snapshot)
            write_new_json(
                args.output,
                binding,
                forbidden_roots=tuple(
                    Path(repository["path"]) for repository in snapshot["repositories"]
                ),
            )
        except ValueError as error:
            parser.error(str(error))
        print(
            f"release binding frozen: {args.output} "
            f"sha256={canonical_release_binding_fingerprint(binding)} "
            f"review_input_sha256={binding['review_input_fingerprint']}"
        )
        return 0

    if not args.repo_targets:
        parser.error("review snapshot requires at least one --repo-target")
    if args.release_commit:
        parser.error("review snapshot does not accept --release-commit")
    if any(args.output == artifact for artifact, _ in args.artifact):
        parser.error("snapshot output must not overwrite a frozen artifact")
    if any(is_path_within(args.output, repository) for repository, _ in args.repo_targets):
        parser.error("snapshot output must stay outside release repositories")
    try:
        snapshot = build_snapshot(tuple(args.repo_targets), tuple(args.artifact))
        write_new_json(
            args.output,
            snapshot,
            forbidden_roots=tuple(
                Path(repository["path"]) for repository in snapshot["repositories"]
            ),
        )
    except ValueError as error:
        parser.error(str(error))
    print(
        f"snapshot frozen: {args.output} sha256={canonical_fingerprint(snapshot)} "
        f"review_input_sha256={review_input_fingerprint(snapshot)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
