#!/usr/bin/env python3
"""校验冻结实现来源，并按明确审查风险选择 Reviewer。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import tomllib

from freeze_snapshot import (
    SCOPE_CONTRACT_ROLES,
    load_and_verify_snapshot,
    parse_absolute_path,
    read_verified_artifact,
    snapshot_artifact_entry,
    snapshot_file_paths,
    validate_relative_path,
)


# 常规研发使用 Sol，按需页面实现使用 Terra，高风险使用 Astra。
# unknown 表示真实模型无法核验，不能据此宣称模型家族独立。
FAMILY_ORDER = ("luna", "terra", "sol", "astra", "unknown")
ENTRY_TYPES = ("implementation", "scope_contract")
EXTERNAL_IMPLEMENTERS = {"main_agent", "human", "external_agent", "unknown_source"}
AGENTS_DIR = Path(__file__).resolve().parents[3] / "agents"
IMPLEMENTATION_AGENTS = (
    "feature_delivery_simple_implementer",
    "feature_delivery_implementer",
    "feature_delivery_ui_implementer",
    "feature_delivery_deep_implementer",
    "feature_delivery_critical_implementer",
    "feature_delivery_test_specialist",
)
SCOPE_CONTRACT_AGENTS = (
    "feature_delivery_planner",
    "feature_delivery_architect",
)
MODEL_FAMILY_PATTERN = re.compile(r"-(luna|terra|sol|astra)$")
MODULE_ID_PATTERN = re.compile(r"[^\s]{1,128}")
# 主会话没有固定 Agent TOML；这里只验证如实记录的 model/effort 格式，不推导 family。
MAIN_MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/(?:none|minimal|low|medium|high|xhigh|max|ultra)")


class ProvenanceError(ValueError):
    """来源、风险或模型配置无法满足校验要求时抛出。"""


@dataclass(frozen=True)
class ProvenanceSummary:
    families: tuple[str, ...]
    selected_reviewer: str
    review_independence: str


def load_agent_model(agent: str) -> tuple[str, str]:
    """从 Agent TOML 读取唯一机器模型配置，并返回 model/effort 与 family。"""
    path = AGENTS_DIR / f"{agent}.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ProvenanceError(f"cannot read Agent model config: {agent}") from error
    model = data.get("model")
    effort = data.get("model_reasoning_effort")
    if not isinstance(model, str) or not isinstance(effort, str) or not model or not effort:
        raise ProvenanceError(f"Agent model config is incomplete: {agent}")
    family_match = MODEL_FAMILY_PATTERN.search(model)
    if family_match is None:
        raise ProvenanceError(f"Agent model family is unsupported: {agent}")
    return f"{model}/{effort}", family_match.group(1)


def models_for_entry_type(entry_type: str) -> dict[str, tuple[str, str]]:
    """返回某类发布范围允许使用的 Agent，并从各自 TOML 读取模型。"""
    if entry_type == "implementation":
        agents = IMPLEMENTATION_AGENTS
    elif entry_type == "scope_contract":
        agents = SCOPE_CONTRACT_AGENTS
    else:
        raise ProvenanceError("implementation provenance entry_type is invalid")
    return {agent: load_agent_model(agent) for agent in agents}


def parse_optional_path(value: str) -> Path | None:
    if value == "none":
        return None
    try:
        return parse_absolute_path(value)
    except argparse.ArgumentTypeError as error:
        raise argparse.ArgumentTypeError("must be none or an absolute path") from error


def canonical_families(values: object) -> tuple[str, ...]:
    if not isinstance(values, set):
        values = set(values)
    unknown = values - set(FAMILY_ORDER)
    if unknown:
        raise ProvenanceError("implementation provenance has an unknown model family")
    return tuple(family for family in FAMILY_ORDER if family in values)


def reviewer_for_risk(risk_level: str, families: tuple[str, ...]) -> tuple[str, str]:
    """按审查风险选择 Reviewer；实现家族只决定独立性标记。"""
    if risk_level not in ("small", "normal", "high"):
        raise ProvenanceError("reviewer routing requires a valid risk level")
    families = canonical_families(families)
    reviewer = (
        "feature_delivery_sol_reviewer"
        if risk_level == "high"
        else "feature_delivery_reviewer"
    )
    # 角色名沿用 sol；同家族判断必须读取真实配置，不能依赖角色名。
    _, reviewer_family = load_agent_model(reviewer)
    independence = (
        "source_unknown" if "unknown" in families
        else "same_family_unavoidable" if reviewer_family in families
        else "independent"
    )
    return reviewer, independence


def parse_provenance_bytes(data: bytes) -> dict[str, object]:
    """解析已由 snapshot 校验过的来源文件内容。"""
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ProvenanceError(f"cannot read implementation provenance: {error}") from error
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "entries"}:
        raise ProvenanceError("implementation provenance has an unexpected schema")
    if raw["schema_version"] not in (2, 3) or not isinstance(raw["entries"], list):
        raise ProvenanceError("implementation provenance has an invalid schema_version or entries")

    task_ids: set[str] = set()
    implementation_claims: set[tuple[str, str]] = set()
    scope_contract_claims: set[tuple[str, str]] = set()
    for entry in raw["entries"]:
        expected_keys = {
            "entry_type",
            "task_id",
            "module_id",
            "selected_agent",
            "selected_model",
            "plan_item_ids",
            "files",
        }
        external = (
            isinstance(entry, dict)
            and entry.get("entry_type") == "implementation"
            and isinstance(entry.get("selected_agent"), str)
            and entry.get("selected_agent") in EXTERNAL_IMPLEMENTERS
        )
        if external:
            expected_keys.add("source_evidence")
        if not isinstance(entry, dict) or set(entry) != expected_keys:
            raise ProvenanceError("implementation provenance entry has an unexpected schema")
        task_id = entry["task_id"]
        module_id = entry["module_id"]
        entry_type = entry["entry_type"]
        agent = entry["selected_agent"]
        model = entry["selected_model"]
        if not all(
            isinstance(value, str)
            for value in (entry_type, task_id, module_id, agent, model)
        ):
            raise ProvenanceError("implementation provenance entry has invalid identity fields")
        if not MODULE_ID_PATTERN.fullmatch(task_id) or not MODULE_ID_PATTERN.fullmatch(module_id):
            raise ProvenanceError("implementation provenance entry has invalid task_id or module_id")
        if task_id in task_ids:
            raise ProvenanceError("implementation provenance task_id must be unique")
        task_ids.add(task_id)
        if external:
            if raw["schema_version"] != 3:
                raise ProvenanceError("external implementation sources require schema_version=3")
            # 来源记录描述实际作者；后来复核的 Agent 不得认领既有实现。
            if agent == "human":
                valid_model = model == "none"
            elif agent == "unknown_source":
                valid_model = model == "unknown"
            else:
                valid_model = bool(MAIN_MODEL_PATTERN.fullmatch(model)) and model.split("/", 1)[0] not in {"current", "default"}
                valid_model = valid_model or (agent == "external_agent" and model == "unknown")
            if not valid_model:
                raise ProvenanceError("external implementation source has invalid actual model/effort")
            try:
                if not isinstance(entry["source_evidence"], str):
                    raise ValueError("invalid evidence path")
                parse_absolute_path(entry["source_evidence"])
            except (ValueError, argparse.ArgumentTypeError) as error:
                raise ProvenanceError("external source_evidence must be an absolute path") from error
        elif entry_type == "scope_contract" and agent == "main_agent":
            if not MAIN_MODEL_PATTERN.fullmatch(model) or model.split("/", 1)[0] in {"current", "default"}:
                raise ProvenanceError("main_agent scope contract requires actual model/effort")
        else:
            models = models_for_entry_type(entry_type)
            if agent not in models:
                raise ProvenanceError(
                    "implementation provenance selected_agent is not approved for entry_type"
                )
            expected_model, _ = models[agent]
            if model != expected_model:
                raise ProvenanceError("implementation provenance selected_model does not match selected_agent")
        if not isinstance(entry["plan_item_ids"], list) or not all(
            isinstance(item, str) and item for item in entry["plan_item_ids"]
        ):
            raise ProvenanceError("implementation provenance plan_item_ids must be a string list")
        if len(set(entry["plan_item_ids"])) != len(entry["plan_item_ids"]):
            raise ProvenanceError("implementation provenance plan_item_ids must be unique")
        if not isinstance(entry["files"], list) or not entry["files"]:
            raise ProvenanceError("implementation provenance entry must own at least one file")
        entry_claims: set[tuple[str, str]] = set()
        for file_entry in entry["files"]:
            if not isinstance(file_entry, dict) or set(file_entry) != {"repo", "path"}:
                raise ProvenanceError("implementation provenance file has an unexpected schema")
            if not isinstance(file_entry["repo"], str) or not isinstance(file_entry["path"], str):
                raise ProvenanceError("implementation provenance file has invalid fields")
            try:
                repo = str(parse_absolute_path(file_entry["repo"]))
                relative_path = validate_relative_path(file_entry["path"])
            except (argparse.ArgumentTypeError, ValueError) as error:
                raise ProvenanceError("implementation provenance file has an invalid path") from error
            claim = (repo, relative_path)
            if claim in entry_claims:
                raise ProvenanceError("implementation provenance entry cannot claim a file twice")
            entry_claims.add(claim)
            if entry_type == "implementation":
                if claim in implementation_claims:
                    raise ProvenanceError("implementation provenance implementation ownership must be unique")
                implementation_claims.add(claim)
            else:
                # 同一 plan 可由 Planner 与 Architect 共同提供 scope contract；
                # 这不等同于实现文件的多人所有权。
                scope_contract_claims.add(claim)
    if implementation_claims & scope_contract_claims:
        raise ProvenanceError(
            "implementation provenance cannot classify one file as both implementation and scope_contract"
        )
    return raw


def load_provenance(path: Path) -> dict[str, object]:
    try:
        return parse_provenance_bytes(path.read_bytes())
    except OSError as error:
        raise ProvenanceError(f"cannot read implementation provenance: {error}") from error


def scope_contract_snapshot_files(
    snapshot: dict[str, object], scope_contract_artifacts: tuple[str, ...]
) -> set[tuple[str, str]]:
    """返回同时属于冻结 contract 与 Git 发布 diff 的文件。

    scope contract 可以放在仓库外，也可以是仓库内已有 plan。只有后一种且该文件
    位于当前 diff 时，才必须由实际 plan 写入者的 scope_contract 条目认领。
    """
    expected_files = snapshot_file_paths(snapshot)
    result: set[tuple[str, str]] = set()
    for raw_artifact in scope_contract_artifacts:
        try:
            artifact = parse_absolute_path(raw_artifact)
        except argparse.ArgumentTypeError as error:
            raise ProvenanceError("scope contract artifact path is invalid") from error
        try:
            artifact_entry = snapshot_artifact_entry(snapshot, artifact)
        except ValueError as error:
            raise ProvenanceError("scope contract artifacts must be included in the snapshot") from error
        if artifact_entry["role"] not in SCOPE_CONTRACT_ROLES:
            raise ProvenanceError(
                "scope contract artifact must use plan_manifest or no_plan_contract role"
            )
        matches: list[tuple[str, str]] = []
        for repository in snapshot["repositories"]:
            repo = parse_absolute_path(repository["path"])
            try:
                relative_path = artifact.relative_to(repo).as_posix()
            except ValueError:
                continue
            claim = (str(repo), relative_path)
            if claim in expected_files:
                matches.append(claim)
        if len(matches) > 1:
            raise ProvenanceError(
                "scope contract artifact maps to multiple release repositories"
            )
        result.update(matches)
    return result


def implementation_family(entry: dict[str, object], snapshot: dict[str, object]) -> str | None:
    """核对非固定角色的冻结来源证据，返回实际模型家族或未知标记。"""
    agent = entry["selected_agent"]
    if agent not in EXTERNAL_IMPLEMENTERS:
        return models_for_entry_type("implementation")[agent][1]
    evidence_path = parse_absolute_path(entry["source_evidence"])
    try:
        artifact = snapshot_artifact_entry(snapshot, evidence_path)
        if artifact["role"] != "auxiliary":
            raise ValueError("wrong source evidence role")
        # 证据必须包含可读的用户声明、任务记录或 Git 来源说明，不能用空文件占位。
        if not read_verified_artifact(snapshot, evidence_path).decode("utf-8").strip():
            raise ValueError("empty source evidence")
    except (ValueError, OSError, UnicodeError) as error:
        raise ProvenanceError("external source evidence must be a nonempty frozen auxiliary artifact") from error
    if agent == "human":
        return None
    family_match = MODEL_FAMILY_PATTERN.search(entry["selected_model"].split("/", 1)[0])
    return family_match.group(1) if family_match else "unknown"


def validate_provenance(
    provenance: dict[str, object],
    snapshot: dict[str, object],
    expected_plan_item_ids: tuple[str, ...],
    scope_contract_artifacts: tuple[str, ...],
    *,
    risk_level: str,
) -> ProvenanceSummary:
    """校验来源覆盖范围，并结合明确的审查风险返回 Reviewer 与独立性。"""
    expected_files = snapshot_file_paths(snapshot)
    expected_contract_files = scope_contract_snapshot_files(
        snapshot, scope_contract_artifacts
    )
    expected_implementation_files = expected_files - expected_contract_files
    claimed_implementation_files: set[tuple[str, str]] = set()
    claimed_contract_files: set[tuple[str, str]] = set()
    plan_items: set[str] = set()
    families: set[str] = set()
    for entry in provenance["entries"]:
        entry_type = entry["entry_type"]
        if entry_type == "implementation":
            family = implementation_family(entry, snapshot)
            if family is not None:
                families.add(family)
        plan_items.update(entry["plan_item_ids"])
        for file_entry in entry["files"]:
            claim = (str(parse_absolute_path(file_entry["repo"])), file_entry["path"])
            if entry_type == "implementation":
                claimed_implementation_files.add(claim)
            else:
                # main_agent 的轻量例外只允许真正冻结为 plan_manifest 的文件。
                if entry["selected_agent"] == "main_agent":
                    plan_artifacts = tuple(
                        path for path in scope_contract_artifacts
                        if snapshot_artifact_entry(snapshot, parse_absolute_path(path))["role"] == "plan_manifest"
                    )
                    if claim not in scope_contract_snapshot_files(snapshot, plan_artifacts):
                        raise ProvenanceError("main_agent scope contract may only claim plan_manifest files")
                claimed_contract_files.add(claim)
    if claimed_implementation_files != expected_implementation_files:
        missing = expected_implementation_files - claimed_implementation_files
        unexpected = claimed_implementation_files - expected_implementation_files
        if missing:
            raise ProvenanceError(
                "implementation provenance does not cover implementation snapshot files"
            )
        raise ProvenanceError(
            "implementation provenance contains implementation files outside its scope"
        )
    if claimed_contract_files != expected_contract_files:
        missing = expected_contract_files - claimed_contract_files
        unexpected = claimed_contract_files - expected_contract_files
        if missing:
            raise ProvenanceError(
                "implementation provenance does not cover scope contract snapshot files"
            )
        raise ProvenanceError(
            "implementation provenance contains scope contract files outside its scope"
        )
    if not plan_items.issubset(set(expected_plan_item_ids)):
        raise ProvenanceError("implementation provenance plan_item_ids exceed expected plan items")
    canonical = canonical_families(families)
    reviewer, independence = reviewer_for_risk(risk_level, canonical)
    return ProvenanceSummary(canonical, reviewer, independence)


def validate_provenance_artifact(
    snapshot: dict[str, object], provenance_path: Path
) -> None:
    """来源文件必须是仓外、且明确声明 role 的冻结证据。"""
    try:
        artifact = snapshot_artifact_entry(snapshot, provenance_path)
    except ValueError as error:
        raise ProvenanceError(
            "implementation provenance must be included in the snapshot"
        ) from error
    if artifact["role"] != "implementation_provenance":
        raise ProvenanceError(
            "implementation provenance artifact must use implementation_provenance role"
        )
    for repository in snapshot["repositories"]:
        repo = parse_absolute_path(repository["path"])
        try:
            provenance_path.relative_to(repo)
        except ValueError:
            continue
        raise ProvenanceError("implementation provenance must stay outside release repositories")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-manifest", type=parse_optional_path, required=True)
    parser.add_argument("--implementation-provenance", type=parse_optional_path, required=True)
    parser.add_argument(
        "--scope-contract-artifact",
        type=parse_absolute_path,
        action="append",
        required=True,
    )
    # 风险必须由当前审查范围明确给出，禁止从实现模型隐式推断。
    parser.add_argument("--risk-level", choices=("small", "normal", "high"), required=True)
    parser.add_argument("--expected-plan-item-ids", default="none")
    args = parser.parse_args()
    if args.snapshot_manifest is None or args.implementation_provenance is None:
        parser.error("snapshot-manifest and implementation-provenance must be absolute paths")
    expected_plan_item_ids = () if args.expected_plan_item_ids == "none" else tuple(
        item for item in args.expected_plan_item_ids.split(",") if item
    )
    try:
        snapshot, _ = load_and_verify_snapshot(args.snapshot_manifest)
        validate_provenance_artifact(snapshot, args.implementation_provenance)
        provenance = parse_provenance_bytes(
            read_verified_artifact(snapshot, args.implementation_provenance)
        )
        summary = validate_provenance(
            provenance,
            snapshot,
            expected_plan_item_ids,
            tuple(str(path) for path in args.scope_contract_artifact),
            risk_level=args.risk_level,
        )
    except (ProvenanceError, ValueError) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                "implementation_model_families": list(summary.families),
                "selected_reviewer": summary.selected_reviewer,
                "review_independence": summary.review_independence,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
