#!/usr/bin/env python3
"""implementation_provenance.py 的确定性回归测试。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from freeze_snapshot import load_and_verify_snapshot
from implementation_provenance import (
    ProvenanceError,
    load_provenance,
    validate_provenance,
    canonical_families,
    reviewer_for_risk,
)


FREEZE_SCRIPT = Path(__file__).with_name("freeze_snapshot.py")


class AstraRoutingTest(unittest.TestCase):
    """风险与来源家族独立变化时，路由和独立性必须保持一致。"""

    def test_model_families_and_reviewer_independence(self) -> None:
        self.assertEqual(canonical_families({"astra", "luna", "terra", "sol"}), ("luna", "terra", "sol", "astra"))
        for risk in ("small", "normal", "high"):
            reviewer = "feature_delivery_sol_reviewer" if risk == "high" else "feature_delivery_reviewer"
            review_family = "astra" if risk == "high" else "sol"
            for families in ((), ("luna",), ("terra",), ("astra",), ("terra", "astra"), ("sol",)):
                with self.subTest(risk=risk, families=families):
                    independence = "same_family_unavoidable" if review_family in families else "independent"
                    self.assertEqual(reviewer_for_risk(risk, families), (reviewer, independence))
        for invalid in (None, "", "unknown"):
            with self.subTest(invalid=invalid), self.assertRaises(ProvenanceError):
                reviewer_for_risk(invalid, ("terra",))
        self.assertEqual(
            reviewer_for_risk("normal", ("unknown",)),
            ("feature_delivery_reviewer", "source_unknown"),
        )
        with self.assertRaises(ProvenanceError):
            reviewer_for_risk("normal", ("invented_family",))


def current_branch_ref(repository: Path) -> str:
    """测试夹具显式传入真实 target branch，不能再以 HEAD 充当发布基线。"""
    return subprocess.run(
        ["git", "-C", str(repository), "symbolic-ref", "-q", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def plan_manifest_text(description: str) -> str:
    return "\n".join(
        (
            "# 计划",
            "## 模块1：后端",
            description,
            "## 计划交付项清单",
            "| 交付项 ID | 范围状态 | 来源章节 | 交付内容 | 责任端/仓库 | 不适用依据 |",
            "| --- | --- | --- | --- | --- | --- |",
            "| M1.backend | required | 模块1：后端 | 实现服务 | repo | - |",
            "",
        )
    )


class ImplementationProvenanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        directory = Path(cls._temp.name)
        cls.repo = directory / "repo"
        cls.repo.mkdir()
        for arguments in (
            ("init", "-q"),
            ("config", "user.email", "skill-test@example.invalid"),
            ("config", "user.name", "Skill Test"),
        ):
            subprocess.run(["git", "-C", str(cls.repo), *arguments], check=True)
        for filename in ("a.go", "b.go"):
            (cls.repo / filename).write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(cls.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(cls.repo), "commit", "-qm", "base"], check=True)
        (cls.repo / "a.go").write_text("changed a\n", encoding="utf-8")
        (cls.repo / "b.go").write_text("changed b\n", encoding="utf-8")
        cls.snapshot_path = directory / "snapshot.json"
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(FREEZE_SCRIPT),
                "--repo-target",
                f"{cls.repo}={current_branch_ref(cls.repo)}",
                "--output",
                str(cls.snapshot_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.snapshot, _ = load_and_verify_snapshot(cls.snapshot_path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def provenance(self, name: str, entries: list[dict[str, object]]) -> dict[str, object]:
        path = Path(self._temp.name) / name
        path.write_text(
            json.dumps({"schema_version": 2, "entries": entries}), encoding="utf-8"
        )
        return load_provenance(path)

    def entry(
        self,
        task_id: str,
        agent: str,
        model: str,
        paths: list[str],
        *,
        entry_type: str = "implementation",
    ) -> dict[str, object]:
        return {
            "entry_type": entry_type,
            "task_id": task_id,
            "module_id": task_id,
            "selected_agent": agent,
            "selected_model": model,
            "plan_item_ids": ["M1.backend"],
            "files": [{"repo": str(self.repo), "path": path} for path in paths],
        }

    def test_derives_heterogeneous_reviewer_route(self) -> None:
        luna = self.provenance(
            "luna.json",
            [
                self.entry(
                    "impl-luna",
                    "feature_delivery_simple_implementer",
                    "gpt-6-luna/high",
                    ["a.go", "b.go"],
                )
            ],
        )
        luna_summary = validate_provenance(
            luna, self.snapshot, ("M1.backend",), (), risk_level="normal",
        )
        self.assertEqual(luna_summary.families, ("luna",))
        self.assertEqual(luna_summary.selected_reviewer, "feature_delivery_reviewer")
        self.assertEqual(luna_summary.review_independence, "independent")

        mixed = self.provenance(
            "mixed.json",
            [
                self.entry(
                    "impl-sol",
                    "feature_delivery_implementer",
                    "gpt-6.1-sol/high",
                    ["a.go"],
                ),
                self.entry(
                    "impl-astra",
                    "feature_delivery_critical_implementer",
                    "gpt-6-astra/medium",
                    ["b.go"],
                ),
            ],
        )
        mixed_summary = validate_provenance(
            mixed, self.snapshot, ("M1.backend",), (), risk_level="high",
        )
        self.assertEqual(mixed_summary.families, ("sol", "astra"))
        self.assertEqual(mixed_summary.selected_reviewer, "feature_delivery_sol_reviewer")
        self.assertEqual(mixed_summary.review_independence, "same_family_unavoidable")

    def external_bundle(self, name, agent, model, *, evidence_text="用户声明与会话/Git来源：a.go、b.go\n"):
        """冻结人工/主会话来源，不读真实项目或连接外部服务。"""
        directory = Path(self._temp.name)
        evidence = directory / f"{name}-source.txt"
        evidence.write_text(evidence_text, encoding="utf-8")
        entry = self.entry(name, agent, model, ["a.go", "b.go"])
        entry["source_evidence"] = str(evidence)
        provenance = directory / f"{name}-v3.json"
        provenance.write_text(json.dumps({"schema_version": 3, "entries": [entry]}))
        output = directory / f"{name}-snapshot.json"
        result = subprocess.run([
            sys.executable, "-B", str(FREEZE_SCRIPT),
            "--repo-target", f"{self.repo}={current_branch_ref(self.repo)}",
            "--artifact", f"implementation_provenance={provenance}",
            "--artifact", f"auxiliary={evidence}", "--output", str(output),
        ], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot, _ = load_and_verify_snapshot(output)
        return load_provenance(provenance), snapshot, evidence, provenance

    def test_external_sources_preserve_truthful_family_and_coverage(self):
        """人工不冒充模型；已知主会话按真实家族判断，未知来源不宣称异构。"""
        cases = (
            ("human", "none", (), "independent"),
            ("main_agent", "gpt-6-astra/medium", ("astra",), "independent"),
            ("main_agent", "gpt-6-sol/high", ("sol",), "same_family_unavoidable"),
            ("main_agent", "gpt-6.1-sol/high", ("sol",), "same_family_unavoidable"),
            ("external_agent", "unknown", ("unknown",), "source_unknown"),
            ("unknown_source", "unknown", ("unknown",), "source_unknown"),
            ("external_agent", "other-model/high", ("unknown",), "source_unknown"),
        )
        for index, (agent, model, families, independence) in enumerate(cases):
            with self.subTest(agent=agent, model=model):
                provenance, snapshot, _, _ = self.external_bundle(f"source-{index}", agent, model)
                summary = validate_provenance(provenance, snapshot, ("M1.backend",), (), risk_level="normal")
                self.assertEqual(summary.families, families)
                self.assertEqual(summary.review_independence, independence)
                provenance["entries"][0]["files"].pop()
                with self.assertRaisesRegex(ProvenanceError, "does not cover implementation"):
                    validate_provenance(provenance, snapshot, ("M1.backend",), (), risk_level="normal")

    def test_external_source_requires_frozen_nonempty_unchanged_evidence(self):
        """只声明作者不足以通过，来源证据必须冻结且不能在审查后被替换。"""
        provenance, snapshot, evidence, _ = self.external_bundle("evidence-change", "human", "none")
        with self.assertRaisesRegex(ProvenanceError, "frozen auxiliary"):
            validate_provenance(provenance, self.snapshot, ("M1.backend",), (), risk_level="normal")
        evidence.write_text("改写来源\n", encoding="utf-8")
        with self.assertRaisesRegex(ProvenanceError, "frozen auxiliary"):
            validate_provenance(provenance, snapshot, ("M1.backend",), (), risk_level="normal")
        empty, empty_snapshot, _, _ = self.external_bundle("empty-source", "human", "none", evidence_text=" ")
        with self.assertRaisesRegex(ProvenanceError, "frozen auxiliary"):
            validate_provenance(empty, empty_snapshot, ("M1.backend",), (), risk_level="normal")

    def test_external_source_rejects_false_models_legacy_schema_and_missing_evidence(self):
        """新来源必须显式用 v3，不能伪造模型或省掉来源文件。"""
        provenance, _, _, path = self.external_bundle("invalid-source", "human", "none")
        cases = (
            {"schema_version": 2},
            {"selected_model": "gpt-6-astra/medium"},
            {"source_evidence": "relative.txt"},
            {"selected_agent": []},
            {"drop_evidence": True},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                raw = json.loads(json.dumps(provenance))
                if "schema_version" in changes:
                    raw.update(changes)
                elif "drop_evidence" in changes:
                    del raw["entries"][0]["source_evidence"]
                else:
                    raw["entries"][0].update(changes)
                path.write_text(json.dumps(raw))
                with self.assertRaises(ProvenanceError):
                    load_provenance(path)

    def test_rejects_missing_or_false_writer_provenance(self) -> None:
        missing = self.provenance(
            "missing.json",
            [
                self.entry(
                    "impl-sol",
                    "feature_delivery_implementer",
                    "gpt-6.1-sol/high",
                    ["a.go"],
                )
            ],
        )
        with self.assertRaisesRegex(
            ProvenanceError, "does not cover implementation snapshot files"
        ):
            validate_provenance(missing, self.snapshot, ("M1.backend",), (), risk_level="normal",)

        path = Path(self._temp.name) / "wrong-model.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "entries": [
                        self.entry(
                            "impl-false",
                            "feature_delivery_implementer",
                            "gpt-5.6-sol/high",
                            ["a.go", "b.go"],
                        )
                    ],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ProvenanceError, "does not match selected_agent"):
            load_provenance(path)

        # 旧 Sol 来源和未经配置的 high 档位不能作为迁移后 Astra/medium 的实现证据。
        for model in ("gpt-5.6-sol/high", "gpt-6-astra/high"):
            with self.subTest(model=model), self.assertRaisesRegex(ProvenanceError, "does not match selected_agent"):
                self.provenance("old-critical.json", [self.entry(
                    "critical-old", "feature_delivery_critical_implementer", model, ["a.go", "b.go"]
                )])

    def test_rejects_previous_sol_model_for_pinned_agent(self) -> None:
        """固定 Agent 升级后，旧型号来源不能冒充新型号证据。"""
        with self.assertRaisesRegex(ProvenanceError, "does not match selected_agent"):
            self.provenance("previous-sol.json", [self.entry(
                "previous-sol", "feature_delivery_implementer", "gpt-6-sol/high",
                ["a.go", "b.go"],
            )])

    def test_scope_contract_has_planner_source_without_polluting_reviewer_route(self) -> None:
        """仓库内 plan 的真实写入来源必须保留，但不能误算为代码实现 family。"""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            repository = directory / "repo"
            repository.mkdir()
            for arguments in (
                ("init", "-q"),
                ("config", "user.email", "skill-test@example.invalid"),
                ("config", "user.name", "Skill Test"),
            ):
                subprocess.run(["git", "-C", str(repository), *arguments], check=True)
            (repository / "service.go").write_text("base\n", encoding="utf-8")
            plan = repository / "plan.md"
            plan.write_text(plan_manifest_text("base"), encoding="utf-8")
            subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repository), "commit", "-qm", "base"], check=True
            )
            (repository / "service.go").write_text("changed\n", encoding="utf-8")
            plan.write_text(plan_manifest_text("changed"), encoding="utf-8")
            provenance_path = directory / "provenance.json"
            provenance_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "entries": [
                            {
                                "entry_type": "implementation",
                                "task_id": "impl",
                                "module_id": "backend",
                                "selected_agent": "feature_delivery_implementer",
                                "selected_model": "gpt-6.1-sol/high",
                                "plan_item_ids": ["M1.backend"],
                                "files": [
                                    {"repo": str(repository), "path": "service.go"}
                                ],
                            },
                            {
                                "entry_type": "scope_contract",
                                "task_id": "plan",
                                "module_id": "whole",
                                "selected_agent": "feature_delivery_planner",
                                "selected_model": "gpt-6.1-sol/xhigh",
                                "plan_item_ids": ["M1.backend"],
                                "files": [{"repo": str(repository), "path": "plan.md"}],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            snapshot_path = directory / "snapshot.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(FREEZE_SCRIPT),
                    "--repo-target",
                    f"{repository}={current_branch_ref(repository)}",
                    "--artifact",
                    f"plan_manifest={plan}",
                    "--artifact",
                    f"implementation_provenance={provenance_path}",
                    "--output",
                    str(snapshot_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot, _ = load_and_verify_snapshot(snapshot_path)
            provenance = load_provenance(provenance_path)
            summary = validate_provenance(
                provenance,
                snapshot,
                ("M1.backend",),
                (str(plan),), risk_level="normal",
            )
            self.assertEqual(summary.families, ("sol",))
            self.assertEqual(
                summary.selected_reviewer, "feature_delivery_reviewer"
            )
            self.assertEqual(summary.review_independence, "same_family_unavoidable")

    def test_rejects_scope_contract_file_claimed_as_implementation(self) -> None:
        """Planner 的仓库内 plan 不能靠伪装成 Implementer 通过 Gate。"""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            repository = directory / "repo"
            repository.mkdir()
            for arguments in (
                ("init", "-q"),
                ("config", "user.email", "skill-test@example.invalid"),
                ("config", "user.name", "Skill Test"),
            ):
                subprocess.run(["git", "-C", str(repository), *arguments], check=True)
            plan = repository / "plan.md"
            plan.write_text(plan_manifest_text("base"), encoding="utf-8")
            subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repository), "commit", "-qm", "base"], check=True
            )
            plan.write_text(plan_manifest_text("changed"), encoding="utf-8")
            provenance_path = directory / "wrong-provenance.json"
            provenance_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "entries": [
                            {
                                "entry_type": "implementation",
                                "task_id": "wrong",
                                "module_id": "whole",
                                "selected_agent": "feature_delivery_implementer",
                                "selected_model": "gpt-6.1-sol/high",
                                "plan_item_ids": [],
                                "files": [{"repo": str(repository), "path": "plan.md"}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            snapshot_path = directory / "wrong-snapshot.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(FREEZE_SCRIPT),
                    "--repo-target",
                    f"{repository}={current_branch_ref(repository)}",
                    "--artifact",
                    f"plan_manifest={plan}",
                    "--artifact",
                    f"implementation_provenance={provenance_path}",
                    "--output",
                    str(snapshot_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot, _ = load_and_verify_snapshot(snapshot_path)
            provenance = load_provenance(provenance_path)
            with self.assertRaisesRegex(
                ProvenanceError, "contains implementation files outside its scope"
            ):
                validate_provenance(
                    provenance,
                    snapshot,
                    (),
                    (str(plan),), risk_level="normal",
                )

    def test_auxiliary_migration_cannot_be_promoted_to_scope_contract(self) -> None:
        """migration/API artefact 即使被列入 scope 参数，也不能逃避实施来源覆盖。"""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            repository = directory / "repo"
            repository.mkdir()
            for arguments in (
                ("init", "-q"),
                ("config", "user.email", "skill-test@example.invalid"),
                ("config", "user.name", "Skill Test"),
            ):
                subprocess.run(["git", "-C", str(repository), *arguments], check=True)
            migration = repository / "001.sql"
            migration.write_text("-- base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repository), "commit", "-qm", "base"], check=True)
            migration.write_text("-- reviewed DDL\n", encoding="utf-8")
            provenance_path = directory / "provenance.json"
            provenance_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "entries": [
                            {
                                "entry_type": "implementation",
                                "task_id": "ddl",
                                "module_id": "database",
                                "selected_agent": "feature_delivery_implementer",
                                "selected_model": "gpt-6.1-sol/high",
                                "plan_item_ids": [],
                                "files": [{"repo": str(repository), "path": "001.sql"}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            snapshot_path = directory / "migration-snapshot.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(FREEZE_SCRIPT),
                    "--repo-target",
                    f"{repository}={current_branch_ref(repository)}",
                    "--artifact",
                    f"auxiliary={migration}",
                    "--artifact",
                    f"implementation_provenance={provenance_path}",
                    "--output",
                    str(snapshot_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot, _ = load_and_verify_snapshot(snapshot_path)
            provenance = load_provenance(provenance_path)
            with self.assertRaisesRegex(ProvenanceError, "must use plan_manifest"):
                validate_provenance(
                    provenance, snapshot, (), (str(migration),), risk_level="normal",
                )
            summary = validate_provenance(provenance, snapshot, (), (), risk_level="normal",)
            self.assertEqual(summary.families, ("sol",))

    def test_multiple_scope_contributors_can_attest_same_plan(self) -> None:
        """同一 plan 可由 Planner 和 Architect 提供边界，不会变成实现的多写入。"""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            repository = directory / "repo"
            repository.mkdir()
            for arguments in (
                ("init", "-q"),
                ("config", "user.email", "skill-test@example.invalid"),
                ("config", "user.name", "Skill Test"),
            ):
                subprocess.run(["git", "-C", str(repository), *arguments], check=True)
            service = repository / "service.go"
            plan = repository / "plan.md"
            service.write_text("base\n", encoding="utf-8")
            plan.write_text(plan_manifest_text("base"), encoding="utf-8")
            subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repository), "commit", "-qm", "base"], check=True)
            service.write_text("changed\n", encoding="utf-8")
            plan.write_text(plan_manifest_text("changed"), encoding="utf-8")
            provenance_path = directory / "contributors.json"
            entries = [
                {
                    "entry_type": "implementation",
                    "task_id": "impl",
                    "module_id": "backend",
                    "selected_agent": "feature_delivery_implementer",
                    "selected_model": "gpt-6.1-sol/high",
                    "plan_item_ids": ["M1.backend"],
                    "files": [{"repo": str(repository), "path": "service.go"}],
                },
                {
                    "entry_type": "scope_contract",
                    "task_id": "planner",
                    "module_id": "scope",
                    "selected_agent": "feature_delivery_planner",
                    "selected_model": "gpt-6.1-sol/xhigh",
                    "plan_item_ids": ["M1.backend"],
                    "files": [{"repo": str(repository), "path": "plan.md"}],
                },
                {
                    "entry_type": "scope_contract",
                    "task_id": "architect",
                    "module_id": "scope",
                    "selected_agent": "feature_delivery_architect",
                    "selected_model": "gpt-6.1-sol/xhigh",
                    "plan_item_ids": ["M1.backend"],
                    "files": [{"repo": str(repository), "path": "plan.md"}],
                },
            ]
            provenance_path.write_text(json.dumps({"schema_version": 2, "entries": entries}), encoding="utf-8")
            snapshot_path = directory / "contributors-snapshot.json"
            result = subprocess.run(
                [
                    sys.executable, "-B", str(FREEZE_SCRIPT), "--repo-target", f"{repository}={current_branch_ref(repository)}",
                    "--artifact", f"plan_manifest={plan}",
                    "--artifact", f"implementation_provenance={provenance_path}",
                    "--output", str(snapshot_path),
                ], capture_output=True, text=True, check=False
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot, _ = load_and_verify_snapshot(snapshot_path)
            summary = validate_provenance(
                load_provenance(provenance_path), snapshot, ("M1.backend",), (str(plan),), risk_level="normal",
            )
            self.assertEqual(summary.families, ("sol",))

            # 同一冻结 plan 的主会话增量来源不改变业务实现的 Reviewer 路由。
            main_entry = dict(entries[1], task_id="main-plan-update",
                              selected_agent="main_agent", selected_model="gpt-6-astra/medium")
            parsed = self.provenance("main-plan.json", [*entries, main_entry])
            main_summary = validate_provenance(parsed, snapshot, ("M1.backend",), (str(plan),), risk_level="normal",)
            self.assertEqual(main_summary, summary)

            # 文档来源不能认领业务代码；主会话实现必须走 v3 并提供冻结来源证据。
            bad_entry = dict(main_entry, files=[{"repo": str(repository), "path": "service.go"}])
            bad = self.provenance("main-code.json", [bad_entry])
            with self.assertRaisesRegex(ProvenanceError, "only claim plan_manifest"):
                validate_provenance(bad, snapshot, ("M1.backend",), (str(plan),), risk_level="normal",)
            with self.assertRaises(ProvenanceError):
                self.provenance("main-impl.json", [dict(main_entry, entry_type="implementation")])
            for model in ("", "current", "default/high", "current/medium", "gpt-6-astra", "gpt-6-astra/invalid"):
                with self.subTest(model=model), self.assertRaisesRegex(ProvenanceError, "actual model/effort"):
                    self.provenance("main-model.json", [dict(main_entry, selected_model=model)])


if __name__ == "__main__":
    unittest.main()
