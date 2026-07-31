# Global Currency Dashboard Upgrade

This upgrade changes the visible dashboard name, expands scheduled trend tracking,
and adds a secure interactive converter.

## Final design

- Visible name: **Global Currency Trend & Converter**
- Scheduled trend pairs:
  - EUR/INR
  - USD/INR
  - GBP/INR
  - EUR/USD
  - USD/JPY
  - AUD/USD
- Converter: 37 common currencies from multiple regions
- API key: stays in the existing AWS Secrets Manager secret
- IAM: reuses the existing AWS Academy `LabRole`; no IAM role or policy is created
- Public URL: the existing API Gateway URL remains unchanged

## Files to replace

Copy these files into the repository root, replacing the current versions:

- `website/handler.py`
- `website/index.html`
- `website.tf`
- `tests/test_website_handler.py`

## Update the local terraform.tfvars

Replace only the `currency_pairs` value with:

```hcl
currency_pairs = [
  "EUR/INR",
  "USD/INR",
  "GBP/INR",
  "EUR/USD",
  "USD/JPY",
  "AUD/USD"
]
```

Do not upload `terraform.tfvars` to GitHub.

## Validate

```powershell
terraform fmt -recursive
terraform validate
pytest -q
git diff --check
terraform plan
```

Because the website is already deployed, the plan should normally show:
- one new API Gateway route: `GET /api/convert`
- an in-place update to the website Lambda
- an in-place update to the processor Lambda after adding tracked pairs
- zero resources destroyed
- no IAM role or IAM policy resources

Review the actual plan rather than relying only on an expected resource count.

## Deploy

```powershell
terraform apply
```

Confirm only after the plan shows zero resources to destroy.

## Create first records for the new tracked pairs

```powershell
'{}' | Set-Content -Path .\manual-upgrade-event.json -Encoding ascii

aws lambda invoke `
  --function-name "currency-trend-alert-dev-processor" `
  --payload fileb://manual-upgrade-event.json `
  .\manual-upgrade-result.json

Get-Content .\manual-upgrade-result.json
```

The generated JSON files are ignored by the project `.gitignore` pattern for
generated outputs. Delete them after testing if preferred.

## Test the converter

```powershell
$websiteUrl = terraform output -raw website_url

Invoke-RestMethod `
  "$websiteUrl/api/convert?from=EUR&to=INR&amount=100" |
  ConvertTo-Json -Depth 10

Start-Process $websiteUrl
```

On the page:
1. Enter an amount.
2. Choose the source currency.
3. Choose the target currency.
4. Press **Convert**.
5. Confirm the six tracked-pair cards appear after the processor invocation.

## Security notes

- The browser never receives the ExchangeRate-API key.
- The website Lambda reads the existing secret at runtime.
- Inputs are restricted to supported currency codes.
- The amount must be greater than zero and no more than 1,000,000,000.
- Warm Lambda instances cache pair rates for five minutes to reduce API quota use.
- The converter endpoint is public for the university demo, so API Gateway throttling remains enabled.
