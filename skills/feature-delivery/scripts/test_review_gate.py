#!/usr/bin/env python3
"""review_gate.py 的确定性回归测试。"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from freeze_snapshot import load_and_verify_snapshot, review_input_fingerprint
from review_gate import parser as gate_parser, review_gate_payload
import review_gate as review_gate_module


SCRIPT = Path(__file__).with_name("review_gate.py")
FREEZE_SCRIPT = Path(__file__).with_name("freeze_snapshot.py")
HIGH_PASSES = "intent_contract,state_failure,data_integration,test_counterexample,clean_room"
NORMAL_PASSES = "full_surface,clean_room"
SMALL_PASSES = "targeted_fix"
PLAN_TEMPLATE = """# 计划

## 模块一：基础
基础交付。

## 模块三：首次免费展示
后端和 App 交付。

## 计划交付项清单
| 交付项 ID | 范围状态 | 来源章节 | 交付内容 | 责任端/仓库 | 不适用依据 |
| --- | --- | --- | --- | --- | --- |
| `M1.backend` | `required` | 模块一：基础 | 基础后端 | api | - |
| `M3.backend` | `required` | 模块三：首次免费展示 | 首次免费文案 | api | - |
| `M3.app` | `{app_scope}` | 模块三：首次免费展示 | App 按钮文案 | App | {app_reason} |
"""


# 这 51 个 fixture 把 v2 JSON 字段、无 report 的 pass CLI 和可覆盖 snapshot 写死在 helper 中。
# 它们不再能作为 v4 的可执行合同；对应策略已迁入下方 ReviewGateV4Test 的表驱动断言。
@unittest.skip("deprecated schema-v2 fixtures; semantic coverage migrated to ReviewGateV4Test")
class ReviewGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        directory = Path(cls._temp.name)
        cls.plan = directory / "plan.md"
        cls.plan.write_text(
            PLAN_TEMPLATE.format(app_scope="required", app_reason="-"),
            encoding="utf-8",
        )
        cls.plan_with_not_applicable = directory / "plan-not-applicable.md"
        cls.plan_with_not_applicable.write_text(
            PLAN_TEMPLATE.format(
                app_scope="not_applicable",
                app_reason="用户确认 App 不在本期范围",
            ),
            encoding="utf-8",
        )
        cls.repository = directory / "snapshot-repository"
        cls.repository.mkdir()
        for arguments in (
            ("init", "-q"),
            ("config", "user.email", "skill-test@example.invalid"),
            ("config", "user.name", "Skill Test"),
        ):
            subprocess.run(
                ["git", "-C", str(cls.repository), *arguments], check=True
            )
        cls.snapshot_target = cls.repository / "tracked.txt"
        cls.snapshot_target.write_text("base\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(cls.repository), "add", "tracked.txt"], check=True
        )
        subprocess.run(
            ["git", "-C", str(cls.repository), "commit", "-qm", "base"], check=True
        )
        cls.default_provenance = directory / "default-implementation-provenance.json"
        cls.default_provenance.write_text(
            json.dumps({"schema_version": 2, "entries": []}), encoding="utf-8"
        )
        cls.default_snapshot = directory / "default-snapshot.json"
        cls.default_evidence = directory / "default-gate-evidence.json"
        cls.snapshot_provenance: dict[Path, Path] = {}
        cls.refresh_default_snapshot()

    @classmethod
    def refresh_default_snapshot(cls) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(FREEZE_SCRIPT),
                "--repo-base",
                f"{cls.repository}=HEAD",
                "--artifact",
                str(cls.plan),
                "--artifact",
                str(cls.default_provenance),
                "--output",
                str(cls.default_snapshot),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr)

    def setUp(self) -> None:
        """让使用默认 pass 的测试始终面对干净、可重算的范围。"""
        self.snapshot_target.write_text("base\n", encoding="utf-8")
        self.default_evidence.unlink(missing_ok=True)
        self.refresh_default_snapshot()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def run_gate(self, **overrides: object) -> subprocess.CompletedProcess[str]:
        values = {
            "expected-baseline": "repo@abc123+dirty",
            "baseline": "repo@abc123+dirty",
            "expected-risk": "high",
            "risk": "high",
            "expected-review-phase": "initial",
            "review-phase": "initial",
            "expected-review-gate-scope": "final_release",
            "review-gate-scope": "final_release",
            "scope-promotion": "false",
            "previous-gate-evidence": "none",
            "snapshot-manifest": str(self.default_snapshot),
            "scope-contract-artifact": [str(self.plan)],
            "implementation-provenance": str(self.default_provenance),
            "implementation-model-families": "none",
            "selected-reviewer": "feature_delivery_reviewer",
            "review-independence": "independent",
            "release-diff-kind": "not_applicable",
            "reused-passes": "none",
            "delta-reviewed": "false",
            "write-gate-evidence": str(self.default_evidence),
            "required-passes": "5",
            "completed-passes": HIGH_PASSES,
            "ledger-closed": "true",
            "expected-plan-coverage-required": "true",
            "plan-coverage-required": "true",
            "expected-plan-manifest": str(self.plan),
            "plan-manifest": str(self.plan),
            "expected-plan-item-ids": "M1.backend,M3.backend,M3.app",
            "gate-plan-item-ids": "M1.backend,M3.backend,M3.app",
            "reported-plan-item-ids": "M1.backend,M3.backend,M3.app",
            "reviewed-plan-item-ids": "M1.backend,M3.backend,M3.app",
            "satisfied-plan-item-ids": "M1.backend,M3.backend,M3.app",
            "not-applicable-plan-item-ids": "none",
            "missing-plan-item-ids": "none",
            "blocked-plan-item-ids": "none",
            "external-plan-item-ids": "none",
            "expected-sql-check-required": "false",
            "sql-check-required": "false",
            "sql-check": "not_applicable",
            "dynamic-validation": "completed",
            "findings": "0",
            "gate-finding-ids": "none",
            "reported-finding-ids": "none",
            "gate-finding-plan-item-ids": "none",
            "reported-finding-plan-item-ids": "none",
            "initial-findings": "0",
            "baseline-findings": "0",
            "fix-introduced": "0",
            "newly-exposed": "0",
            "unknown-origin": "0",
            "gate": "pass",
            "release-ready": "true",
        }
        values.update(overrides)
        if values["gate"] != "pass":
            for key, value in {
                "snapshot-manifest": "none",
                "scope-contract-artifact": [],
                "implementation-provenance": "none",
                "implementation-model-families": "none",
                "selected-reviewer": "none",
                "review-independence": "none",
                "write-gate-evidence": "none",
            }.items():
                if key not in overrides:
                    values[key] = value
        command = [sys.executable, "-B", str(SCRIPT)]
        for key, value in values.items():
            if isinstance(value, (list, tuple)):
                for item in value:
                    command.extend((f"--{key}", str(item)))
            elif value is not None:
                command.extend((f"--{key}", str(value)))
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def write_snapshot(self, filename: str, content: str = "changed\n") -> Path:
        """冻结当前临时 Git 发布范围，模拟真实 Gate 的输入。"""
        self.snapshot_target.write_text(content, encoding="utf-8")
        output = Path(self._temp.name) / filename
        provenance = Path(self._temp.name) / f"{filename}.provenance.json"
        provenance.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "entries": [
                        {
                            "entry_type": "implementation",
                            "task_id": f"impl-{filename}",
                            "module_id": "whole",
                            "selected_agent": "feature_delivery_implementer",
                            "selected_model": "gpt-6.1-sol/high",
                            "plan_item_ids": ["M1.backend"],
                            "files": [
                                {
                                    "repo": str(self.repository),
                                    "path": "tracked.txt",
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(FREEZE_SCRIPT),
                "--repo-base",
                f"{self.repository}=HEAD",
                "--artifact",
                str(self.plan),
                "--artifact",
                str(provenance),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.snapshot_provenance[output] = provenance
        return output

    def snapshot_pass_overrides(self, snapshot: Path, evidence: Path) -> dict[str, object]:
        return {
            "snapshot-manifest": str(snapshot),
            "scope-contract-artifact": [str(self.plan)],
            "implementation-provenance": str(self.snapshot_provenance[snapshot]),
            "implementation-model-families": "sol",
            "selected-reviewer": "feature_delivery_reviewer",
            "review-independence": "same_family_unavoidable",
            "write-gate-evidence": str(evidence),
        }

    def write_contract_snapshot(self, filename: str, contract: Path) -> Path:
        """为无代码差异的契约 Gate 冻结指定 contract。"""
        output = Path(self._temp.name) / filename
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(FREEZE_SCRIPT),
                "--repo-base",
                f"{self.repository}=HEAD",
                "--artifact",
                str(contract),
                "--artifact",
                str(self.default_provenance),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.snapshot_provenance[output] = self.default_provenance
        return output

    def write_previous_evidence(
        self,
        filename: str,
        snapshot: Path,
        *,
        baseline: str = "repo@abc123+dirty",
        phase: str = "initial",
        scope: str = "review_only",
        risk: str = "normal",
    ) -> Path:
        """经由真实 Gate 保存一份可用于 scope 提升的旧证据。"""
        path = Path(self._temp.name) / filename
        completed = {
            "small": SMALL_PASSES,
            "normal": NORMAL_PASSES,
            "high": HIGH_PASSES,
        }[risk]
        values = self.snapshot_pass_overrides(snapshot, path)
        values.update(
            {
                "expected-baseline": baseline,
                "baseline": baseline,
                "expected-risk": risk,
                "risk": risk,
                "expected-review-phase": phase,
                "review-phase": phase,
                "expected-review-gate-scope": scope,
                "review-gate-scope": scope,
                "required-passes": str(len(completed.split(","))),
                "completed-passes": completed,
            }
        )
        result = self.run_gate(**values)
        self.assertEqual(result.returncode, 0, result.stderr)
        return path

    def assert_valid(self, **overrides: str) -> None:
        result = self.run_gate(**overrides)
        self.assertEqual(result.returncode, 0, result.stderr)

    def assert_invalid(self, expected_error: str, **overrides: str) -> None:
        result = self.run_gate(**overrides)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(expected_error, result.stderr)

    def test_valid_pass(self) -> None:
        self.assert_valid()

    def test_gate_evidence_cannot_overwrite_frozen_artifact(self) -> None:
        self.assert_invalid(
            "gate evidence output must not overwrite a frozen artifact",
            **{"write-gate-evidence": str(self.plan)},
        )

    def test_gate_evidence_cannot_pollute_release_repository(self) -> None:
        self.assert_invalid(
            "gate evidence output must stay outside release repositories",
            **{
                "write-gate-evidence": str(
                    self.repository / "gate-evidence.json"
                )
            },
        )

    def test_gate_evidence_must_not_overwrite_existing_pass(self) -> None:
        self.default_evidence.write_text("old evidence\n", encoding="utf-8")
        self.assert_invalid("gate evidence output path must be new and not already exist")

    def test_pass_requires_frozen_evidence(self) -> None:
        self.assert_invalid(
            "pass gate requires a verified snapshot manifest",
            **{
                "snapshot-manifest": "none",
                "write-gate-evidence": "none",
                "scope-contract-artifact": [],
                "implementation-provenance": "none",
                "implementation-model-families": "none",
                "selected-reviewer": "none",
                "review-independence": "none",
            },
        )

    def test_plan_contract_must_be_frozen(self) -> None:
        snapshot = self.write_contract_snapshot(
            "wrong-plan-snapshot.json", self.plan_with_not_applicable
        )
        self.assert_invalid(
            "plan coverage pass requires plan_manifest in the snapshot",
            **{
                "snapshot-manifest": str(snapshot),
                "scope-contract-artifact": [str(self.plan)],
                "implementation-provenance": str(self.default_provenance),
                "implementation-model-families": "none",
                "selected-reviewer": "feature_delivery_reviewer",
                "review-independence": "independent",
                "write-gate-evidence": str(
                    Path(self._temp.name) / "wrong-plan-evidence.json"
                ),
            },
        )

    def test_no_plan_pass_requires_contract_artifact(self) -> None:
        self.assert_invalid(
            "pass gate requires at least one scope contract artifact",
            **{
                "scope-contract-artifact": [],
                "expected-plan-coverage-required": "false",
                "plan-coverage-required": "false",
                "expected-plan-manifest": "none",
                "plan-manifest": "none",
                "expected-plan-item-ids": "none",
                "gate-plan-item-ids": "none",
                "reported-plan-item-ids": "none",
                "reviewed-plan-item-ids": "none",
                "satisfied-plan-item-ids": "none",
            },
        )

    def test_reported_model_family_must_match_provenance(self) -> None:
        snapshot = self.write_snapshot("family-snapshot.json")
        values = self.snapshot_pass_overrides(
            snapshot, Path(self._temp.name) / "family-evidence.json"
        )
        values["implementation-model-families"] = "luna"
        self.assert_invalid("implementation model families do not match provenance", **values)

    def test_normal_can_upgrade_to_high(self) -> None:
        result = self.run_gate(**{"expected-risk": "normal"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("risk upgraded normal->high", result.stdout)

    def test_valid_small_fix_without_plan(self) -> None:
        self.assert_valid(
            **{
                "expected-risk": "small",
                "risk": "small",
                "required-passes": "1",
                "completed-passes": SMALL_PASSES,
                "expected-plan-coverage-required": "false",
                "plan-coverage-required": "false",
                "expected-plan-manifest": "none",
                "plan-manifest": "none",
                "expected-plan-item-ids": "none",
                "gate-plan-item-ids": "none",
                "reported-plan-item-ids": "none",
                "reviewed-plan-item-ids": "none",
                "satisfied-plan-item-ids": "none",
            }
        )

    def test_small_fix_can_upgrade_to_normal(self) -> None:
        result = self.run_gate(
            **{
                "expected-risk": "small",
                "risk": "normal",
                "required-passes": "2",
                "completed-passes": NORMAL_PASSES,
            }
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("risk upgraded small->normal", result.stdout)

    def test_normal_cannot_downgrade_to_small(self) -> None:
        self.assert_invalid(
            "risk cannot be downgraded from normal to small",
            **{
                "expected-risk": "normal",
                "risk": "small",
                "required-passes": "1",
                "completed-passes": SMALL_PASSES,
            },
        )

    def test_small_fix_rejects_plan_coverage(self) -> None:
        self.assert_invalid(
            "small risk requires plan coverage disabled",
            **{
                "expected-risk": "small",
                "risk": "small",
                "required-passes": "1",
                "completed-passes": SMALL_PASSES,
            },
        )

    def test_small_fix_rejects_sql_check(self) -> None:
        self.assert_invalid(
            "small risk cannot require SQL check",
            **{
                "expected-risk": "small",
                "risk": "small",
                "required-passes": "1",
                "completed-passes": SMALL_PASSES,
                "expected-plan-coverage-required": "false",
                "plan-coverage-required": "false",
                "expected-plan-manifest": "none",
                "plan-manifest": "none",
                "expected-plan-item-ids": "none",
                "gate-plan-item-ids": "none",
                "reported-plan-item-ids": "none",
                "reviewed-plan-item-ids": "none",
                "satisfied-plan-item-ids": "none",
                "expected-sql-check-required": "true",
                "sql-check-required": "true",
                "sql-check": "completed",
            },
        )

    def test_high_cannot_downgrade_to_normal(self) -> None:
        self.assert_invalid(
            "risk cannot be downgraded",
            **{
                "risk": "normal",
                "required-passes": "2",
                "completed-passes": "full_surface,clean_room",
            },
        )

    def test_baseline_must_match(self) -> None:
        self.assert_invalid("baseline=repo@def456", baseline="repo@def456")

    def test_review_gate_scope_must_match(self) -> None:
        self.assert_invalid(
            "review_gate_scope=test_release, expected=final_release",
            **{"review-gate-scope": "test_release"},
        )

    def test_review_only_scope_is_valid_when_expected(self) -> None:
        self.assert_valid(
            **{
                "expected-review-gate-scope": "review_only",
                "review-gate-scope": "review_only",
            }
        )

    def test_scope_promotion_can_reuse_completed_passes(self) -> None:
        snapshot = self.write_snapshot("same-snapshot.json")
        evidence = self.write_previous_evidence("previous-pass.json", snapshot)
        values = self.snapshot_pass_overrides(
            snapshot, Path(self._temp.name) / "promoted-pass.json"
        )
        values.update(
            {
                "expected-risk": "normal",
                "risk": "normal",
                "expected-review-gate-scope": "test_release",
                "review-gate-scope": "test_release",
                "required-passes": "2",
                "completed-passes": NORMAL_PASSES,
                "scope-promotion": "true",
                "previous-gate-evidence": str(evidence),
                "release-diff-kind": "same",
                "reused-passes": NORMAL_PASSES,
                "delta-reviewed": "false",
            }
        )
        result = self.run_gate(**values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("scope-promoted", result.stdout)

    def test_scope_promotion_requires_a_new_evidence_path(self) -> None:
        snapshot = self.write_snapshot("same-evidence-snapshot.json")
        previous_evidence = self.write_previous_evidence(
            "same-evidence-previous.json", snapshot
        )
        values = self.snapshot_pass_overrides(snapshot, previous_evidence)
        values.update(
            {
                "expected-risk": "normal",
                "risk": "normal",
                "expected-review-gate-scope": "test_release",
                "review-gate-scope": "test_release",
                "required-passes": "2",
                "completed-passes": NORMAL_PASSES,
                "scope-promotion": "true",
                "previous-gate-evidence": str(previous_evidence),
                "release-diff-kind": "same",
                "reused-passes": NORMAL_PASSES,
                "delta-reviewed": "false",
            }
        )
        self.assert_invalid(
            "gate evidence output must use a new path for scope promotion", **values
        )

    def test_scope_promotion_requires_snapshot_match(self) -> None:
        old_snapshot = self.write_snapshot("old-snapshot.json", "old\n")
        evidence = self.write_previous_evidence("previous-fingerprint.json", old_snapshot)
        current_snapshot = self.write_snapshot("current-snapshot.json", "new\n")
        values = self.snapshot_pass_overrides(
            current_snapshot, Path(self._temp.name) / "mismatch-pass.json"
        )
        values.update(
            {
                "expected-risk": "normal",
                "risk": "normal",
                "expected-review-gate-scope": "test_release",
                "review-gate-scope": "test_release",
                "required-passes": "2",
                "completed-passes": NORMAL_PASSES,
                "scope-promotion": "true",
                "previous-gate-evidence": str(evidence),
                "release-diff-kind": "same",
                "reused-passes": NORMAL_PASSES,
                "delta-reviewed": "false",
            }
        )
        self.assert_invalid(
            "same-diff scope promotion requires a matching snapshot fingerprint",
            **values,
        )

    def test_scope_promotion_must_preserve_review_phase(self) -> None:
        snapshot = self.write_snapshot("phase-snapshot.json")
        evidence = self.write_previous_evidence(
            "previous-rereview.json",
            snapshot,
            phase="rereview",
        )
        values = self.snapshot_pass_overrides(
            snapshot, Path(self._temp.name) / "phase-pass.json"
        )
        values.update(
            {
                "expected-risk": "normal",
                "risk": "normal",
                "expected-review-gate-scope": "test_release",
                "review-gate-scope": "test_release",
                "required-passes": "2",
                "completed-passes": NORMAL_PASSES,
                "scope-promotion": "true",
                "previous-gate-evidence": str(evidence),
                "release-diff-kind": "same",
                "reused-passes": NORMAL_PASSES,
                "delta-reviewed": "false",
            }
        )
        self.assert_invalid(
            "scope promotion must preserve review phase",
            **values,
        )

    def test_scope_promotion_rejects_self_reported_or_invalid_evidence(self) -> None:
        invalid_evidence = Path(self._temp.name) / "not-a-gate.json"
        invalid_evidence.write_text("{}", encoding="utf-8")
        snapshot = self.write_snapshot("invalid-evidence-snapshot.json")
        values = self.snapshot_pass_overrides(
            snapshot, Path(self._temp.name) / "invalid-evidence-pass.json"
        )
        values.update(
            {
                "expected-risk": "normal",
                "risk": "normal",
                "expected-review-gate-scope": "test_release",
                "review-gate-scope": "test_release",
                "required-passes": "2",
                "completed-passes": NORMAL_PASSES,
                "scope-promotion": "true",
                "previous-gate-evidence": str(invalid_evidence),
                "release-diff-kind": "same",
                "reused-passes": NORMAL_PASSES,
                "delta-reviewed": "false",
            }
        )
        self.assert_invalid(
            "previous gate evidence has an unexpected schema",
            **values,
        )

    def test_scope_promotion_same_diff_requires_same_baseline(self) -> None:
        snapshot = self.write_snapshot("baseline-snapshot.json")
        evidence = self.write_previous_evidence(
            "previous-other-baseline.json",
            snapshot,
            baseline="repo@old123+dirty",
        )
        values = self.snapshot_pass_overrides(
            snapshot, Path(self._temp.name) / "baseline-pass.json"
        )
        values.update(
            {
                "expected-risk": "normal",
                "risk": "normal",
                "expected-review-gate-scope": "test_release",
                "review-gate-scope": "test_release",
                "required-passes": "2",
                "completed-passes": NORMAL_PASSES,
                "scope-promotion": "true",
                "previous-gate-evidence": str(evidence),
                "release-diff-kind": "same",
                "reused-passes": NORMAL_PASSES,
                "delta-reviewed": "false",
            }
        )
        self.assert_invalid(
            "same-diff scope promotion requires previous baseline",
            **values,
        )

    def test_valid_pass_can_write_reusable_evidence(self) -> None:
        snapshot = self.write_snapshot("evidence-snapshot.json")
        evidence = Path(self._temp.name) / "written-pass.json"
        self.assert_valid(**self.snapshot_pass_overrides(snapshot, evidence))
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        self.assertEqual(payload["review_gate_scope"], "final_release")
        self.assertEqual(
            payload["snapshot_fingerprint"], load_and_verify_snapshot(snapshot)[1]
        )
        self.assertEqual(payload["schema_version"], 2)

    def test_scope_promotion_rejects_bounded_delta(self) -> None:
        snapshot = self.write_snapshot("bounded-old.json", "old\n")
        evidence = self.write_previous_evidence("bounded-old-pass.json", snapshot)
        current = self.write_snapshot("bounded-current.json", "new\n")
        values = self.snapshot_pass_overrides(
            current, Path(self._temp.name) / "bounded-current-pass.json"
        )
        values.update(
            {
                "expected-risk": "normal",
                "risk": "normal",
                "expected-review-gate-scope": "test_release",
                "review-gate-scope": "test_release",
                "required-passes": "2",
                "completed-passes": NORMAL_PASSES,
                "scope-promotion": "true",
                "previous-gate-evidence": str(evidence),
                "release-diff-kind": "bounded_delta",
                "reused-passes": NORMAL_PASSES,
                "delta-reviewed": "true",
            }
        )
        self.assert_invalid(
            "bounded_delta requires a new full Review",
            **values,
        )

    def test_required_sql_check_cannot_be_not_applicable(self) -> None:
        self.assert_invalid(
            "required SQL check must be completed",
            **{
                "expected-sql-check-required": "true",
                "sql-check-required": "true",
            },
        )

    def test_reported_sql_requirement_must_match_task(self) -> None:
        self.assert_invalid(
            "does not match the task package",
            **{"sql-check-required": "true"},
        )

    def test_plan_coverage_requirement_must_match_task(self) -> None:
        self.assert_invalid(
            "plan_coverage_required does not match",
            **{"plan-coverage-required": "false"},
        )

    def test_required_plan_coverage_cannot_have_empty_expectation(self) -> None:
        self.assert_invalid(
            "must exactly match the plan manifest",
            **{
                "expected-plan-item-ids": "none",
                "gate-plan-item-ids": "none",
                "reported-plan-item-ids": "none",
                "reviewed-plan-item-ids": "none",
                "satisfied-plan-item-ids": "none",
            },
        )

    def test_gate_plan_items_must_match_task(self) -> None:
        self.assert_invalid(
            "gate plan item IDs must exactly match expected",
            **{"gate-plan-item-ids": "M1.backend,M3.backend"},
        )

    def test_reported_plan_items_must_match_task(self) -> None:
        self.assert_invalid(
            "reported plan item IDs must exactly match expected",
            **{"reported-plan-item-ids": "M1.backend,M3.backend"},
        )

    def test_plan_item_statuses_must_not_overlap(self) -> None:
        self.assert_invalid(
            "status sets must not overlap",
            **{"not-applicable-plan-item-ids": "M3.app"},
        )

    def test_not_applicable_must_be_preapproved_by_manifest(self) -> None:
        self.assert_invalid(
            "not_applicable plan item IDs must exactly match",
            **{
                "satisfied-plan-item-ids": "none",
                "not-applicable-plan-item-ids": "M1.backend,M3.backend,M3.app",
            },
        )

    def test_manifest_can_preapprove_not_applicable_item(self) -> None:
        snapshot = self.write_contract_snapshot(
            "not-applicable-snapshot.json", self.plan_with_not_applicable
        )
        self.assert_valid(
            **{
                "snapshot-manifest": str(snapshot),
                "scope-contract-artifact": [str(self.plan_with_not_applicable)],
                "implementation-provenance": str(self.default_provenance),
                "implementation-model-families": "none",
                "selected-reviewer": "feature_delivery_reviewer",
                "review-independence": "independent",
                "write-gate-evidence": str(
                    Path(self._temp.name) / "not-applicable-evidence.json"
                ),
                "expected-plan-manifest": str(self.plan_with_not_applicable),
                "plan-manifest": str(self.plan_with_not_applicable),
                "satisfied-plan-item-ids": "M1.backend,M3.backend",
                "not-applicable-plan-item-ids": "M3.app",
            }
        )

    def test_missing_plan_item_blocks_pass(self) -> None:
        self.assert_invalid(
            "pass gate requires missing, blocked and external",
            **{
                "satisfied-plan-item-ids": "M1.backend,M3.app",
                "missing-plan-item-ids": "M3.backend",
            },
        )

    def test_valid_findings_gate_with_missing_plan_item(self) -> None:
        self.assert_valid(
            **{
                "satisfied-plan-item-ids": "M1.backend,M3.app",
                "missing-plan-item-ids": "M3.backend",
                "findings": "1",
                "gate-finding-ids": "F001",
                "reported-finding-ids": "F001",
                "gate-finding-plan-item-ids": "M3.backend",
                "reported-finding-plan-item-ids": "M3.backend",
                "initial-findings": "1",
                "gate": "findings",
                "release-ready": "false",
            }
        )

    def test_valid_finding_blocks_an_implemented_plan_item(self) -> None:
        self.assert_valid(
            **{
                "satisfied-plan-item-ids": "M1.backend,M3.app",
                "blocked-plan-item-ids": "M3.backend",
                "findings": "1",
                "gate-finding-ids": "F001",
                "reported-finding-ids": "F001",
                "gate-finding-plan-item-ids": "M3.backend",
                "reported-finding-plan-item-ids": "M3.backend",
                "initial-findings": "1",
                "gate": "findings",
                "release-ready": "false",
            }
        )

    def test_external_plan_item_blocks_pass(self) -> None:
        self.assert_invalid(
            "pass gate requires missing, blocked and external",
            **{
                "satisfied-plan-item-ids": "M1.backend,M3.backend",
                "external-plan-item-ids": "M3.app",
            },
        )

    def test_v19_missing_backend_and_external_app_are_reported_together(self) -> None:
        self.assert_valid(
            **{
                "satisfied-plan-item-ids": "M1.backend",
                "missing-plan-item-ids": "M3.backend",
                "external-plan-item-ids": "M3.app",
                "findings": "2",
                "gate-finding-ids": "F001,F002",
                "reported-finding-ids": "F001,F002",
                "gate-finding-plan-item-ids": "M3.backend,M3.app",
                "reported-finding-plan-item-ids": "M3.backend,M3.app",
                "initial-findings": "2",
                "gate": "findings",
                "release-ready": "false",
            }
        )

    def test_valid_blocked_gate_with_external_plan_item(self) -> None:
        self.assert_valid(
            **{
                "satisfied-plan-item-ids": "M1.backend,M3.backend",
                "external-plan-item-ids": "M3.app",
                "dynamic-validation": "blocked",
                "gate": "blocked",
                "release-ready": "false",
            }
        )

    def test_external_item_alone_cannot_hide_behind_blocked_gate(self) -> None:
        self.assert_invalid(
            "requires an incomplete or blocked review prerequisite",
            **{
                "satisfied-plan-item-ids": "M1.backend,M3.backend",
                "external-plan-item-ids": "M3.app",
                "gate": "blocked",
                "release-ready": "false",
            },
        )

    def test_problem_plan_items_must_map_to_findings(self) -> None:
        self.assert_invalid(
            "must exactly cover missing, blocked and external",
            **{
                "satisfied-plan-item-ids": "M1.backend",
                "missing-plan-item-ids": "M3.backend",
                "external-plan-item-ids": "M3.app",
                "findings": "1",
                "gate-finding-ids": "F999",
                "reported-finding-ids": "F999",
                "initial-findings": "1",
                "gate": "findings",
                "release-ready": "false",
            },
        )

    def test_valid_no_plan_gate(self) -> None:
        self.assert_valid(
            **{
                "expected-plan-coverage-required": "false",
                "plan-coverage-required": "false",
                "expected-plan-manifest": "none",
                "plan-manifest": "none",
                "expected-plan-item-ids": "none",
                "gate-plan-item-ids": "none",
                "reported-plan-item-ids": "none",
                "reviewed-plan-item-ids": "none",
                "satisfied-plan-item-ids": "none",
            }
        )

    def test_review_phase_must_match_task(self) -> None:
        self.assert_invalid(
            "review_phase=rereview",
            **{"review-phase": "rereview"},
        )

    def test_blocked_passes_must_be_ordered_prefix(self) -> None:
        self.assert_invalid(
            "ordered pass prefix",
            **{
                "completed-passes": "garbage",
                "ledger-closed": "false",
                "gate": "blocked",
                "release-ready": "false",
            },
        )

    def test_valid_partial_blocked_gate(self) -> None:
        self.assert_valid(
            **{
                "completed-passes": "intent_contract,state_failure",
                "ledger-closed": "false",
                "dynamic-validation": "blocked",
                "gate": "blocked",
                "release-ready": "false",
            }
        )

    def test_valid_blocked_gate_before_any_pass(self) -> None:
        self.assert_valid(
            **{
                "completed-passes": "none",
                "ledger-closed": "false",
                "dynamic-validation": "blocked",
                "gate": "blocked",
                "release-ready": "false",
            }
        )

    def test_gate_and_report_finding_ids_must_match(self) -> None:
        self.assert_invalid(
            "must exactly match reported",
            **{
                "findings": "2",
                "gate-finding-ids": "F001,F002",
                "reported-finding-ids": "F001",
                "initial-findings": "2",
                "gate": "findings",
                "release-ready": "false",
            },
        )

    def test_initial_review_uses_initial_origin(self) -> None:
        self.assert_invalid(
            "origin=initial",
            **{
                "findings": "1",
                "gate-finding-ids": "F001",
                "reported-finding-ids": "F001",
                "baseline-findings": "1",
                "gate": "findings",
                "release-ready": "false",
            },
        )

    def test_valid_rereview_findings(self) -> None:
        self.assert_valid(
            **{
                "review-phase": "rereview",
                "expected-review-phase": "rereview",
                "findings": "2",
                "gate-finding-ids": "F001,F002",
                "reported-finding-ids": "F001,F002",
                "baseline-findings": "1",
                "fix-introduced": "1",
                "gate": "findings",
                "release-ready": "false",
            }
        )


class ReviewGateV4Test(unittest.TestCase):
    """覆盖 v4 的冻结输入、报告绑定、release binding 与 scope 提升。"""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.directory = Path(self._temp.name)
        self.repository = self.directory / "repo"
        self.repository.mkdir()
        for arguments in (
            ("init", "-q"),
            ("config", "user.email", "skill-test@example.invalid"),
            ("config", "user.name", "Skill Test"),
        ):
            subprocess.run(["git", "-C", str(self.repository), *arguments], check=True)
        self.source = self.repository / "service.go"
        self.source.write_text("package service\n", encoding="utf-8")
        # 保留一个基线目录，使输出祖先被换入仓库的回归可不改变冻结 diff。
        self.evidence_slot = self.repository / "evidence-slot"
        self.evidence_slot.mkdir()
        (self.evidence_slot / ".keep").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repository), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repository), "commit", "-qm", "base"], check=True)
        self.target_ref = subprocess.run(
            ["git", "-C", str(self.repository), "symbolic-ref", "-q", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        # Review 始终从候选 feature branch 指向独立的目标分支；不能用同一 HEAD
        # 伪装 target/candidate 绑定关系。
        subprocess.run(["git", "-C", str(self.repository), "switch", "-qc", "feature"], check=True)

    def tearDown(self) -> None:
        self._temp.cleanup()

    @staticmethod
    def _command_args(values: dict[str, object]) -> list[str]:
        command: list[str] = []
        for key, value in values.items():
            if isinstance(value, (list, tuple)):
                for item in value:
                    command.extend((f"--{key}", str(item)))
            else:
                command.extend((f"--{key}", str(value)))
        return command

    def _freeze(self, output: Path, artifacts: list[tuple[str, Path]]) -> None:
        command = [
            sys.executable,
            "-B",
            str(FREEZE_SCRIPT),
            "--repo-target",
            f"{self.repository}={self.target_ref}",
        ]
        for role, path in artifacts:
            command.extend(("--artifact", f"{role}={path}"))
        command.extend(("--output", str(output)))
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def _bind_release(self, snapshot: Path, name: str) -> Path:
        """发布阶段才暂存；Review 工作树阶段不依赖 index。"""
        subprocess.run(["git", "-C", str(self.repository), "add", "--all"], check=True)
        binding = self.directory / f"{name}-release-binding.json"
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(FREEZE_SCRIPT),
                "--bind-release-snapshot",
                str(snapshot),
                "--output",
                str(binding),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return binding

    def _invoke(self, values: dict[str, object]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), *self._command_args(values)],
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def _plan_text() -> str:
        return "# 计划\n\n## 模块1：服务\n本期实现服务改动。\n\n## 计划交付项清单\n| 交付项 ID | 范围状态 | 来源章节 | 交付内容 | 责任端/仓库 | 不适用依据 |\n| --- | --- | --- | --- | --- | --- |\n| M1.backend | required | 模块1：服务 | 服务改动 | repo | - |\n"

    @staticmethod
    def _no_plan_text() -> str:
        return "# 无 plan 契约\n\n## 目标\n验证仅契约交付。\n\n## 非目标\n不修改仓库代码。\n\n## 发布范围\n无代码发布范围。\n\n## 验证\n执行 Gate。\n\n## 授权边界\n仅生成证据。\n"

    def _values(
        self,
        *,
        snapshot: Path,
        provenance: Path,
        report: Path,
        evidence: Path,
        contract: Path,
        has_plan: bool,
    ) -> dict[str, object]:
        items = "M1.backend" if has_plan else "none"
        families = "sol" if has_plan else "none"
        reviewer = "feature_delivery_reviewer"
        risk = "normal" if has_plan else "small"
        passes = NORMAL_PASSES if has_plan else SMALL_PASSES
        plan_value = str(contract) if has_plan else "none"
        no_plan_value = "none" if has_plan else str(contract)
        return {
            "expected-baseline": "repo@base", "baseline": "repo@base",
            "expected-risk": risk, "risk": risk,
            "expected-review-phase": "initial", "review-phase": "initial",
            "expected-review-gate-scope": "review_only", "review-gate-scope": "review_only",
            "scope-promotion": "false", "previous-gate-evidence": "none",
            "snapshot-manifest": str(snapshot),
            "scope-contract-artifact": [str(contract)],
            "implementation-provenance": str(provenance), "review-report": str(report),
            "release-binding": "none",
            "no-plan-contract": no_plan_value,
            "implementation-model-families": families, "selected-reviewer": reviewer,
            "review-independence": "same_family_unavoidable" if has_plan else "independent", "release-diff-kind": "not_applicable",
            "reused-passes": "none", "delta-reviewed": "false",
            "write-gate-evidence": str(evidence),
            "write-review-evidence": "none",
            "required-passes": "2" if has_plan else "1", "completed-passes": passes,
            "ledger-closed": "true",
            "expected-plan-coverage-required": "true" if has_plan else "false",
            "plan-coverage-required": "true" if has_plan else "false",
            "expected-plan-manifest": plan_value, "plan-manifest": plan_value,
            "expected-plan-item-ids": items, "gate-plan-item-ids": items,
            "reported-plan-item-ids": items, "reviewed-plan-item-ids": items,
            "satisfied-plan-item-ids": items, "not-applicable-plan-item-ids": "none",
            "missing-plan-item-ids": "none", "blocked-plan-item-ids": "none",
            "external-plan-item-ids": "none", "expected-sql-check-required": "false",
            "sql-check-required": "false", "sql-check": "not_applicable",
            "dynamic-validation": "completed", "findings": "0",
            "gate-finding-ids": "none", "reported-finding-ids": "none",
            "gate-finding-plan-item-ids": "none",
            "reported-finding-plan-item-ids": "none", "initial-findings": "0",
            "baseline-findings": "0", "fix-introduced": "0", "newly-exposed": "0",
            "unknown-origin": "0", "gate": "pass", "release-ready": "true",
        }

    def _bundle(
        self,
        name: str,
        *,
        has_plan: bool,
        bad_fingerprint: bool = False,
        with_validation_evidence: bool = False,
        astra_implementation: bool = False,
        external_source: tuple[str, str] | None = None,
    ) -> tuple[dict[str, object], Path, Path]:
        if has_plan:
            self.source.write_text("package service\n// reviewed\n", encoding="utf-8")
            contract = self.directory / f"{name}-plan.md"
            contract.write_text(self._plan_text(), encoding="utf-8")
            entries: list[dict[str, object]] = [{
                "entry_type": "implementation", "task_id": f"{name}-impl",
                "module_id": "service", "selected_agent": "feature_delivery_implementer",
                "selected_model": "gpt-6.1-sol/high", "plan_item_ids": ["M1.backend"],
                "files": [{"repo": str(self.repository), "path": "service.go"}],
            }]
            role = "plan_manifest"
        else:
            contract = self.directory / "no-plan-contract.md"
            contract.write_text(self._no_plan_text(), encoding="utf-8")
            entries = []
            role = "no_plan_contract"
        if astra_implementation:
            # Astra 关键实现使用真实高风险来源，验证完整冻结和 Gate 链路。
            assert has_plan
            entries[0]["selected_agent"] = "feature_delivery_critical_implementer"
            entries[0]["selected_model"] = "gpt-6-astra/medium"
        source_evidence = None
        if external_source is not None:
            assert has_plan and not astra_implementation
            agent, model = external_source
            source_evidence = self.directory / f"{name}-source.txt"
            source_evidence.write_text("用户已提供实现来源：service.go 来自本次会话/工作树。\n", encoding="utf-8")
            entries[0].update(selected_agent=agent, selected_model=model, source_evidence=str(source_evidence))
        provenance = self.directory / f"{name}-provenance.json"
        provenance.write_text(json.dumps({"schema_version": 3 if external_source else 2, "entries": entries}), encoding="utf-8")
        preview = self.directory / f"{name}-preview.json"
        report = self.directory / f"{name}-report.json"
        snapshot = self.directory / f"{name}-snapshot.json"
        evidence = self.directory / f"{name}-gate.json"
        validation = self.directory / f"{name}-validation.txt"
        preview_artifacts = [(role, contract), ("implementation_provenance", provenance)]
        if source_evidence is not None:
            preview_artifacts.append(("auxiliary", source_evidence))
        if with_validation_evidence:
            validation.write_text("targeted test passed\n", encoding="utf-8")
            preview_artifacts.append(("validation_evidence", validation))
        self._freeze(preview, preview_artifacts)
        values = self._values(
            snapshot=snapshot, provenance=provenance, report=report, evidence=evidence,
            contract=contract, has_plan=has_plan,
        )
        preview_snapshot, _ = load_and_verify_snapshot(preview)
        if astra_implementation:
            values.update({
                "expected-risk": "high", "risk": "high",
                "required-passes": "5", "completed-passes": HIGH_PASSES,
                "implementation-model-families": "astra",
                "selected-reviewer": "feature_delivery_sol_reviewer",
            })
        if external_source:
            agent, model = external_source
            source_families = [] if agent == "human" else ["astra"] if model.startswith("gpt-6-astra/") else ["unknown"]
            values["implementation-model-families"] = ",".join(source_families) or "none"
            values["review-independence"] = "source_unknown" if source_families == ["unknown"] else "independent"
        parsed = gate_parser().parse_args(self._command_args(values))
        if astra_implementation:
            selected_reviewer, selected_model, families = (
                "feature_delivery_sol_reviewer", "gpt-6-astra/medium", ["astra"]
            )
        elif has_plan:
            selected_reviewer, selected_model, families = (
                "feature_delivery_reviewer", "gpt-6.1-sol/high", ["sol"]
            )
        else:
            selected_reviewer, selected_model, families = (
                "feature_delivery_reviewer", "gpt-6.1-sol/high", []
            )
        if external_source:
            families = source_families
        report.write_text(json.dumps({
            "schema_version": 1,
            "reviewed_release_fingerprint": "0" * 64 if bad_fingerprint else review_input_fingerprint(preview_snapshot),
            "selected_reviewer": selected_reviewer, "selected_model": selected_model,
            "implementation_model_families": families,
            "review_independence": values["review-independence"],
            "gate": review_gate_payload(parsed),
            "validation_evidence_paths": [str(validation.resolve())]
            if with_validation_evidence
            else [],
        }), encoding="utf-8")
        self._freeze(snapshot, [*preview_artifacts, ("review_report", report)])
        return values, snapshot, report

    def test_gate_accepts_evidenced_external_sources_without_false_independence(self):
        """完整 Gate 读取新来源并拒绝将未知模型改写为已证实独立。"""
        for index, source in enumerate((("human", "none"), ("main_agent", "gpt-6-astra/medium"), ("unknown_source", "unknown"))):
            with self.subTest(source=source):
                values, _, _ = self._bundle(f"external-{index}", has_plan=True, external_source=source)
                result = self._invoke(values)
                self.assertEqual(result.returncode, 0, result.stderr)
                if source[0] == "unknown_source":
                    values["review-independence"] = "independent"
                    values["write-gate-evidence"] = str(self.directory / "false-independence.json")
                    rejected = self._invoke(values)
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertIn("independence", rejected.stderr)

    def test_gate_rejects_source_evidence_changed_after_review(self):
        """来源说明与代码一样受冻结保护，不因作者类型放宽审后修改。"""
        values, _, _ = self._bundle("external-tamper", has_plan=True, external_source=("human", "none"))
        (self.directory / "external-tamper-source.txt").write_text("changed source\n", encoding="utf-8")
        result = self._invoke(values)
        self.assertNotEqual(result.returncode, 0)

    def _nonpass_values(self, name: str, gate: str) -> dict[str, object]:
        values, _, _ = self._bundle(name, has_plan=True)
        values.update({
            "snapshot-manifest": "none",
            "scope-contract-artifact": [],
            "implementation-provenance": "none",
            "review-report": "none",
            "no-plan-contract": "none",
            "implementation-model-families": "none",
            "selected-reviewer": "none",
            "review-independence": "none",
            "release-binding": "none",
            "write-gate-evidence": "none",
            "write-review-evidence": "none",
            "gate": gate,
            "release-ready": "false",
        })
        return values

    def _rebind_report_to_values(
        self, values: dict[str, object], report: Path, name: str
    ) -> None:
        """为仍合法的 v4 参数变化重签 Reviewer 回传并重冻最终 snapshot。"""
        prior_report = json.loads(report.read_text(encoding="utf-8"))
        plan_value = values["plan-manifest"]
        contract = Path(plan_value if plan_value != "none" else values["no-plan-contract"])
        contract_role = "plan_manifest" if plan_value != "none" else "no_plan_contract"
        provenance = Path(values["implementation-provenance"])
        artifacts: list[tuple[str, Path]] = [
            (contract_role, contract), ("implementation_provenance", provenance)
        ]
        for raw_path in prior_report["validation_evidence_paths"]:
            artifacts.append(("validation_evidence", Path(raw_path)))
        preview = self.directory / f"{name}-preview.json"
        snapshot = self.directory / f"{name}-snapshot.json"
        self._freeze(preview, artifacts)
        preview_snapshot, _ = load_and_verify_snapshot(preview)
        values["snapshot-manifest"] = str(snapshot)
        parsed = gate_parser().parse_args(self._command_args(values))
        prior_report["reviewed_release_fingerprint"] = review_input_fingerprint(preview_snapshot)
        prior_report["gate"] = review_gate_payload(parsed)
        report.write_text(json.dumps(prior_report), encoding="utf-8")
        self._freeze(snapshot, [*artifacts, ("review_report", report)])

    def test_provenance_cli_requires_explicit_risk(self) -> None:
        """同一冻结来源可按真实风险选模，缺少或错误风险必须拒绝。"""
        values, snapshot, _ = self._bundle("explicit-risk", has_plan=True, astra_implementation=True)
        command = [sys.executable, "-B", str(SCRIPT.with_name("implementation_provenance.py")),
                   "--snapshot-manifest", str(snapshot),
                   "--implementation-provenance", values["implementation-provenance"],
                   "--scope-contract-artifact", values["plan-manifest"],
                   "--expected-plan-item-ids", "M1.backend"]
        for risk, expected in (("normal", "feature_delivery_reviewer"),
                               ("high", "feature_delivery_sol_reviewer"),
                               (None, None), ("unknown", None)):
            with self.subTest(risk=risk):
                result = subprocess.run(command + ([] if risk is None else ["--risk-level", risk]),
                                        capture_output=True, text=True, check=False)
                if expected is None:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("--risk-level", result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout)["selected_reviewer"], expected)

    def test_astra_source_can_use_normal_risk_reviewer(self) -> None:
        """实现来源不会把已确定的普通审查风险隐式提高。"""
        values, _, report = self._bundle("astra-normal", has_plan=True, astra_implementation=True)
        values.update({
            "expected-risk": "normal", "risk": "normal",
            "required-passes": "2", "completed-passes": NORMAL_PASSES,
            "selected-reviewer": "feature_delivery_reviewer",
            "review-independence": "independent",
        })
        raw = json.loads(report.read_text())
        raw.update({"selected_reviewer": "feature_delivery_reviewer",
                    "selected_model": "gpt-6.1-sol/high", "review_independence": "independent"})
        report.write_text(json.dumps(raw))
        self._rebind_report_to_values(values, report, "astra-normal-rebound")
        result = self._invoke(values)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_high_risk_rejects_normal_reviewer_even_for_sol_source(self) -> None:
        """报告与 CLI 同时自报错误 Reviewer，也不能绕过高风险路由。"""
        values, _, report = self._bundle("sol-wrong-high", has_plan=True)
        values.update({"expected-risk": "high", "risk": "high",
                       "required-passes": "5", "completed-passes": HIGH_PASSES})
        self._rebind_report_to_values(values, report, "sol-wrong-high-rebound")
        result = self._invoke(values)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reviewer", result.stderr)
        self.assertFalse(Path(values["write-gate-evidence"]).exists())

    def test_astra_high_review_can_bind_final_release(self) -> None:
        """Astra 关键实现及同家族审查可通过完整五遍 Gate 和正式发布绑定。"""
        values, snapshot, report = self._bundle("astra-final", has_plan=True, astra_implementation=True)
        values.update({
            "expected-review-gate-scope": "final_release",
            "review-gate-scope": "final_release",
        })
        self._rebind_report_to_values(values, report, "astra-final-bound")
        values["release-binding"] = str(self._bind_release(Path(values["snapshot-manifest"]), "astra-final"))
        result = self._invoke(values)
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = json.loads(Path(values["write-gate-evidence"]).read_text())
        self.assertEqual(evidence["implementation_model_families"], ["astra"])
        self.assertEqual(evidence["selected_reviewer"], "feature_delivery_sol_reviewer")
        self.assertEqual(evidence["review_independence"], "same_family_unavoidable")

    def test_astra_review_rejects_false_model_independence_and_incomplete_passes(self) -> None:
        """模型迁移不放松真实档位、同家族标记和完整五遍要求。"""
        for name, report_changes, value_changes in (
            ("old-model", {"selected_model": "gpt-5.6-sol/high"}, {}),
            ("false-effort", {"selected_model": "gpt-6-astra/high"}, {}),
            ("false-independence", {"review_independence": "independent"}, {"review-independence": "independent"}),
            ("missing-pass", {}, {"completed-passes": NORMAL_PASSES}),
        ):
            with self.subTest(case=name):
                values, _, report = self._bundle(name, has_plan=True, astra_implementation=True)
                data = json.loads(report.read_text())
                data.update(report_changes)
                report.write_text(json.dumps(data))
                values.update(value_changes)
                self._rebind_report_to_values(values, report, name + "-rebound")
                result = self._invoke(values)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertFalse(Path(values["write-gate-evidence"]).exists())

    def test_rejects_previous_sol_reviewer_model(self) -> None:
        """已冻结报告仍须与 Reviewer 当前型号一致，旧报告不能冒充升级后的审查。"""
        values, _, report = self._bundle("previous-sol-reviewer", has_plan=True)
        raw = json.loads(report.read_text())
        raw["selected_model"] = "gpt-6-sol/high"
        report.write_text(json.dumps(raw))
        self._rebind_report_to_values(values, report, "previous-sol-reviewer-rebound")
        result = self._invoke(values)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("selected_model", result.stderr)
        self.assertFalse(Path(values["write-gate-evidence"]).exists())

    def test_initial_pass_uses_report_fingerprint_without_report_self_hash(self) -> None:
        values, snapshot, report = self._bundle("initial", has_plan=True)
        result = self._invoke(values)
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = json.loads(Path(values["write-gate-evidence"]).read_text(encoding="utf-8"))
        self.assertEqual(evidence["schema_version"], 4)
        self.assertEqual(evidence["review_report"], str(report.resolve()))
        self.assertEqual(
            evidence["review_input_fingerprint"],
            review_input_fingerprint(load_and_verify_snapshot(snapshot)[0]),
        )

    def test_rejects_report_not_bound_to_frozen_input(self) -> None:
        values, _, _ = self._bundle("bad-report", has_plan=True, bad_fingerprint=True)
        result = self._invoke(values)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not bind the frozen review input", result.stderr)

    def test_pass_requires_a_structured_reviewer_report(self) -> None:
        values, _, _ = self._bundle("missing-report", has_plan=True)
        values["review-report"] = "none"
        result = self._invoke(values)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pass gate requires a structured review report", result.stderr)

    def test_replacing_a_frozen_report_invalidates_the_gate_input(self) -> None:
        values, _, report = self._bundle("replaced-report", has_plan=True)
        report.write_text("{}", encoding="utf-8")
        result = self._invoke(values)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("snapshot manifest no longer matches", result.stderr)

    def test_gate_evidence_never_overwrites_an_existing_path(self) -> None:
        values, _, _ = self._bundle("existing-evidence", has_plan=True)
        Path(values["write-gate-evidence"]).write_text("old", encoding="utf-8")
        result = self._invoke(values)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gate evidence output path must be new", result.stderr)

    def test_gate_evidence_cannot_pollute_the_release_repository(self) -> None:
        values, _, _ = self._bundle("repository-evidence", has_plan=True)
        values["write-gate-evidence"] = str(self.repository / "gate-evidence.json")
        result = self._invoke(values)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must stay outside release repositories", result.stderr)

    def test_gate_evidence_cannot_overwrite_a_frozen_artifact(self) -> None:
        values, _, _ = self._bundle("frozen-artifact-output", has_plan=True)
        values["write-gate-evidence"] = values["plan-manifest"]
        result = self._invoke(values)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gate evidence output must not overwrite a frozen artifact", result.stderr)

    def test_pass_requires_a_verified_snapshot(self) -> None:
        values, _, _ = self._bundle("missing-snapshot", has_plan=True)
        values.update({"snapshot-manifest": "none", "write-gate-evidence": "none"})
        result = self._invoke(values)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pass gate requires a verified snapshot manifest", result.stderr)

    def test_validation_evidence_is_frozen_and_preserved_in_gate_evidence(self) -> None:
        values, _, _ = self._bundle(
            "validation-evidence", has_plan=True, with_validation_evidence=True
        )
        result = self._invoke(values)
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = json.loads(Path(values["write-gate-evidence"]).read_text(encoding="utf-8"))
        self.assertEqual(
            evidence["validation_evidence_paths"],
            [str((self.directory / "validation-evidence-validation.txt").resolve())],
        )

    def test_rejects_cli_self_report_not_matching_reviewer_return(self) -> None:
        values, _, _ = self._bundle("self-report", has_plan=True)
        values["dynamic-validation"] = "not_applicable"
        result = self._invoke(values)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("review report gate conclusion does not match Gate input", result.stderr)

    def test_gate_rechecks_snapshot_after_reading_frozen_artifacts(self) -> None:
        values, _, _ = self._bundle("toctou", has_plan=True)
        real_read = review_gate_module.read_verified_artifact
        plan_path = Path(values["plan-manifest"]).resolve()

        def mutate_after_plan(snapshot: dict[str, object], path: Path) -> bytes:
            data = real_read(snapshot, path)
            if path == plan_path:
                self.source.write_text("package service\n// swapped during Gate\n", encoding="utf-8")
            return data

        with contextlib.redirect_stderr(io.StringIO()), mock.patch.object(
            review_gate_module, "read_verified_artifact", side_effect=mutate_after_plan
        ), mock.patch.object(
            sys,
            "argv",
            [str(SCRIPT), *self._command_args(values)],
        ):
            result = review_gate_module.main()
        self.assertEqual(result, 1)
        self.assertFalse(Path(values["write-gate-evidence"]).exists())

    def test_gate_writer_rejects_ancestor_swapped_to_release_repository(self) -> None:
        """最终快照复核后发生祖先软链替换，也不能把 Gate evidence 写进仓库。"""
        values, _, _ = self._bundle("output-race", has_plan=True)
        evidence_root = self.directory / "outside-evidence-root"
        (evidence_root / "evidence-slot").mkdir(parents=True)
        target = evidence_root / "evidence-slot" / "gate.json"
        values["write-gate-evidence"] = str(target)
        relocated = self.directory / "outside-evidence-root-before-swap"
        real_write = review_gate_module.write_gate_evidence

        def replace_ancestor_then_write(*args: object, **kwargs: object) -> None:
            evidence_root.rename(relocated)
            evidence_root.symlink_to(self.repository, target_is_directory=True)
            real_write(*args, **kwargs)

        with contextlib.redirect_stderr(io.StringIO()), mock.patch.object(
            review_gate_module,
            "write_gate_evidence",
            side_effect=replace_ancestor_then_write,
        ), mock.patch.object(
            sys,
            "argv",
            [str(SCRIPT), *self._command_args(values)],
        ):
            result = review_gate_module.main()
        self.assertEqual(result, 1)
        self.assertFalse((self.evidence_slot / "gate.json").exists())

    def test_same_snapshot_scope_promotion_reuses_same_report(self) -> None:
        values, snapshot, report = self._bundle("promote", has_plan=True)
        initial = self._invoke(values)
        self.assertEqual(initial.returncode, 0, initial.stderr)
        binding = self._bind_release(snapshot, "promote")
        promoted = dict(values)
        promoted.update({
            "expected-review-gate-scope": "test_release",
            "review-gate-scope": "test_release",
            "scope-promotion": "true",
            "previous-gate-evidence": str(values["write-gate-evidence"]),
            "release-diff-kind": "same",
            "reused-passes": NORMAL_PASSES,
            "release-binding": str(binding),
            "write-gate-evidence": str(self.directory / "promoted-gate.json"),
        })
        result = self._invoke(promoted)
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = json.loads(Path(promoted["write-gate-evidence"]).read_text(encoding="utf-8"))
        self.assertEqual(evidence["review_report"], str(report.resolve()))

    def test_scope_promotion_rejects_rewritten_report_even_when_semantics_match(self) -> None:
        values, _, report = self._bundle("rewritten-report", has_plan=True)
        initial = self._invoke(values)
        self.assertEqual(initial.returncode, 0, initial.stderr)
        report.write_text(
            json.dumps(json.loads(report.read_text(encoding="utf-8")), indent=2),
            encoding="utf-8",
        )
        replacement_snapshot = self.directory / "rewritten-report-replacement-snapshot.json"
        plan = Path(values["plan-manifest"])
        provenance = Path(values["implementation-provenance"])
        self._freeze(
            replacement_snapshot,
            [
                ("plan_manifest", plan),
                ("implementation_provenance", provenance),
                ("review_report", report),
            ],
        )
        binding = self._bind_release(replacement_snapshot, "rewritten-report")
        promoted = dict(values)
        promoted.update({
            "snapshot-manifest": str(replacement_snapshot),
            "expected-review-gate-scope": "test_release",
            "review-gate-scope": "test_release",
            "scope-promotion": "true",
            "previous-gate-evidence": str(values["write-gate-evidence"]),
            "release-diff-kind": "same",
            "reused-passes": NORMAL_PASSES,
            "release-binding": str(binding),
            "write-gate-evidence": str(self.directory / "rewritten-promoted.json"),
        })
        result = self._invoke(promoted)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("matching snapshot fingerprint", result.stderr)

    def test_scope_promotion_rejects_changed_validation_precondition(self) -> None:
        values, snapshot, _ = self._bundle("promotion-precondition", has_plan=True)
        initial = self._invoke(values)
        self.assertEqual(initial.returncode, 0, initial.stderr)
        binding = self._bind_release(snapshot, "promotion-precondition")
        promoted = dict(values)
        promoted.update({
            "expected-review-gate-scope": "test_release",
            "review-gate-scope": "test_release",
            "scope-promotion": "true",
            "previous-gate-evidence": str(values["write-gate-evidence"]),
            "release-diff-kind": "same",
            "reused-passes": NORMAL_PASSES,
            "release-binding": str(binding),
            "dynamic-validation": "not_applicable",
            "write-gate-evidence": str(self.directory / "precondition-promoted.json"),
        })
        result = self._invoke(promoted)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(
            "review report gate conclusion" in result.stderr
            or "unchanged dynamic validation" in result.stderr,
            result.stderr,
        )

    def test_contract_only_no_plan_routes_to_sol_reviewer(self) -> None:
        values, _, _ = self._bundle("contract-only", has_plan=False)
        result = self._invoke(values)
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = json.loads(Path(values["write-gate-evidence"]).read_text(encoding="utf-8"))
        self.assertEqual(evidence["implementation_model_families"], [])
        self.assertEqual(evidence["selected_reviewer"], "feature_delivery_reviewer")

    def test_no_plan_pass_requires_the_frozen_no_plan_contract(self) -> None:
        values, _, _ = self._bundle("missing-no-plan", has_plan=False)
        values.update({"no-plan-contract": "none", "scope-contract-artifact": []})
        result = self._invoke(values)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("completed review without plan coverage requires a no-plan contract", result.stderr)

    def test_migrated_pass_policy_invariants(self) -> None:
        """迁移 v2 的风险、范围、SQL、计划和来源一致性断言。"""
        cases = (
            (
                "baseline",
                {"baseline": "repo@other"},
                "baseline=repo@other",
            ),
            (
                "risk",
                {"expected-risk": "high", "risk": "small", "required-passes": "1", "completed-passes": SMALL_PASSES},
                "risk cannot be downgraded",
            ),
            (
                "scope",
                {"review-gate-scope": "test_release"},
                "review_gate_scope=test_release",
            ),
            (
                "provenance-route",
                {"implementation-model-families": "luna"},
                "implementation model families do not match provenance",
            ),
            (
                "sql",
                {"expected-sql-check-required": "true", "sql-check-required": "true"},
                "required SQL check must be completed",
            ),
            (
                "plan-task",
                {"gate-plan-item-ids": "none"},
                "gate plan item IDs must exactly match expected",
            ),
            (
                "plan-status-overlap",
                {"not-applicable-plan-item-ids": "M1.backend"},
                "status sets must not overlap",
            ),
            (
                "missing-release-item",
                {"satisfied-plan-item-ids": "none", "missing-plan-item-ids": "M1.backend"},
                "pass gate requires missing, blocked and external",
            ),
        )
        for name, changes, expected in cases:
            with self.subTest(name=name):
                values, _, _ = self._bundle(f"policy-{name}", has_plan=True)
                values.update(changes)
                result = self._invoke(values)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)

    def test_migrated_risk_upgrades_remain_valid_with_a_matching_report(self) -> None:
        """v2 的正常/小修复升级语义保留，但 v4 必须由 Reviewer 对新风险签回。"""
        normal_to_high, _, high_report = self._bundle("upgrade-high", has_plan=True)
        normal_to_high.update({
            "expected-risk": "normal",
            "risk": "high",
            "required-passes": "5",
            "completed-passes": HIGH_PASSES,
            "write-gate-evidence": str(self.directory / "upgrade-high-gate.json"),
        })
        normal_to_high.update({
            "selected-reviewer": "feature_delivery_sol_reviewer",
            "review-independence": "independent",
        })
        report_data = json.loads(high_report.read_text())
        report_data.update({
            "selected_reviewer": "feature_delivery_sol_reviewer",
            "selected_model": "gpt-6-astra/medium",
            "review_independence": "independent",
        })
        high_report.write_text(json.dumps(report_data))
        self._rebind_report_to_values(normal_to_high, high_report, "upgrade-high-rebound")
        high_result = self._invoke(normal_to_high)
        self.assertEqual(high_result.returncode, 0, high_result.stderr)
        self.assertIn("risk upgraded normal->high", high_result.stdout)

        small_to_normal, _, normal_report = self._bundle("upgrade-normal", has_plan=True)
        small_to_normal.update({
            "expected-risk": "small",
            "risk": "normal",
            "write-gate-evidence": str(self.directory / "upgrade-normal-gate.json"),
        })
        self._rebind_report_to_values(small_to_normal, normal_report, "upgrade-normal-rebound")
        normal_result = self._invoke(small_to_normal)
        self.assertEqual(normal_result.returncode, 0, normal_result.stderr)
        self.assertIn("risk upgraded small->normal", normal_result.stdout)

    def test_migrated_findings_and_blocked_invariants(self) -> None:
        """findings 保存完整审查链但只能产出不可复用的 review evidence。"""
        findings, _, findings_report = self._bundle("findings", has_plan=True)
        findings.update({
            "satisfied-plan-item-ids": "none",
            "missing-plan-item-ids": "M1.backend",
            "findings": "1",
            "gate-finding-ids": "F001",
            "reported-finding-ids": "F001",
            "gate-finding-plan-item-ids": "M1.backend",
            "reported-finding-plan-item-ids": "M1.backend",
            "initial-findings": "1",
            "gate": "findings",
            "release-ready": "false",
            "write-gate-evidence": "none",
            "write-review-evidence": str(self.directory / "findings-review-evidence.json"),
        })
        self._rebind_report_to_values(findings, findings_report, "findings-rebound")
        findings_result = self._invoke(findings)
        self.assertEqual(findings_result.returncode, 0, findings_result.stderr)
        findings_evidence = Path(findings["write-review-evidence"])
        payload = json.loads(findings_evidence.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["evidence_kind"], "review_findings")
        self.assertFalse(Path(self.directory / "findings-gate.json").exists())
        with self.assertRaisesRegex(ValueError, "unexpected schema"):
            review_gate_module.load_gate_evidence(findings_evidence)

        bad_finding_ids = dict(findings)
        bad_finding_ids["reported-finding-ids"] = "F002"
        bad_finding_ids["write-review-evidence"] = str(
            self.directory / "findings-review-evidence-invalid.json"
        )
        bad_result = self._invoke(bad_finding_ids)
        self.assertNotEqual(bad_result.returncode, 0)
        self.assertIn("must exactly match reported", bad_result.stderr)

        blocked = self._nonpass_values("blocked", "blocked")
        blocked.update({
            "completed-passes": "full_surface",
            "ledger-closed": "false",
            "dynamic-validation": "blocked",
        })
        blocked_result = self._invoke(blocked)
        self.assertEqual(blocked_result.returncode, 0, blocked_result.stderr)

        unordered = dict(blocked)
        unordered["completed-passes"] = "clean_room"
        unordered_result = self._invoke(unordered)
        self.assertNotEqual(unordered_result.returncode, 0)
        self.assertIn("ordered pass prefix", unordered_result.stderr)

    def test_scope_promotion_rejects_review_only_to_final_and_test_to_final(self) -> None:
        """正式发布目标不同；任何跳级或 test->final 复用都必须重做完整 Review。"""
        values, snapshot, _ = self._bundle("promotion-final-boundary", has_plan=True)
        initial = self._invoke(values)
        self.assertEqual(initial.returncode, 0, initial.stderr)
        binding = self._bind_release(snapshot, "promotion-final-boundary")
        direct_final = dict(values)
        direct_final.update({
            "expected-review-gate-scope": "final_release",
            "review-gate-scope": "final_release",
            "scope-promotion": "true",
            "previous-gate-evidence": str(values["write-gate-evidence"]),
            "release-diff-kind": "same",
            "reused-passes": NORMAL_PASSES,
            "release-binding": str(binding),
            "write-gate-evidence": str(self.directory / "direct-final-gate.json"),
        })
        direct_result = self._invoke(direct_final)
        self.assertNotEqual(direct_result.returncode, 0)
        self.assertIn("only supports review_only -> test_release", direct_result.stderr)

        test_release = dict(values)
        test_release.update({
            "expected-review-gate-scope": "test_release",
            "review-gate-scope": "test_release",
            "scope-promotion": "true",
            "previous-gate-evidence": str(values["write-gate-evidence"]),
            "release-diff-kind": "same",
            "reused-passes": NORMAL_PASSES,
            "release-binding": str(binding),
            "write-gate-evidence": str(self.directory / "test-release-gate.json"),
        })
        promoted_result = self._invoke(test_release)
        self.assertEqual(promoted_result.returncode, 0, promoted_result.stderr)
        final_from_test = dict(test_release)
        final_from_test.update({
            "expected-review-gate-scope": "final_release",
            "review-gate-scope": "final_release",
            "previous-gate-evidence": str(test_release["write-gate-evidence"]),
            "write-gate-evidence": str(self.directory / "test-to-final-gate.json"),
        })
        final_result = self._invoke(final_from_test)
        self.assertNotEqual(final_result.returncode, 0)
        self.assertIn("only supports review_only -> test_release", final_result.stderr)

    def test_scope_promotion_rejects_target_or_merge_binding_drift(self) -> None:
        """首次 review_only->test 必须重新证明固定 target 与候选 merge tree 未漂移。"""
        values, snapshot, _ = self._bundle("promotion-binding-drift", has_plan=True)
        initial = self._invoke(values)
        self.assertEqual(initial.returncode, 0, initial.stderr)
        binding = self._bind_release(snapshot, "promotion-binding-drift")
        common = {
            "expected-review-gate-scope": "test_release",
            "review-gate-scope": "test_release",
            "scope-promotion": "true",
            "previous-gate-evidence": str(values["write-gate-evidence"]),
            "release-diff-kind": "same",
            "reused-passes": NORMAL_PASSES,
            "release-binding": str(binding),
        }

        original_binding = binding.read_text(encoding="utf-8")
        tampered_binding = json.loads(original_binding)
        tampered_binding["repositories"][0]["merge_tree"] = "0" * 40
        binding.write_text(json.dumps(tampered_binding), encoding="utf-8")
        merge_drift = dict(values)
        merge_drift.update(common)
        merge_drift["write-gate-evidence"] = str(self.directory / "merge-drift-gate.json")
        merge_result = self._invoke(merge_drift)
        self.assertNotEqual(merge_result.returncode, 0)
        self.assertIn("release binding no longer matches", merge_result.stderr)
        binding.write_text(original_binding, encoding="utf-8")

        target_revision = subprocess.run(
            ["git", "-C", str(self.repository), "rev-parse", self.target_ref],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        target_tree = subprocess.run(
            ["git", "-C", str(self.repository), "rev-parse", f"{self.target_ref}^{{tree}}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        advanced_target = subprocess.run(
            ["git", "-C", str(self.repository), "commit-tree", target_tree, "-p", target_revision],
            input="target advanced after review\n",
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "-C", str(self.repository), "update-ref", self.target_ref, advanced_target],
            check=True,
        )
        target_drift = dict(values)
        target_drift.update(common)
        target_drift["write-gate-evidence"] = str(self.directory / "target-drift-gate.json")
        target_result = self._invoke(target_drift)
        self.assertNotEqual(target_result.returncode, 0)
        self.assertIn("snapshot manifest no longer matches", target_result.stderr)

    def test_migrated_scope_promotion_policy_invariants(self) -> None:
        """迁移 v2 的提升边界：不可降级、不可带 delta、不可复用不同阶段。"""
        values, snapshot, _ = self._bundle("promotion-policy", has_plan=True)
        initial = self._invoke(values)
        self.assertEqual(initial.returncode, 0, initial.stderr)
        binding = self._bind_release(snapshot, "promotion-policy")
        common = {
            "expected-review-gate-scope": "test_release",
            "review-gate-scope": "test_release",
            "scope-promotion": "true",
            "previous-gate-evidence": str(values["write-gate-evidence"]),
            "release-diff-kind": "same",
            "reused-passes": NORMAL_PASSES,
            "release-binding": str(binding),
            "write-gate-evidence": str(self.directory / "promotion-policy-next.json"),
        }
        bounded = dict(values)
        bounded.update(common)
        bounded.update({"release-diff-kind": "bounded_delta", "delta-reviewed": "true"})
        bounded_result = self._invoke(bounded)
        self.assertNotEqual(bounded_result.returncode, 0)
        self.assertIn("bounded_delta requires a new full Review", bounded_result.stderr)

        phase = dict(values)
        phase.update(common)
        phase.update({
            "expected-review-phase": "rereview",
            "review-phase": "rereview",
            "write-gate-evidence": str(self.directory / "promotion-policy-phase.json"),
        })
        phase_result = self._invoke(phase)
        self.assertNotEqual(phase_result.returncode, 0)
        self.assertIn("scope promotion must preserve review phase", phase_result.stderr)

    def test_scope_promotion_requires_new_evidence_and_valid_previous_evidence(self) -> None:
        values, snapshot, _ = self._bundle("promotion-evidence", has_plan=True)
        initial = self._invoke(values)
        self.assertEqual(initial.returncode, 0, initial.stderr)
        binding = self._bind_release(snapshot, "promotion-evidence")
        common = {
            "expected-review-gate-scope": "test_release",
            "review-gate-scope": "test_release",
            "scope-promotion": "true",
            "previous-gate-evidence": str(values["write-gate-evidence"]),
            "release-diff-kind": "same",
            "reused-passes": NORMAL_PASSES,
            "release-binding": str(binding),
        }
        reused_path = dict(values)
        reused_path.update(common)
        reused_path["write-gate-evidence"] = str(values["write-gate-evidence"])
        reused_result = self._invoke(reused_path)
        self.assertNotEqual(reused_result.returncode, 0)
        self.assertIn("must use a new path for scope promotion", reused_result.stderr)

        invalid_previous = self.directory / "invalid-previous.json"
        invalid_previous.write_text("{}", encoding="utf-8")
        bad_previous = dict(values)
        bad_previous.update(common)
        bad_previous["previous-gate-evidence"] = str(invalid_previous)
        bad_previous["write-gate-evidence"] = str(self.directory / "invalid-previous-output.json")
        invalid_result = self._invoke(bad_previous)
        self.assertNotEqual(invalid_result.returncode, 0)
        self.assertIn("previous gate evidence has an unexpected schema", invalid_result.stderr)


if __name__ == "__main__":
    unittest.main()
