import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from schemas import AppError, ExtractData
from services.deepseek_extract import (
    ExtractModelOutput,
    apply_page_city_defaults,
    parse_model_output,
    validate_business_completeness,
)

client = TestClient(app)


def test_extract_success():
    data = ExtractData(
        city_a="杭州",
        address_a="杭州东站",
        city_b="杭州",
        address_b="西湖龙翔桥地铁站",
        category="咖啡店",
    )
    with patch(
        "api.extract.extract_meetup_info",
        new=AsyncMock(return_value=data),
    ):
        response = client.post(
            "/extract",
            json={
                "text": "我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店。",
                "city": "杭州",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"]
    assert body["data"] == data.model_dump()
    assert "party_count" not in body["data"]
    assert "incomplete_reason" not in body["data"]


def test_extract_missing_text():
    response = client.post("/extract", json={"city": "杭州"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "MISSING_FIELD"
    assert body["error"]["stage"] == "extract"


def test_extract_empty_text():
    response = client.post("/extract", json={"text": "   ", "city": "杭州"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MISSING_FIELD"


def test_extract_cross_city_via_endpoint():
    with patch(
        "api.extract.extract_meetup_info",
        new=AsyncMock(
            side_effect=AppError(
                status_code=422,
                code="CROSS_CITY",
                message="当前仅支持同一城市内两人碰面，请重新说明两位都在同一城市的位置。",
                stage="extract",
                request_id="req_c",
            )
        ),
    ):
        response = client.post(
            "/extract",
            json={
                "text": "我在杭州东站，朋友在上海虹桥站，找中间咖啡店。",
                "city": "杭州",
            },
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CROSS_CITY"


def test_parse_model_output_rejects_bad_json():
    with pytest.raises(AppError) as exc:
        parse_model_output("not-json", request_id="req_j")
    assert exc.value.code == "MODEL_OUTPUT_INVALID"
    assert exc.value.status_code == 502


def test_parse_model_output_rejects_missing_keys():
    with pytest.raises(AppError) as exc:
        parse_model_output(
            json.dumps({"city_a": "杭州", "address_a": "东站"}),
            request_id="req_m",
        )
    assert exc.value.code == "MODEL_OUTPUT_INVALID"


def test_business_party_count_invalid():
    model = ExtractModelOutput(
        city_a="杭州",
        address_a="杭州东站",
        city_b="杭州",
        address_b="龙翔桥",
        category="咖啡店",
        party_count=3,
        incomplete_reason="三人",
    )
    with pytest.raises(AppError) as exc:
        validate_business_completeness(model, request_id="req_p")
    assert exc.value.code == "PARTY_COUNT_INVALID"
    assert exc.value.status_code == 422


def test_business_missing_vague_address():
    model = ExtractModelOutput(
        city_a="杭州",
        address_a="我家",
        city_b="杭州",
        address_b="公司",
        category="咖啡店",
        party_count=2,
        incomplete_reason="含糊",
    )
    with pytest.raises(AppError) as exc:
        validate_business_completeness(model, request_id="req_a")
    assert exc.value.code == "MISSING_ADDRESS"


def test_business_cross_city():
    model = ExtractModelOutput(
        city_a="杭州",
        address_a="杭州东站",
        city_b="上海",
        address_b="虹桥站",
        category="咖啡店",
        party_count=2,
        incomplete_reason=None,
    )
    with pytest.raises(AppError) as exc:
        validate_business_completeness(model, request_id="req_x")
    assert exc.value.code == "CROSS_CITY"


def test_page_city_and_default_category():
    model = ExtractModelOutput(
        city_a=None,
        address_a="火车东站",
        city_b=None,
        address_b="龙翔桥",
        category=None,
        party_count=2,
        incomplete_reason=None,
    )
    filled = apply_page_city_defaults(model, "杭州")
    assert filled.city_a == "杭州"
    assert filled.city_b == "杭州"
    assert filled.category == "咖啡店"
    data = validate_business_completeness(filled, request_id="req_d")
    assert data.category == "咖啡店"


def test_complete_flow_with_mocked_http(monkeypatch):
    raw_model = {
        "city_a": "杭州",
        "address_a": "杭州东站",
        "city_b": "杭州",
        "address_b": "西湖龙翔桥地铁站",
        "category": "咖啡店",
        "party_count": 2,
        "incomplete_reason": None,
    }

    class _Settings:
        deepseek_api_key = "sk-test"
        deepseek_base_url = "https://api.deepseek.com"
        deepseek_model = "deepseek-v4-flash"
        extract_timeout_sec = 15.0

    class _Response:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {"message": {"content": json.dumps(raw_model, ensure_ascii=False)}}
                ]
            }

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return _Response()

    from services import deepseek_extract

    monkeypatch.setattr(deepseek_extract, "get_settings", lambda: _Settings())
    monkeypatch.setattr(deepseek_extract.httpx, "AsyncClient", _FakeClient)

    response = client.post(
        "/extract",
        json={
            "text": "我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店。",
            "city": "杭州",
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["address_a"] == "杭州东站"
    assert "party_count" not in response.json()["data"]
