#!/usr/bin/env python3
"""校验 api-handoff 生成的 Swagger 2.0 ApiPost 导入 JSON。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch"})
PARAMETER_LOCATIONS = frozenset({"query", "header", "path", "formData", "body"})
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
STATUS_CODE_RE = re.compile(r"^[1-5][0-9]{2}$")
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


def validate_string_field(
    data: dict[str, Any], field: str, prefix: str, *, non_empty: bool = True
) -> list[str]:
    """校验对象中的字符串字段。"""
    if field not in data:
        return [f"{prefix} 缺少 {field}"]
    value = data[field]
    if not isinstance(value, str):
        return [f"{prefix}.{field} 必须是字符串"]
    if non_empty and not value.strip():
        return [f"{prefix}.{field} 必须是非空字符串"]
    return []


def validate_ref(value: Any, prefix: str) -> list[str]:
    """校验 Swagger 引用的基本形态，不在本地展开外部定义。"""
    if not isinstance(value, str) or not value.strip():
        return [f"{prefix} 必须是非空字符串引用"]
    return []


def is_sensitive_name(name: str | None) -> bool:
    """判断参数或 schema 属性名是否承载登录身份或凭据。"""
    if not isinstance(name, str):
        return False
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name.strip())
    normalized = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", normalized)
    return bool(
        SENSITIVE_NAME_RE.search(normalized)
        or SENSITIVE_CHINESE_NAME_RE.search(name.strip())
    )


def is_variable_template(value: str) -> bool:
    """仅接受变量本身，或 Authorization 的固定认证方案前缀加变量。"""
    return bool(VARIABLE_TEMPLATE_RE.fullmatch(value.strip()))


def is_document_placeholder(value: str) -> bool:
    """允许文档说明中使用变量或尖括号占位，而不是实际凭据。"""
    normalized = value.strip().strip("\"'")
    return bool(
        is_variable_template(normalized)
        or re.fullmatch(r"(?:bearer|token|uid|basic)\s+<[^>\r\n]+>", normalized, re.IGNORECASE)
        or re.fullmatch(r"<[^>\r\n]+>", normalized)
    )


def contains_sensitive_assignment(value: str) -> bool:
    """阻止描述和扩展字段以赋值形式携带真实敏感信息。"""
    for match in ASSIGNMENT_RE.finditer(value):
        if is_sensitive_name(match.group("name")) and not is_document_placeholder(
            match.group("value")
        ):
            return True
    return False


def contains_real_sensitive_value(value: Any, context_name: str | None) -> bool:
    """识别任何值位置中不可进入导入文件的真实身份和凭据。"""
    if value in (None, ""):
        return False
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or is_variable_template(stripped):
            return False
        if contains_sensitive_assignment(stripped):
            return True
        if (
            RAW_AUTH_VALUE_RE.match(stripped)
            or RAW_UID_VALUE_RE.match(stripped)
            or JWT_RE.search(stripped)
            or AWS_ACCESS_KEY_RE.search(stripped)
            or PHONE_RE.search(stripped)
            or EMAIL_RE.search(stripped)
            or CHINA_ID_CARD_RE.search(stripped)
        ):
            return True
        return is_sensitive_name(context_name)
    return is_sensitive_name(context_name)


def validate_sensitive_values(
    value: Any, prefix: str, *, context_name: str | None = None
) -> list[str]:
    """递归检查示例、枚举、items、正文、响应和扩展中的真实敏感值。"""
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
        if key == "properties" and isinstance(child, dict):
            for property_name, property_schema in child.items():
                errors.extend(
                    validate_sensitive_values(
                        property_schema,
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
            validate_sensitive_values(
                child,
                child_prefix,
                context_name=child_context,
            )
        )
    return errors


def validate_parameter(parameter: Any, prefix: str) -> tuple[list[str], tuple[str, str] | None, str | None]:
    """校验直接声明的 Swagger 参数并返回其位置、名称和 path 参数名。"""
    if not isinstance(parameter, dict):
        return [f"{prefix} 必须是对象"], None, None
    if "$ref" in parameter:
        return validate_ref(parameter["$ref"], f"{prefix}.$ref"), None, None

    errors = validate_string_field(parameter, "name", prefix)
    errors.extend(validate_string_field(parameter, "in", prefix))
    name = parameter.get("name")
    location = parameter.get("in")
    if isinstance(location, str) and location not in PARAMETER_LOCATIONS:
        errors.append(f"{prefix}.in 不支持: {location}")
    if "required" in parameter and not isinstance(parameter["required"], bool):
        errors.append(f"{prefix}.required 必须是布尔值")

    if location == "path" and parameter.get("required") is not True:
        errors.append(f"{prefix} path 参数必须 required: true")
    if location == "body":
        if "schema" not in parameter:
            errors.append(f"{prefix} body 参数缺少 schema")
        elif not isinstance(parameter["schema"], dict):
            errors.append(f"{prefix}.schema 必须是对象")
    elif isinstance(location, str) and location in PARAMETER_LOCATIONS:
        errors.extend(validate_string_field(parameter, "type", prefix))

    key = (
        (location, name)
        if isinstance(location, str) and isinstance(name, str) and name.strip()
        else None
    )
    path_name = name if location == "path" and isinstance(name, str) else None
    return errors, key, path_name


def validate_parameters(parameters: Any, prefix: str) -> tuple[list[str], set[tuple[str, str]], set[str], bool]:
    """校验参数数组并统计直接声明的参数，引用参数保留给导入器解析。"""
    if not isinstance(parameters, list):
        return [f"{prefix} 必须是数组"], set(), set(), False

    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    path_names: set[str] = set()
    has_reference = False
    body_count = 0
    for index, parameter in enumerate(parameters):
        item_prefix = f"{prefix}[{index}]"
        item_errors, key, path_name = validate_parameter(parameter, item_prefix)
        errors.extend(item_errors)
        if isinstance(parameter, dict) and "$ref" in parameter:
            has_reference = True
        if key is not None:
            if key in seen:
                errors.append(f"{item_prefix} 参数重复: {key[0]} {key[1]}")
            seen.add(key)
            if key[0] == "body":
                body_count += 1
        if path_name:
            path_names.add(path_name)
    if body_count > 1:
        errors.append(f"{prefix} 最多只能有一个 body 参数")
    return errors, seen, path_names, has_reference


def validate_response(response: Any, prefix: str) -> list[str]:
    """校验单个 Swagger Response Object 的最小导入契约。"""
    if not isinstance(response, dict):
        return [f"{prefix} 必须是对象"]
    if "$ref" in response:
        return validate_ref(response["$ref"], f"{prefix}.$ref")
    errors = validate_string_field(response, "description", prefix)
    if "schema" in response and not isinstance(response["schema"], dict):
        errors.append(f"{prefix}.schema 必须是对象")
    return errors


def validate_operation(
    operation: Any,
    prefix: str,
    path_parameters: Any,
    placeholders: set[str],
) -> list[str]:
    """校验单个 HTTP Operation 的参数、响应和路径参数对应关系。"""
    if not isinstance(operation, dict):
        return [f"{prefix} 必须是对象"]

    errors: list[str] = []
    path_errors, path_keys, path_names, path_has_reference = validate_parameters(
        path_parameters, f"{prefix.rsplit('.', 1)[0]}.parameters"
    )
    errors.extend(path_errors)
    operation_parameters = operation.get("parameters", [])
    operation_errors, operation_keys, operation_path_names, operation_has_reference = validate_parameters(
        operation_parameters, f"{prefix}.parameters"
    )
    errors.extend(operation_errors)

    direct_path_names = path_names | operation_path_names
    has_parameter_reference = path_has_reference or operation_has_reference
    if not has_parameter_reference:
        for name in sorted(placeholders - direct_path_names):
            errors.append(f"{prefix} 路径占位符 {{{name}}} 缺少 path 参数")
    for name in sorted(direct_path_names - placeholders):
        errors.append(f"{prefix} path 参数 {name} 不在路径中")

    combined_body_count = sum(1 for location, _ in path_keys | operation_keys if location == "body")
    if combined_body_count > 1:
        errors.append(f"{prefix} 合并路径参数后最多只能有一个 body 参数")

    responses = operation.get("responses")
    if not isinstance(responses, dict) or not responses:
        errors.append(f"{prefix}.responses 必须是非空对象")
    else:
        for status, response in responses.items():
            response_prefix = f"{prefix}.responses.{status}"
            if not isinstance(status, str) or (
                status != "default" and not STATUS_CODE_RE.fullmatch(status)
            ):
                errors.append(f"{response_prefix} 响应码必须是 HTTP 状态码或 default")
            errors.extend(validate_response(response, response_prefix))
    return errors


def validate_payload(payload: Any) -> tuple[list[str], int]:
    """校验 Swagger 2.0 导入文件，返回错误列表和 HTTP 接口数。"""
    if not isinstance(payload, dict):
        return ["根节点必须是对象"], 0

    errors: list[str] = []
    if payload.get("swagger") != "2.0":
        errors.append('根字段 swagger 必须是 "2.0"')

    info = payload.get("info")
    if not isinstance(info, dict):
        errors.append("根字段 info 必须是对象")
    else:
        errors.extend(validate_string_field(info, "title", "info"))
        errors.extend(validate_string_field(info, "version", "info"))
        if "description" in info and not isinstance(info["description"], str):
            errors.append("info.description 必须是字符串")

    for field in ("host", "schemes", "basePath"):
        if field in payload:
            errors.append(
                f"根字段 {field} 不允许出现；请求基址只能由本机私有环境的 {{{{base_url}}}} 提供"
            )

    paths = payload.get("paths")
    if not isinstance(paths, dict) or not paths:
        errors.append("根字段 paths 必须是非空对象")
        errors.extend(validate_sensitive_values(payload, "根节点"))
        return errors, 0

    api_count = 0
    for raw_path, path_item in paths.items():
        path_prefix = f"paths.{raw_path}"
        if not isinstance(raw_path, str) or not raw_path.startswith("/") or "?" in raw_path or "#" in raw_path:
            errors.append(f"{path_prefix} 路径必须以 / 开头且不含 query/hash")
            continue
        if not isinstance(path_item, dict):
            errors.append(f"{path_prefix} 必须是对象")
            continue

        placeholders = set(re.findall(r"\{([^{}]+)\}", raw_path))
        path_parameters = path_item.get("parameters", [])
        has_operation = False
        for member, operation in path_item.items():
            if member in HTTP_METHODS:
                has_operation = True
                api_count += 1
                errors.extend(
                    validate_operation(operation, f"{path_prefix}.{member}", path_parameters, placeholders)
                )
            elif member in {"parameters", "$ref"} or member.startswith("x-"):
                if member == "$ref":
                    errors.extend(validate_ref(operation, f"{path_prefix}.$ref"))
            else:
                errors.append(f"{path_prefix} 不支持的 Path Item 字段: {member}")
        if not has_operation:
            errors.append(f"{path_prefix} 至少需要一个小写 HTTP method")

    errors.extend(validate_sensitive_values(payload, "根节点"))
    return errors, api_count


def main() -> int:
    """读取导入文件并以非零退出码阻止不安全或不完整的交付。"""
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
