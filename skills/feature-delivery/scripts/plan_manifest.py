#!/usr/bin/env python3
"""解析 plan 中机器可校验的原子交付项清单。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys

from plan_context import mask_non_effective_markdown, parse_sections


MANIFEST_TITLE = "计划交付项清单"
PLAN_ITEM_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,127}")
MODULE_HEADING_PATTERN = re.compile(
    r"模块[零〇一二三四五六七八九十百0-9]+(?:[：:\s]|$)"
)
SCOPES = {"required", "not_applicable"}
HEADER = ("交付项 id", "范围状态", "来源章节", "交付内容", "责任端/仓库", "不适用依据")


class PlanManifestError(ValueError):
    """plan 交付项清单缺失或格式不合法。"""


@dataclass(frozen=True)
class PlanItem:
    item_id: str
    scope: str
    source: str
    description: str
    owner: str
    not_applicable_reason: str
    line: int


@dataclass(frozen=True)
class PlanManifest:
    items: tuple[PlanItem, ...]

    @property
    def item_ids(self) -> tuple[str, ...]:
        return tuple(item.item_id for item in self.items)

    @property
    def not_applicable_ids(self) -> tuple[str, ...]:
        return tuple(
            item.item_id for item in self.items if item.scope == "not_applicable"
        )


def clean_cell(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        value = value[1:-1].strip()
    return value


def split_row(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return None
    return tuple(clean_cell(cell) for cell in stripped[1:-1].split("|"))


def is_delimiter(cells: tuple[str, ...]) -> bool:
    return bool(cells) and all(
        re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells
    )


def parse_plan_manifest(text: str) -> PlanManifest:
    sections = parse_sections(text)
    matches = [section for section in sections if section.title == MANIFEST_TITLE]
    if len(matches) != 1:
        raise PlanManifestError(
            f"必须且只能有一个标题为“{MANIFEST_TITLE}”的章节，当前为 {len(matches)} 个"
        )

    section = matches[0]
    visible_lines = mask_non_effective_markdown(text).splitlines()
    body = visible_lines[section.start : section.end]
    header_index = -1
    for index, line in enumerate(body):
        cells = split_row(line)
        if cells and tuple(cell.casefold() for cell in cells) == HEADER:
            header_index = index
            break
    if header_index < 0:
        raise PlanManifestError(
            "交付项清单必须使用固定六列表头：交付项 ID、范围状态、来源章节、交付内容、责任端/仓库、不适用依据"
        )
    if header_index + 1 >= len(body):
        raise PlanManifestError("交付项清单缺少表头分隔行")
    delimiter = split_row(body[header_index + 1])
    if delimiter is None or len(delimiter) != len(HEADER) or not is_delimiter(delimiter):
        raise PlanManifestError("交付项清单表头分隔行不合法")

    heading_titles = {item.title for item in sections}
    items: list[PlanItem] = []
    table_ended = False
    for offset in range(header_index + 2, len(body)):
        cells = split_row(body[offset])
        if cells is None:
            if not items:
                raise PlanManifestError("交付项清单表头后必须直接给出数据行")
            if body[offset].strip():
                raise PlanManifestError("交付项清单数据后不能包含其他正文")
            table_ended = True
            continue
        line = section.start + offset + 1
        if table_ended:
            raise PlanManifestError(f"第 {line} 行交付项数据必须保持连续")
        if len(cells) != len(HEADER):
            raise PlanManifestError(f"第 {line} 行必须包含六列")
        item_id, scope, source, description, owner, reason = cells
        scope = scope.casefold()
        if not PLAN_ITEM_PATTERN.fullmatch(item_id):
            raise PlanManifestError(f"第 {line} 行交付项 ID 不合法: {item_id}")
        if scope not in SCOPES:
            raise PlanManifestError(
                f"第 {line} 行范围状态只能是 required 或 not_applicable"
            )
        if source not in heading_titles or source == MANIFEST_TITLE:
            raise PlanManifestError(f"第 {line} 行来源章节不是当前 plan 的真实标题: {source}")
        if not description or not owner:
            raise PlanManifestError(f"第 {line} 行交付内容和责任端/仓库不能为空")
        if scope == "not_applicable" and reason in ("", "-", "无", "不涉及"):
            raise PlanManifestError(f"第 {line} 行 not_applicable 必须填写已确认依据")
        if scope == "required" and reason not in ("", "-"):
            raise PlanManifestError(f"第 {line} 行 required 的不适用依据必须为 -")
        items.append(
            PlanItem(item_id, scope, source, description, owner, reason, line)
        )

    if not items:
        raise PlanManifestError("交付项清单至少需要一条数据")
    ids = [item.item_id for item in items]
    if len(set(ids)) != len(ids):
        raise PlanManifestError("交付项 ID 必须唯一")

    referenced_sources = {item.source for item in items}
    module_titles = {
        item.title for item in sections if MODULE_HEADING_PATTERN.search(item.title)
    }
    missing_modules = sorted(module_titles - referenced_sources)
    if missing_modules:
        raise PlanManifestError(
            "以下功能模块没有任何原子交付项: " + "、".join(missing_modules)
        )
    return PlanManifest(tuple(items))


def load_plan_manifest(path: Path) -> PlanManifest:
    if not path.is_file():
        raise PlanManifestError(f"plan 不存在: {path}")
    return parse_plan_manifest(path.read_text(encoding="utf-8"))


def render_ids(values: tuple[str, ...]) -> str:
    return ",".join(values) if values else "none"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    args = parser.parse_args()
    try:
        manifest = load_plan_manifest(args.plan)
    except (OSError, UnicodeError, PlanManifestError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    print(f"plan_item_ids={render_ids(manifest.item_ids)}")
    print(
        "not_applicable_plan_item_ids="
        f"{render_ids(manifest.not_applicable_ids)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
