"""AWS Lambda for the Global Currency Trend & Converter dashboard.

Routes:
- GET /             -> HTML dashboard
- GET /index.html   -> HTML dashboard
- GET /api/rates    -> Latest tracked rates and recent DynamoDB history
- GET /api/convert  -> Live currency conversion using ExchangeRate-API
- GET /health       -> Health response

The Lambda reads the existing DynamoDB table and the existing API key from
AWS Secrets Manager. It never exposes the API key to the browser.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

DEFAULT_HISTORY_LIMIT = 7
MAX_HISTORY_LIMIT = 30
MAX_CONVERSION_AMOUNT = Decimal("1000000000")
RATE_CACHE_SECONDS = 300
HTML_DOCUMENT = (Path(__file__).with_name("index.html")).read_text(encoding="utf-8")

SUPPORTED_CURRENCIES = {
    "AED": "UAE Dirham",
    "ARS": "Argentine Peso",
    "AUD": "Australian Dollar",
    "BRL": "Brazilian Real",
    "CAD": "Canadian Dollar",
    "CHF": "Swiss Franc",
    "CNY": "Chinese Yuan",
    "CZK": "Czech Koruna",
    "DKK": "Danish Krone",
    "EGP": "Egyptian Pound",
    "EUR": "Euro",
    "GBP": "British Pound",
    "HKD": "Hong Kong Dollar",
    "HUF": "Hungarian Forint",
    "IDR": "Indonesian Rupiah",
    "ILS": "Israeli New Shekel",
    "INR": "Indian Rupee",
    "JPY": "Japanese Yen",
    "KRW": "South Korean Won",
    "MXN": "Mexican Peso",
    "MYR": "Malaysian Ringgit",
    "NGN": "Nigerian Naira",
    "NOK": "Norwegian Krone",
    "NZD": "New Zealand Dollar",
    "PHP": "Philippine Peso",
    "PLN": "Polish Zloty",
    "QAR": "Qatari Riyal",
    "RON": "Romanian Leu",
    "SAR": "Saudi Riyal",
    "SEK": "Swedish Krona",
    "SGD": "Singapore Dollar",
    "THB": "Thai Baht",
    "TRY": "Turkish Lira",
    "TWD": "New Taiwan Dollar",
    "USD": "US Dollar",
    "VND": "Vietnamese Dong",
    "ZAR": "South African Rand",
}

# Warm Lambda environments can reuse a rate for five minutes, reducing API quota use.
_RATE_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def parse_pairs(raw_pairs: str) -> list[str]:
    """Return normalized, unique currency pairs from an environment variable."""
    pairs: list[str] = []
    for raw_pair in raw_pairs.split(","):
        pair = raw_pair.strip().upper()
        if pair and pair not in pairs:
            pairs.append(pair)
    if not pairs:
        raise RuntimeError("CURRENCY_PAIRS is empty.")
    return pairs


def decimal_to_native(value: Any) -> Any:
    """Convert DynamoDB Decimal values into JSON-compatible numbers."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {key: decimal_to_native(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decimal_to_native(item) for item in value]
    return value


def response(
    status_code: int,
    body: str,
    content_type: str,
    *,
    cache_control: str = "no-store",
) -> dict[str, Any]:
    """Build an API Gateway HTTP API payload-v2 response."""
    return {
        "statusCode": status_code,
        "headers": {
            "content-type": content_type,
            "cache-control": cache_control,
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
            "referrer-policy": "no-referrer",
        },
        "body": body,
    }


def json_response(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    return response(
        status_code,
        json.dumps(decimal_to_native(payload), separators=(",", ":")),
        "application/json; charset=utf-8",
    )


def request_path(event: dict[str, Any] | None) -> str:
    """Extract the request path from an API Gateway HTTP API event."""
    if not event:
        return "/"
    request_context = event.get("requestContext", {})
    http_context = request_context.get("http", {})
    return str(http_context.get("path") or event.get("rawPath") or "/")


def query_parameters(event: dict[str, Any] | None) -> dict[str, str]:
    return (event or {}).get("queryStringParameters") or {}


def requested_limit(event: dict[str, Any] | None) -> int:
    """Parse and bound the optional history limit query parameter."""
    raw_limit = query_parameters(event).get("limit")
    if raw_limit is None:
        return DEFAULT_HISTORY_LIMIT
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return DEFAULT_HISTORY_LIMIT
    return max(1, min(limit, MAX_HISTORY_LIMIT))


def query_pair_history(table: Any, pair: str, limit: int) -> list[dict[str, Any]]:
    """Read newest records for one currency pair using the table primary key."""
    result = table.query(
        KeyConditionExpression=Key("pair").eq(pair),
        ScanIndexForward=False,
        Limit=limit,
    )
    return list(result.get("Items", []))


def public_record(item: dict[str, Any]) -> dict[str, Any]:
    """Expose only fields useful to the public dashboard."""
    allowed_fields = (
        "pair",
        "observed_at",
        "rate",
        "previous_rate",
        "daily_change_pct",
        "daily_direction",
        "rolling_7d_avg_rate",
        "change_vs_7d_avg_pct",
        "seven_day_change_pct",
        "trend_direction",
        "trend_sample_count",
        "alert_threshold_pct",
        "alert_triggered",
        "alert_sent",
        "fetched_at",
        "source_updated_utc",
        "api_source",
    )
    return {field: item[field] for field in allowed_fields if field in item}


def build_dashboard_payload(table: Any, pairs: list[str], limit: int) -> dict[str, Any]:
    """Build latest-rate cards and recent history for each configured pair."""
    pair_results: list[dict[str, Any]] = []

    for pair in pairs:
        items = query_pair_history(table, pair, limit)
        public_items = [public_record(item) for item in items]
        pair_results.append(
            {
                "pair": pair,
                "latest": public_items[0] if public_items else None,
                "history": list(reversed(public_items)),
            }
        )

    return {
        "service": "Global Currency Trend & Converter",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "history_limit": limit,
        "pair_count": len(pair_results),
        "pairs": pair_results,
    }


def _extract_api_key(secret_string: str) -> str:
    """Support either a raw key or a JSON secret such as {"api_key": "..."}."""
    raw = secret_string.strip()
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        decoded = None

    if isinstance(decoded, dict):
        candidates = (
            decoded.get("api_key"),
            decoded.get("API_KEY"),
            decoded.get("key"),
            decoded.get("exchange_rate_api_key"),
        )
        api_key = next(
            (str(candidate).strip() for candidate in candidates if candidate),
            "",
        )
    elif isinstance(decoded, str):
        api_key = decoded.strip()
    else:
        api_key = raw

    if not api_key or not re.fullmatch(r"[A-Za-z0-9_-]+", api_key):
        raise RuntimeError("The Secrets Manager value does not contain a valid API key.")
    return api_key


def get_api_key(secret_arn: str) -> str:
    """Read the existing ExchangeRate-API key from Secrets Manager."""
    if not secret_arn:
        raise RuntimeError("SECRET_ARN is missing.")
    result = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)
    secret_string = result.get("SecretString")
    if not secret_string:
        raise RuntimeError("The API key secret does not contain SecretString.")
    return _extract_api_key(secret_string)


def validate_currency(code: str | None, field_name: str) -> str:
    normalized = (code or "").strip().upper()
    if normalized not in SUPPORTED_CURRENCIES:
        raise ValueError(f"{field_name} must be a supported three-letter currency code.")
    return normalized


def validate_amount(raw_amount: str | None) -> Decimal:
    try:
        amount = Decimal(str(raw_amount or "").strip())
    except (InvalidOperation, ValueError):
        raise ValueError("amount must be a valid number.") from None

    if not amount.is_finite() or amount <= 0:
        raise ValueError("amount must be greater than zero.")
    if amount > MAX_CONVERSION_AMOUNT:
        raise ValueError("amount must not exceed 1,000,000,000.")
    return amount


def _fetch_rate_from_provider(base: str, target: str, secret_arn: str) -> dict[str, Any]:
    """Call the provider pair endpoint and return the current conversion rate."""
    api_key = get_api_key(secret_arn)
    url = (
        "https://v6.exchangerate-api.com/v6/"
        f"{urllib.parse.quote(api_key, safe='')}/pair/{base}/{target}"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "currency-trend-capstone/1.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as provider_response:
            payload = json.loads(provider_response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Exchange-rate provider returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Exchange-rate provider could not be reached.") from exc
    except (TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("Exchange-rate provider returned an invalid response.") from exc

    if payload.get("result") != "success":
        error_type = payload.get("error-type", "unknown-provider-error")
        raise RuntimeError(f"Exchange-rate provider error: {error_type}.")

    try:
        conversion_rate = Decimal(str(payload["conversion_rate"]))
    except (KeyError, InvalidOperation):
        raise RuntimeError("Provider response did not contain a valid conversion rate.") from None

    if conversion_rate <= 0:
        raise RuntimeError("Provider returned a non-positive conversion rate.")

    return {
        "conversion_rate": conversion_rate,
        "source_updated_utc": payload.get("time_last_update_utc"),
        "next_update_utc": payload.get("time_next_update_utc"),
    }


def current_rate(base: str, target: str, secret_arn: str) -> dict[str, Any]:
    """Return a cached or live conversion rate."""
    if base == target:
        return {
            "conversion_rate": Decimal("1"),
            "source_updated_utc": None,
            "next_update_utc": None,
            "cached": False,
        }

    now = time.time()
    cache_key = (base, target)
    cached = _RATE_CACHE.get(cache_key)
    if cached and now - cached["cached_at"] < RATE_CACHE_SECONDS:
        return {
            "conversion_rate": cached["conversion_rate"],
            "source_updated_utc": cached.get("source_updated_utc"),
            "next_update_utc": cached.get("next_update_utc"),
            "cached": True,
        }

    fresh = _fetch_rate_from_provider(base, target, secret_arn)
    _RATE_CACHE[cache_key] = {**fresh, "cached_at": now}
    return {**fresh, "cached": False}


def conversion_payload(
    base: str,
    target: str,
    amount: Decimal,
    rate_data: dict[str, Any],
) -> dict[str, Any]:
    rate = Decimal(str(rate_data["conversion_rate"]))
    converted = (amount * rate).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    return {
        "from": base,
        "from_name": SUPPORTED_CURRENCIES[base],
        "to": target,
        "to_name": SUPPORTED_CURRENCIES[target],
        "amount": amount,
        "conversion_rate": rate,
        "converted_amount": converted,
        "source_updated_utc": rate_data.get("source_updated_utc"),
        "next_update_utc": rate_data.get("next_update_utc"),
        "cached": bool(rate_data.get("cached")),
        "provider": "ExchangeRate-API",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def lambda_handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    """Serve the dashboard HTML and its read-only APIs."""
    path = request_path(event)

    if path in ("/", "/index.html"):
        return response(
            200,
            HTML_DOCUMENT,
            "text/html; charset=utf-8",
            cache_control="no-cache",
        )

    if path == "/health":
        return json_response(
            200,
            {
                "status": "ok",
                "service": "global-currency-trend-converter",
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )

    if path == "/api/rates":
        try:
            table_name = os.getenv("TABLE_NAME", "").strip()
            raw_pairs = os.getenv("CURRENCY_PAIRS", "").strip()
            if not table_name:
                raise RuntimeError("TABLE_NAME is missing.")
            pairs = parse_pairs(raw_pairs)
            limit = requested_limit(event)
            table = boto3.resource("dynamodb").Table(table_name)
            payload = build_dashboard_payload(table, pairs, limit)
            return json_response(200, payload)
        except Exception:
            LOGGER.exception("Could not build dashboard response")
            return json_response(
                500,
                {
                    "error": "dashboard_data_unavailable",
                    "message": "The dashboard could not read the latest exchange-rate data.",
                },
            )

    if path == "/api/convert":
        try:
            query = query_parameters(event)
            base = validate_currency(query.get("from"), "from")
            target = validate_currency(query.get("to"), "to")
            amount = validate_amount(query.get("amount"))
            secret_arn = os.getenv("SECRET_ARN", "").strip()
            rate_data = current_rate(base, target, secret_arn)
            return json_response(
                200,
                conversion_payload(base, target, amount, rate_data),
            )
        except ValueError as exc:
            return json_response(
                400,
                {
                    "error": "invalid_conversion_request",
                    "message": str(exc),
                },
            )
        except Exception:
            LOGGER.exception("Could not convert currency")
            return json_response(
                502,
                {
                    "error": "conversion_unavailable",
                    "message": "The live conversion service is temporarily unavailable.",
                },
            )

    return json_response(
        404,
        {
            "error": "not_found",
            "message": "The requested page does not exist.",
        },
    )
