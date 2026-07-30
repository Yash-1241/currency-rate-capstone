locals {
  website_lambda_function_name = substr("${local.resource_prefix}-website", 0, 64)
}

resource "aws_cloudwatch_log_group" "website_lambda" {
  name              = "/aws/lambda/${local.website_lambda_function_name}"
  retention_in_days = var.log_retention_days
}

data "archive_file" "website_lambda" {
  type        = "zip"
  source_dir  = "${path.module}/website"
  output_path = "${path.module}/build/website_lambda.zip"

  excludes = [
    "__pycache__",
    "*.pyc"
  ]
}

resource "aws_lambda_function" "website" {
  function_name = local.website_lambda_function_name
  description   = "Serves the global currency dashboard, reads DynamoDB trends, and performs live conversions"

  # Reuses the existing AWS Academy role. No IAM role is created.
  role             = data.aws_iam_role.lab_role.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  architectures    = ["x86_64"]
  filename         = data.archive_file.website_lambda.output_path
  source_code_hash = data.archive_file.website_lambda.output_base64sha256
  memory_size      = 256
  timeout          = 30

  environment {
    variables = {
      TABLE_NAME     = aws_dynamodb_table.currency_rates.name
      CURRENCY_PAIRS = join(",", local.normalized_pairs)
      SECRET_ARN     = aws_secretsmanager_secret.exchange_rate_api.arn
      LOG_LEVEL      = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.website_lambda]
}

resource "aws_apigatewayv2_api" "website" {
  name          = "${local.resource_prefix}-website-api"
  protocol_type = "HTTP"
  description   = "Public HTTP API for the global currency trend and converter dashboard"
}

resource "aws_apigatewayv2_integration" "website" {
  api_id                 = aws_apigatewayv2_api.website.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.website.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}

resource "aws_apigatewayv2_route" "website_root" {
  api_id    = aws_apigatewayv2_api.website.id
  route_key = "GET /"
  target    = "integrations/${aws_apigatewayv2_integration.website.id}"
}

resource "aws_apigatewayv2_route" "website_index" {
  api_id    = aws_apigatewayv2_api.website.id
  route_key = "GET /index.html"
  target    = "integrations/${aws_apigatewayv2_integration.website.id}"
}

resource "aws_apigatewayv2_route" "website_rates" {
  api_id    = aws_apigatewayv2_api.website.id
  route_key = "GET /api/rates"
  target    = "integrations/${aws_apigatewayv2_integration.website.id}"
}

resource "aws_apigatewayv2_route" "website_convert" {
  api_id    = aws_apigatewayv2_api.website.id
  route_key = "GET /api/convert"
  target    = "integrations/${aws_apigatewayv2_integration.website.id}"
}

resource "aws_apigatewayv2_route" "website_health" {
  api_id    = aws_apigatewayv2_api.website.id
  route_key = "GET /health"
  target    = "integrations/${aws_apigatewayv2_integration.website.id}"
}

resource "aws_apigatewayv2_stage" "website" {
  api_id      = aws_apigatewayv2_api.website.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }
}

resource "aws_lambda_permission" "allow_api_gateway_website" {
  statement_id  = "AllowExecutionFromApiGatewayWebsite"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.website.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.website.execution_arn}/*"
}
