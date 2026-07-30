locals {
  resource_prefix = "${var.project_name}-${var.environment}"
  normalized_pairs = distinct([
    for pair in var.currency_pairs : upper(trimspace(pair))
  ])
  lambda_function_name = substr("${local.resource_prefix}-processor", 0, 64)
}
