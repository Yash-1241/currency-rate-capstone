resource "aws_dynamodb_table" "currency_rates" {
  name         = "${local.resource_prefix}-rates"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pair"
  range_key    = "observed_at"

  attribute {
    name = "pair"
    type = "S"
  }

  attribute {
    name = "observed_at"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  server_side_encryption {
    enabled = true
  }
}
