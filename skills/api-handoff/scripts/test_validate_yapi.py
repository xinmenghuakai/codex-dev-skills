#!/usr/bin/env python3
"""validate_yapi.py 的完整协议与结构回归测试。"""

from __future__ import annotations

import copy
import unittest

from validate_yapi import strip_json_comments, validate_payload


def valid_get_payload() -> list[dict]:
    """构造符合 api-handoff 约定的最小 GET 文档。"""
    return [
        {
            "name": "优惠券",
            "desc": "统一响应为 {code,msg,data}",
            "list": [
                {
                    "title": "优惠券详情",
                    "path": "/coupon/detail",
                    "method": "GET",
                    "status": "undone",
                    "markdown": "按 ID 查询优惠券详情",
                    "desc": "优惠券详情",
                    "req_query": [
                        {
                            "name": "coupon_id",
                            "desc": "优惠券 ID",
                            "required": "1",
                            "example": "123",
                        }
                    ],
                    "req_body_is_json_schema": False,
                    "res_body_type": "json",
                    "res_body_is_json_schema": False,
                    "res_body": (
                        "{\n"
                        '  "code": 0, // 成功\n'
                        '  "msg": "ok",\n'
                        '  "data": {"url": "https://example.com/a//b"}\n'
                        "}"
                    ),
                }
            ],
        }
    ]


def valid_json_payload() -> list[dict]:
    """构造 JSON POST 文档。"""
    payload = valid_get_payload()
    api = payload[0]["list"][0]
    api.update(
        {
            "method": "POST",
            "req_headers": [{"name": "Content-Type", "value": "application/json"}],
            "req_body_type": "json",
            "req_body_is_json_schema": False,
            "req_body_other": '{"coupon_id": 123, /* 来源：请求 */ "enabled": true}',
        }
    )
    api.pop("req_query")
    return payload


def valid_form_payload(*, empty: bool = False) -> list[dict]:
    """构造 form POST 文档，允许真实存在的空 form。"""
    payload = valid_get_payload()
    api = payload[0]["list"][0]
    api.update(
        {
            "method": "POST",
            "req_headers": [
                {
                    "name": "Content-Type",
                    "value": "application/x-www-form-urlencoded",
                }
            ],
            "req_body_type": "form",
            "req_body_is_json_schema": False,
            "req_body_form": []
            if empty
            else [
                {
                    "name": "coupon_id",
                    "type": "text",
                    "desc": "优惠券 ID",
                    "required": "1",
                    "example": "123",
                }
            ],
        }
    )
    api.pop("req_query")
    return payload


def valid_no_body_payload() -> list[dict]:
    """构造 POST 无 body 文档。"""
    payload = valid_get_payload()
    api = payload[0]["list"][0]
    api["method"] = "POST"
    api["req_query"] = []
    api["req_headers"] = [
        {
            "name": "X-Internal-Key",
            "value": "",
            "desc": "内部任务密钥",
            "required": "1",
        }
    ]
    return payload


def valid_raw_response_payload() -> list[dict]:
    """构造外部协议约定纯文本响应的文档。"""
    payload = valid_no_body_payload()
    api = payload[0]["list"][0]
    api["res_body_type"] = "raw"
    api["res_body"] = "success"
    return payload


class ValidateYapiTest(unittest.TestCase):
    def assert_valid(self, payload: list[dict], count: int = 1) -> None:
        errors, actual_count = validate_payload(payload)
        self.assertEqual([], errors)
        self.assertEqual(count, actual_count)

    def assert_invalid(self, payload: object, expected: str) -> None:
        errors, _ = validate_payload(payload)
        self.assertTrue(any(expected in error for error in errors), errors)

    def assert_sensitive_rejected(self, payload: object, marker: str) -> None:
        """验证脱敏拦截不把待测的真实值回显到错误信息。"""
        errors, _ = validate_payload(payload)
        self.assertTrue(any("禁止写入真实敏感值" in error for error in errors), errors)
        self.assertFalse(any(marker in error for error in errors), errors)

    def test_all_supported_request_shapes(self) -> None:
        for name, payload in (
            ("get", valid_get_payload()),
            ("json", valid_json_payload()),
            ("form", valid_form_payload()),
            ("empty_form", valid_form_payload(empty=True)),
            ("no_body", valid_no_body_payload()),
            ("raw_response", valid_raw_response_payload()),
        ):
            with self.subTest(name=name):
                self.assert_valid(payload)

    def test_root_category_and_core_field_types(self) -> None:
        self.assert_invalid({}, "根节点必须是非空数组")
        self.assert_invalid([], "根节点必须是非空数组")

        payload = valid_get_payload()
        payload[0]["name"] = 123
        self.assert_invalid(payload, ".name 必须是字符串")

        payload = valid_get_payload()
        payload[0].pop("desc")
        self.assert_invalid(payload, "缺少 desc")

        for field in ("title", "path", "method", "status", "markdown", "desc"):
            with self.subTest(field=field):
                payload = valid_get_payload()
                payload[0]["list"][0][field] = 123
                self.assert_invalid(payload, f".{field} 必须是字符串")

    def test_method_path_and_status_values(self) -> None:
        cases = (
            ("method", "get", ".method 必须是支持的大写 HTTP method"),
            ("method", "TRACE", ".method 必须是支持的大写 HTTP method"),
            ("path", "coupon/detail", ".path 必须以 / 开头"),
            ("status", "done", '.status 必须是 "undone"'),
        )
        for field, value, expected in cases:
            with self.subTest(field=field, value=value):
                payload = valid_get_payload()
                payload[0]["list"][0][field] = value
                self.assert_invalid(payload, expected)

    def test_query_parameter_structure_types_and_duplicates(self) -> None:
        for field in ("name", "desc", "required", "example"):
            with self.subTest(missing=field):
                payload = valid_get_payload()
                payload[0]["list"][0]["req_query"][0].pop(field)
                self.assert_invalid(payload, f"缺少 {field}")

        for field, value, expected in (
            ("name", 1, ".name 必须是字符串"),
            ("desc", {}, ".desc 必须是字符串"),
            ("required", 1, ".required 必须是字符串"),
            ("required", "2", ".required 必须是字符串"),
            ("example", {}, ".example 必须是字符串"),
        ):
            with self.subTest(field=field, value=value):
                payload = valid_get_payload()
                payload[0]["list"][0]["req_query"][0][field] = value
                self.assert_invalid(payload, expected)

        payload = valid_get_payload()
        query = payload[0]["list"][0]["req_query"]
        query.append(copy.deepcopy(query[0]))
        self.assert_invalid(payload, "参数重复: coupon_id")

    def test_get_rejects_body_but_allows_false_schema_metadata(self) -> None:
        self.assert_valid(valid_get_payload())
        for field, value in (
            ("req_body_type", "json"),
            ("req_body_other", "{}"),
            ("req_body_form", [{}]),
        ):
            with self.subTest(field=field):
                payload = valid_get_payload()
                payload[0]["list"][0][field] = value
                self.assert_invalid(payload, "GET 接口不应包含请求体")

    def test_json_request_contract_and_jsonc(self) -> None:
        cases = (
            ("req_headers", None, "req_headers 必须是数组"),
            ("req_body_is_json_schema", True, "必须是 false"),
            ("req_body_other", {"coupon_id": 123}, "必须是 JSON 字符串"),
            ("req_body_other", "not-json", "不是合法 JSON/JSONC"),
            ("req_body_other", "123", "顶层必须是对象或数组"),
        )
        for field, value, expected in cases:
            with self.subTest(field=field):
                payload = valid_json_payload()
                payload[0]["list"][0][field] = value
                self.assert_invalid(payload, expected)

        payload = valid_json_payload()
        payload[0]["list"][0]["req_headers"][0]["value"] = "text/plain"
        self.assert_invalid(payload, "缺少 Content-Type: application/json")

        payload = valid_json_payload()
        payload[0]["list"][0]["req_headers"][0]["value"] = "application/jsonp"
        self.assert_invalid(payload, "缺少 Content-Type: application/json")

        payload = valid_json_payload()
        payload[0]["list"][0]["req_headers"][0]["value"] = (
            "application/json; charset=utf-8"
        )
        self.assert_valid(payload)

        payload = valid_json_payload()
        payload[0]["list"][0]["req_body_form"] = [{}]
        self.assert_invalid(payload, "JSON 请求不应包含 req_body_form")

    def test_form_request_contract_and_parameters(self) -> None:
        payload = valid_form_payload()
        payload[0]["list"][0]["req_headers"][0]["value"] = "application/json"
        self.assert_invalid(payload, "application/x-www-form-urlencoded")

        for field in ("name", "type", "desc", "required", "example"):
            with self.subTest(missing=field):
                payload = valid_form_payload()
                payload[0]["list"][0]["req_body_form"][0].pop(field)
                self.assert_invalid(payload, f"缺少 {field}")

        payload = valid_form_payload()
        payload[0]["list"][0]["req_body_form"][0]["required"] = 2
        self.assert_invalid(payload, ".required 必须是字符串")

        payload = valid_form_payload()
        form = payload[0]["list"][0]["req_body_form"]
        form.append(copy.deepcopy(form[0]))
        self.assert_invalid(payload, "参数重复: coupon_id")

        payload = valid_form_payload()
        form = payload[0]["list"][0]["req_body_form"]
        form.append(copy.deepcopy(form[0]))
        form[1]["name"] = "coupon_id "
        self.assert_invalid(payload, ".name 首尾不能有空白")
        self.assert_invalid(payload, "参数重复: coupon_id")

        payload = valid_form_payload()
        payload[0]["list"][0]["req_body_other"] = "{}"
        self.assert_invalid(payload, "form 请求不应包含 req_body_other")

    def test_no_body_contract(self) -> None:
        payload = valid_no_body_payload()
        payload[0]["list"][0].pop("req_query")
        self.assert_invalid(payload, "req_query 必须是数组")

        payload = valid_no_body_payload()
        payload[0]["list"][0]["req_body_other"] = "{}"
        self.assert_invalid(payload, "无 body 请求不应包含请求体字段")

        payload = valid_no_body_payload()
        payload[0]["list"][0]["req_body_type"] = "xml"
        self.assert_invalid(payload, "req_body_type 不支持")

    def test_header_structure_and_duplicates(self) -> None:
        payload = valid_json_payload()
        payload[0]["list"][0]["req_headers"][0]["name"] = 1
        self.assert_invalid(payload, ".name 必须是字符串")

        payload = valid_json_payload()
        headers = payload[0]["list"][0]["req_headers"]
        headers.append(copy.deepcopy(headers[0]))
        self.assert_invalid(payload, "请求头重复")

        payload = valid_json_payload()
        payload[0]["list"][0]["req_headers"][0]["name"] = " Content-Type "
        self.assert_invalid(payload, ".name 首尾不能有空白")

        payload = valid_no_body_payload()
        payload[0]["list"][0]["req_headers"][0]["required"] = "2"
        self.assert_invalid(payload, ".required 必须是字符串")

    def test_real_sensitive_values_are_rejected_in_all_yapi_value_positions(self) -> None:
        marker = "not-a-variable"
        cases: list[list[dict]] = []

        payload = valid_get_payload()
        parameter = payload[0]["list"][0]["req_query"][0]
        parameter.update({"name": "uid", "example": "10001"})
        cases.append(payload)

        payload = valid_no_body_payload()
        header = payload[0]["list"][0]["req_headers"][0]
        header.update({"name": "X-Debug-Key", "value": marker})
        cases.append(payload)

        payload = valid_no_body_payload()
        header = payload[0]["list"][0]["req_headers"][0]
        header.update({"name": "X-Internal-Key", "value": marker})
        cases.append(payload)

        payload = valid_json_payload()
        payload[0]["list"][0]["req_body_other"] = '{"data":{"uid":10001}}'
        cases.append(payload)

        payload = valid_get_payload()
        payload[0]["list"][0]["res_body"] = (
            '{"data":{"token":{"items":["not-a-variable"]}}}'
        )
        cases.append(payload)

        payload = valid_get_payload()
        payload[0]["list"][0]["x-fixture"] = {"debug_key": marker}
        cases.append(payload)

        payload = valid_get_payload()
        payload[0]["list"][0]["markdown"] = f"debug_key={marker}"
        cases.append(payload)

        for payload in cases:
            with self.subTest(payload=payload):
                self.assert_sensitive_rejected(payload, marker)

    def test_sensitive_variables_and_document_placeholders_remain_valid(self) -> None:
        payload = valid_json_payload()
        api = payload[0]["list"][0]
        api["req_headers"].append(
            {"name": "X-Debug-Key", "value": "{{debug_key}}"}
        )
        api["req_body_other"] = (
            '{"data":{"uid":"{{uid}}","token":{"enum":["{{access_token}}"]}}}'
        )
        api["res_body"] = '{"data":{"order_id":"{{order_id}}"}}'
        api["markdown"] = "debug_key={{debug_key}}；Authorization: token <加密令牌>"
        self.assert_valid(payload)

    def test_chinese_sensitive_fields_are_rejected_or_template_only(self) -> None:
        phone_marker = "13800138000"
        payload = valid_json_payload()
        payload[0]["list"][0]["req_body_other"] = (
            f'{{"手机号":"{phone_marker}","订单号":{{"enum":["not-a-variable"]}}}}'
        )
        self.assert_sensitive_rejected(payload, phone_marker)

        payload = valid_get_payload()
        payload[0]["list"][0]["markdown"] = f"手机号={phone_marker}"
        self.assert_sensitive_rejected(payload, phone_marker)

        payload = valid_json_payload()
        payload[0]["list"][0]["req_body_other"] = (
            '{"手机号":"{{phone}}","订单号":{"enum":["{{order_no}}"]}}'
        )
        self.assert_valid(payload)

    def test_phone_value_is_rejected_even_with_a_non_sensitive_field_name(self) -> None:
        phone_marker = "13800138000"
        payload = valid_json_payload()
        payload[0]["list"][0]["req_body_other"] = (
            f'{{"contact":"{phone_marker}"}}'
        )
        self.assert_sensitive_rejected(payload, phone_marker)

    def test_email_value_is_rejected_even_with_a_non_sensitive_field_name(self) -> None:
        email_marker = "sample@example.invalid"
        payload = valid_json_payload()
        payload[0]["list"][0]["req_body_other"] = (
            f'{{"contact":"{email_marker}"}}'
        )
        self.assert_sensitive_rejected(payload, email_marker)

    def test_identity_alias_and_value_are_rejected(self) -> None:
        payload = valid_json_payload()
        payload[0]["list"][0]["req_body_other"] = (
            '{"idNo":"not-a-variable"}'
        )
        self.assert_sensitive_rejected(payload, "not-a-variable")

        id_marker = "00000020000101000X"
        payload = valid_json_payload()
        payload[0]["list"][0]["req_body_other"] = (
            f'{{"identity":"{id_marker}"}}'
        )
        self.assert_sensitive_rejected(payload, id_marker)

    def test_response_contract_and_jsonc(self) -> None:
        cases = (
            ("res_body_type", "xml", '.res_body_type 必须是 "json" 或 "raw"'),
            ("res_body_is_json_schema", True, "必须是 false"),
            ("res_body", ["code", "msg", "data"], "必须是 JSON 字符串"),
            ("res_body", "not-json", "不是合法 JSON/JSONC"),
            ("res_body", "123", "顶层必须是对象或数组"),
        )
        for field, value, expected in cases:
            with self.subTest(field=field, value=value):
                payload = valid_get_payload()
                payload[0]["list"][0][field] = value
                self.assert_invalid(payload, expected)

        for response in (
            "[]",
            '{"ActionStatus":"OK","ErrorCode":0,"ErrorInfo":""}',
            '{"success":true,"data":{"id":1}}',
        ):
            with self.subTest(valid_response=response):
                payload = valid_get_payload()
                payload[0]["list"][0]["res_body"] = response
                self.assert_valid(payload)

        payload = valid_raw_response_payload()
        payload[0]["list"][0]["res_body"] = ""
        self.assert_invalid(payload, ".res_body 必须是非空字符串")

        payload = valid_raw_response_payload()
        payload[0]["list"][0]["res_body"] = {"code": "SUCCESS"}
        self.assert_invalid(payload, ".res_body 必须是字符串")

    def test_jsonc_comment_parser_preserves_urls_and_rejects_open_block(self) -> None:
        raw = '{"url":"https://example.com/a//b",/* note */"id":1}// tail'
        self.assertEqual(
            {"url": "https://example.com/a//b", "id": 1},
            __import__("json").loads(strip_json_comments(raw)),
        )
        with self.assertRaisesRegex(ValueError, "块注释未闭合"):
            strip_json_comments('{"id":1} /* open')

    def test_pending_markers_and_duplicate_api_are_rejected(self) -> None:
        for marker in ("待补", "待确认", "TODO", "TBD", "FIXME"):
            with self.subTest(marker=marker):
                payload = valid_get_payload()
                payload[0]["list"][0]["desc"] = marker
                self.assert_invalid(payload, f"占位标记 {marker}")

        payload = valid_get_payload()
        payload[0]["list"][0]["desc"] = "https://example.com/tbdomain"
        self.assert_valid(payload)

        payload = valid_get_payload()
        payload[0]["list"].append(copy.deepcopy(payload[0]["list"][0]))
        self.assert_invalid(payload, "接口重复")


if __name__ == "__main__":
    unittest.main()
