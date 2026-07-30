import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import lambda_function as app  # noqa: E402


def test_parse_currency_pairs_normalizes_and_deduplicates():
    assert app.parse_currency_pairs(" eur/inr,USD/INR,eur/inr ") == ["EUR/INR", "USD/INR"]


def test_parse_currency_pairs_rejects_invalid_format():
    with pytest.raises(ValueError):
        app.parse_currency_pairs("EUR-INR")


def test_calculate_trend_with_full_history():
    history = [
        {"rate": Decimal("91")},
        {"rate": Decimal("90")},
        {"rate": Decimal("89")},
        {"rate": Decimal("88")},
        {"rate": Decimal("87")},
        {"rate": Decimal("86")},
    ]
    trend = app.calculate_trend(Decimal("92"), history)

    assert trend["daily_change_pct"] == Decimal("1.0989")
    assert trend["trend_sample_count"] == 7
    assert trend["rolling_7d_avg_rate"] == Decimal("89.0000000000")
    assert trend["seven_day_change_pct"] == Decimal("6.9767")
    assert trend["daily_direction"] == "UP"


def test_get_api_key_accepts_json_secret():
    client = Mock()
    client.get_secret_value.return_value = {"SecretString": json.dumps({"api_key": "secret-key"})}
    assert app.get_api_key("arn:test", client) == "secret-key"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_fetch_base_rates_parses_success_response():
    payload = {
        "result": "success",
        "time_last_update_unix": 1767225600,
        "time_last_update_utc": "Thu, 01 Jan 2026 00:00:00 +0000",
        "base_code": "EUR",
        "conversion_rates": {"INR": 90.5},
    }

    def opener(request, timeout):
        assert "latest/EUR" in request.full_url
        assert timeout == app.HTTP_TIMEOUT_SECONDS
        return FakeResponse(payload)

    result = app.fetch_base_rates("EUR", "not-logged-key", opener=opener)
    assert result["base_code"] == "EUR"
    assert result["conversion_rates"]["INR"] == 90.5
    assert result["observed_at"] == "2026-01-01"


def test_build_record_triggers_alert():
    trend = {
        "previous_rate": Decimal("90"),
        "daily_change_pct": Decimal("1.1111"),
        "daily_direction": "UP",
        "rolling_7d_avg_rate": Decimal("90.5000000000"),
        "change_vs_7d_avg_pct": Decimal("0.5525"),
        "seven_day_change_pct": None,
        "trend_direction": "ABOVE_AVERAGE",
        "trend_sample_count": 2,
    }
    record = app.build_record(
        pair="EUR/INR",
        current_rate=Decimal("91"),
        observed_at="2026-01-02",
        fetched_at="2026-01-02T08:00:00+00:00",
        source_data={"source_updated_at": 1767312000},
        trend=trend,
        threshold=Decimal("1.0"),
        retention_days=400,
        alert_sent=False,
    )
    assert record["alert_triggered"] is True
    assert record["daily_change_pct"] == Decimal("1.1111")
