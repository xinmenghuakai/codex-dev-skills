#!/usr/bin/env python3
"""校验 feature-delivery reviewer 的结构化完成门禁。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

from plan_manifest import (
    PLAN_ITEM_PATTERN,
    PlanManifestError,
    parse_plan_manifest,
)
from freeze_snapshot import (
    canonical_fingerprint,
    canonical_release_binding_fingerprint,
    load_and_verify_snapshot,
    load_and_verify_release_binding,
    parse_absolute_path,
    parse_absolute_literal_path,
    read_verified_artifact,
    review_input_fingerprint,
    snapshot_artifact_entry,
    snapshot_artifact_paths,
    validate_release_binding_structure,
    validate_snapshot_structure,
    write_new_json,
)
from implementation_provenance import (
    ProvenanceError,
    ProvenanceSummary,
    canonical_families,
    parse_provenance_bytes,
    load_agent_model,
    reviewer_for_risk,
    validate_provenance_artifact,
    validate_provenance,
)


PASS_IDS = {
    "small": ("targeted_fix",),
    "normal": ("full_surface", "clean_room"),
    "high": (
        "intent_contract",
        "state_failure",
        "data_integration",
        "test_counterexample",
        "clean_room",
    ),
}
RISK_RANK = {"small": 0, "normal": 1, "high": 2}
REVIEW_GATE_SCOPES = ("review_only", "test_release", "final_release")
REVIEW_GATE_SCOPE_RANK = {scope: index for index, scope in enumerate(REVIEW_GATE_SCOPES)}
BASELINE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}")
FINDING_PATTERN = re.compile(r"F[0-9]{3,}")
REVIEW_REPORT_SCHEMA_VERSION = 1
GATE_EVIDENCE_SCHEMA_VERSION = 4
FINDINGS_EVIDENCE_SCHEMA_VERSION = 1
REVIEWER_AGENTS = (
    "feature_delivery_reviewer",
    "feature_delivery_sol_reviewer",
)


def parse_bool(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise argparse.ArgumentTypeError("must be true or false")


def parse_baseline(value: str) -> str:
    if not BASELINE_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError("must be a non-empty token without whitespace")
    return value


def parse_optional_evidence_path(value: str) -> Path | None:
    if value == "none":
        return None
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("must be none or an absolute evidence path")
    return path.resolve()


def parse_optional_output_evidence_path(value: str) -> Path | None:
    """Gate 输出保留字面路径，避免 .resolve() 先跟随可替换的中间软链。"""
    if value == "none":
        return None
    try:
        return parse_absolute_literal_path(value)
    except argparse.ArgumentTypeError as error:
        raise argparse.ArgumentTypeError(
            "must be none or an absolute literal evidence path"
        ) from error


def parse_optional_snapshot_manifest(value: str) -> Path | None:
    if value == "none":
        return None
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("must be none or an absolute snapshot manifest path")
    return path.resolve()


def parse_optional_provenance_path(value: str) -> Path | None:
    if value == "none":
        return None
    try:
        return parse_absolute_path(value)
    except argparse.ArgumentTypeError as error:
        raise argparse.ArgumentTypeError(
            "must be none or an absolute implementation provenance path"
        ) from error


def parse_model_families(value: str) -> tuple[str, ...]:
    if value == "none":
        return ()
    values = tuple(item.strip() for item in value.split(",") if item.strip())
    if not values or len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("must be none or unique comma-separated model families")
    try:
        canonical = canonical_families(values)
    except ProvenanceError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    if canonical != values:
        raise argparse.ArgumentTypeError("model families must use luna,terra,sol,astra,unknown order")
    return canonical


def parse_finding_ids(value: str) -> tuple[str, ...]:
    if value == "none":
        return ()
    result = tuple(item.strip() for item in value.split(",") if item.strip())
    if not result or any(not FINDING_PATTERN.fullmatch(item) for item in result):
        raise argparse.ArgumentTypeError("must be none or comma-separated F001-style IDs")
    return result


def parse_completed_passes(value: str) -> tuple[str, ...]:
    if value == "none":
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def parse_plan_item_ids(value: str) -> tuple[str, ...]:
    if value == "none":
        return ()
    result = tuple(item.strip() for item in value.split(","))
    if not result or any(not PLAN_ITEM_PATTERN.fullmatch(item) for item in result):
        raise argparse.ArgumentTypeError(
            "must be none or comma-separated stable plan item IDs"
        )
    return result


def parse_manifest_path(value: str) -> Path | None:
    if value == "none":
        return None
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("must be none or an absolute plan path")
    return path.resolve()


def is_path_within(path: Path, parent: Path) -> bool:
    """判断 Gate 输出是否会污染或覆盖已冻结的发布范围。"""
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def is_same_existing_file(left: Path, right: Path) -> bool:
    """仅用于诊断同一既存文件的字面路径别名；安全写入仍由 dir_fd 链负责。"""
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--expected-baseline", type=parse_baseline, required=True)
    result.add_argument("--baseline", type=parse_baseline, required=True)
    result.add_argument("--expected-risk", choices=PASS_IDS, required=True)
    result.add_argument("--risk", choices=PASS_IDS, required=True)
    result.add_argument(
        "--expected-review-phase", choices=("initial", "rereview"), required=True
    )
    result.add_argument("--review-phase", choices=("initial", "rereview"), required=True)
    result.add_argument(
        "--expected-review-gate-scope", choices=REVIEW_GATE_SCOPES, required=True
    )
    result.add_argument(
        "--review-gate-scope", choices=REVIEW_GATE_SCOPES, required=True
    )
    result.add_argument("--scope-promotion", type=parse_bool, required=True)
    result.add_argument(
        "--previous-gate-evidence", type=parse_optional_evidence_path, required=True
    )
    result.add_argument(
        "--snapshot-manifest",
        type=parse_optional_snapshot_manifest,
        required=True,
    )
    result.add_argument(
        "--scope-contract-artifact",
        type=parse_absolute_path,
        action="append",
        default=[],
    )
    result.add_argument(
        "--implementation-provenance",
        type=parse_optional_provenance_path,
        required=True,
    )
    result.add_argument(
        "--review-report", type=parse_optional_evidence_path, required=True
    )
    result.add_argument(
        "--release-binding", type=parse_optional_evidence_path, required=True
    )
    result.add_argument(
        "--no-plan-contract", type=parse_manifest_path, required=True
    )
    result.add_argument(
        "--implementation-model-families", type=parse_model_families, required=True
    )
    result.add_argument(
        "--selected-reviewer",
        choices=("feature_delivery_reviewer", "feature_delivery_sol_reviewer", "none"),
        required=True,
    )
    result.add_argument(
        "--review-independence",
        choices=("independent", "same_family_unavoidable", "source_unknown", "none"),
        required=True,
    )
    result.add_argument(
        "--release-diff-kind",
        choices=("not_applicable", "same", "bounded_delta", "changed"),
        required=True,
    )
    result.add_argument("--reused-passes", type=parse_completed_passes, required=True)
    result.add_argument("--delta-reviewed", type=parse_bool, required=True)
    result.add_argument(
        "--write-gate-evidence",
        type=parse_optional_output_evidence_path,
        required=True,
    )
    result.add_argument(
        "--write-review-evidence",
        type=parse_optional_output_evidence_path,
        required=True,
    )
    result.add_argument("--required-passes", type=int, required=True)
    result.add_argument("--completed-passes", type=parse_completed_passes, required=True)
    result.add_argument("--ledger-closed", type=parse_bool, required=True)
    result.add_argument(
        "--expected-plan-coverage-required", type=parse_bool, required=True
    )
    result.add_argument("--plan-coverage-required", type=parse_bool, required=True)
    result.add_argument(
        "--expected-plan-manifest", type=parse_manifest_path, required=True
    )
    result.add_argument("--plan-manifest", type=parse_manifest_path, required=True)
    result.add_argument(
        "--expected-plan-item-ids", type=parse_plan_item_ids, required=True
    )
    result.add_argument("--gate-plan-item-ids", type=parse_plan_item_ids, required=True)
    result.add_argument(
        "--reported-plan-item-ids", type=parse_plan_item_ids, required=True
    )
    result.add_argument(
        "--reviewed-plan-item-ids", type=parse_plan_item_ids, required=True
    )
    result.add_argument(
        "--satisfied-plan-item-ids", type=parse_plan_item_ids, required=True
    )
    result.add_argument(
        "--not-applicable-plan-item-ids", type=parse_plan_item_ids, required=True
    )
    result.add_argument(
        "--missing-plan-item-ids", type=parse_plan_item_ids, required=True
    )
    result.add_argument(
        "--blocked-plan-item-ids", type=parse_plan_item_ids, required=True
    )
    result.add_argument(
        "--external-plan-item-ids", type=parse_plan_item_ids, required=True
    )
    result.add_argument("--expected-sql-check-required", type=parse_bool, required=True)
    result.add_argument("--sql-check-required", type=parse_bool, required=True)
    result.add_argument(
        "--sql-check", choices=("completed", "not_applicable", "blocked"), required=True
    )
    result.add_argument(
        "--dynamic-validation",
        choices=("completed", "limited", "blocked", "not_applicable"),
        required=True,
    )
    result.add_argument("--findings", type=int, required=True)
    result.add_argument("--gate-finding-ids", type=parse_finding_ids, required=True)
    result.add_argument("--reported-finding-ids", type=parse_finding_ids, required=True)
    result.add_argument(
        "--gate-finding-plan-item-ids", type=parse_plan_item_ids, required=True
    )
    result.add_argument(
        "--reported-finding-plan-item-ids", type=parse_plan_item_ids, required=True
    )
    result.add_argument("--initial-findings", type=int, required=True)
    result.add_argument("--baseline-findings", type=int, required=True)
    result.add_argument("--fix-introduced", type=int, required=True)
    result.add_argument("--newly-exposed", type=int, required=True)
    result.add_argument("--unknown-origin", type=int, required=True)
    result.add_argument("--gate", choices=("pass", "findings", "blocked"), required=True)
    result.add_argument("--release-ready", type=parse_bool, required=True)
    return result


def fail(errors: list[str]) -> int:
    for error in errors:
        print(f"review gate invalid: {error}", file=sys.stderr)
    return 1


def review_gate_payload(args: argparse.Namespace) -> dict[str, object]:
    """提取 Reviewer 必须签回的完整结论，避免 Gate 只信任 CLI 自报。"""
    return {
        "baseline_id": args.baseline,
        "risk_level": args.risk,
        "review_phase": args.review_phase,
        "review_gate_scope": args.review_gate_scope,
        "required_passes": args.required_passes,
        "completed_passes": list(args.completed_passes),
        "ledger_closed": args.ledger_closed,
        "plan_coverage_required": args.plan_coverage_required,
        "plan_manifest": "none" if args.plan_manifest is None else str(args.plan_manifest),
        "plan_item_ids": list(args.gate_plan_item_ids),
        "reported_plan_item_ids": list(args.reported_plan_item_ids),
        "reviewed_plan_item_ids": list(args.reviewed_plan_item_ids),
        "satisfied_plan_item_ids": list(args.satisfied_plan_item_ids),
        "not_applicable_plan_item_ids": list(args.not_applicable_plan_item_ids),
        "missing_plan_item_ids": list(args.missing_plan_item_ids),
        "blocked_plan_item_ids": list(args.blocked_plan_item_ids),
        "external_plan_item_ids": list(args.external_plan_item_ids),
        "sql_check_required": args.sql_check_required,
        "sql_check": args.sql_check,
        "dynamic_validation": args.dynamic_validation,
        "findings": args.findings,
        "finding_ids": list(args.gate_finding_ids),
        "reported_finding_ids": list(args.reported_finding_ids),
        "finding_plan_item_ids": list(args.gate_finding_plan_item_ids),
        "reported_finding_plan_item_ids": list(args.reported_finding_plan_item_ids),
        "origins": {
            "initial": args.initial_findings,
            "baseline": args.baseline_findings,
            "fix_introduced": args.fix_introduced,
            "newly_exposed": args.newly_exposed,
            "unknown": args.unknown_origin,
        },
        "gate": args.gate,
        "release_ready": args.release_ready,
    }


def parse_review_report_bytes(data: bytes) -> dict[str, object]:
    """解析 Reviewer 的结构化回传；实际 artefact 哈希由调用方先验证。"""
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read review report: {error}") from error
    expected = {
        "schema_version",
        "reviewed_release_fingerprint",
        "selected_reviewer",
        "selected_model",
        "implementation_model_families",
        "review_independence",
        "gate",
        "validation_evidence_paths",
    }
    if not isinstance(raw, dict) or set(raw) != expected:
        raise ValueError("review report has an unexpected schema")
    if raw["schema_version"] != REVIEW_REPORT_SCHEMA_VERSION:
        raise ValueError(
            f"review report schema_version must be {REVIEW_REPORT_SCHEMA_VERSION}"
        )
    if not isinstance(raw["reviewed_release_fingerprint"], str) or not re.fullmatch(
        r"[a-f0-9]{64}", raw["reviewed_release_fingerprint"]
    ):
        raise ValueError("review report has an invalid reviewed_release_fingerprint")
    try:
        reviewer_models = {
            agent: load_agent_model(agent)[0] for agent in REVIEWER_AGENTS
        }
    except ProvenanceError as error:
        raise ValueError("cannot load reviewer Agent model config") from error
    if raw["selected_reviewer"] not in reviewer_models:
        raise ValueError("review report has an invalid selected_reviewer")
    if raw["selected_model"] != reviewer_models[raw["selected_reviewer"]]:
        raise ValueError("review report selected_model does not match selected_reviewer")
    try:
        families = canonical_families(raw["implementation_model_families"])
    except (ProvenanceError, TypeError) as error:
        raise ValueError("review report has invalid implementation_model_families") from error
    if list(families) != raw["implementation_model_families"]:
        raise ValueError("review report model families are not canonical")
    if not isinstance(raw["gate"], dict):
        raise ValueError("review report gate must be an object")
    reviewer, independence = reviewer_for_risk(raw["gate"].get("risk_level"), families)
    if (
        raw["selected_reviewer"] != reviewer
        or raw["review_independence"] != independence
    ):
        raise ValueError("review report reviewer route does not match review risk and implementation families")
    if not isinstance(raw["validation_evidence_paths"], list) or not all(
        isinstance(item, str) for item in raw["validation_evidence_paths"]
    ):
        raise ValueError("review report validation_evidence_paths must be a string list")
    if len(set(raw["validation_evidence_paths"])) != len(raw["validation_evidence_paths"]):
        raise ValueError("review report validation_evidence_paths must be unique")
    if not isinstance(raw["gate"], dict):
        raise ValueError("review report gate must be an object")
    return raw


def validate_review_report(
    report: dict[str, object],
    snapshot: dict[str, object],
    args: argparse.Namespace,
    provenance_summary: ProvenanceSummary,
) -> None:
    """把报告、冻结范围、来源路由和 CLI 声明收敛为同一份结论。"""
    if report["reviewed_release_fingerprint"] != review_input_fingerprint(snapshot):
        raise ValueError("review report does not bind the frozen review input")
    if report["selected_reviewer"] != provenance_summary.selected_reviewer:
        raise ValueError("review report selected reviewer does not match implementation provenance")
    if report["implementation_model_families"] != list(provenance_summary.families):
        raise ValueError("review report model families do not match implementation provenance")
    if report["review_independence"] != provenance_summary.review_independence:
        raise ValueError("review report independence does not match implementation provenance")
    expected_gate = review_gate_payload(args)
    if args.scope_promotion:
        report_scope = report["gate"].get("review_gate_scope")
        if report_scope not in REVIEW_GATE_SCOPES:
            raise ValueError("review report has an invalid reviewed gate scope")
        # 同一冻结 Review 可提升发布范围；不能要求 Reviewer 事后重写原报告。
        expected_gate["review_gate_scope"] = report_scope
    if report["gate"] != expected_gate:
        raise ValueError("review report gate conclusion does not match Gate input")
    for raw_path in report["validation_evidence_paths"]:
        try:
            artifact = snapshot_artifact_entry(snapshot, parse_absolute_path(raw_path))
        except (argparse.ArgumentTypeError, ValueError) as error:
            raise ValueError("review report validation evidence is not frozen") from error
        if artifact["role"] != "validation_evidence":
            raise ValueError("review report validation evidence must use validation_evidence role")


def load_gate_evidence(path: Path) -> dict[str, object]:
    """读取此前已通过 Gate 的复用证据。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read previous gate evidence: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("previous gate evidence must be a JSON object")

    required = {
        "schema_version",
        "baseline_id",
        "review_phase",
        "review_gate_scope",
        "risk_level",
        "completed_passes",
        "gate",
        "release_ready",
        "snapshot_fingerprint",
        "review_input_fingerprint",
        "snapshot",
        "scope_contract_artifacts",
        "no_plan_contract",
        "implementation_provenance",
        "implementation_model_families",
        "selected_reviewer",
        "review_independence",
        "review_report",
        "review_report_sha256",
        "validation_evidence_paths",
        "release_binding_path",
        "release_binding_fingerprint",
        "release_binding",
        "sql_check_required",
        "sql_check",
        "dynamic_validation",
        "plan_coverage_required",
        "plan_manifest",
        "plan_item_ids",
    }
    if set(raw) != required:
        raise ValueError("previous gate evidence has an unexpected schema")
    if raw["schema_version"] != GATE_EVIDENCE_SCHEMA_VERSION:
        raise ValueError(
            f"previous gate evidence schema_version must be {GATE_EVIDENCE_SCHEMA_VERSION}"
        )
    if not isinstance(raw["baseline_id"], str) or not BASELINE_PATTERN.fullmatch(raw["baseline_id"]):
        raise ValueError("previous gate evidence has an invalid baseline_id")
    if raw["review_phase"] not in ("initial", "rereview"):
        raise ValueError("previous gate evidence has an invalid review_phase")
    if raw["review_gate_scope"] not in REVIEW_GATE_SCOPES:
        raise ValueError("previous gate evidence has an invalid review_gate_scope")
    if raw["risk_level"] not in PASS_IDS:
        raise ValueError("previous gate evidence has an invalid risk_level")
    if not isinstance(raw["completed_passes"], list) or tuple(raw["completed_passes"]) != PASS_IDS[raw["risk_level"]]:
        raise ValueError("previous gate evidence has invalid completed_passes")
    if raw["gate"] != "pass" or raw["release_ready"] is not True:
        raise ValueError("previous gate evidence must be a release-ready pass Gate")
    if not isinstance(raw["snapshot_fingerprint"], str) or not re.fullmatch(r"[a-f0-9]{64}", raw["snapshot_fingerprint"]):
        raise ValueError("previous gate evidence has an invalid snapshot fingerprint")
    try:
        snapshot = validate_snapshot_structure(raw["snapshot"])
    except ValueError as error:
        raise ValueError(f"previous gate evidence has an invalid snapshot: {error}") from error
    if canonical_fingerprint(snapshot) != raw["snapshot_fingerprint"]:
        raise ValueError("previous gate evidence snapshot fingerprint does not match snapshot")
    if raw["review_input_fingerprint"] != review_input_fingerprint(snapshot):
        raise ValueError("previous gate evidence review input fingerprint does not match snapshot")
    if not isinstance(raw["scope_contract_artifacts"], list) or not raw["scope_contract_artifacts"]:
        raise ValueError("previous gate evidence has invalid scope_contract_artifacts")
    if not all(isinstance(item, str) for item in raw["scope_contract_artifacts"]):
        raise ValueError("previous gate evidence has invalid scope_contract_artifacts")
    if len(set(raw["scope_contract_artifacts"])) != len(raw["scope_contract_artifacts"]):
        raise ValueError("previous gate evidence scope_contract_artifacts must be unique")
    artifacts = snapshot_artifact_paths(snapshot)
    if not set(raw["scope_contract_artifacts"]).issubset(artifacts):
        raise ValueError("previous gate evidence scope contracts are not in its snapshot")
    for scope_path in raw["scope_contract_artifacts"]:
        if snapshot_artifact_entry(snapshot, parse_absolute_path(scope_path))["role"] not in (
            "plan_manifest",
            "no_plan_contract",
        ):
            raise ValueError("previous gate evidence scope contract has an unsafe artifact role")
    if raw["no_plan_contract"] != "none":
        if not isinstance(raw["no_plan_contract"], str):
            raise ValueError("previous gate evidence has an invalid no-plan contract")
        if raw["no_plan_contract"] not in raw["scope_contract_artifacts"]:
            raise ValueError("previous gate evidence no-plan contract is not a scope contract")
        if snapshot_artifact_entry(
            snapshot, parse_absolute_path(raw["no_plan_contract"])
        )["role"] != "no_plan_contract":
            raise ValueError("previous gate evidence no-plan contract has an invalid artifact role")
    if not isinstance(raw["implementation_provenance"], str):
        raise ValueError("previous gate evidence has an invalid implementation provenance")
    if raw["implementation_provenance"] not in artifacts:
        raise ValueError("previous gate evidence implementation provenance is not in its snapshot")
    if snapshot_artifact_entry(
        snapshot, parse_absolute_path(raw["implementation_provenance"])
    )["role"] != "implementation_provenance":
        raise ValueError("previous gate evidence implementation provenance has an invalid artifact role")
    if not isinstance(raw["implementation_model_families"], list):
        raise ValueError("previous gate evidence has invalid implementation model families")
    try:
        families = canonical_families(raw["implementation_model_families"])
    except ProvenanceError as error:
        raise ValueError(str(error)) from error
    if list(families) != raw["implementation_model_families"]:
        raise ValueError("previous gate evidence model families are not canonical")
    reviewer, independence = reviewer_for_risk(raw["risk_level"], families)
    if raw["selected_reviewer"] != reviewer or raw["review_independence"] != independence:
        raise ValueError("previous gate evidence reviewer route does not match review risk and model families")
    if not isinstance(raw["review_report"], str) or raw["review_report"] not in artifacts:
        raise ValueError("previous gate evidence review report is not in its snapshot")
    report_artifact = snapshot_artifact_entry(snapshot, parse_absolute_path(raw["review_report"]))
    if report_artifact["role"] != "review_report":
        raise ValueError("previous gate evidence review report has an invalid artifact role")
    if raw["review_report_sha256"] != report_artifact["sha256"]:
        raise ValueError("previous gate evidence review report digest does not match snapshot")
    if not isinstance(raw["validation_evidence_paths"], list) or not all(
        isinstance(item, str) for item in raw["validation_evidence_paths"]
    ):
        raise ValueError("previous gate evidence has invalid validation evidence paths")
    for validation_path in raw["validation_evidence_paths"]:
        if validation_path not in artifacts or snapshot_artifact_entry(
            snapshot, parse_absolute_path(validation_path)
        )["role"] != "validation_evidence":
            raise ValueError("previous gate evidence validation evidence is not frozen")
    if raw["review_gate_scope"] == "review_only":
        if (
            raw["release_binding_path"] != "none"
            or raw["release_binding_fingerprint"] != "none"
            or raw["release_binding"] is not None
        ):
            raise ValueError("review_only gate evidence must not contain a release binding")
    else:
        if not isinstance(raw["release_binding_path"], str):
            raise ValueError("previous gate evidence has an invalid release binding path")
        try:
            parse_absolute_path(raw["release_binding_path"])
        except argparse.ArgumentTypeError as error:
            raise ValueError("previous gate evidence has an invalid release binding path") from error
        try:
            binding = validate_release_binding_structure(raw["release_binding"], snapshot)
        except ValueError as error:
            raise ValueError("previous gate evidence has an invalid release binding") from error
        if (
            not isinstance(raw["release_binding_fingerprint"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", raw["release_binding_fingerprint"])
            or canonical_release_binding_fingerprint(binding)
            != raw["release_binding_fingerprint"]
        ):
            raise ValueError("previous gate evidence release binding fingerprint does not match binding")
    if not isinstance(raw["sql_check_required"], bool) or raw["sql_check"] not in (
        "completed",
        "not_applicable",
        "blocked",
    ) or raw["dynamic_validation"] not in (
        "completed",
        "limited",
        "blocked",
        "not_applicable",
    ):
        raise ValueError("previous gate evidence has invalid validation prerequisites")
    if not isinstance(raw["plan_coverage_required"], bool):
        raise ValueError("previous gate evidence has invalid plan coverage prerequisite")
    if raw["plan_manifest"] != "none" and not isinstance(raw["plan_manifest"], str):
        raise ValueError("previous gate evidence has invalid plan manifest")
    if not isinstance(raw["plan_item_ids"], list) or not all(
        isinstance(item, str) and PLAN_ITEM_PATTERN.fullmatch(item)
        for item in raw["plan_item_ids"]
    ):
        raise ValueError("previous gate evidence has invalid plan item IDs")
    return raw


def write_gate_evidence(
    path: Path,
    args: argparse.Namespace,
    snapshot: dict[str, object],
    snapshot_fingerprint: str,
    provenance_summary: ProvenanceSummary,
    scope_contract_artifacts: tuple[str, ...],
    review_report: dict[str, object],
    release_binding: dict[str, object] | None,
    release_binding_fingerprint: str | None,
) -> None:
    """独占保存当前通过 Gate 的复用证据，供后续 scope 提升校验。"""
    if args.review_report is None:
        raise ValueError("cannot write gate evidence without a review report")
    report_artifact = snapshot_artifact_entry(snapshot, args.review_report)
    evidence = {
        "schema_version": GATE_EVIDENCE_SCHEMA_VERSION,
        "baseline_id": args.baseline,
        "review_phase": args.review_phase,
        "review_gate_scope": args.review_gate_scope,
        "risk_level": args.risk,
        "completed_passes": list(args.completed_passes),
        "gate": args.gate,
        "release_ready": args.release_ready,
        "snapshot_fingerprint": snapshot_fingerprint,
        "review_input_fingerprint": review_input_fingerprint(snapshot),
        "snapshot": snapshot,
        "scope_contract_artifacts": list(scope_contract_artifacts),
        "no_plan_contract": "none"
        if args.no_plan_contract is None
        else str(args.no_plan_contract),
        "implementation_provenance": str(args.implementation_provenance),
        "implementation_model_families": list(provenance_summary.families),
        "selected_reviewer": provenance_summary.selected_reviewer,
        "review_independence": provenance_summary.review_independence,
        "review_report": str(args.review_report),
        "review_report_sha256": report_artifact["sha256"],
        "validation_evidence_paths": list(review_report["validation_evidence_paths"]),
        "release_binding_path": "none"
        if args.release_binding is None
        else str(args.release_binding),
        "release_binding_fingerprint": "none"
        if release_binding_fingerprint is None
        else release_binding_fingerprint,
        "release_binding": release_binding,
        "sql_check_required": args.sql_check_required,
        "sql_check": args.sql_check,
        "dynamic_validation": args.dynamic_validation,
        "plan_coverage_required": args.plan_coverage_required,
        "plan_manifest": "none" if args.plan_manifest is None else str(args.plan_manifest),
        "plan_item_ids": list(args.gate_plan_item_ids),
    }
    write_new_json(
        path,
        evidence,
        forbidden_roots=tuple(
            Path(repository["path"]) for repository in snapshot["repositories"]
        ),
    )


def write_review_evidence(
    path: Path,
    args: argparse.Namespace,
    snapshot: dict[str, object],
    snapshot_fingerprint: str,
    provenance_summary: ProvenanceSummary,
    scope_contract_artifacts: tuple[str, ...],
    review_report: dict[str, object],
) -> None:
    """保存 findings 的完整、不可提升、不可发布的审查证据。"""
    if args.review_report is None:
        raise ValueError("cannot write review evidence without a review report")
    report_artifact = snapshot_artifact_entry(snapshot, args.review_report)
    evidence = {
        "schema_version": FINDINGS_EVIDENCE_SCHEMA_VERSION,
        "evidence_kind": "review_findings",
        "baseline_id": args.baseline,
        "review_phase": args.review_phase,
        "review_gate_scope": args.review_gate_scope,
        "risk_level": args.risk,
        "snapshot_fingerprint": snapshot_fingerprint,
        "review_input_fingerprint": review_input_fingerprint(snapshot),
        "snapshot": snapshot,
        "scope_contract_artifacts": list(scope_contract_artifacts),
        "no_plan_contract": "none"
        if args.no_plan_contract is None
        else str(args.no_plan_contract),
        "implementation_provenance": str(args.implementation_provenance),
        "implementation_model_families": list(provenance_summary.families),
        "selected_reviewer": provenance_summary.selected_reviewer,
        "review_independence": provenance_summary.review_independence,
        "review_report": str(args.review_report),
        "review_report_sha256": report_artifact["sha256"],
        "validation_evidence_paths": list(review_report["validation_evidence_paths"]),
        "gate": review_gate_payload(args),
    }
    write_new_json(
        path,
        evidence,
        forbidden_roots=tuple(
            Path(repository["path"]) for repository in snapshot["repositories"]
        ),
    )


def main() -> int:
    args = parser().parse_args()
    errors: list[str] = []
    expected_passes = PASS_IDS[args.risk]
    completed_passes = args.completed_passes
    origins = (
        args.initial_findings,
        args.baseline_findings,
        args.fix_introduced,
        args.newly_exposed,
        args.unknown_origin,
    )
    expected_plan_items = args.expected_plan_item_ids
    plan_item_lists = {
        "expected": expected_plan_items,
        "gate": args.gate_plan_item_ids,
        "reported": args.reported_plan_item_ids,
        "reviewed": args.reviewed_plan_item_ids,
        "satisfied": args.satisfied_plan_item_ids,
        "not_applicable": args.not_applicable_plan_item_ids,
        "missing": args.missing_plan_item_ids,
        "blocked": args.blocked_plan_item_ids,
        "external": args.external_plan_item_ids,
        "gate_finding": args.gate_finding_plan_item_ids,
        "reported_finding": args.reported_finding_plan_item_ids,
    }
    status_plan_items = (
        args.satisfied_plan_item_ids
        + args.not_applicable_plan_item_ids
        + args.missing_plan_item_ids
        + args.blocked_plan_item_ids
        + args.external_plan_item_ids
    )

    if args.baseline != args.expected_baseline:
        errors.append(
            f"baseline={args.baseline}, expected={args.expected_baseline}"
        )
    if RISK_RANK[args.risk] < RISK_RANK[args.expected_risk]:
        errors.append(
            f"risk cannot be downgraded from {args.expected_risk} to {args.risk}"
        )
    if args.review_phase != args.expected_review_phase:
        errors.append(
            f"review_phase={args.review_phase}, expected={args.expected_review_phase}"
        )
    if args.review_gate_scope != args.expected_review_gate_scope:
        errors.append(
            "review_gate_scope="
            f"{args.review_gate_scope}, expected={args.expected_review_gate_scope}"
        )
    snapshot: dict[str, object] | None = None
    snapshot_fingerprint = None
    if args.snapshot_manifest is not None:
        try:
            snapshot, snapshot_fingerprint = load_and_verify_snapshot(args.snapshot_manifest)
        except ValueError as error:
            errors.append(str(error))
    if snapshot is not None:
        for repository in snapshot["repositories"]:
            repository_path = Path(repository["path"])
            if (
                args.snapshot_manifest is not None
                and is_path_within(args.snapshot_manifest, repository_path)
            ):
                errors.append("snapshot manifest must stay outside release repositories")
                break
        for repository in snapshot["repositories"]:
            repository_path = Path(repository["path"])
            if (
                args.implementation_provenance is not None
                and is_path_within(args.implementation_provenance, repository_path)
            ):
                errors.append(
                    "implementation provenance must stay outside release repositories"
                )
                break

    scope_contract_artifacts = tuple(str(path) for path in args.scope_contract_artifact)
    if len(set(scope_contract_artifacts)) != len(scope_contract_artifacts):
        errors.append("scope contract artifacts must be unique")
    provenance_summary: ProvenanceSummary | None = None
    review_report: dict[str, object] | None = None
    release_binding: dict[str, object] | None = None
    release_binding_fingerprint: str | None = None

    if snapshot is not None:
        for raw_path in scope_contract_artifacts:
            try:
                scope_artifact = snapshot_artifact_entry(
                    snapshot, parse_absolute_path(raw_path)
                )
            except (argparse.ArgumentTypeError, ValueError):
                errors.append("scope contract artifacts must be included in the snapshot")
                continue
            if scope_artifact["role"] not in ("plan_manifest", "no_plan_contract"):
                errors.append(
                    "scope contract artifacts must use plan_manifest or no_plan_contract role"
                )
        if args.plan_manifest is not None:
            try:
                plan_artifact = snapshot_artifact_entry(snapshot, args.plan_manifest)
                if plan_artifact["role"] != "plan_manifest":
                    errors.append("plan manifest must use plan_manifest artifact role")
            except ValueError:
                errors.append("plan manifest must be included in the snapshot")
        if args.no_plan_contract is not None:
            try:
                no_plan_artifact = snapshot_artifact_entry(snapshot, args.no_plan_contract)
                if no_plan_artifact["role"] != "no_plan_contract":
                    errors.append("no-plan contract must use no_plan_contract artifact role")
            except ValueError:
                errors.append("no-plan contract must be included in the snapshot")
            for repository in snapshot["repositories"]:
                if is_path_within(args.no_plan_contract, Path(repository["path"])):
                    errors.append("no-plan contract must stay outside release repositories")
                    break

    completed_review = args.gate in ("pass", "findings")
    if completed_review:
        label = "pass" if args.gate == "pass" else "findings"
        if args.snapshot_manifest is None or snapshot is None:
            errors.append(f"{label} gate requires a verified snapshot manifest")
        if not scope_contract_artifacts:
            errors.append(f"{label} gate requires at least one scope contract artifact")
        if args.implementation_provenance is None:
            errors.append(f"{label} gate requires implementation provenance")
        if args.review_report is None:
            errors.append(f"{label} gate requires a structured review report")
        if args.gate == "pass" and args.write_gate_evidence is None:
            errors.append("pass gate requires writing gate evidence")
        if args.gate == "findings" and args.write_review_evidence is None:
            errors.append("findings gate requires writing review evidence")
        if snapshot is not None:
            artifact_paths = snapshot_artifact_paths(snapshot)
            if not set(scope_contract_artifacts).issubset(artifact_paths):
                errors.append("scope contract artifacts must be included in the snapshot")
            if args.implementation_provenance is not None:
                provenance_path = str(args.implementation_provenance)
                if provenance_path not in artifact_paths:
                    errors.append("implementation provenance must be included in the snapshot")
                if provenance_path in scope_contract_artifacts:
                    errors.append("implementation provenance cannot serve as a scope contract artifact")
                try:
                    validate_provenance_artifact(snapshot, args.implementation_provenance)
                    provenance = parse_provenance_bytes(
                        read_verified_artifact(snapshot, args.implementation_provenance)
                    )
                    provenance_summary = validate_provenance(
                        provenance,
                        snapshot,
                        expected_plan_items,
                        scope_contract_artifacts,
                        risk_level=args.risk,
                    )
                except (ProvenanceError, ValueError) as error:
                    errors.append(str(error))
            if args.review_report is not None:
                try:
                    review_artifact = snapshot_artifact_entry(snapshot, args.review_report)
                    if review_artifact["role"] != "review_report":
                        raise ValueError("review report must use review_report artifact role")
                    review_report = parse_review_report_bytes(
                        read_verified_artifact(snapshot, args.review_report)
                    )
                except ValueError as error:
                    errors.append(str(error))
        if provenance_summary is not None:
            if args.implementation_model_families != provenance_summary.families:
                errors.append("implementation model families do not match provenance")
            if args.selected_reviewer != provenance_summary.selected_reviewer:
                errors.append("selected reviewer does not match implementation provenance")
            if args.review_independence != provenance_summary.review_independence:
                errors.append("review independence does not match implementation provenance")
            if review_report is not None and snapshot is not None:
                try:
                    validate_review_report(
                        review_report, snapshot, args, provenance_summary
                    )
                except ValueError as error:
                    errors.append(str(error))
    elif any(
        (
            args.snapshot_manifest is not None,
            args.implementation_provenance is not None,
            args.review_report is not None,
            args.no_plan_contract is not None,
            args.implementation_model_families,
            args.selected_reviewer != "none",
            args.review_independence != "none",
            scope_contract_artifacts,
            args.release_binding is not None,
            args.write_gate_evidence is not None,
            args.write_review_evidence is not None,
        )
    ):
        errors.append("blocked gate requires snapshot, provenance, report and evidence fields to be none")

    if args.gate == "pass":
        if args.write_review_evidence is not None:
            errors.append("pass gate requires write-review-evidence=none")
        if args.review_gate_scope == "review_only":
            if args.release_binding is not None:
                errors.append("review_only pass requires release-binding=none")
        else:
            if args.release_binding is None:
                errors.append(
                    "test_release and final_release pass require a verified release binding"
                )
            elif snapshot is not None:
                for repository in snapshot["repositories"]:
                    if is_path_within(args.release_binding, Path(repository["path"])):
                        errors.append(
                            "release binding must stay outside release repositories"
                        )
                        break
                if str(args.release_binding) in snapshot_artifact_paths(snapshot):
                    errors.append("release binding cannot be a frozen artifact or scope contract")
                try:
                    release_binding, release_binding_fingerprint = (
                        load_and_verify_release_binding(args.release_binding, snapshot)
                    )
                except ValueError as error:
                    errors.append(str(error))
    elif args.gate == "findings":
        if args.release_binding is not None:
            errors.append("findings gate requires release-binding=none")
        if args.write_gate_evidence is not None:
            errors.append("findings gate requires write-gate-evidence=none")
    else:
        # blocked 不产生冻结审查结论；不能伪装成可复用或可审计的完整 review。
        if args.release_binding is not None:
            errors.append("blocked gate requires release-binding=none")

    if args.scope_promotion:
        if args.previous_gate_evidence is None:
            errors.append("scope promotion requires previous gate evidence")
            previous_evidence = None
        else:
            try:
                previous_evidence = load_gate_evidence(args.previous_gate_evidence)
            except ValueError as error:
                errors.append(str(error))
                previous_evidence = None
        if snapshot_fingerprint is None:
            errors.append("scope promotion requires a verified snapshot manifest")
        if args.gate != "pass":
            errors.append("scope promotion requires a pass Gate")
        if args.release_diff_kind != "same":
            errors.append("scope promotion only supports release diff kind=same; bounded_delta requires a new full Review")
        if args.reused_passes != expected_passes:
            errors.append("scope promotion reused_passes must match all required passes")
        if args.delta_reviewed:
            errors.append("same-diff scope promotion requires delta_reviewed=false")
        if previous_evidence is not None:
            previous_scope = previous_evidence["review_gate_scope"]
            if (previous_scope, args.review_gate_scope) != (
                "review_only",
                "test_release",
            ):
                errors.append(
                    "scope promotion only supports review_only -> test_release; "
                    "final release requires a new full review against the final target"
                )
            if previous_evidence["release_binding"] is not None:
                errors.append(
                    "scope promotion source review_only evidence must not contain a release binding"
                )
            if release_binding is None or release_binding_fingerprint is None:
                errors.append(
                    "review_only -> test_release promotion requires a new verified release binding"
                )
            if previous_evidence["review_phase"] != args.review_phase:
                errors.append("scope promotion must preserve review phase")
            if review_report is not None and review_report["gate"].get(
                "review_gate_scope"
            ) != previous_scope:
                errors.append("scope promotion review report must retain the prior reviewed scope")
            if previous_evidence["risk_level"] != args.risk:
                errors.append("scope promotion must preserve risk level")
            if tuple(previous_evidence["completed_passes"]) != expected_passes:
                errors.append("scope promotion previous evidence must cover all required passes")
            if previous_evidence["baseline_id"] != args.baseline:
                errors.append("same-diff scope promotion requires previous baseline")
            if previous_evidence["snapshot_fingerprint"] != snapshot_fingerprint:
                errors.append(
                    "same-diff scope promotion requires a matching snapshot fingerprint"
                )
            if snapshot is not None and previous_evidence["snapshot"] != snapshot:
                errors.append("same-diff scope promotion requires a matching frozen snapshot")
            if tuple(previous_evidence["scope_contract_artifacts"]) != scope_contract_artifacts:
                errors.append("scope promotion requires unchanged scope contract artifacts")
            if str(args.implementation_provenance) != previous_evidence["implementation_provenance"]:
                errors.append("scope promotion requires unchanged implementation provenance path")
            if list(args.implementation_model_families) != previous_evidence["implementation_model_families"]:
                errors.append("scope promotion requires unchanged implementation model families")
            if args.selected_reviewer != previous_evidence["selected_reviewer"]:
                errors.append("scope promotion requires unchanged selected reviewer")
            if args.review_independence != previous_evidence["review_independence"]:
                errors.append("scope promotion requires unchanged review independence")
            if args.review_report is None or str(args.review_report) != previous_evidence["review_report"]:
                errors.append("scope promotion requires the same frozen review report")
            elif snapshot is not None:
                try:
                    current_report = snapshot_artifact_entry(snapshot, args.review_report)
                    if current_report["sha256"] != previous_evidence["review_report_sha256"]:
                        errors.append("scope promotion requires unchanged review report content")
                except ValueError:
                    errors.append("scope promotion review report is not frozen")
            if review_report is not None and list(review_report["validation_evidence_paths"]) != previous_evidence["validation_evidence_paths"]:
                errors.append("scope promotion requires unchanged validation evidence")
            if args.sql_check_required != previous_evidence["sql_check_required"]:
                errors.append("scope promotion requires unchanged SQL-check requirement")
            if args.sql_check != previous_evidence["sql_check"]:
                errors.append("scope promotion requires unchanged SQL-check result")
            if args.dynamic_validation != previous_evidence["dynamic_validation"]:
                errors.append("scope promotion requires unchanged dynamic validation")
            if args.plan_coverage_required != previous_evidence["plan_coverage_required"]:
                errors.append("scope promotion requires unchanged plan-coverage requirement")
            current_plan_manifest = "none" if args.plan_manifest is None else str(args.plan_manifest)
            if current_plan_manifest != previous_evidence["plan_manifest"]:
                errors.append("scope promotion requires unchanged plan manifest")
            if list(args.gate_plan_item_ids) != previous_evidence["plan_item_ids"]:
                errors.append("scope promotion requires unchanged plan item IDs")
            current_no_plan_contract = "none" if args.no_plan_contract is None else str(args.no_plan_contract)
            if current_no_plan_contract != previous_evidence["no_plan_contract"]:
                errors.append("scope promotion requires unchanged no-plan contract")
            if snapshot is not None and previous_evidence["review_input_fingerprint"] != review_input_fingerprint(snapshot):
                errors.append("scope promotion requires unchanged frozen review input")
    else:
        if args.previous_gate_evidence is not None:
            errors.append("non-promotion gate requires previous gate evidence=none")
        if (
            args.snapshot_manifest is not None
            and args.gate in ("pass", "findings")
            and args.write_gate_evidence is None
            and args.write_review_evidence is None
        ):
            errors.append(
                "non-promotion completed review snapshot requires writing its evidence"
            )
        if args.release_diff_kind != "not_applicable":
            errors.append("non-promotion gate requires release diff kind=not_applicable")
        if args.reused_passes:
            errors.append("non-promotion gate requires reused_passes=none")
        if args.delta_reviewed:
            errors.append("non-promotion gate requires delta_reviewed=false")
    if args.write_gate_evidence is not None:
        if args.gate != "pass" or not args.release_ready:
            errors.append("writing gate evidence requires a release-ready pass Gate")
        if snapshot_fingerprint is None:
            errors.append("writing gate evidence requires a verified snapshot manifest")
        if provenance_summary is None:
            errors.append("writing gate evidence requires validated implementation provenance")
        if args.snapshot_manifest is not None and is_same_existing_file(
            args.write_gate_evidence, args.snapshot_manifest
        ):
            errors.append("gate evidence output must not overwrite the snapshot manifest")
        if args.previous_gate_evidence is not None and is_same_existing_file(
            args.write_gate_evidence, args.previous_gate_evidence
        ):
            errors.append("gate evidence output must use a new path for scope promotion")
        if os.path.lexists(args.write_gate_evidence):
            errors.append("gate evidence output path must be new and not already exist")
        if snapshot is not None:
            protected_artifacts = snapshot_artifact_paths(snapshot)
            if str(args.write_gate_evidence) in protected_artifacts or any(
                is_same_existing_file(args.write_gate_evidence, Path(artifact))
                for artifact in protected_artifacts
            ):
                errors.append("gate evidence output must not overwrite a frozen artifact")
            for repository in snapshot["repositories"]:
                if is_path_within(args.write_gate_evidence, Path(repository["path"])):
                    errors.append("gate evidence output must stay outside release repositories")
                    break
    if args.write_review_evidence is not None:
        if args.gate != "findings" or args.release_ready:
            errors.append("writing review evidence requires a non-release findings Gate")
        if snapshot_fingerprint is None:
            errors.append("writing review evidence requires a verified snapshot manifest")
        if provenance_summary is None or review_report is None:
            errors.append("writing review evidence requires a validated completed review")
        if args.snapshot_manifest is not None and is_same_existing_file(
            args.write_review_evidence, args.snapshot_manifest
        ):
            errors.append("review evidence output must not overwrite the snapshot manifest")
        if os.path.lexists(args.write_review_evidence):
            errors.append("review evidence output path must be new and not already exist")
        if snapshot is not None:
            protected_artifacts = snapshot_artifact_paths(snapshot)
            if str(args.write_review_evidence) in protected_artifacts or any(
                is_same_existing_file(args.write_review_evidence, Path(artifact))
                for artifact in protected_artifacts
            ):
                errors.append("review evidence output must not overwrite a frozen artifact")
            for repository in snapshot["repositories"]:
                if is_path_within(args.write_review_evidence, Path(repository["path"])):
                    errors.append("review evidence output must stay outside release repositories")
                    break
    if args.sql_check_required != args.expected_sql_check_required:
        errors.append(
            "sql_check_required does not match the task package expectation"
        )
    if args.plan_coverage_required != args.expected_plan_coverage_required:
        errors.append(
            "plan_coverage_required does not match the task package expectation"
        )
    if args.risk == "small":
        if args.plan_coverage_required or args.expected_plan_coverage_required:
            errors.append("small risk requires plan coverage disabled")
        if args.sql_check_required or args.expected_sql_check_required:
            errors.append("small risk cannot require SQL check")
    if args.plan_manifest != args.expected_plan_manifest:
        errors.append("plan_manifest does not match the task package expectation")
    if args.plan_manifest is not None and args.no_plan_contract is not None:
        errors.append("plan manifest and no-plan contract are mutually exclusive")
    for label, values in plan_item_lists.items():
        if len(set(values)) != len(values):
            errors.append(f"{label} plan item IDs must be unique")
    if not args.plan_coverage_required:
        if args.plan_manifest is not None or args.expected_plan_manifest is not None:
            errors.append("plan coverage disabled requires plan_manifest=none")
        if any(plan_item_lists.values()):
            errors.append("plan coverage disabled requires all plan item IDs to be none")
        if args.gate in ("pass", "findings"):
            if args.no_plan_contract is None:
                errors.append("completed review without plan coverage requires a no-plan contract")
            elif str(args.no_plan_contract) not in scope_contract_artifacts:
                errors.append("no-plan contract must be a scope contract artifact")
    else:
        if args.no_plan_contract is not None:
            errors.append("plan coverage requires no-plan contract=none")
        manifest = None
        if args.plan_manifest is None:
            errors.append("required plan coverage needs a plan manifest path")
        else:
            try:
                if snapshot is None:
                    if args.gate == "pass":
                        raise ValueError("plan manifest requires a verified snapshot")
                    # findings/blocked 不会产出发布许可；保留其对当前任务 plan 的诊断能力。
                    manifest = parse_plan_manifest(
                        args.plan_manifest.read_text(encoding="utf-8")
                    )
                else:
                    manifest = parse_plan_manifest(
                        read_verified_artifact(snapshot, args.plan_manifest).decode("utf-8")
                    )
            except (OSError, UnicodeError, PlanManifestError, ValueError) as error:
                errors.append(f"invalid plan manifest: {error}")
        if manifest is not None:
            if expected_plan_items != manifest.item_ids:
                errors.append(
                    "expected plan item IDs must exactly match the plan manifest"
                )
            if set(args.not_applicable_plan_item_ids) != set(
                manifest.not_applicable_ids
            ):
                errors.append(
                    "not_applicable plan item IDs must exactly match the plan manifest"
                )
        if args.gate_plan_item_ids != expected_plan_items:
            errors.append("gate plan item IDs must exactly match expected plan item IDs")
        if args.reported_plan_item_ids != expected_plan_items:
            errors.append("reported plan item IDs must exactly match expected plan item IDs")
        if len(set(status_plan_items)) != len(status_plan_items):
            errors.append("plan item status sets must not overlap")
        if set(status_plan_items) != set(expected_plan_items):
            errors.append("plan item statuses must exactly partition expected plan items")
        if not set(args.reviewed_plan_item_ids).issubset(expected_plan_items):
            errors.append("reviewed plan item IDs must be a subset of expected plan items")
    if (
        args.gate in ("pass", "findings")
        and args.plan_coverage_required
        and args.plan_manifest is not None
    ):
        plan_path = str(args.plan_manifest)
        if plan_path not in scope_contract_artifacts:
            errors.append("completed plan review requires plan_manifest as a scope contract artifact")
        if snapshot is not None and plan_path not in snapshot_artifact_paths(snapshot):
            errors.append("completed plan review requires plan_manifest in the snapshot")
    if args.required_passes != len(expected_passes):
        errors.append(
            f"required_passes={args.required_passes}, expected={len(expected_passes)}"
        )
    if args.findings < 0 or any(value < 0 for value in origins):
        errors.append("finding counts must be non-negative")
    if args.gate_finding_ids != args.reported_finding_ids:
        errors.append("gate finding IDs must exactly match reported finding IDs")
    if args.gate_finding_plan_item_ids != args.reported_finding_plan_item_ids:
        errors.append(
            "gate finding plan item IDs must exactly match reported finding plan item IDs"
        )
    if len(set(args.gate_finding_ids)) != len(args.gate_finding_ids):
        errors.append("finding IDs must be unique")
    if len(args.gate_finding_ids) != args.findings:
        errors.append(
            f"finding ID total={len(args.gate_finding_ids)}, findings={args.findings}"
        )
    if args.findings == 0 and args.gate_finding_plan_item_ids:
        errors.append("zero findings require finding plan item IDs to be none")
    if args.review_phase == "initial":
        if args.initial_findings != args.findings or any(origins[1:]):
            errors.append("initial review findings must all use origin=initial")
    elif args.initial_findings != 0 or sum(origins[1:]) != args.findings:
        errors.append("rereview findings must use only rereview origins")
    if args.release_ready and args.gate != "pass":
        errors.append("release_ready=true requires gate=pass")

    if args.gate == "blocked":
        if completed_passes != expected_passes[: len(completed_passes)]:
            errors.append("blocked completed_passes must be an ordered pass prefix")
        if completed_passes != expected_passes and args.ledger_closed:
            errors.append("an incomplete blocked review cannot close the ledger")
        if args.findings != 0:
            errors.append("blocked gate cannot return partial findings")
        if args.missing_plan_item_ids:
            errors.append("blocked gate cannot expose partial missing-item findings")
        review_is_actually_blocked = (
            completed_passes != expected_passes
            or not args.ledger_closed
            or args.sql_check == "blocked"
            or args.dynamic_validation == "blocked"
        )
        if not review_is_actually_blocked:
            errors.append("blocked gate requires an incomplete or blocked review prerequisite")
        if args.release_ready:
            errors.append("blocked gate cannot be release ready")
    else:
        if completed_passes != expected_passes:
            errors.append(
                "completed_passes must exactly match " + ",".join(expected_passes)
            )
        if not args.ledger_closed:
            errors.append(f"gate={args.gate} requires ledger_closed=true")
        if args.sql_check_required and args.sql_check != "completed":
            errors.append("required SQL check must be completed")
        if args.sql_check == "blocked" or args.dynamic_validation == "blocked":
            errors.append(f"gate={args.gate} cannot contain a blocked prerequisite")
        if set(args.reviewed_plan_item_ids) != set(expected_plan_items):
            errors.append(f"gate={args.gate} requires every expected plan item reviewed")

    if args.gate == "pass":
        if args.findings != 0:
            errors.append("pass gate requires findings=0")
        if not args.release_ready:
            errors.append("pass gate requires release_ready=true")
        if args.dynamic_validation == "limited":
            errors.append("limited dynamic validation cannot be release ready")
        if (
            args.missing_plan_item_ids
            or args.blocked_plan_item_ids
            or args.external_plan_item_ids
        ):
            errors.append("pass gate requires missing, blocked and external plan items empty")
    elif args.gate == "findings":
        if args.findings == 0:
            errors.append("findings gate requires findings>0")
        if args.release_ready:
            errors.append("findings gate cannot be release ready")
        problem_plan_items = set(
            args.missing_plan_item_ids
            + args.blocked_plan_item_ids
            + args.external_plan_item_ids
        )
        if set(args.gate_finding_plan_item_ids) != problem_plan_items:
            errors.append(
                "finding plan item IDs must exactly cover missing, blocked and external plan items"
            )

    # 所有 report/provenance 均已按 snapshot 读入；落任意审查证据前再确认范围未漂移。
    if (
        not errors
        and completed_review
        and args.snapshot_manifest is not None
        and snapshot is not None
        and snapshot_fingerprint is not None
    ):
        try:
            final_snapshot, final_fingerprint = load_and_verify_snapshot(
                args.snapshot_manifest
            )
            if final_snapshot != snapshot or final_fingerprint != snapshot_fingerprint:
                errors.append("frozen release range changed while Gate was evaluating it")
        except ValueError as error:
            errors.append(f"frozen release range changed while Gate was evaluating it: {error}")
    if (
        not errors
        and args.gate == "pass"
        and release_binding is not None
        and release_binding_fingerprint is not None
        and args.release_binding is not None
        and snapshot is not None
    ):
        try:
            final_binding, final_binding_fingerprint = load_and_verify_release_binding(
                args.release_binding, snapshot
            )
            if (
                final_binding != release_binding
                or final_binding_fingerprint != release_binding_fingerprint
            ):
                errors.append("release binding changed while Gate was evaluating it")
        except ValueError as error:
            errors.append(f"release binding changed while Gate was evaluating it: {error}")

    if errors:
        return fail(errors)
    if args.write_gate_evidence is not None:
        try:
            if (
                snapshot is None
                or snapshot_fingerprint is None
                or provenance_summary is None
                or review_report is None
            ):
                return fail(["cannot write incomplete gate evidence"])
            write_gate_evidence(
                args.write_gate_evidence,
                args,
                snapshot,
                snapshot_fingerprint,
                provenance_summary,
                scope_contract_artifacts,
                review_report,
                release_binding,
                release_binding_fingerprint,
            )
        except ValueError as error:
            return fail([str(error)])
    if args.write_review_evidence is not None:
        try:
            if (
                snapshot is None
                or snapshot_fingerprint is None
                or provenance_summary is None
                or review_report is None
            ):
                return fail(["cannot write incomplete review evidence"])
            write_review_evidence(
                args.write_review_evidence,
                args,
                snapshot,
                snapshot_fingerprint,
                provenance_summary,
                scope_contract_artifacts,
                review_report,
            )
        except ValueError as error:
            return fail([str(error)])
    suffix = (
        f" (risk upgraded {args.expected_risk}->{args.risk})"
        if args.expected_risk != args.risk
        else ""
    )
    promotion_suffix = " scope-promoted" if args.scope_promotion else ""
    print(
        "review gate valid: "
        f"{args.gate} scope={args.review_gate_scope}{suffix}{promotion_suffix}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
