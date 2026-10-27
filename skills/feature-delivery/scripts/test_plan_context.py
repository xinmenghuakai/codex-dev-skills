from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plan_context import (
    Section,
    main,
    parse_explicit_range,
    parse_sections,
    select_by_title,
    select_sections,
)


PLAN = """# 研发计划

## 范围与非目标
范围正文

## 功能模块
模块总览

### 模块一
模块一正文

### 模块二
模块二正文

## 验证记录
验证正文
"""


class PlanContextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sections = parse_sections(PLAN)

    def test_section_ranges_follow_heading_levels(self) -> None:
        ranges = [(item.title, item.start, item.end) for item in self.sections]
        self.assertEqual(
            ranges,
            [
                ("研发计划", 1, 16),
                ("范围与非目标", 3, 5),
                ("功能模块", 6, 14),
                ("模块一", 9, 11),
                ("模块二", 12, 14),
                ("验证记录", 15, 16),
            ],
        )

    def test_exact_title_wins_over_partial_match(self) -> None:
        section = select_by_title(self.sections, "功能模块")
        self.assertEqual(section.start, 6)

    def test_ambiguous_partial_title_requires_line(self) -> None:
        with self.assertRaisesRegex(ValueError, "匹配不唯一"):
            select_by_title(self.sections, "模块")

    def test_nested_selection_is_not_duplicated(self) -> None:
        selected = select_sections(self.sections, ["功能模块"], [9])
        self.assertEqual([(item.start, item.end) for item in selected], [(6, 14)])

    def test_headings_inside_fenced_code_are_ignored(self) -> None:
        sections = parse_sections("# 计划\n\n```md\n## 伪标题\n```\n\n## 真实标题\n正文\n")
        self.assertEqual([item.title for item in sections], ["计划", "真实标题"])

    def test_tilde_fence_and_longer_closing_fence_are_supported(self) -> None:
        sections = parse_sections("# 计划\n~~~md\n## 伪标题\n~~~~   \n## 真实标题\n")
        self.assertEqual([item.title for item in sections], ["计划", "真实标题"])

    def test_different_marker_does_not_close_fence(self) -> None:
        sections = parse_sections("# 计划\n```md\n~~~\n## 伪标题\n``` \n## 真实标题\n")
        self.assertEqual([item.title for item in sections], ["计划", "真实标题"])

    def test_invalid_backtick_info_does_not_open_fence(self) -> None:
        sections = parse_sections("# 计划\n```md`bad\n## 真实标题\n")
        self.assertEqual([item.title for item in sections], ["计划", "真实标题"])

    def test_commonmark_heading_indentation_and_closing_hashes(self) -> None:
        sections = parse_sections("# 计划\n  ## 兼容 C#\n   ### 细节 ###\n")
        self.assertEqual([item.title for item in sections], ["计划", "兼容 C#", "细节"])

    def test_html_comments_do_not_create_headings(self) -> None:
        sections = parse_sections(
            "# 计划\n<!--\n## 已废弃\n-->\n## 当前 <!-- 行内说明 -->\n"
        )
        self.assertEqual([item.title for item in sections], ["计划", "当前"])

    def test_html_comment_marker_inside_inline_code_is_preserved(self) -> None:
        sections = parse_sections(
            "# 计划\n说明 HTML 字面量 `<!--` 的用法\n## 后续章节\n正文\n"
        )
        self.assertEqual([item.title for item in sections], ["计划", "后续章节"])

    def test_html_comment_marker_inside_fence_info_does_not_leak(self) -> None:
        sections = parse_sections(
            "# 计划\n```html <!--\n## 伪标题\n```\n## 后续章节\n"
        )
        self.assertEqual([item.title for item in sections], ["计划", "后续章节"])

    def test_escaped_html_comment_opener_does_not_hide_heading(self) -> None:
        sections = parse_sections("# 计划\n\\<!-- 字面量\n## 后续章节\n")
        self.assertEqual([item.title for item in sections], ["计划", "后续章节"])

    def test_tab_indented_fence_marker_does_not_open_fence(self) -> None:
        sections = parse_sections("# 计划\n\t```md\n## 后续章节\n")
        self.assertEqual([item.title for item in sections], ["计划", "后续章节"])

    def test_unclosed_backtick_does_not_hide_real_html_comment(self) -> None:
        sections = parse_sections(
            "# 计划\n未闭合 ` 标记 <!--\n## 已注释标题\n-->\n## 后续章节\n"
        )
        self.assertEqual([item.title for item in sections], ["计划", "后续章节"])

    def test_unclosed_multiline_backtick_does_not_override_html_comment(self) -> None:
        sections = parse_sections(
            "# 计划\n前文 `\n<!-- `\n## 已注释标题\n-->\n## 后续章节\n"
        )
        self.assertEqual([item.title for item in sections], ["计划", "后续章节"])

    def test_ambiguous_title_error_is_bounded(self) -> None:
        sections = [
            Section(level=2, title=f"模块{index}", start=index, end=index)
            for index in range(1, 1001)
        ]
        with self.assertRaisesRegex(ValueError, "另有 980 个候选") as context:
            select_by_title(sections, "模块")
        self.assertLess(len(str(context.exception)), 2000)

    def test_empty_title_query_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "不能为空"):
            select_by_title(self.sections, " ")

    def test_unmatched_title_error_is_bounded(self) -> None:
        with self.assertRaises(ValueError) as context:
            select_by_title(self.sections, "不存在" * 1000)
        self.assertLess(len(str(context.exception)), 200)

    def test_explicit_range_validates_file_bounds(self) -> None:
        self.assertEqual(
            parse_explicit_range("2:4", 5),
            Section(level=0, title="精确行段", start=2, end=4),
        )
        for raw_range in ("0:1", "3:2", "1:6", "bad"):
            with self.subTest(raw_range=raw_range):
                with self.assertRaises(ValueError):
                    parse_explicit_range(raw_range, 5)

    def test_list_limit_and_title_filter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.md"
            plan.write_text(
                "# 计划\n" + "".join(f"## 模块{index}\n正文\n" for index in range(4)),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["plan_context.py", str(plan), "--list", "--max-sections", "2"],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(main(), 2)
            self.assertEqual(stdout.getvalue().count("\t"), 2)
            self.assertIn("--find", stderr.getvalue())

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "plan_context.py",
                        str(plan),
                        "--find",
                        "模块3",
                        "--max-sections",
                        "2",
                    ],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(main(), 0)
            self.assertIn("模块3", stdout.getvalue())
            self.assertEqual(stderr.getvalue(), "")

    def test_selected_output_character_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.md"
            plan.write_text("# 计划\n" + "正文" * 100, encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "plan_context.py",
                        str(plan),
                        "--section",
                        "计划",
                        "--max-chars",
                        "20",
                    ],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(main(), 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("--max-chars=20", stderr.getvalue())

    def test_explicit_range_can_split_long_leaf_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.md"
            plan.write_text("# 超长章节\n" + "正文\n" * 500, encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "plan_context.py",
                        str(plan),
                        "--section",
                        "超长章节",
                    ],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(main(), 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("--max-lines=400", stderr.getvalue())

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "plan_context.py",
                        str(plan),
                        "--range",
                        "1:200",
                    ],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(main(), 0)
            self.assertIn("--- 1-200 精确行段 ---", stdout.getvalue())
            self.assertEqual(stderr.getvalue(), "")

    def test_explicit_range_rejects_plan_without_heading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.md"
            plan.write_text("第一行\n第二行\n", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["plan_context.py", str(plan), "--range", "1:2"],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(main(), 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("没有 Markdown 标题", stderr.getvalue())

    def test_explicit_range_rejects_short_leaf_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.md"
            plan.write_text(PLAN, encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["plan_context.py", str(plan), "--range", "9:10"],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(main(), 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("无需使用 --range", stderr.getvalue())

    def test_explicit_range_rejects_cross_heading_and_different_leaves(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.md"
            text = (
                "# 计划\n\n## 第一章节\n"
                + "甲\n" * 500
                + "## 第二章节\n"
                + "乙\n" * 500
            )
            plan.write_text(text, encoding="utf-8")
            first, second = parse_sections(text)[1:]

            cases = [
                (
                    [
                        "--range",
                        f"{first.end - 1}:{second.start + 1}",
                    ],
                    "不能跨标题",
                ),
                (
                    [
                        "--range",
                        f"{first.start}:{first.start + 10}",
                        "--range",
                        f"{second.start}:{second.start + 10}",
                    ],
                    "同一个超长叶子章节",
                ),
            ]
            for arguments, expected_error in cases:
                with self.subTest(arguments=arguments):
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with (
                        mock.patch.object(
                            sys,
                            "argv",
                            ["plan_context.py", str(plan), *arguments],
                        ),
                        contextlib.redirect_stdout(stdout),
                        contextlib.redirect_stderr(stderr),
                    ):
                        self.assertEqual(main(), 2)
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertIn(expected_error, stderr.getvalue())

    def test_explicit_range_rejects_mixed_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.md"
            plan.write_text("# 超长章节\n" + "正文\n" * 500, encoding="utf-8")
            for selector in (["--section", "超长章节"], ["--line", "1"]):
                with self.subTest(selector=selector):
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with (
                        mock.patch.object(
                            sys,
                            "argv",
                            [
                                "plan_context.py",
                                str(plan),
                                *selector,
                                "--range",
                                "1:100",
                            ],
                        ),
                        contextlib.redirect_stdout(stdout),
                        contextlib.redirect_stderr(stderr),
                    ):
                        self.assertEqual(main(), 1)
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertIn("不能与 --section/--line 同时使用", stderr.getvalue())

    def test_repeated_ranges_must_be_ordered_and_non_overlapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.md"
            plan.write_text("# 超长章节\n" + "正文\n" * 500, encoding="utf-8")
            cases = [
                (["100:120", "50:80"], "升序"),
                (["1:200", "200:300"], "不能重叠"),
            ]
            for ranges, expected_error in cases:
                with self.subTest(ranges=ranges):
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    arguments = [
                        argument
                        for selected_range in ranges
                        for argument in ("--range", selected_range)
                    ]
                    with (
                        mock.patch.object(
                            sys,
                            "argv",
                            ["plan_context.py", str(plan), *arguments],
                        ),
                        contextlib.redirect_stdout(stdout),
                        contextlib.redirect_stderr(stderr),
                    ):
                        self.assertEqual(main(), 2)
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertIn(expected_error, stderr.getvalue())

    def test_repeated_ranges_in_same_long_leaf_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.md"
            plan.write_text("# 超长章节\n" + "正文\n" * 500, encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "plan_context.py",
                        str(plan),
                        "--range",
                        "1:200",
                        "--range",
                        "201:400",
                    ],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(main(), 0)
            self.assertIn("--- 1-200 精确行段 ---", stdout.getvalue())
            self.assertIn("--- 201-400 精确行段 ---", stdout.getvalue())
            self.assertEqual(stderr.getvalue(), "")

    def test_explicit_range_supports_leaf_over_character_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.md"
            plan.write_text(
                "# 超宽章节\n" + ("字" * 200 + "\n") * 100,
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["plan_context.py", str(plan), "--range", "1:50"],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(main(), 0)
            self.assertIn("--- 1-50 精确行段 ---", stdout.getvalue())
            self.assertEqual(stderr.getvalue(), "")

    def test_explicit_range_uses_lower_effective_limits(self) -> None:
        cases = [
            (
                "# 中等章节\n" + "正文\n" * 149,
                ["--range", "1:100", "--max-lines", "100"],
                "--- 1-100 精确行段 ---",
            ),
            (
                "# 中等宽章节\n" + ("字" * 100 + "\n") * 80,
                ["--range", "1:30", "--max-chars", "4000"],
                "--- 1-30 精确行段 ---",
            ),
        ]
        for text, arguments, expected_header in cases:
            with self.subTest(arguments=arguments):
                with tempfile.TemporaryDirectory() as directory:
                    plan = Path(directory) / "plan.md"
                    plan.write_text(text, encoding="utf-8")
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with (
                        mock.patch.object(
                            sys,
                            "argv",
                            ["plan_context.py", str(plan), *arguments],
                        ),
                        contextlib.redirect_stdout(stdout),
                        contextlib.redirect_stderr(stderr),
                    ):
                        self.assertEqual(main(), 0)
                    self.assertIn(expected_header, stdout.getvalue())
                    self.assertEqual(stderr.getvalue(), "")

    def test_output_limits_cannot_exceed_hard_caps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.md"
            plan.write_text(PLAN, encoding="utf-8")
            cases = [
                ("--max-sections", "121", "120"),
                ("--max-lines", "401", "400"),
                ("--max-chars", "12001", "12000"),
            ]
            for option, value, hard_limit in cases:
                with self.subTest(option=option):
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with (
                        mock.patch.object(
                            sys,
                            "argv",
                            ["plan_context.py", str(plan), option, value],
                        ),
                        contextlib.redirect_stdout(stdout),
                        contextlib.redirect_stderr(stderr),
                    ):
                        self.assertEqual(main(), 1)
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertIn(f"硬上限 {hard_limit}", stderr.getvalue())

    def test_list_output_including_final_newline_respects_character_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.md"
            plan.write_text("# 计划\n## " + "长标题" * 100 + "\n", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "plan_context.py",
                        str(plan),
                        "--list",
                        "--max-chars",
                        "12",
                    ],
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(main(), 2)
            self.assertLessEqual(len(stdout.getvalue()), 12)
            self.assertIn("--find", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
