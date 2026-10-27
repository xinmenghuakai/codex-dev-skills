from __future__ import annotations

import unittest

from audit_plan import audit_text


VALID_REQUIRED_TEXT = """
## 范围与非目标
已确认业务口径
整体数据流和存储总览
## 模块一：示例
### 模块职责及范围
模块职责；不负责外部系统。
### 调用方式、调用方与触发时机
调用方式、调用方、触发时机均已明确。
### 接口与内部方法执行流程
接口与内部方法的执行流程已经明确。
### 数据设计
字段、类型、默认值、备注、索引、唯一约束、逻辑删除和查询方式已经明确。
### 事务、幂等、并发与失败处理
事务、幂等、并发和失败补偿均已明确。
### 代码落点与改动性质
代码落点区分现有改造、直接复用和拟新增。
### 验证范围
验证范围包含正常、边界、重复和失败用例。
改动汇总
待确认项：无
验证记录
## 计划交付项清单
| 交付项 ID | 范围状态 | 来源章节 | 交付内容 | 责任端/仓库 | 不适用依据 |
| --- | --- | --- | --- | --- | --- |
| `M1.example` | `required` | 模块一：示例 | 示例交付 | example | - |
## 附加验证材料
"""


class AuditPlanTest(unittest.TestCase):
    def test_each_module_must_be_closed_in_place(self) -> None:
        text = VALID_REQUIRED_TEXT.replace(
            "### 数据设计\n字段、类型、默认值、备注、索引、唯一约束、逻辑删除和查询方式已经明确。\n",
            "",
        ) + "\n## 存储设计\n字段和索引已经明确。\n"
        errors, _ = audit_text(text, strict=True)
        self.assertTrue(any("未在模块内闭环: 数据设计" in item for item in errors))

    def test_module_data_design_requires_each_contract_dimension(self) -> None:
        data_contract = "字段、类型、默认值、备注、索引、唯一约束、逻辑删除和查询方式已经明确。"
        for concept in (
            "字段",
            "类型",
            "默认值",
            "备注",
            "索引",
            "唯一约束",
            "逻辑删除",
            "查询方式",
        ):
            with self.subTest(concept=concept):
                text = VALID_REQUIRED_TEXT.replace(
                    data_contract,
                    data_contract.replace(concept, "对应内容已经明确", 1),
                )
                errors, _ = audit_text(text, strict=True)
                self.assertTrue(
                    any("未在模块内闭环: 数据设计" in item for item in errors)
                )

    def test_non_strict_reports_module_closure_as_warning(self) -> None:
        text = VALID_REQUIRED_TEXT.replace("代码落点", "文件位置")
        errors, warnings = audit_text(text, strict=False)
        self.assertFalse(any("未在模块内闭环" in item for item in errors))
        self.assertTrue(any("未在模块内闭环" in item for item in warnings))

    def test_fenced_example_does_not_trigger_blocking_pattern(self) -> None:
        text = VALID_REQUIRED_TEXT + "\n```text\n字段后续定稿\n```\n"
        errors, warnings = audit_text(text, strict=True)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_effective_blocking_pattern_still_reports_original_line(self) -> None:
        text = VALID_REQUIRED_TEXT + "\n<!-- 字段后续定稿 -->\n字段后续定稿\n"
        errors, _ = audit_text(text, strict=True)
        expected_line = text.splitlines().index("字段后续定稿") + 1
        self.assertEqual(
            errors,
            [f"第 {expected_line} 行: 接口或字段仍待定: 字段后续定稿"],
        )

    def test_commented_keywords_do_not_satisfy_required_sections(self) -> None:
        text = (
            "<!-- 范围 非目标 业务口径 数据流 存储总览 模块职责 "
            "触发时机 实现逻辑 存储设计 改动汇总 待确认项 验证记录 -->"
        )
        errors, _ = audit_text(text, strict=True)
        self.assertTrue(any("缺少章节或等价内容" in item for item in errors))

    def test_strict_audit_requires_valid_plan_manifest(self) -> None:
        text = VALID_REQUIRED_TEXT.split("## 计划交付项清单", 1)[0]
        errors, _ = audit_text(text, strict=True)
        self.assertTrue(any("计划交付项清单无效" in item for item in errors))

        errors, warnings = audit_text(text, strict=False)
        self.assertFalse(any("计划交付项清单无效" in item for item in errors))
        self.assertTrue(any("计划交付项清单无效" in item for item in warnings))

    def test_compound_required_concepts_cannot_replace_each_other(self) -> None:
        text = """
非目标
业务口径
存储总览
模块职责
触发时机
实现逻辑
存储设计
改动汇总
待确认项：无
验证记录
"""
        errors, _ = audit_text(text, strict=True)
        missing = next(
            item for item in errors if "缺少章节或等价内容" in item
        )
        for label in ("范围", "整体数据流", "调用方式", "接口或内部方法"):
            self.assertIn(label, missing)

    def test_commented_pending_items_do_not_block(self) -> None:
        text = VALID_REQUIRED_TEXT + "\n<!--\n## 待确认项\n- 已废弃问题\n-->\n"
        errors, _ = audit_text(text, strict=True)
        self.assertEqual(errors, [])

    def test_pending_section_requires_explicitly_resolved_content(self) -> None:
        unresolved_bodies = (
            "采用 A 还是 B？",
            "| 方案 | 状态 |\n| --- | --- |\n| A | 待定 |",
            "1) 确认是否回填",
            "",
        )
        for body in unresolved_bodies:
            with self.subTest(body=body):
                text = VALID_REQUIRED_TEXT + f"\n## 待确认项\n{body}\n"
                errors, _ = audit_text(text, strict=True)
                self.assertTrue(
                    any("仍有进入实现前待确认内容" in item for item in errors)
                )

        for resolved in ("无", "- 无", "1. 暂无", "已全部确认，无阻塞项"):
            with self.subTest(resolved=resolved):
                text = VALID_REQUIRED_TEXT + f"\n## 待确认项\n{resolved}\n"
                errors, _ = audit_text(text, strict=True)
                self.assertEqual(errors, [])

        errors, _ = audit_text(
            VALID_REQUIRED_TEXT + "\n## 进入实现前必须补齐：无\n",
            strict=True,
        )
        self.assertEqual(errors, [])

    def test_plain_pending_label_with_unresolved_body_is_blocking(self) -> None:
        text = VALID_REQUIRED_TEXT + "\n待确认项：\n- 采用 A 还是 B\n"
        errors, _ = audit_text(text, strict=True)
        self.assertTrue(
            any("仍有进入实现前待确认内容" in item for item in errors)
        )

    def test_inline_code_does_not_satisfy_or_trigger_audit_patterns(self) -> None:
        labels = (
            "范围 非目标 已确认业务口径 数据流 存储总览 模块职责 "
            "触发时机 实现逻辑 存储设计 改动汇总 待确认项 验证记录"
        )
        errors, _ = audit_text(f"`{labels}`", strict=True)
        self.assertTrue(any("缺少章节或等价内容" in item for item in errors))

        errors, _ = audit_text(
            VALID_REQUIRED_TEXT + "\n示例：`字段后续定稿`\n",
            strict=True,
        )
        self.assertEqual(errors, [])

        errors, _ = audit_text(
            VALID_REQUIRED_TEXT + "\n\\`字段后续定稿`\n",
            strict=True,
        )
        self.assertTrue(any("接口或字段仍待定" in item for item in errors))

        errors, _ = audit_text(
            VALID_REQUIRED_TEXT + "\n示例：`\n后续补充\n`\n",
            strict=True,
        )
        self.assertTrue(any("实现细节仍为空" in item for item in errors))

        errors, _ = audit_text(
            VALID_REQUIRED_TEXT
            + "\n未闭合 `\n- 字段后续定稿\n`\n",
            strict=True,
        )
        self.assertTrue(any("接口或字段仍待定" in item for item in errors))

        errors, _ = audit_text(
            VALID_REQUIRED_TEXT
            + "\n未闭合 `\n> 字段后续定稿\n`\n",
            strict=True,
        )
        self.assertTrue(any("接口或字段仍待定" in item for item in errors))

    def test_specific_validation_scope_is_not_treated_as_placeholder(self) -> None:
        errors, _ = audit_text(
            VALID_REQUIRED_TEXT
            + "\n验证至少覆盖以下明确用例：正常、空值、重复回调、超时\n",
            strict=True,
        )
        self.assertEqual(errors, [])

        errors, _ = audit_text(
            VALID_REQUIRED_TEXT + "\n至少覆盖\n",
            strict=True,
        )
        self.assertTrue(any("验证范围不具体" in item for item in errors))

        errors, _ = audit_text(
            VALID_REQUIRED_TEXT
            + "\n验证至少覆盖：\n- 正常路径\n- 空值边界\n- 重复回调\n",
            strict=True,
        )
        self.assertEqual(errors, [])

        errors, _ = audit_text(
            VALID_REQUIRED_TEXT
            + "\n验证至少覆盖：\n- `TestCreate`\n",
            strict=True,
        )
        self.assertEqual(errors, [])

        for placeholder in ("待定", "TODO", "具体范围尚未确定", "   ", "`TODO`"):
            with self.subTest(placeholder=placeholder):
                errors, _ = audit_text(
                    VALID_REQUIRED_TEXT
                    + f"\n验证至少覆盖：\n- {placeholder}\n",
                    strict=True,
                )
                self.assertTrue(
                    any("验证范围不具体" in item for item in errors)
                )

        errors, _ = audit_text(
            VALID_REQUIRED_TEXT
            + "\n验证至少覆盖：\n- 正常路径\n- TODO\n",
            strict=True,
        )
        self.assertTrue(any("验证范围不具体" in item for item in errors))

    def test_repeated_and_long_findings_are_bounded_and_counted(self) -> None:
        long_match = "接口字段" + "很长" * 1000 + "后续定稿"
        text = VALID_REQUIRED_TEXT + "\n" + "\n".join(
            [long_match] + ["字段后续定稿"] * 100
        )
        errors, _ = audit_text(text, strict=True)
        self.assertEqual(len(errors), 6)
        self.assertTrue(all(len(item) < 220 for item in errors))
        self.assertIn("共 101 处，仅列前 5 处", errors[-1])


if __name__ == "__main__":
    unittest.main()
