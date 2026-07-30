resource "aws_secretsmanager_secret" "exchange_rate_api" {
  name                    = "${local.resource_prefix}/exchange-rate-api"
  description             = "ExchangeRate-API key for the currency trend alert capstone"
  recovery_window_in_days = 0
}

# Deliberately no aws_secretsmanager_secret_version resource.
# Add the API key after terraform apply so the key is not stored in Terraform state.
