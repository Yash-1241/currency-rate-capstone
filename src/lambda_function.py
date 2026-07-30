"""AWS Lambda handler for the Currency Exchange Rate Trend Alert Service.

The function:
1. Reads the ExchangeRate-API key from AWS Secrets Manager.
2. Fetches current rates for configured currency pairs.
3. Reads earlier records from DynamoDB.
4. Calculates daily change and rolling seven-sample trend values.
5. Stores one record per currency pair per API observation date.
6. Publishes an SNS alert when the daily movement reaches the threshold.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

import boto3
from boto3.dynamodb.conditions import Key

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

PAIR_PATTERN = re.compile(r"^[A-Z]{3}/[A-Z]{3}$")
API_ROOT = "https://v6.exchangerate-api.com/v6"
HTTP_TIMEOUT_SECONDS = 12
SEVEN_DAY_SAMPLE_SIZE = 7


def parse_currency_pairs(raw_pairs: str) -> list[str]:
    """Parse, validate, normalize, and de-duplicate comma-separated pairs."""
    pairs: list[str] = []
    for raw_pair in raw_pairs.split(","):
        pair = raw_pair.strip().upper()
        if not pair:
            continue
        if not PAIR_PATTERN.fullmatch(pair):
            raise ValueError(f"Invalid currency pair '{raw_pair}'. Use BASE/QUOTE, for example EUR/INR.")
        if pair not in pairs:
            pairs.append(pair)

    if not pairs:
        raise ValueError("CURRENCY_PAIRS does not contain any valid currency pairs.")
    return pairs


def decimal_value(value: float | int | str | Decimal, places: str = "0.0000000001") -> Decimal:
    """Convert a number to a DynamoDB-safe Decimal with predictable precision."""
    return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def percentage_change(current: Decimal, previous: Decimal | None) -> Decimal | None:
    """Return percentage change, or None when no usable previous value exists."""
    if previous is None or previous == 0:
        return None
    return ((current - previous) / previous * Decimal("100")).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def get_api_key(secret_arn: str, secrets_client: Any) -> str:
    """Read an API key stored either as raw text or as {\"api_key\": \"...\"}."""
    response = secrets_client.get_secret_value(SecretId=secret_arn)
    secret_string = response.get("SecretString")
    if not secret_string:
        raise RuntimeError("The ExchangeRate-API secret has no SecretString value.")

    try:
        decoded = json.loads(secret_string)
    except json.JSONDecodeError:
        decoded = None

    if isinstance(decoded, dict):
        api_key = str(decoded.get("api_key", "")).strip()
    else:
        api_key = secret_string.strip()

    if not api_key:
        raise RuntimeError("The ExchangeRate-API key is empty.")
    return api_key


def fetch_base_rates(base_currency: str, api_key: str, opener: Any = urllib.request.urlopen) -> dict[str, Any]:
    """Fetch the standard ExchangeRate-API response for one base currency."""
    encoded_key = urllib.parse.quote(api_key, safe="")
    url = f"{API_ROOT}/{encoded_key}/latest/{base_currency}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "currency-trend-capstone/1.0"},
        method="GET",
    )

    try:
        with opener(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"ExchangeRate-API returned HTTP {exc.code} for base {base_currency}.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach ExchangeRate-API for base {base_currency}: {exc.reason}") from exc
    except (TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"Invalid or timed-out ExchangeRate-API response for base {base_currency}.") from exc

    if payload.get("result") != "success":
        error_type = payload.get("error-type", "unknown-error")
        raise RuntimeError(f"ExchangeRate-API failed for base {base_currency}: {error_type}")

    conversion_rates = payload.get("conversion_rates")
    if not isinstance(conversion_rates, dict):
        raise RuntimeError(f"ExchangeRate-API response for {base_currency} has no conversion_rates object.")

    source_epoch = payload.get("time_last_update_unix")
    if source_epoch is not None:
        observed_at = datetime.fromtimestamp(int(source_epoch), tz=timezone.utc).date().isoformat()
    else:
        observed_at = datetime.now(timezone.utc).date().isoformat()

    return {
        "base_code": str(payload.get("base_code", base_currency)).upper(),
        "conversion_rates": conversion_rates,
        "observed_at": observed_at,
        "source_updated_at": int(source_epoch) if source_epoch is not None else None,
        "source_updated_utc": payload.get("time_last_update_utc"),
    }


def query_history(table: Any, pair: str, before_date: str, limit: int = 6) -> list[dict[str, Any]]:
    """Return newest historical records strictly before the current observation date."""
    response = table.query(
        KeyConditionExpression=Key("pair").eq(pair) & Key("observed_at").lt(before_date),
        ProjectionExpression="#rate, observed_at",
        ExpressionAttributeNames={"#rate": "rate"},
        ScanIndexForward=False,
        Limit=limit,
    )
    return list(response.get("Items", []))


def calculate_trend(current_rate: Decimal, history: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Calculate daily change and rolling seven-sample trend metrics."""
    historical_rates = [Decimal(str(item["rate"])) for item in history if item.get("rate") is not None]
    previous_rate = historical_rates[0] if historical_rates else None
    daily_change = percentage_change(current_rate, previous_rate)

    rolling_rates = [current_rate, *historical_rates[: SEVEN_DAY_SAMPLE_SIZE - 1]]
    rolling_average = (sum(rolling_rates) / Decimal(len(rolling_rates))).quantize(
        Decimal("0.0000000001"), rounding=ROUND_HALF_UP
    )
    change_vs_average = percentage_change(current_rate, rolling_average)

    seven_day_change: Decimal | None = None
    if len(rolling_rates) == SEVEN_DAY_SAMPLE_SIZE:
        seven_day_change = percentage_change(current_rate, rolling_rates[-1])

    if daily_change is None:
        daily_direction = "NO_HISTORY"
    elif daily_change > 0:
        daily_direction = "UP"
    elif daily_change < 0:
        daily_direction = "DOWN"
    else:
        daily_direction = "UNCHANGED"

    if change_vs_average is None or abs(change_vs_average) < Decimal("0.0500"):
        trend_direction = "NEAR_AVERAGE"
    elif change_vs_average > 0:
        trend_direction = "ABOVE_AVERAGE"
    else:
        trend_direction = "BELOW_AVERAGE"

    return {
        "previous_rate": previous_rate,
        "daily_change_pct": daily_change,
        "daily_direction": daily_direction,
        "rolling_7d_avg_rate": rolling_average,
        "change_vs_7d_avg_pct": change_vs_average,
        "seven_day_change_pct": seven_day_change,
        "trend_direction": trend_direction,
        "trend_sample_count": len(rolling_rates),
    }


def build_record(
    *,
    pair: str,
    current_rate: Decimal,
    observed_at: str,
    fetched_at: str,
    source_data: dict[str, Any],
    trend: dict[str, Any],
    threshold: Decimal,
    retention_days: int,
    alert_sent: bool,
) -> dict[str, Any]:
    """Build the DynamoDB item for one currency pair and observation date."""
    expires_at = int((datetime.now(timezone.utc) + timedelta(days=retention_days)).timestamp())
    daily_change = trend["daily_change_pct"]
    alert_triggered = daily_change is not None and abs(daily_change) >= threshold

    record: dict[str, Any] = {
        "pair": pair,
        "observed_at": observed_at,
        "base_currency": pair.split("/", maxsplit=1)[0],
        "quote_currency": pair.split("/", maxsplit=1)[1],
        "rate": current_rate,
        "fetched_at": fetched_at,
        "api_source": "ExchangeRate-API",
        "daily_direction": trend["daily_direction"],
        "rolling_7d_avg_rate": trend["rolling_7d_avg_rate"],
        "trend_direction": trend["trend_direction"],
        "trend_sample_count": trend["trend_sample_count"],
        "alert_threshold_pct": threshold,
        "alert_triggered": alert_triggered,
        "alert_sent": alert_sent,
        "expires_at": expires_at,
    }

    optional_fields = {
        "source_updated_at": source_data.get("source_updated_at"),
        "source_updated_utc": source_data.get("source_updated_utc"),
        "previous_rate": trend.get("previous_rate"),
        "daily_change_pct": trend.get("daily_change_pct"),
        "change_vs_7d_avg_pct": trend.get("change_vs_7d_avg_pct"),
        "seven_day_change_pct": trend.get("seven_day_change_pct"),
    }
    for key, value in optional_fields.items():
        if value is not None:
            record[key] = value

    return record


def publish_alert(sns_client: Any, topic_arn: str, record: dict[str, Any]) -> str:
    """Publish a concise exchange-rate movement alert and return the SNS message ID."""
    daily_change = record["daily_change_pct"]
    subject = f"FX alert: {record['pair']} moved {daily_change:+.2f}%"
    message = {
        "type": "currency_movement_alert",
        "pair": record["pair"],
        "observed_at": record["observed_at"],
        "current_rate": str(record["rate"]),
        "previous_rate": str(record.get("previous_rate", "")),
        "daily_change_percent": str(daily_change),
        "threshold_percent": str(record["alert_threshold_pct"]),
        "rolling_7d_average": str(record["rolling_7d_avg_rate"]),
        "trend_direction": record["trend_direction"],
    }
    response = sns_client.publish(
        TopicArn=topic_arn,
        Subject=subject[:100],
        Message=json.dumps(message, indent=2),
    )
    return str(response.get("MessageId", ""))


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is missing.")
    return value


def lambda_handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    """Lambda entry point."""
    table_name = required_environment("TABLE_NAME")
    secret_arn = required_environment("SECRET_ARN")
    sns_topic_arn = required_environment("SNS_TOPIC_ARN")
    pairs = parse_currency_pairs(required_environment("CURRENCY_PAIRS"))
    threshold = Decimal(os.getenv("ALERT_THRESHOLD_PERCENT", "1.0"))
    retention_days = int(os.getenv("HISTORY_RETENTION_DAYS", "400"))

    if threshold <= 0:
        raise ValueError("ALERT_THRESHOLD_PERCENT must be greater than zero.")
    if retention_days < 1:
        raise ValueError("HISTORY_RETENTION_DAYS must be at least one day.")

    secrets_client = boto3.client("secretsmanager")
    sns_client = boto3.client("sns")
    table = boto3.resource("dynamodb").Table(table_name)
    api_key = get_api_key(secret_arn, secrets_client)

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    base_response_cache: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    LOGGER.info("Processing %d currency pair(s): %s", len(pairs), ", ".join(pairs))

    for pair in pairs:
        try:
            base_currency, quote_currency = pair.split("/", maxsplit=1)
            if base_currency not in base_response_cache:
                base_response_cache[base_currency] = fetch_base_rates(base_currency, api_key)

            source_data = base_response_cache[base_currency]
            raw_rate = source_data["conversion_rates"].get(quote_currency)
            if raw_rate is None:
                raise RuntimeError(f"ExchangeRate-API returned no rate for {pair}.")

            current_rate = decimal_value(raw_rate)
            observed_at = source_data["observed_at"]
            history = query_history(table, pair, observed_at, limit=SEVEN_DAY_SAMPLE_SIZE - 1)
            trend = calculate_trend(current_rate, history)

            existing_response = table.get_item(Key={"pair": pair, "observed_at": observed_at})
            existing_item = existing_response.get("Item", {})
            alert_already_sent = bool(existing_item.get("alert_sent", False))

            record = build_record(
                pair=pair,
                current_rate=current_rate,
                observed_at=observed_at,
                fetched_at=fetched_at,
                source_data=source_data,
                trend=trend,
                threshold=threshold,
                retention_days=retention_days,
                alert_sent=alert_already_sent,
            )
            table.put_item(Item=record)

            if record["alert_triggered"] and not alert_already_sent:
                message_id = publish_alert(sns_client, sns_topic_arn, record)
                table.update_item(
                    Key={"pair": pair, "observed_at": observed_at},
                    UpdateExpression="SET alert_sent = :true, alert_message_id = :message_id",
                    ExpressionAttributeValues={":true": True, ":message_id": message_id},
                )
                record["alert_sent"] = True
                record["alert_message_id"] = message_id

            result = {
                "pair": pair,
                "observed_at": observed_at,
                "rate": str(record["rate"]),
                "daily_change_pct": str(record.get("daily_change_pct"))
                if record.get("daily_change_pct") is not None
                else None,
                "rolling_7d_avg_rate": str(record["rolling_7d_avg_rate"]),
                "trend_sample_count": record["trend_sample_count"],
                "alert_triggered": record["alert_triggered"],
                "alert_sent": record["alert_sent"],
            }
            results.append(result)
            LOGGER.info("Processed %s: %s", pair, json.dumps(result))
        except Exception as exc:  # Continue other pairs, then fail the invocation for visibility/retry.
            LOGGER.exception("Failed to process %s", pair)
            failures.append({"pair": pair, "error": str(exc)})

    response_body = {
        "processed_count": len(results),
        "failed_count": len(failures),
        "results": results,
        "failures": failures,
    }

    if failures:
        raise RuntimeError(json.dumps(response_body))

    return {"statusCode": 200, "body": json.dumps(response_body)}
