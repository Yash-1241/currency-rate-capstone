output "website_url" {
  description = "Public professor-facing dashboard URL."
  value       = aws_apigatewayv2_api.website.api_endpoint
}

output "website_rates_api_url" {
  description = "Read-only JSON endpoint used by the dashboard."
  value       = "${aws_apigatewayv2_api.website.api_endpoint}/api/rates"
}

output "website_lambda_function_name" {
  description = "Lambda function that serves the website and read-only API."
  value       = aws_lambda_function.website.function_name
}

output "website_cloudwatch_log_group" {
  description = "CloudWatch log group for the website Lambda."
  value       = aws_cloudwatch_log_group.website_lambda.name
}
