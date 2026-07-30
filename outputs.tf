output "aws_account_id" {
  description = "AWS account used for this deployment."
  value       = data.aws_caller_identity.current.account_id
}

output "lambda_function_name" {
  description = "Lambda function name used for manual tests."
  value       = aws_lambda_function.currency_processor.function_name
}

output "dynamodb_table_name" {
  description = "DynamoDB table that stores historical rates and trend values."
  value       = aws_dynamodb_table.currency_rates.name
}

output "exchange_rate_secret_arn" {
  description = "Secrets Manager ARN. Add the API key to this secret after terraform apply."
  value       = aws_secretsmanager_secret.exchange_rate_api.arn
}

output "sns_topic_arn" {
  description = "SNS topic used for exchange-rate and Lambda error alerts."
  value       = aws_sns_topic.alerts.arn
}

output "eventbridge_rule_name" {
  description = "Daily EventBridge rule name."
  value       = aws_cloudwatch_event_rule.daily.name
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group for the Lambda function."
  value       = aws_cloudwatch_log_group.lambda.name
}
