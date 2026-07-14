terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }

    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

data "aws_iam_role" "labrole" {
  name = "LabRole"
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/lambda/handler.py"
  output_path = "${path.module}/lambda_function.zip"
}

resource "aws_secretsmanager_secret" "exchange_api_key" {
  name        = "currency-rate-tracker/exchangerate-api-key"
  description = "API key for ExchangeRate-API. Value is added manually outside Terraform."
}

resource "aws_lambda_function" "currency_tracker" {
  function_name = "currency-rate-tracker-fixed-response"
  role          = data.aws_iam_role.labrole.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"

  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  timeout = 15

  environment {
    variables = {
      SECRET_NAME    = aws_secretsmanager_secret.exchange_api_key.name
      DYNAMODB_TABLE = aws_dynamodb_table.currency_rates.name
    }
  }
}

output "lambda_function_name" {
  value = aws_lambda_function.currency_tracker.function_name
}

output "lambda_execution_role_arn" {
  value = aws_lambda_function.currency_tracker.role
}

output "secret_name" {
  value = aws_secretsmanager_secret.exchange_api_key.name
}

output "secret_arn" {
  value = aws_secretsmanager_secret.exchange_api_key.arn
}
resource "aws_dynamodb_table" "currency_rates" {
  name         = "currency-rate-tracker-rates"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "currency_pair"
  range_key    = "recorded_at"

  attribute {
    name = "currency_pair"
    type = "S"
  }

  attribute {
    name = "recorded_at"
    type = "S"
  }

  tags = {
    Project = "Currency Rate Tracker"
  }
}

output "dynamodb_table_name" {
  value = aws_dynamodb_table.currency_rates.name
}
output "dynamodb_billing_mode" {
  value = aws_dynamodb_table.currency_rates.billing_mode
}

output "dynamodb_partition_key" {
  value = aws_dynamodb_table.currency_rates.hash_key
}

output "dynamodb_region" {
  value = "us-east-1"
}
# --------------------------------------------------
# API Gateway HTTP API
# --------------------------------------------------

resource "aws_apigatewayv2_api" "currency_api" {
  name          = "currency-rate-tracker-api"
  protocol_type = "HTTP"
}

# --------------------------------------------------
# API Gateway Lambda Integration
# Uses the existing AWS Academy LabRole
# --------------------------------------------------

resource "aws_apigatewayv2_integration" "currency_lambda" {
  api_id = aws_apigatewayv2_api.currency_api.id

  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.currency_tracker.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"

  credentials_arn = data.aws_iam_role.labrole.arn
}

# --------------------------------------------------
# GET /rates route
# --------------------------------------------------

resource "aws_apigatewayv2_route" "get_rates" {
  api_id = aws_apigatewayv2_api.currency_api.id

  route_key = "GET /rates"

  target = "integrations/${aws_apigatewayv2_integration.currency_lambda.id}"
}

# --------------------------------------------------
# Default API stage with automatic deployment
# --------------------------------------------------

resource "aws_apigatewayv2_stage" "default" {
  api_id = aws_apigatewayv2_api.currency_api.id

  name        = "$default"
  auto_deploy = true
}

# --------------------------------------------------
# API endpoint output
# --------------------------------------------------

output "currency_api_endpoint" {
  value = "${aws_apigatewayv2_api.currency_api.api_endpoint}/rates"
}