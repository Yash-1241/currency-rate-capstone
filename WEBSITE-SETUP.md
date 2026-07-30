# Website Addition Setup

This package adds a public AWS-hosted dashboard to the existing currency-rate
capstone. It does not create an IAM role or IAM policy.

## Architecture

Browser -> API Gateway HTTP API -> Website Lambda -> Existing DynamoDB table

The website Lambda:
- Serves `index.html` at `/`
- Returns read-only JSON at `/api/rates`
- Returns health information at `/health`
- Reuses the existing AWS Academy `LabRole`
- Does not call ExchangeRate-API
- Does not write to DynamoDB

## Copy into the repository

Copy these items into the root of `currency-rate-capstone-git`:

- `website/`
- `website.tf`
- `website_outputs.tf`
- `tests/test_website_handler.py`

Do not copy Terraform state files from this package; none are included.

## Validate

```powershell
terraform fmt -recursive
terraform validate
pytest -q
terraform plan
```

Review the plan. It should add:
- One website Lambda
- One Lambda CloudWatch log group
- One HTTP API
- One Lambda integration
- Four HTTP routes
- One default API stage
- One Lambda permission for API Gateway

It must not add an IAM role or IAM policy.

## Deploy

```powershell
terraform apply
```

After apply:

```powershell
terraform output -raw website_url
terraform output -raw website_rates_api_url
```

Open the website URL in a browser.

## Test

```powershell
$websiteUrl = terraform output -raw website_url
Invoke-RestMethod "$websiteUrl/health"
Invoke-RestMethod "$websiteUrl/api/rates?limit=7"
Start-Process $websiteUrl
```

## Notes

The dashboard is publicly readable because it displays non-sensitive exchange-rate
results. The API key remains in Secrets Manager and is never returned by the website.
