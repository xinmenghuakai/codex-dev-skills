#!/usr/bin/env python3
"""校验 api-handoff 生成的 YApi 导入 JSON。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
QUERY_PARAM_FIELDS = ("name", "desc", "required", "example")
FORM_PARAM_FIELDS = ("name", "type", "desc", "required", "example")
PENDING_MARKERS = ("待补", "待确认", "TODO", "TBD", "FIXME")
SENSITIVE_NAME_RE = re.compile(
    r"(?:^|[-_])(?:authorization|auth|token|secret|password|passwd|"
    r"api[-_]?key|debug[-_]?key|private[-_]?key|access[-_]?key|"
    r"internal[-_]?key|app[-_]?key|client[-_]?key|signature|sign|"
    r"cookie|session|credential|uid|user[-_]?id|phone|mobile|email|"
    r"id[-_]?card|(?:id|identity|cert(?:ificate)?|card)[-_]?(?:no|number)|"
    r"(?:identity|cert(?:ificate)?)[-_]?card|open[-_]?id|union[-_]?id|order[-_]?id|order[-_]?no|"
    r"trade[-_]?no|transaction[-_]?id)(?:$|[-_])",
    re.IGNORECASE,
)
SENSITIVE_CHINESE_NAME_RE = re.compile(
    r"(?:手机号|手机号码|手机|电话|令牌|访问令牌|密码|口令|密钥|调试密钥|"
    r"私钥|授权码|身份证(?:号)?|证件号|订单(?:号|编号)|交易(?:号|编号)|"
    r"流水号|用户(?:ID|id|编号|标识))"
)
VARIABLE_TEMPLATE_RE = re.compile(
    r"(?:(?:bearer|token|uid|basic)\s+)?\{\{[A-Za-z_][A-Za-z0-9_.-]*\}\}",
    re.IGNORECASE,
)
RAW_AUTH_VALUE_RE = re.compile(r"^(?:bearer|token|basic)\s+\S+$", re.IGNORECASE)
RAW_UID_VALUE_RE = re.compile(r"^uid\s+\d+$", re.IGNORECASE)
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
AWS_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
CHINA_ID_CARD_RE = re.compile(
    r"(?<![0-9A-Za-z])\d{6}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])"
    r"(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?![0-9A-Za-z])"
)
ASSIGNMENT_RE = re.compile(
    r'''(?ix)
    (?<![A-Za-z0-9_-])
    ["']?(?P<name>[A-Za-z][A-Za-z0-9_-]*|手机号|手机号码|手机|电话|令牌|访问令牌|密码|口令|密钥|调试密钥|私钥|授权码|身份证(?:号)?|证件号|订单(?:号|编号)|交易(?:号|编号)|流水号|用户(?:ID|id|编号|标识))["']?
    \s*(?:=|:|：)\s*
    (?P<value>
        (?:bearer|token|uid|basic)\s+(?:\{\{[A-Za-z_][A-Za-z0-9_.-]*\}\}|<[^>\r\n]+>)
        |\{\{[A-Za-z_][A-Za-z0-9_.-]*\}\}
        |"[^"\r\n]*"
        |'[^'\r\n]*'
        |[^\s,;，；}\]\r\n]+)
    ''',
)
VALUE_BEARING_KEYS = frozenset(
    {
        "value",
        "default",
        "example",
        "examples",
        "enum",
        "items",
        "schema",
        "properties",
        "additionalProperties",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "body",
        "response",
        "responses",
        "data",
    }
)
SERIALIZED_JSON_KEYS = frozenset({"req_body_other", "res_body"})


def validate_string_field(
    data: dict[str, Any], field: str, prefix: str, *, non_empty: bool = True
) -> list[str]:
    """校验必需字符串字段，并区分缺失、类型错误和空值。"""
    if field not in data:
        return [f"{prefix} 缺少 {field}"]
    value = data[field]
    if not isinstance(value, str):
        return [f"{prefix}.{field} 必须是字符串"]
    if non_empty and not value.strip():
        return [f"{prefix}.{field} 必须是非空字符串"]
    return []


def is_sensitive_name(name: str | None) -> bool:
    """判断字段名是否承载凭据、身份或不应进入文档的真实业务标识。"""
    if not isinstance(name, str):
        return False
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name.strip())
    normalized = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", normalized)
    return bool(
        SENSITIVE_NAME_RE.search(normalized)
        or SENSITIVE_CHINESE_NAME_RE.search(name.strip())
    )


def is_variable_template(value: str) -> bool:
    """只允许单独变量或固定认证 scheme 加变量作为敏感字段示例。"""
    return bool(VARIABLE_TEMPLATE_RE.fullmatch(value.strip()))


def is_document_placeholder(value: str) -> bool:
    """允许文档中使用变量或尖括号占位说明，而非真实凭据。"""
    normalized = value.strip().strip("\"'")
    return bool(
        is_variable_template(normalized)
        or re.fullmatch(r"(?:bearer|token|uid|basic)\s+<[^>\r\n]+>", normalized, re.IGNORECASE)
        or re.fullmatch(r"<[^>\r\n]+>", normalized)
    )


def contains_sensitive_assignment(value: str) -> bool:
    """阻止说明或扩展字段写入“敏感字段名=真实值”，且不回显该值。"""
    for match in ASSIGNMENT_RE.finditer(value):
        if is_sensitive_name(match.group("name")) and not is_document_placeholder(
            match.group("value")
        ):
            return True
    return False


def contains_real_sensitive_value(value: Any, context_name: str | None) -> bool:
    """判断标量是否为不应进入导入文件的真实凭据或测试数据。"""
    if value in (None, ""):
        return False
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized or is_variable_template(normalized):
            return False
        if contains_sensitive_assignment(normalized):
            return True
        if (
            RAW_AUTH_VALUE_RE.match(normalized)
            or RAW_UID_VALUE_RE.match(normalized)
            or JWT_RE.search(normalized)
            or AWS_ACCESS_KEY_RE.search(normalized)
            or PHONE_RE.search(normalized)
            or EMAIL_RE.search(normalized)
            or CHINA_ID_CARD_RE.search(normalized)
        ):
            return True
        return is_sensitive_name(context_name)
    return is_sensitive_name(context_name)


def validate_sensitive_values(
    value: Any, prefix: str, *, context_name: str | None = None
) -> list[str]:
    """递归检查正文、响应、enum、items、扩展和说明中的真实敏感值。"""
    if isinstance(value, list):
        errors: list[str] = []
        for index, item in enumerate(value):
            errors.extend(
                validate_sensitive_values(
                    item,
                    f"{prefix}[{index}]",
                    context_name=context_name,
                )
            )
        return errors

    if not isinstance(value, dict):
        if contains_real_sensitive_value(value, context_name):
            return [f"{prefix} 禁止写入真实敏感值；请改用 {{{{变量名}}}}"]
        return []

    errors: list[str] = []
    own_name = value.get("name")
    effective_context = own_name if is_sensitive_name(own_name) else context_name
    for key, child in value.items():
        child_prefix = f"{prefix}.{key}"
        if key in SERIALIZED_JSON_KEYS:
            # JSON/JSONC 请求体与响应在解析后单独递归，避免把对象起始符误判为赋值值。
            continue
        if key == "properties" and isinstance(child, dict):
            for property_name, property_value in child.items():
                errors.extend(
                    validate_sensitive_values(
                        property_value,
                        f"{child_prefix}.{property_name}",
                        context_name=str(property_name),
                    )
                )
            continue
        if is_sensitive_name(key):
            child_context = key
        elif key in VALUE_BEARING_KEYS or key.startswith(("x-", "x_")):
            child_context = effective_context
        else:
            child_context = key
        errors.extend(
            validate_sensitive_values(child, child_prefix, context_name=child_context)
        )
    return errors


def strip_json_comments(text: str) -> str:
    """移除 JSONC 行/块注释，同时保留字符串中的 URL 和转义字符。"""
    result: list[str] = []
    index = 0
    in_string = False
    escaped = False

    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue

        if char == "/" and next_char == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue

        if char == "/" and next_char == "*":
            index += 2
            closed = False
            while index + 1 < len(text):
                if text[index] == "*" and text[index + 1] == "/":
                    index += 2
                    closed = True
                    break
                if text[index] in "\r\n":
                    result.append(text[index])
                index += 1
            if not closed:
                raise ValueError("块注释未闭合")
            continue

        result.append(char)
        index += 1

    return "".join(result)


def parse_jsonc_string(value: Any, prefix: str) -> tuple[list[str], Any]:
    """校验 YApi JSON/JSONC 字符串并返回解析结果。"""
    if not isinstance(value, str):
        return [f"{prefix} 必须是 JSON 字符串"], None
    if not value.strip():
        return [f"{prefix} 必须是非空 JSON 字符串"], None
    try:
        return [], json.loads(strip_json_comments(value))
    except (json.JSONDecodeError, ValueError) as exc:
        return [f"{prefix} 不是合法 JSON/JSONC: {exc}"], None


def validate_headers(
    headers: Any, prefix: str, *, required_content_type: str | None = None
) -> list[str]:
    """校验请求头结构及指定的 Content-Type。"""
    errors: list[str] = []
    if not isinstance(headers, list):
        return [f"{prefix} 必须是数组"]

    seen_names: set[str] = set()
    content_type_found = False
    for header_index, header in enumerate(headers):
        header_prefix = f"{prefix}[{header_index}]"
        if not isinstance(header, dict):
            errors.append(f"{header_prefix} 必须是对象")
            continue
        errors.extend(validate_string_field(header, "name", header_prefix))
        errors.extend(validate_string_field(header, "value", header_prefix, non_empty=False))
        if "desc" in header and not isinstance(header["desc"], str):
            errors.append(f"{header_prefix}.desc 必须是字符串")
        if "required" in header and header["required"] not in ("0", "1"):
            errors.append(f'{header_prefix}.required 必须是字符串 "0" 或 "1"')

        name = header.get("name")
        if isinstance(name, str) and name.strip():
            normalized_name = name.strip().lower()
            if name != name.strip():
                errors.append(f"{header_prefix}.name 首尾不能有空白")
            if normalized_name in seen_names:
                errors.append(f"{header_prefix} 请求头重复: {name}")
            seen_names.add(normalized_name)
            if normalized_name == "content-type":
                value = header.get("value")
                if required_content_type and isinstance(value, str):
                    media_type = value.split(";", 1)[0].strip().lower()
                    if media_type == required_content_type:
                        content_type_found = True

    if required_content_type and not content_type_found:
        errors.append(f"{prefix} 缺少 Content-Type: {required_content_type}")
    return errors


def validate_parameters(
    parameters: Any,
    prefix: str,
    *,
    require_type: bool,
    allow_empty: bool,
) -> list[str]:
    """校验 query/form 参数字段、类型、必填枚举和重名。"""
    errors: list[str] = []
    if not isinstance(parameters, list):
        return [f"{prefix} 必须是数组"]
    if not allow_empty and not parameters:
        return [f"{prefix} 必须是非空数组"]

    required_fields = FORM_PARAM_FIELDS if require_type else QUERY_PARAM_FIELDS
    seen_names: set[str] = set()
    for parameter_index, parameter in enumerate(parameters):
        parameter_prefix = f"{prefix}[{parameter_index}]"
        if not isinstance(parameter, dict):
            errors.append(f"{parameter_prefix} 必须是对象")
            continue

        for field in required_fields:
            if field == "required":
                if field not in parameter:
                    errors.append(f"{parameter_prefix} 缺少 required")
                elif parameter[field] not in ("0", "1"):
                    errors.append(f'{parameter_prefix}.required 必须是字符串 "0" 或 "1"')
            else:
                errors.extend(
                    validate_string_field(
                        parameter,
                        field,
                        parameter_prefix,
                        non_empty=field != "example",
                    )
                )

        name = parameter.get("name")
        if isinstance(name, str) and name.strip():
            normalized_name = name.strip()
            if name != normalized_name:
                errors.append(f"{parameter_prefix}.name 首尾不能有空白")
            if normalized_name in seen_names:
                errors.append(f"{parameter_prefix} 参数重复: {name}")
            seen_names.add(normalized_name)

    return errors


def validate_request(api: dict[str, Any], method: str, item: str) -> list[str]:
    """按 GET、JSON、form、无 body 四种真实请求形态校验。"""
    errors: list[str] = []
    body_type = api.get("req_body_type")

    if method == "GET":
        errors.extend(validate_parameters(api.get("req_query"), f"{item}.req_query", require_type=False, allow_empty=True))
        if body_type not in (None, "") or api.get("req_body_other") not in (None, "") or api.get("req_body_form") not in (None, []):
            errors.append(f"{item} GET 接口不应包含请求体")
        if api.get("req_body_is_json_schema") not in (None, False):
            errors.append(f"{item}.req_body_is_json_schema 只能省略或为 false")
        if "req_headers" in api:
            errors.extend(validate_headers(api["req_headers"], f"{item}.req_headers"))
        return errors

    if body_type == "json":
        errors.extend(
            validate_headers(
                api.get("req_headers"),
                f"{item}.req_headers",
                required_content_type="application/json",
            )
        )
        if api.get("req_body_is_json_schema") is not False:
            errors.append(f"{item}.req_body_is_json_schema 必须是 false")
        body_errors, body = parse_jsonc_string(api.get("req_body_other"), f"{item}.req_body_other")
        errors.extend(body_errors)
        if not body_errors and not isinstance(body, (dict, list)):
            errors.append(f"{item}.req_body_other 顶层必须是对象或数组")
        if not body_errors:
            errors.extend(
                validate_sensitive_values(body, f"{item}.req_body_other")
            )
        if api.get("req_body_form") not in (None, []):
            errors.append(f"{item} JSON 请求不应包含 req_body_form")
    elif body_type == "form":
        errors.extend(
            validate_headers(
                api.get("req_headers"),
                f"{item}.req_headers",
                required_content_type="application/x-www-form-urlencoded",
            )
        )
        if api.get("req_body_is_json_schema") is not False:
            errors.append(f"{item}.req_body_is_json_schema 必须是 false")
        errors.extend(
            validate_parameters(
                api.get("req_body_form"),
                f"{item}.req_body_form",
                require_type=True,
                allow_empty=True,
            )
        )
        if api.get("req_body_other") not in (None, ""):
            errors.append(f"{item} form 请求不应包含 req_body_other")
    elif body_type in (None, ""):
        errors.extend(validate_parameters(api.get("req_query"), f"{item}.req_query", require_type=False, allow_empty=True))
        if api.get("req_body_other") not in (None, "") or api.get("req_body_form") not in (None, []):
            errors.append(f"{item} 无 body 请求不应包含请求体字段")
        if api.get("req_body_is_json_schema") not in (None, False):
            errors.append(f"{item}.req_body_is_json_schema 只能省略或为 false")
        if "req_headers" in api:
            errors.extend(validate_headers(api["req_headers"], f"{item}.req_headers"))
    else:
        errors.append(f"{item}.req_body_type 不支持: {body_type!r}")

    if "req_query" in api and body_type in ("json", "form"):
        errors.extend(validate_parameters(api["req_query"], f"{item}.req_query", require_type=False, allow_empty=True))
    return errors


def validate_response(api: dict[str, Any], item: str) -> list[str]:
    """校验 JSON/JSONC 或 raw 响应，响应业务结构由真实代码决定。"""
    errors: list[str] = []
    body_type = api.get("res_body_type")
    if body_type not in ("json", "raw"):
        errors.append(f'{item}.res_body_type 必须是 "json" 或 "raw"')
    if api.get("res_body_is_json_schema") is not False:
        errors.append(f"{item}.res_body_is_json_schema 必须是 false")

    if body_type == "raw":
        errors.extend(
            validate_string_field(api, "res_body", item, non_empty=True)
        )
        errors.extend(
            validate_sensitive_values(api.get("res_body"), f"{item}.res_body")
        )
        return errors
    if body_type != "json":
        return errors

    body_errors, response = parse_jsonc_string(api.get("res_body"), f"{item}.res_body")
    errors.extend(body_errors)
    if body_errors:
        return errors
    if not isinstance(response, (dict, list)):
        errors.append(f"{item}.res_body 顶层必须是对象或数组")
    errors.extend(validate_sensitive_values(response, f"{item}.res_body"))
    return errors


def validate_pending_markers(value: Any, prefix: str) -> list[str]:
    """阻止待补、待确认和常见英文占位标记进入最终交付。"""
    serialized = json.dumps(value, ensure_ascii=False).upper()
    errors: list[str] = []
    for marker in PENDING_MARKERS:
        normalized = marker.upper()
        if marker.isascii():
            found = re.search(
                rf"(?<![A-Z0-9_]){re.escape(normalized)}(?![A-Z0-9_])",
                serialized,
            )
        else:
            found = normalized in serialized
        if found:
            errors.append(f"{prefix} 仍包含占位标记 {marker}")
    return errors


def validate_payload(payload: Any) -> tuple[list[str], int]:
    """校验完整 YApi 导入结构，返回错误列表和接口数量。"""
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    api_count = 0

    if not isinstance(payload, list) or not payload:
        return ["根节点必须是非空数组"], 0

    for category_index, category in enumerate(payload):
        prefix = f"分类[{category_index}]"
        if not isinstance(category, dict):
            errors.append(f"{prefix} 必须是对象")
            continue
        errors.extend(validate_string_field(category, "name", prefix))
        errors.extend(validate_string_field(category, "desc", prefix))
        errors.extend(
            validate_pending_markers(
                {"name": category.get("name"), "desc": category.get("desc")},
                prefix,
            )
        )
        errors.extend(
            validate_sensitive_values(
                {"name": category.get("name"), "desc": category.get("desc")},
                prefix,
            )
        )

        apis = category.get("list")
        if not isinstance(apis, list):
            errors.append(f"{prefix}.list 必须是数组")
            continue
        if not apis:
            errors.append(f"{prefix}.list 必须是非空数组")
            continue

        for api_index, api in enumerate(apis):
            api_count += 1
            item = f"{prefix}.list[{api_index}]"
            if not isinstance(api, dict):
                errors.append(f"{item} 必须是对象")
                continue

            errors.extend(validate_string_field(api, "title", item))
            errors.extend(validate_string_field(api, "path", item))
            errors.extend(validate_string_field(api, "method", item))
            errors.extend(validate_string_field(api, "status", item))
            errors.extend(validate_string_field(api, "markdown", item, non_empty=False))
            errors.extend(validate_string_field(api, "desc", item))

            method = api.get("method")
            path = api.get("path")
            if isinstance(method, str):
                if method not in HTTP_METHODS:
                    errors.append(f"{item}.method 必须是支持的大写 HTTP method")
            if isinstance(path, str) and path and not path.startswith("/"):
                errors.append(f"{item}.path 必须以 / 开头")
            if api.get("status") != "undone":
                errors.append(f'{item}.status 必须是 "undone"')

            if isinstance(method, str) and method and isinstance(path, str) and path:
                key = (method, path)
                if key in seen:
                    errors.append(f"{item} 接口重复: {method} {path}")
                seen.add(key)

            errors.extend(validate_request(api, method if isinstance(method, str) else "", item))
            errors.extend(validate_response(api, item))
            errors.extend(validate_pending_markers(api, item))
            errors.extend(validate_sensitive_values(api, item))

    return errors, api_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    args = parser.parse_args()

    try:
        payload = json.loads(args.file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL 无法读取合法 JSON: {exc}")
        return 1

    errors, api_count = validate_payload(payload)
    if errors:
        print(f"FAIL {args.file}")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"PASS {args.file}: {api_count} 个接口")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
