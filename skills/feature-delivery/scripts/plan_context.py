#!/usr/bin/env python3
"""列出或定向提取 Markdown plan 章节，避免阶段 Agent 默认读取全文。"""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
import re
import sys
from dataclasses import dataclass
from pathlib import Path


HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
LINE_RANGE_RE = re.compile(r"^(\d+):(\d+)$")
BACKTICK_RUN_RE = re.compile(r"`+")
MAX_AMBIGUOUS_OPTIONS = 20
MAX_DISPLAY_TITLE_CHARS = 160
MAX_SECTIONS = 120
MAX_OUTPUT_LINES = 400
MAX_OUTPUT_CHARS = 12000


@dataclass(frozen=True)
class Section:
    level: int
    title: str
    start: int
    end: int


def mask_segment(segment: str) -> str:
    """用空格屏蔽文本并保留换行和字符偏移。"""
    return "".join(char if char in "\r\n" else " " for char in segment)


def backtick_run_positions(line: str) -> dict[int, list[int]]:
    """按反引号连续长度预索引本行位置，避免重复扫描整行。"""
    positions: dict[int, list[int]] = {}
    for match in BACKTICK_RUN_RE.finditer(line):
        positions.setdefault(len(match.group(0)), []).append(match.start())
    return positions


def has_closing_backtick_run(
    positions: dict[int, list[int]],
    start: int,
    marker_length: int,
) -> bool:
    """确认本行存在等长闭合符，避免未闭合标记吞掉后续结构。"""
    candidates = positions.get(marker_length, [])
    return bisect_left(candidates, start) < len(candidates)


def is_escaped(line: str, position: int) -> bool:
    """判断当前位置前是否有奇数个连续反斜杠。"""
    backslashes = 0
    cursor = position - 1
    while cursor >= 0 and line[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def mask_non_effective_markdown(text: str, mask_inline_code: bool = False) -> str:
    """屏蔽 fenced code 与 HTML 注释，可选屏蔽行内代码并保留偏移。"""
    output: list[str] = []
    fence_char: str | None = None
    fence_length = 0
    in_html_comment = False
    inline_code_ticks = 0
    lines = text.splitlines(keepends=True)

    for line in lines:
        if fence_char is not None:
            fence = FENCE_RE.match(line)
            if fence:
                marker = fence.group(1)
                info = fence.group(2)
                if (
                    marker[0] == fence_char
                    and len(marker) >= fence_length
                    and not info.strip()
                ):
                    fence_char = None
                    fence_length = 0
            output.append(mask_segment(line))
            continue

        if not in_html_comment and inline_code_ticks == 0:
            fence = FENCE_RE.match(line)
            if fence:
                marker = fence.group(1)
                info = fence.group(2)
                if not (marker[0] == "`" and "`" in info):
                    fence_char = marker[0]
                    fence_length = len(marker)
                    output.append(mask_segment(line))
                    continue

        visible: list[str] = []
        cursor = 0
        tick_positions = backtick_run_positions(line)
        while cursor < len(line):
            if in_html_comment:
                end = line.find("-->", cursor)
                if end < 0:
                    visible.append(mask_segment(line[cursor:]))
                    cursor = len(line)
                    continue
                visible.append(mask_segment(line[cursor : end + 3]))
                cursor = end + 3
                in_html_comment = False
                continue

            if inline_code_ticks:
                if line[cursor] == "`":
                    end = cursor
                    while end < len(line) and line[end] == "`":
                        end += 1
                    marker = line[cursor:end]
                    visible.append(mask_segment(marker) if mask_inline_code else marker)
                    if len(marker) == inline_code_ticks:
                        inline_code_ticks = 0
                    cursor = end
                    continue
                visible.append(
                    mask_segment(line[cursor])
                    if mask_inline_code
                    else line[cursor]
                )
                cursor += 1
                continue

            if line.startswith("<!--", cursor) and not is_escaped(line, cursor):
                visible.append(mask_segment("<!--"))
                in_html_comment = True
                cursor += 4
                continue

            if line[cursor] == "`" and not is_escaped(line, cursor):
                end = cursor
                while end < len(line) and line[end] == "`":
                    end += 1
                marker = line[cursor:end]
                closes_inline_code = has_closing_backtick_run(
                    tick_positions,
                    end,
                    len(marker),
                )
                visible.append(
                    mask_segment(marker)
                    if mask_inline_code and closes_inline_code
                    else marker
                )
                if closes_inline_code:
                    inline_code_ticks = len(marker)
                cursor = end
                continue

            visible.append(line[cursor])
            cursor += 1
        output.append("".join(visible))
    return "".join(output)


def normalize_heading_title(raw_title: str | None) -> str:
    """只移除符合 ATX 语法的闭合井号，保留 C# 等合法标题内容。"""
    title = (raw_title or "").strip()
    if re.fullmatch(r"#+", title):
        return ""
    return re.sub(r"[ \t]+#+[ \t]*$", "", title).strip()


def parse_sections(text: str) -> list[Section]:
    lines = mask_non_effective_markdown(text).splitlines()
    headings: list[tuple[int, int, str]] = []
    for line_no, line in enumerate(lines, start=1):
        match = HEADING_RE.match(line)
        if match:
            headings.append(
                (line_no, len(match.group(1)), normalize_heading_title(match.group(2)))
            )

    ends = [len(lines)] * len(headings)
    open_headings: list[int] = []
    for index, (start, level, _) in enumerate(headings):
        while open_headings and headings[open_headings[-1]][1] >= level:
            ends[open_headings.pop()] = start - 1
        open_headings.append(index)
    return [
        Section(level=level, title=title, start=start, end=ends[index])
        for index, (start, level, title) in enumerate(headings)
    ]


def display_title(title: str, max_chars: int = MAX_DISPLAY_TITLE_CHARS) -> str:
    if len(title) <= max_chars:
        return title
    return title[: max_chars - 1] + "…"


def select_by_title(sections: list[Section], query: str) -> Section:
    normalized = query.casefold().strip()
    if not normalized:
        raise ValueError("标题查询不能为空")
    exact = [section for section in sections if section.title.casefold() == normalized]
    matches = exact or [section for section in sections if normalized in section.title.casefold()]
    if not matches:
        raise ValueError(f"标题未匹配: {display_title(query, 80)}")
    if len(matches) > 1:
        shown = matches[:MAX_AMBIGUOUS_OPTIONS]
        options = "、".join(
            f"{item.start}:{display_title(item.title, 80)}" for item in shown
        )
        remaining = len(matches) - len(shown)
        suffix = f"；另有 {remaining} 个候选" if remaining else ""
        raise ValueError(
            f"标题匹配不唯一，共 {len(matches)} 个: {display_title(query, 80)} -> "
            f"{options}{suffix}；请改用 --find 或 --line"
        )
    return matches[0]


def select_sections(
    sections: list[Section],
    titles: list[str],
    start_lines: list[int],
) -> list[Section]:
    by_start = {section.start: section for section in sections}
    selected = [select_by_title(sections, title) for title in titles]
    for line_no in start_lines:
        if line_no not in by_start:
            raise ValueError(f"第 {line_no} 行不是标题起始行")
        selected.append(by_start[line_no])
    unique: list[Section] = []
    for section in sorted(set(selected), key=lambda item: (item.start, -item.end)):
        if any(item.start <= section.start and section.end <= item.end for item in unique):
            continue
        unique.append(section)
    return unique


def parse_explicit_range(raw_range: str, total_lines: int) -> Section:
    """解析受文件边界约束的精确行段，供超长叶子章节继续拆包。"""
    match = LINE_RANGE_RE.fullmatch(raw_range.strip())
    if not match:
        raise ValueError(f"无效行段 {display_title(raw_range, 80)}，应使用 起始行:结束行")
    start, end = (int(value) for value in match.groups())
    if start < 1 or end < start or end > total_lines:
        raise ValueError(
            f"行段越界: {start}:{end}，文件有效范围为 1:{total_lines}"
        )
    return Section(level=0, title="精确行段", start=start, end=end)


def render_section(section: Section, lines: list[str]) -> str:
    """渲染单个章节或精确行段，并保留来源行号。"""
    return (
        f"--- {section.start}-{section.end} {display_title(section.title)} ---\n"
        + "\n".join(lines[section.start - 1 : section.end])
    )


def leaf_sections(sections: list[Section]) -> list[Section]:
    """返回没有子标题的叶子章节。"""
    return [
        section
        for index, section in enumerate(sections)
        if index + 1 == len(sections)
        or sections[index + 1].level <= section.level
    ]


def validate_explicit_ranges(
    ranges: list[Section],
    sections: list[Section],
    lines: list[str],
    max_lines: int,
    max_chars: int,
) -> None:
    """限制精确行段只能拆分同一个超出本次输出上限的叶子章节。"""
    leaves = leaf_sections(sections)
    leaf_starts = [section.start for section in leaves]
    source_leaf: Section | None = None
    previous: Section | None = None

    for selected_range in ranges:
        leaf_index = bisect_right(leaf_starts, selected_range.start) - 1
        if leaf_index < 0 or selected_range.end > leaves[leaf_index].end:
            raise ValueError(
                f"行段 {selected_range.start}:{selected_range.end} "
                "必须完整位于一个叶子章节内，不能跨标题"
            )
        leaf = leaves[leaf_index]
        leaf_lines = leaf.end - leaf.start + 1
        leaf_chars = len(render_section(leaf, lines)) + 1
        if leaf_lines <= max_lines and leaf_chars <= max_chars:
            raise ValueError(
                f"叶子章节 {display_title(leaf.title, 80)} 未超过 "
                f"{max_lines} 行且未超过 {max_chars} 字符，"
                "无需使用 --range"
            )
        if source_leaf is not None and leaf != source_leaf:
            raise ValueError("重复的 --range 必须位于同一个超长叶子章节")
        if previous is not None:
            if selected_range.start < previous.start:
                raise ValueError("重复的 --range 必须按起始行升序提供")
            if selected_range.start <= previous.end:
                raise ValueError("重复的 --range 不能重叠")
        source_leaf = leaf
        previous = selected_range


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--list", action="store_true", help="只列出标题与精确行范围")
    parser.add_argument("--find", action="append", default=[], help="按标题关键词过滤列表，可重复")
    parser.add_argument("--section", action="append", default=[], help="按唯一标题提取，可重复")
    parser.add_argument("--line", action="append", default=[], type=int, help="按标题起始行提取，可重复")
    parser.add_argument(
        "--range",
        action="append",
        default=[],
        help="拆分同一超长叶子章节，可重复使用精确起始行:结束行",
    )
    parser.add_argument(
        "--max-sections",
        type=int,
        default=MAX_SECTIONS,
        help=f"列表最多输出的标题数，不得超过 {MAX_SECTIONS}",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=MAX_OUTPUT_LINES,
        help=f"最多输出的正文行数，不得超过 {MAX_OUTPUT_LINES}",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=MAX_OUTPUT_CHARS,
        help=f"最多输出的字符数，不得超过 {MAX_OUTPUT_CHARS}",
    )
    args = parser.parse_args()

    if not args.plan.is_file():
        print(f"FAIL plan 不存在: {args.plan}", file=sys.stderr)
        return 1
    if args.max_lines <= 0:
        print("FAIL --max-lines 必须大于 0", file=sys.stderr)
        return 1
    if args.max_sections <= 0:
        print("FAIL --max-sections 必须大于 0", file=sys.stderr)
        return 1
    if args.max_chars <= 0:
        print("FAIL --max-chars 必须大于 0", file=sys.stderr)
        return 1
    if args.max_lines > MAX_OUTPUT_LINES:
        print(f"FAIL --max-lines 不得超过硬上限 {MAX_OUTPUT_LINES}", file=sys.stderr)
        return 1
    if args.max_sections > MAX_SECTIONS:
        print(f"FAIL --max-sections 不得超过硬上限 {MAX_SECTIONS}", file=sys.stderr)
        return 1
    if args.max_chars > MAX_OUTPUT_CHARS:
        print(f"FAIL --max-chars 不得超过硬上限 {MAX_OUTPUT_CHARS}", file=sys.stderr)
        return 1
    if args.list and (args.section or args.line or args.range):
        print("FAIL --list 不能与 --section/--line/--range 同时使用", file=sys.stderr)
        return 1
    if args.find and (args.section or args.line or args.range):
        print(
            "FAIL --find 只用于标题列表，不能与 --section/--line/--range 同时使用",
            file=sys.stderr,
        )
        return 1
    if args.range and (args.section or args.line):
        print("FAIL --range 不能与 --section/--line 同时使用", file=sys.stderr)
        return 1

    text = args.plan.read_text(encoding="utf-8")
    lines = text.splitlines()
    sections = parse_sections(text)
    if not sections:
        print("FAIL plan 中没有 Markdown 标题", file=sys.stderr)
        return 1

    if args.list or args.find or not (args.section or args.line or args.range):
        listed_sections = sections
        if args.find:
            queries = [query.casefold().strip() for query in args.find if query.strip()]
            if not queries:
                print("FAIL --find 关键词不能为空", file=sys.stderr)
                return 1
            listed_sections = [
                section
                for section in sections
                if any(query in section.title.casefold() for query in queries)
            ]
            if not listed_sections:
                print("FAIL 没有标题匹配 --find 关键词", file=sys.stderr)
                return 2

        output_lines: list[str] = []
        output_chars = 0
        for section in listed_sections[: args.max_sections]:
            line = (
                f"{section.start}-{section.end}\t"
                f"{'#' * section.level} {display_title(section.title)}"
            )
            next_chars = output_chars + (1 if output_lines else 0) + len(line)
            if next_chars + 1 > args.max_chars:
                break
            output_lines.append(line)
            output_chars = next_chars
        if output_lines:
            print("\n".join(output_lines))
        if len(output_lines) < len(listed_sections):
            print(
                f"FAIL 标题共 {len(listed_sections)} 个，仅输出前 "
                f"{len(output_lines)} 个；请使用 --find 缩小范围",
                file=sys.stderr,
            )
            return 2
        return 0

    try:
        explicit_ranges = [
            parse_explicit_range(raw_range, len(lines)) for raw_range in args.range
        ]
        validate_explicit_ranges(
            explicit_ranges,
            sections,
            lines,
            args.max_lines,
            args.max_chars,
        )
        selected = (
            explicit_ranges
            if explicit_ranges
            else select_sections(sections, args.section, args.line)
        )
    except ValueError as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 2

    output_lines = sum(section.end - section.start + 1 for section in selected)
    if output_lines > args.max_lines:
        print(
            f"FAIL 选中 {output_lines} 行，超过 --max-lines={args.max_lines}；请缩小章节范围",
            file=sys.stderr,
        )
        return 2

    blocks = [render_section(section, lines) for section in selected]
    output = "\n\n".join(blocks)
    output_chars = len(output) + 1
    if output_chars > args.max_chars:
        print(
            f"FAIL 选中内容共 {output_chars} 字符，超过 --max-chars={args.max_chars}；"
            "请缩小章节范围",
            file=sys.stderr,
        )
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
