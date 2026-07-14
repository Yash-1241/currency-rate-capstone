import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

import boto3


# Configuration supplied by Terraform.
SECRET_NAME = os.environ["SECRET_NAME"]
DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]

# AWS service clients.
secrets_client = boto3.client("secretsmanager")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(DYNAMODB_TABLE)

# Currency tracker configuration.
BASE_CURRENCY = "EUR"
TARGET_CURRENCIES = ["INR", "USD", "GBP"]


def get_api_key():
    """Read the ExchangeRate-API key from AWS Secrets Manager."""
    response = secrets_client.get_secret_value(
        SecretId=SECRET_NAME
    )

    secret_data = json.loads(response["SecretString"])

    api_key = secret_data.get("api_key")

    if not api_key:
        raise ValueError(
            "api_key was not found in the Secrets Manager secret"
        )

    return api_key


def fetch_exchange_rates(api_key):
    """Call ExchangeRate-API and return the decoded response."""
    api_url = (
        f"https://v6.exchangerate-api.com/v6/"
        f"{api_key}/latest/{BASE_CURRENCY}"
    )

    request = urllib.request.Request(
        api_url,
        method="GET"
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        response_body = response.read().decode("utf-8")

    api_data = json.loads(response_body)

    if api_data.get("result") != "success":
        raise ValueError(
            "ExchangeRate-API returned an unsuccessful response"
        )

    return api_data


def transform_rates(api_data):
    """Keep only the currency rates required by the capstone."""
    conversion_rates = api_data.get("conversion_rates", {})

    transformed_rates = {}

    for currency in TARGET_CURRENCIES:
        rate = conversion_rates.get(currency)

        if rate is None:
            raise ValueError(
                f"Rate for {currency} was not returned by the API"
            )

        transformed_rates[currency] = rate

    return transformed_rates


def store_rates(transformed_rates):
    """Store each transformed currency rate in DynamoDB."""
    recorded_at = datetime.now(timezone.utc).isoformat()

    stored_items = []

    for target_currency, rate in transformed_rates.items():
        currency_pair = f"{BASE_CURRENCY}-{target_currency}"

        item = {
            "currency_pair": currency_pair,
            "recorded_at": recorded_at,
            "base_currency": BASE_CURRENCY,
            "target_currency": target_currency,
            "rate": Decimal(str(rate)),
        }

        table.put_item(Item=item)

        stored_items.append(
            {
                "currency_pair": currency_pair,
                "recorded_at": recorded_at,
                "rate": rate,
            }
        )

    return stored_items


def lambda_handler(event, context):
    """Main Lambda handler."""
    try:
        api_key = get_api_key()

        api_data = fetch_exchange_rates(api_key)

        transformed_rates = transform_rates(api_data)

        stored_items = store_rates(transformed_rates)

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps(
                {
                    "status": "success",
                    "message": (
                        "Exchange rates fetched, transformed, and stored."
                    ),
                    "base_currency": BASE_CURRENCY,
                    "currencies_processed": len(stored_items),
                    "rates": stored_items,
                }
            ),
        }

    except urllib.error.HTTPError as error:
        print(f"External API HTTP error: {error.code}")

        return {
            "statusCode": 502,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps(
                {
                    "status": "error",
                    "message": "External currency API request failed.",
                }
            ),
        }

    except urllib.error.URLError as error:
        print(f"External API connection error: {error.reason}")

        return {
            "statusCode": 502,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps(
                {
                    "status": "error",
                    "message": (
                        "Could not connect to the external currency API."
                    ),
                }
            ),
        }

    except Exception as error:
        print(
            f"Application error: "
            f"{type(error).__name__}: {error}"
        )

        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps(
                {
                    "status": "error",
                    "message": "Currency rate processing failed.",
                }
            ),
        }