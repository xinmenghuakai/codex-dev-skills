#!/usr/bin/env python3
"""validate_apipost_swagger2.py 的定向回归测试。"""

from __future__ import annotations

import copy
import unittest

from validate_apipost_swagger2 import validate_payload


def valid_payload() -> dict:
    """构造含路径参数、鉴权变量和响应的最小 Swagger 2.0 集合。"""
    return {
        "swagger": "2.0",
        "info": {"title": "测试接口", "version": "v1.0.0"},
        "paths": {
            "/users/{uid}": {
                "parameters": [
                    {"name": "uid", "in": "path", "required": True, "type": "string"}
                ],
                "get": {
                    "parameters": [
                        {
                            "name": "Authorization",
                            "in": "header",
                            "required": True,
                            "type": "string",
                            "default": "uid {{uid}}",
                        },
                        {
                            "name": "X-Debug-Key",
                            "in": "header",
                            "required": True,
                            "type": "string",
                            "default": "{{debug_key}}",
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "schema": {
                                "type": "object",
                                "properties": {"id": {"type": "integer"}},
                            },
                        }
                    },
                },
            }
        },
    }


class ValidateApiPostSwagger2Test(unittest.TestCase):
    def assert_valid(self, payload: object, count: int = 1) -> None:
        errors, actual_count = validate_payload(payload)
        self.assertEqual([], errors)
        self.assertEqual(count, actual_count)

    def assert_invalid(self, payload: object, expected: str) -> None:
        errors, _ = validate_payload(payload)
        self.assertTrue(any(expected in error for error in errors), errors)

    def assert_sensitive_rejected(self, payload: object, marker: str) -> None:
        """验证敏感值拦截不把待测值回显到错误信息。"""
        errors, _ = validate_payload(payload)
        self.assertTrue(any("禁止写入真实敏感值" in error for error in errors), errors)
        self.assertFalse(any(marker in error for error in errors), errors)

    def test_valid_minimal_contract_and_variable_defaults(self) -> None:
        self.assert_valid(valid_payload())

        payload = valid_payload()
        payload["paths"]["/users/{uid}"]["get"]["parameters"][0]["default"] = "Bearer {{access_token}}"
        self.assert_valid(payload)

        payload = valid_payload()
        payload["paths"]["/users/{uid}"]["get"]["responses"]["200"]["schema"]["properties"]["password"] = {
            "type": "string",
            "default": "{{password}}",
        }
        self.assert_valid(payload)

    def test_root_info_and_path_contract(self) -> None:
        self.assert_invalid([], "根节点必须是对象")

        for field, value, expected in (
            ("swagger", "3.0", 'swagger 必须是 "2.0"'),
            ("info", [], "info 必须是对象"),
            ("paths", {}, "paths 必须是非空对象"),
        ):
            with self.subTest(field=field):
                payload = valid_payload()
                payload[field] = value
                self.assert_invalid(payload, expected)

        payload = valid_payload()
        payload["info"].pop("title")
        self.assert_invalid(payload, "info 缺少 title")

        payload = valid_payload()
        payload["paths"] = {"users": payload["paths"]["/users/{uid}"]}
        self.assert_invalid(payload, "路径必须以 / 开头")

    def test_default_import_contract_rejects_all_literal_base_fields(self) -> None:
        for field, value in (
            ("host", "api.example.com"),
            ("schemes", ["http"]),
            ("basePath", "/"),
        ):
            with self.subTest(field=field):
                payload = valid_payload()
                payload[field] = value
                self.assert_invalid(payload, f"根字段 {field} 不允许出现")

    def test_http_method_parameter_and_response_contract(self) -> None:
        payload = valid_payload()
        operation = payload["paths"]["/users/{uid}"].pop("get")
        payload["paths"]["/users/{uid}"]["GET"] = operation
        self.assert_invalid(payload, "不支持的 Path Item 字段: GET")

        payload = valid_payload()
        parameter = payload["paths"]["/users/{uid}"]["parameters"][0]
        parameter["required"] = False
        self.assert_invalid(payload, "path 参数必须 required: true")

        payload = valid_payload()
        parameter = payload["paths"]["/users/{uid}"]["get"]["parameters"][0]
        parameter.pop("type")
        self.assert_invalid(payload, "缺少 type")

        payload = valid_payload()
        payload["paths"]["/users/{uid}"]["get"].pop("responses")
        self.assert_invalid(payload, "responses 必须是非空对象")

        payload = valid_payload()
        response = payload["paths"]["/users/{uid}"]["get"]["responses"].pop("200")
        payload["paths"]["/users/{uid}"]["get"]["responses"]["20"] = response
        self.assert_invalid(payload, "响应码必须是 HTTP 状态码或 default")

        payload = valid_payload()
        payload["paths"]["/users/{uid}"]["get"]["responses"]["200"].pop("description")
        self.assert_invalid(payload, "缺少 description")

    def test_body_parameter_requires_schema(self) -> None:
        payload = valid_payload()
        payload["paths"]["/users/{uid}"]["get"]["parameters"].append(
            {"name": "request", "in": "body", "required": True}
        )
        self.assert_invalid(payload, "body 参数缺少 schema")

    def test_real_sensitive_defaults_are_rejected_without_echoing_values(self) -> None:
        cases = (
            ("Authorization", "Bearer non-variable-token"),
            ("X-Debug-Key", "debug-value"),
            ("X-Internal-Key", "internal-key-value"),
            ("debugKey", "debug-value"),
            ("uid", 10001),
        )
        for name, value in cases:
            with self.subTest(name=name):
                payload = valid_payload()
                parameter = payload["paths"]["/users/{uid}"]["get"]["parameters"][0]
                parameter["name"] = name
                parameter["default"] = value
                self.assert_invalid(payload, "default 禁止写入真实敏感值")

        payload = valid_payload()
        payload["paths"]["/users/{uid}"]["get"]["responses"]["200"]["schema"]["properties"]["password"] = {
            "type": "string",
            "default": "plain-text-password",
        }
        self.assert_invalid(payload, "default 禁止写入真实敏感值")

    def test_real_sensitive_examples_are_rejected_without_echoing_values(self) -> None:
        payload = valid_payload()
        payload["paths"]["/users/{uid}"]["get"]["responses"]["200"]["examples"] = {
            "application/json": {"uid": 10001}
        }
        self.assert_invalid(payload, "禁止写入真实敏感值")

        payload = valid_payload()
        parameter = payload["paths"]["/users/{uid}"]["get"]["parameters"][1]
        parameter["example"] = "debug-value"
        self.assert_invalid(payload, "example 禁止写入真实敏感值")

        payload = valid_payload()
        payload["paths"]["/users/{uid}"]["get"]["responses"]["200"]["examples"] = {
            "application/json": {"uid": "{{uid}}"}
        }
        self.assert_valid(payload)

    def test_sensitive_values_are_rejected_in_enum_items_extensions_and_descriptions(self) -> None:
        marker = "not-a-variable"
        cases: list[dict] = []

        payload = valid_payload()
        parameter = payload["paths"]["/users/{uid}"]["get"]["parameters"][1]
        parameter["enum"] = [marker]
        cases.append(payload)

        payload = valid_payload()
        payload["paths"]["/users/{uid}"]["get"]["parameters"].append(
            {
                "name": "request",
                "in": "body",
                "required": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "token": {
                            "type": "array",
                            "items": {"enum": [marker]},
                        }
                    },
                },
            }
        )
        cases.append(payload)

        payload = valid_payload()
        payload["paths"]["/users/{uid}"]["get"]["responses"]["200"]["schema"][
            "properties"
        ]["token"] = {"type": "string", "enum": [marker]}
        cases.append(payload)

        payload = valid_payload()
        payload["paths"]["/users/{uid}"]["get"]["x-fixture"] = {
            "debug_key": marker
        }
        cases.append(payload)

        payload = valid_payload()
        payload["info"]["description"] = f"debug_key={marker}"
        cases.append(payload)

        for payload in cases:
            with self.subTest(payload=payload):
                self.assert_sensitive_rejected(payload, marker)

    def test_sensitive_variables_and_document_placeholders_remain_valid(self) -> None:
        payload = valid_payload()
        parameter = payload["paths"]["/users/{uid}"]["get"]["parameters"][1]
        parameter["enum"] = ["{{debug_key}}"]
        payload["paths"]["/users/{uid}"]["get"]["parameters"].append(
            {
                "name": "request",
                "in": "body",
                "required": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "uid": {
                            "type": "array",
                            "items": {"enum": ["{{uid}}"]},
                        }
                    },
                },
            }
        )
        payload["info"]["description"] = (
            "debug_key={{debug_key}}；Authorization: token <加密令牌>"
        )
        self.assert_valid(payload)

    def test_chinese_sensitive_fields_are_rejected_or_template_only(self) -> None:
        phone_marker = "13800138000"
        payload = valid_payload()
        properties = payload["paths"]["/users/{uid}"]["get"]["responses"]["200"]["schema"]["properties"]
        properties["手机号"] = {"type": "string", "default": phone_marker}
        properties["订单号"] = {"type": "string", "enum": ["not-a-variable"]}
        self.assert_sensitive_rejected(payload, phone_marker)

        payload = valid_payload()
        payload["info"]["description"] = f"手机号={phone_marker}"
        self.assert_sensitive_rejected(payload, phone_marker)

        payload = valid_payload()
        properties = payload["paths"]["/users/{uid}"]["get"]["responses"]["200"]["schema"]["properties"]
        properties["手机号"] = {"type": "string", "default": "{{phone}}"}
        properties["订单号"] = {"type": "string", "enum": ["{{order_no}}"]}
        self.assert_valid(payload)

    def test_phone_value_is_rejected_even_with_a_non_sensitive_field_name(self) -> None:
        phone_marker = "13800138000"
        payload = valid_payload()
        properties = payload["paths"]["/users/{uid}"]["get"]["responses"]["200"]["schema"]["properties"]
        properties["contact"] = {"type": "string", "default": phone_marker}
        self.assert_sensitive_rejected(payload, phone_marker)

    def test_email_value_is_rejected_even_with_a_non_sensitive_field_name(self) -> None:
        email_marker = "sample@example.invalid"
        payload = valid_payload()
        properties = payload["paths"]["/users/{uid}"]["get"]["responses"]["200"]["schema"]["properties"]
        properties["contact"] = {"type": "string", "default": email_marker}
        self.assert_sensitive_rejected(payload, email_marker)

    def test_identity_alias_and_value_are_rejected(self) -> None:
        payload = valid_payload()
        properties = payload["paths"]["/users/{uid}"]["get"]["responses"]["200"]["schema"]["properties"]
        properties["idNo"] = {"type": "string", "default": "not-a-variable"}
        self.assert_sensitive_rejected(payload, "not-a-variable")

        id_marker = "00000020000101000X"
        payload = valid_payload()
        properties = payload["paths"]["/users/{uid}"]["get"]["responses"]["200"]["schema"]["properties"]
        properties["identity"] = {"type": "string", "default": id_marker}
        self.assert_sensitive_rejected(payload, id_marker)

    def test_unrelated_defaults_remain_usable(self) -> None:
        payload = valid_payload()
        payload["paths"]["/users/{uid}"]["get"]["responses"]["200"]["schema"]["properties"]["page_size"] = {
            "type": "integer",
            "default": 20,
        }
        self.assert_valid(payload)

        payload = valid_payload()
        payload["paths"]["/users/{uid}"]["get"]["parameters"].append(
            {
                "name": "page_size",
                "in": "query",
                "required": False,
                "type": "integer",
                "default": 20,
            }
        )
        self.assert_valid(payload)

    def test_duplicate_parameters_are_rejected(self) -> None:
        payload = valid_payload()
        parameters = payload["paths"]["/users/{uid}"]["get"]["parameters"]
        parameters.append(copy.deepcopy(parameters[0]))
        self.assert_invalid(payload, "参数重复: header Authorization")


if __name__ == "__main__":
    unittest.main()
