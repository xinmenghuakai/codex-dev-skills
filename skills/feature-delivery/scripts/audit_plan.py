#!/usr/bin/env python3
"""检查研发 plan 是否达到可确认、可实现的最低结构要求。"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Iterator
import re
import sys
from pathlib import Path

from plan_context import (
    HEADING_RE,
    display_title,
    mask_non_effective_markdown,
    parse_sections,
)
from plan_manifest import PlanManifestError, parse_plan_manifest


BLOCKING_PATTERNS = {
    "验证范围不具体": (
        r"^ {0,3}(?:(?:本模块)?验证(?:范围)?[ \t]*)?"
        r"至少覆盖[ \t]*(?:[：:。；;][ \t]*)?(?=\r?$)"
    ),
    "实现细节仍为空": r"实现时设计|后续补充|(?<!没有)(?<!暂无)(?<!无)待补充",
}

REQUIRED_SECTIONS = {
    "范围": (r"范围",),
    "非目标": (r"非目标",),
    "业务口径": (r"业务口径",),
    "整体数据流": (r"数据流",),
    "存储总览": (r"存储总览",),
    "模块职责": (r"模块职责",),
    "调用方式": (r"调用方式", r"调用方", r"调用入口"),
    "触发时机": (r"触发时机",),
    "接口或内部方法": (r"接口", r"内部方法"),
    "实现逻辑": (r"实现逻辑", r"执行逻辑", r"执行流程"),
    "存储设计": (r"存储设计", r"数据设计"),
    "改动汇总": (r"改动汇总", r"改动总览"),
    "待确认项": (r"待确认项", r"进入实现前必须补齐"),
    "验证记录": (r"验证记录", r"验证矩阵"),
}
MODULE_HEADING_RE = re.compile(
    r"^模块[零〇一二三四五六七八九十百0-9]+(?:[：:\s]|$)"
)
MODULE_REQUIRED_CONCEPTS = {
    "模块职责及范围": (r"模块职责", r"不负责|不包含|不涉及|范围"),
    "调用方式、调用方与触发时机": (r"调用方式", r"调用方", r"触发时机"),
    "接口与内部方法执行流程": (
        r"接口(?:与|或)内部方法|接口|内部方法",
        r"执行顺序|执行流程|实现逻辑|执行逻辑",
    ),
    "数据设计": (
        r"数据设计",
        r"字段|不落库",
        r"类型|不涉及类型",
        r"默认值|不涉及默认值",
        r"备注|不涉及备注",
        r"索引|不涉及索引|无索引",
        r"唯一约束|不涉及唯一约束",
        r"逻辑删除|不涉及逻辑删除",
        r"查询方式|不涉及查询",
    ),
    "事务、幂等、并发与失败处理": (
        r"事务",
        r"幂等",
        r"并发|不涉及并发",
        r"失败|补偿|降级|回滚",
    ),
    "代码落点与改动性质": (
        r"代码落点",
        r"现有改造|直接复用|拟新增",
    ),
    "验证范围": (r"验证范围",),
}
MAX_MATCHES_PER_PATTERN = 5
MAX_PENDING_SECTIONS = 10
MAX_FINDING_TEXT_CHARS = 160
RESOLVED_PENDING_RE = re.compile(
    r"^(?:(?:待确认项|进入实现前必须补齐)\s*[:：]\s*)?"
    r"(?:无|暂无|没有|不涉及|无阻塞(?:项)?|已清空|已全部确认(?:[，,]\s*无阻塞(?:项)?)?)"
    r"[。.!！；;]*$"
)
PLAIN_PENDING_RE = re.compile(
    r"^\s*(?:待确认项|进入实现前必须补齐)\s*[:：]\s*(.*?)\s*$"
)


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def has_following_validation_scope(text: str, offset: int) -> bool:
    """判断行尾“至少覆盖”后是否紧跟具体范围，避免把列表引导语当占位。"""
    if text.startswith("\r\n", offset):
        cursor = offset + 2
    elif text.startswith("\n", offset):
        cursor = offset + 1
    else:
        return False
    found_item = False
    while cursor < len(text):
        line_end = text.find("\n", cursor)
        if line_end < 0:
            line_end = len(text)
        line = text[cursor:line_end].removesuffix("\r")
        if not line.strip() or HEADING_RE.match(line):
            break
        item = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$", line)
        if not item:
            return False
        content = re.sub(r"`+", "", item.group(1)).strip()
        if not content:
            return False
        if re.search(
            r"^(?:待定|TODO|TBD|后续(?:补充|确认)?|尚未确定|未确定|具体范围尚未确定)$",
            content,
            flags=re.IGNORECASE,
        ):
            return False
        found_item = True
        cursor = line_end + 1
    return found_item


def interface_pending_in_line(line: str) -> tuple[int, str] | None:
    """在线性扫描内定位接口/字段仍待定占位。"""
    candidates: list[tuple[int, int]] = []
    direct = line.find("字段后续定稿")
    if direct >= 0:
        candidates.append((direct, direct + len("字段后续定稿")))
    prefix = re.search(r"接口(?:名称)?和?字段", line)
    if prefix:
        suffix = line.find("后续定稿", prefix.end())
        if suffix >= 0:
            candidates.append((prefix.start(), suffix + len("后续定稿")))
    if not candidates:
        return None
    start, end = min(candidates)
    return start, display_title(line[start:end], MAX_FINDING_TEXT_CHARS)


def schema_pending_in_line(line: str) -> tuple[int, str] | None:
    """在线性扫描内定位表结构推迟设计占位。"""
    candidates: list[tuple[int, int]] = []
    prefix = line.find("表结构")
    if prefix >= 0:
        suffixes = [
            position
            for phrase in ("实现时设计", "实现时再设计")
            if (position := line.find(phrase, prefix + len("表结构"))) >= 0
        ]
        if suffixes:
            suffix = min(suffixes)
            phrase = (
                "实现时再设计"
                if line.startswith("实现时再设计", suffix)
                else "实现时设计"
            )
            candidates.append((prefix, suffix + len(phrase)))
    formal = line.find("正式表结构")
    if formal >= 0:
        suffix = line.find("实现时", formal + len("正式表结构"))
        if suffix >= 0:
            candidates.append((formal, suffix + len("实现时")))
    if not candidates:
        return None
    start, end = min(candidates)
    return start, display_title(line[start:end], MAX_FINDING_TEXT_CHARS)


def line_rule_matches(
    text: str, detector: Callable[[str], tuple[int, str] | None]
) -> Iterator[tuple[int, str]]:
    """按行执行无回溯检测器并返回原文偏移。"""
    offset = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        result = detector(content)
        if result:
            position, matched_text = result
            yield offset + position, matched_text
        offset += len(line)


def regex_rule_matches(
    text: str, validation_text: str, label: str, pattern: str
) -> Iterator[tuple[int, str]]:
    """流式返回正则规则命中，避免重复占位产生无界中间列表。"""
    for match in re.finditer(
        pattern, text, flags=re.IGNORECASE | re.MULTILINE
    ):
        if (
            label == "验证范围不具体"
            and has_following_validation_scope(validation_text, match.end())
        ):
            continue
        yield match.start(), match.group(0)


def append_bounded_findings(
    errors: list[str],
    effective_text: str,
    label: str,
    matches: Iterable[tuple[int, str]],
) -> None:
    """每类只展示少量定位样本，同时保留准确总数。"""
    match_count = 0
    for offset, matched_text in matches:
        match_count += 1
        if match_count <= MAX_MATCHES_PER_PATTERN:
            errors.append(
                f"第 {line_number(effective_text, offset)} 行: "
                f"{label}: "
                f"{display_title(matched_text, MAX_FINDING_TEXT_CHARS)}"
            )
    if match_count > MAX_MATCHES_PER_PATTERN:
        errors.append(
            f"{label}: 共 {match_count} 处，仅列前 "
            f"{MAX_MATCHES_PER_PATTERN} 处"
        )


def pending_sections(text: str) -> list[tuple[int, str]]:
    effective_lines = mask_non_effective_markdown(
        text, mask_inline_code=True
    ).splitlines()
    unresolved: list[tuple[int, str]] = []
    for section in parse_sections(text):
        if not re.search(r"待确认项|进入实现前必须补齐", section.title):
            continue
        body_lines = [
            line.strip()
            for line in effective_lines[section.start : section.end]
            if line.strip()
        ]
        normalized_body = [
            re.sub(r"^(?:[-*+]|\d+[.)])\s*", "", line).strip()
            for line in body_lines
        ]
        resolved_title = bool(RESOLVED_PENDING_RE.fullmatch(section.title.strip()))
        resolved_body = bool(normalized_body) and all(
            RESOLVED_PENDING_RE.fullmatch(line) for line in normalized_body
        )
        if not ((resolved_title and not normalized_body) or resolved_body):
            unresolved.append((section.start, section.title))

    for line_index, line in enumerate(effective_lines):
        match = PLAIN_PENDING_RE.fullmatch(line)
        if not match:
            continue
        suffix = match.group(1).strip()
        if suffix:
            if not RESOLVED_PENDING_RE.fullmatch(suffix):
                unresolved.append((line_index + 1, line.strip()))
            continue
        following: list[str] = []
        for next_index in range(line_index + 1, len(effective_lines)):
            candidate = effective_lines[next_index]
            stripped = candidate.strip()
            if not stripped:
                break
            if HEADING_RE.match(candidate):
                break
            following.append(
                re.sub(r"^(?:[-*+]|\d+[.)])\s*", "", stripped).strip()
            )
        if not following or not all(
            RESOLVED_PENDING_RE.fullmatch(item) for item in following
        ):
            unresolved.append((line_index + 1, line.strip()))
    return unresolved


def module_closure_errors(text: str) -> list[str]:
    """逐模块检查方案闭环，禁止由全局章节代替模块内部契约。"""
    effective_lines = mask_non_effective_markdown(
        text, mask_inline_code=True
    ).splitlines()
    modules = [
        section
        for section in parse_sections(text)
        if MODULE_HEADING_RE.search(section.title)
    ]
    errors: list[str] = []
    for module in modules:
        module_text = "\n".join(effective_lines[module.start - 1 : module.end])
        missing = [
            label
            for label, patterns in MODULE_REQUIRED_CONCEPTS.items()
            if not all(
                re.search(pattern, module_text, flags=re.IGNORECASE)
                for pattern in patterns
            )
        ]
        if missing:
            errors.append(
                f"第 {module.start} 行: {display_title(module.title, 80)} "
                "未在模块内闭环: " + "、".join(missing)
            )
    return errors


def audit_text(text: str, strict: bool) -> tuple[list[str], list[str]]:
    effective_text = mask_non_effective_markdown(text, mask_inline_code=True)
    validation_text = mask_non_effective_markdown(text)
    errors: list[str] = []
    warnings: list[str] = []

    for label, detector in (
        ("接口或字段仍待定", interface_pending_in_line),
        ("表结构推迟到实现阶段", schema_pending_in_line),
    ):
        append_bounded_findings(
            errors,
            effective_text,
            label,
            line_rule_matches(effective_text, detector),
        )

    for label, pattern in BLOCKING_PATTERNS.items():
        append_bounded_findings(
            errors,
            effective_text,
            label,
            regex_rule_matches(effective_text, validation_text, label, pattern),
        )

    missing = [
        label
        for label, patterns in REQUIRED_SECTIONS.items()
        if not any(
            re.search(pattern, effective_text, flags=re.IGNORECASE)
            for pattern in patterns
        )
    ]
    if missing:
        message = "缺少章节或等价内容: " + "、".join(missing)
        (errors if strict else warnings).append(message)

    module_errors = module_closure_errors(text)
    (errors if strict else warnings).extend(module_errors)

    try:
        parse_plan_manifest(text)
    except PlanManifestError as error:
        (errors if strict else warnings).append(f"计划交付项清单无效: {error}")

    unresolved = pending_sections(text)
    for line, title in unresolved[:MAX_PENDING_SECTIONS]:
        errors.append(
            f"第 {line} 行: 仍有进入实现前待确认内容: "
            f"{display_title(title, MAX_FINDING_TEXT_CHARS)}"
        )
    if len(unresolved) > MAX_PENDING_SECTIONS:
        errors.append(
            f"进入实现前待确认章节共 {len(unresolved)} 个，仅列前 "
            f"{MAX_PENDING_SECTIONS} 个"
        )
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("--strict", action="store_true", help="缺少必需章节时返回失败")
    args = parser.parse_args()

    if not args.plan.is_file():
        print(f"FAIL plan 不存在: {args.plan}", file=sys.stderr)
        return 1

    text = args.plan.read_text(encoding="utf-8")
    errors, warnings = audit_text(text, args.strict)

    if errors:
        print("FAIL plan 未达到技术方案确认门槛")
        for item in errors:
            print(f"- {item}")
    if warnings:
        print("WARN")
        for item in warnings:
            print(f"- {item}")
    if errors:
        return 1

    print(f"PASS {args.plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
