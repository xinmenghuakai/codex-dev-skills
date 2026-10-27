from __future__ import annotations

import unittest

from plan_manifest import PlanManifestError, parse_plan_manifest


def plan(rows: str, extra_module: str = "") -> str:
    return f"""# 研发计划

## 模块一：后端
后端方案。

## 模块二：客户端
客户端方案。
{extra_module}
## 计划交付项清单

| 交付项 ID | 范围状态 | 来源章节 | 交付内容 | 责任端/仓库 | 不适用依据 |
| --- | --- | --- | --- | --- | --- |
{rows}
"""


VALID_ROWS = """| `M1.backend` | `required` | 模块一：后端 | 调整推荐文案 | api | - |
| `M2.app` | `not_applicable` | 模块二：客户端 | 调整按钮文案 | App | 用户确认不在本期范围 |"""


class PlanManifestTest(unittest.TestCase):
    def test_valid_manifest_preserves_order_and_scope(self) -> None:
        manifest = parse_plan_manifest(plan(VALID_ROWS))
        self.assertEqual(manifest.item_ids, ("M1.backend", "M2.app"))
        self.assertEqual(manifest.not_applicable_ids, ("M2.app",))

    def test_manifest_section_is_required_and_unique(self) -> None:
        with self.assertRaisesRegex(PlanManifestError, "当前为 0 个"):
            parse_plan_manifest("# 计划\n## 模块一：后端\n正文\n")
        with self.assertRaisesRegex(PlanManifestError, "当前为 2 个"):
            parse_plan_manifest(plan(VALID_ROWS) + "\n## 计划交付项清单\n")

    def test_duplicate_id_is_rejected(self) -> None:
        rows = VALID_ROWS + "\n| `M1.backend` | `required` | 模块一：后端 | 重复 | api | - |"
        with self.assertRaisesRegex(PlanManifestError, "必须唯一"):
            parse_plan_manifest(plan(rows))

    def test_scope_and_reason_are_validated(self) -> None:
        invalid_rows = (
            "| `M1.backend` | `pending` | 模块一：后端 | 调整 | api | - |",
            "| `M1.backend` | `not_applicable` | 模块一：后端 | 调整 | api | - |",
            "| `M1.backend` | `required` | 模块一：后端 | 调整 | api | 不该填写 |",
        )
        for rows in invalid_rows:
            with self.subTest(rows=rows):
                with self.assertRaises(PlanManifestError):
                    parse_plan_manifest(plan(rows))

    def test_source_must_be_real_heading(self) -> None:
        rows = "| `M1.backend` | `required` | 不存在模块 | 调整 | api | - |"
        with self.assertRaisesRegex(PlanManifestError, "不.*真实标题"):
            parse_plan_manifest(plan(rows))

    def test_every_module_heading_needs_manifest_item(self) -> None:
        rows = "| `M1.backend` | `required` | 模块一：后端 | 调整 | api | - |"
        with self.assertRaisesRegex(PlanManifestError, "模块二：客户端"):
            parse_plan_manifest(plan(rows))

    def test_fenced_and_commented_fake_manifest_are_ignored(self) -> None:
        text = """# 计划
```md
## 计划交付项清单
| 交付项 ID | 范围状态 | 来源章节 | 交付内容 | 责任端/仓库 | 不适用依据 |
```
<!-- ## 计划交付项清单 -->
"""
        with self.assertRaisesRegex(PlanManifestError, "当前为 0 个"):
            parse_plan_manifest(text)

    def test_manifest_rows_cannot_resume_after_a_blank_line(self) -> None:
        rows = """| `M1.backend` | `required` | 模块一：后端 | 调整 | api | - |

| `M2.app` | `required` | 模块二：客户端 | 调整 | App | - |"""
        with self.assertRaisesRegex(PlanManifestError, "必须保持连续"):
            parse_plan_manifest(plan(rows))

    def test_manifest_rejects_text_after_data_rows(self) -> None:
        rows = VALID_ROWS + "\n补充说明"
        with self.assertRaisesRegex(PlanManifestError, "不能包含其他正文"):
            parse_plan_manifest(plan(rows))


if __name__ == "__main__":
    unittest.main()
