resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.lambda_function_name}"
  retention_in_days = var.log_retention_days
}

data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/src"
  output_path = "${path.module}/build/lambda_function.zip"

  excludes = [
    "__pycache__",
    "*.pyc"
  ]
}

resource "aws_lambda_function" "currency_processor" {
  function_name = local.lambda_function_name
  description   = "Collects exchange rates, calculates trends, stores history, and publishes alerts"

  role             = data.aws_iam_role.lab_role.arn
  runtime          = "python3.12"
  handler          = "lambda_function.lambda_handler"
  architectures    = ["x86_64"]
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256

  memory_size = 256
  timeout     = 60

  environment {
    variables = {
      TABLE_NAME              = aws_dynamodb_table.currency_rates.name
      SECRET_ARN              = aws_secretsmanager_secret.exchange_rate_api.arn
      SNS_TOPIC_ARN           = aws_sns_topic.alerts.arn
      CURRENCY_PAIRS          = join(",", local.normalized_pairs)
      ALERT_THRESHOLD_PERCENT = tostring(var.alert_threshold_percent)
      HISTORY_RETENTION_DAYS  = tostring(var.history_retention_days)
      LOG_LEVEL               = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}
