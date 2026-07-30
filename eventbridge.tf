resource "aws_cloudwatch_event_rule" "daily" {
  name                = "${local.resource_prefix}-daily"
  description         = "Runs the currency trend Lambda function once per day"
  schedule_expression = var.schedule_expression
  state               = var.enable_schedule ? "ENABLED" : "DISABLED"
}

resource "aws_cloudwatch_event_target" "lambda" {
  rule      = aws_cloudwatch_event_rule.daily.name
  target_id = "CurrencyTrendLambda"
  arn       = aws_lambda_function.currency_processor.arn

  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 2
  }
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.currency_processor.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily.arn
}
