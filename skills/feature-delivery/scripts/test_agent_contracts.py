from __future__ import annotations

from pathlib import Path
import re
import sys
import tomllib
import unittest
from unittest.mock import patch


CODEX_HOME = Path(__file__).resolve().parents[3]
AGENTS = CODEX_HOME / "agents"
CONFIG = CODEX_HOME / "config.toml"
SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"
REFERENCES = Path(__file__).resolve().parents[1] / "references"
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import implementation_provenance


def routed_agent_models() -> dict[str, tuple[str, str]]:
    """从唯一人类路由表解析 Agent 的 family/effort。"""
    routing = (REFERENCES / "model-routing.md").read_text(encoding="utf-8")
    result: dict[str, tuple[str, str]] = {}
    for line in routing.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4:
            continue
        agent_match = re.fullmatch(r"`([a-z0-9_]+)`", cells[1])
        model_match = re.fullmatch(r"(Luna|Terra|Sol|Astra)/(low|medium|high|xhigh|max)", cells[2])
        if agent_match is None or model_match is None:
            continue
        result[agent_match.group(1)] = (
            model_match.group(1).lower(),
            model_match.group(2),
        )
    return result


class AgentContractTest(unittest.TestCase):
    def test_agent_toml_matches_complexity_routing(self) -> None:
        for agent, (family, effort) in routed_agent_models().items():
            with self.subTest(agent=agent):
                data = tomllib.loads((AGENTS / f"{agent}.toml").read_text(encoding="utf-8"))
                self.assertTrue(data["model"].endswith(f"-{family}"))
                self.assertEqual(effort, data["model_reasoning_effort"])

    def test_reviewer_routing_does_not_depend_on_main_model(self) -> None:
        """主会话档位可由用户调整，阶段路由只读取对应 Agent 的配置。"""
        read_text = Path.read_text

        def read_agent_only(path: Path, *args, **kwargs):
            if path == CONFIG:
                raise AssertionError("Reviewer routing must not read the main model preference")
            return read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", read_agent_only):
            self.assertEqual(
                ("feature_delivery_reviewer", "independent"),
                implementation_provenance.reviewer_for_risk("normal", ("astra",)),
            )
            self.assertEqual(
                ("feature_delivery_sol_reviewer", "independent"),
                implementation_provenance.reviewer_for_risk("high", ("terra",)),
            )

    def test_simple_fix_is_lightweight_and_bounded(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        modes = (REFERENCES / "modes-and-modules.md").read_text(encoding="utf-8")
        packages = (REFERENCES / "plan-and-task-packages.md").read_text(encoding="utf-8")
        release = (REFERENCES / "review-and-release.md").read_text(encoding="utf-8")
        agent = tomllib.loads(
            (AGENTS / "feature_delivery_simple_implementer.toml").read_text(encoding="utf-8")
        )["developer_instructions"]

        for token in (
            "业务实现最多 3 个文件",
            "既有非敏感配置项",
            "已有模型名、超时",
            "不再启动独立 Reviewer、Verifier 或正式 Gate",
        ):
            self.assertIn(token, skill + modes)
        self.assertIn("targeted_fix/simple_fix` 不产生本节所称任务包", packages)
        self.assertIn("代码、测试、配置、依赖和验证命令未变化时复用", release)
        self.assertIn("不得创建 plan、provenance、snapshot、Review Gate", agent)
        self.assertIn("不得再派 Verifier 重跑", agent)

    def test_review_models_follow_review_risk(self) -> None:
        routing = (REFERENCES / "model-routing.md").read_text(encoding="utf-8")
        self.assertIn("普通风险审查 | `feature_delivery_reviewer` | Sol/high", routing)
        self.assertIn("高风险审查 | `feature_delivery_sol_reviewer` | Astra/medium", routing)
        self.assertEqual(
            ("feature_delivery_reviewer", "same_family_unavoidable"),
            implementation_provenance.reviewer_for_risk("normal", ("sol",)),
        )
        self.assertEqual(
            ("feature_delivery_sol_reviewer", "same_family_unavoidable"),
            implementation_provenance.reviewer_for_risk("high", ("astra",)),
        )

    def test_releaser_reuses_existing_validation_for_simple_fix(self) -> None:
        instructions = tomllib.loads(
            (AGENTS / "feature_delivery_releaser.toml").read_text(encoding="utf-8")
        )["developer_instructions"]
        self.assertIn("targeted_fix|simple_fix", instructions)
        self.assertIn("不要求 Review Gate", instructions)
        self.assertIn("不得重复业务测试或 Review", instructions)
        self.assertIn("whole|modular", instructions)

    def test_product_model_and_speed_controls_are_not_reimplemented(self) -> None:
        paths = [
            SKILL,
            CODEX_HOME / "skills" / "go-test" / "SKILL.md",
            CODEX_HOME / "skills" / "git-pr" / "SKILL.md",
            CODEX_HOME / "skills" / "release" / "SKILL.md",
        ]
        for path in paths:
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                for token in ("/fast on", "/fast off", "/fast status", "fast_state="):
                    self.assertNotIn(token, text)

    def test_progressive_references_remain_discoverable(self) -> None:
        entrypoint = SKILL.read_text(encoding="utf-8")
        self.assertLess(len(entrypoint.encode("utf-8")), 15_000)
        for name in (
            "model-routing.md",
            "modes-and-modules.md",
            "plan-and-task-packages.md",
            "review-and-release.md",
            "runtime-and-recovery.md",
            "targeted-fix.md",
        ):
            with self.subTest(reference=name):
                self.assertTrue((REFERENCES / name).is_file())
                self.assertIn(f"references/{name}", entrypoint)


if __name__ == "__main__":
    unittest.main()
