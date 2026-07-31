from decimal import Decimal
from pathlib import Path
import importlib.util
import sys

MODULE_PATH = Path(__file__).parents[1] / "website" / "handler.py"
spec = importlib.util.spec_from_file_location("website_handler", MODULE_PATH)
website_handler = importlib.util.module_from_spec(spec)
sys.modules["website_handler"] = website_handler
assert spec.loader is not None
spec.loader.exec_module(website_handler)


class FakeTable:
    def query(self, **kwargs):
        return {
            "Items": [
                {
                    "pair": "EUR/INR",
                    "observed_at": "2026-07-30",
                    "rate": Decimal("101.2500"),
                    "rolling_7d_avg_rate": Decimal("101.0000"),
                    "trend_sample_count": 2,
                    "trend_direction": "ABOVE_AVERAGE",
                    "alert_triggered": False,
                    "expires_at": 9999999999,
                }
            ]
        }


def test_parse_pairs_normalizes_and_deduplicates():
    assert website_handler.parse_pairs(" eur/inr,USD/INR,eur/inr ") == ["EUR/INR", "USD/INR"]


def test_decimal_to_native_converts_nested_values():
    value = {"rate": Decimal("101.25"), "items": [Decimal("2")]}
    assert website_handler.decimal_to_native(value) == {"rate": 101.25, "items": [2]}


def test_public_record_excludes_internal_ttl_field():
    record = {
        "pair": "EUR/INR",
        "rate": Decimal("101.25"),
        "expires_at": 9999999999,
    }
    public = website_handler.public_record(record)
    assert public["pair"] == "EUR/INR"
    assert "expires_at" not in public


def test_build_dashboard_payload_returns_latest_and_history():
    payload = website_handler.build_dashboard_payload(FakeTable(), ["EUR/INR"], 7)
    assert payload["pair_count"] == 1
    assert payload["pairs"][0]["latest"]["pair"] == "EUR/INR"
    assert len(payload["pairs"][0]["history"]) == 1


def test_root_route_returns_renamed_html():
    event = {"requestContext": {"http": {"path": "/"}}}
    result = website_handler.lambda_handler(event, None)
    assert result["statusCode"] == 200
    assert result["headers"]["content-type"].startswith("text/html")
    assert "Global Currency Trend &amp; Converter" not in result["body"]
    assert "Global Currency Trend & Converter" in result["body"]


def test_extract_api_key_supports_json_and_raw_secret():
    assert website_handler._extract_api_key('{"api_key":"abc_DEF-123"}') == "abc_DEF-123"
    assert website_handler._extract_api_key("abc_DEF-123") == "abc_DEF-123"


def test_validate_amount_rejects_zero_and_large_values():
    try:
        website_handler.validate_amount("0")
        assert False, "Expected ValueError"
    except ValueError:
        pass

    try:
        website_handler.validate_amount("1000000001")
        assert False, "Expected ValueError"
    except ValueError:
        pass


def test_conversion_payload_calculates_result():
    payload = website_handler.conversion_payload(
        "EUR",
        "INR",
        Decimal("100"),
        {
            "conversion_rate": Decimal("101.25"),
            "source_updated_utc": "Thu, 30 Jul 2026 00:00:01 +0000",
            "next_update_utc": None,
            "cached": False,
        },
    )
    assert payload["converted_amount"] == Decimal("10125.000000")
    assert payload["conversion_rate"] == Decimal("101.25")


def test_same_currency_conversion_does_not_need_provider():
    result = website_handler.current_rate("EUR", "EUR", "unused")
    assert result["conversion_rate"] == Decimal("1")


def test_convert_route_returns_success(monkeypatch):
    monkeypatch.setattr(
        website_handler,
        "current_rate",
        lambda base, target, secret_arn: {
            "conversion_rate": Decimal("101.25"),
            "source_updated_utc": "Thu, 30 Jul 2026 00:00:01 +0000",
            "next_update_utc": None,
            "cached": False,
        },
    )
    monkeypatch.setenv("SECRET_ARN", "arn:example")
    event = {
        "requestContext": {"http": {"path": "/api/convert"}},
        "queryStringParameters": {
            "from": "EUR",
            "to": "INR",
            "amount": "100",
        },
    }
    result = website_handler.lambda_handler(event, None)
    assert result["statusCode"] == 200
    assert '"converted_amount":10125' in result["body"]


def test_convert_route_rejects_unknown_currency():
    event = {
        "requestContext": {"http": {"path": "/api/convert"}},
        "queryStringParameters": {
            "from": "ABC",
            "to": "INR",
            "amount": "100",
        },
    }
    result = website_handler.lambda_handler(event, None)
    assert result["statusCode"] == 400
