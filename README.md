# Currency Exchange Rate Trend Alert Service

Serverless AWS capstone implementation using Terraform, Python Lambda, DynamoDB, Secrets Manager, EventBridge, SNS, and CloudWatch.

## Architecture

```text
EventBridge daily rule
        |
        v
AWS Lambda (Python)
        |---- reads API key from Secrets Manager
        |---- calls ExchangeRate-API
        |---- reads/writes DynamoDB history
        |---- publishes threshold alerts to SNS
        v
CloudWatch Logs + Lambda error alarm
```

The default pairs are EUR/INR, USD/INR, and GBP/INR. The Lambda stores one item per pair per ExchangeRate-API observation date, calculates daily percentage movement, a rolling seven-sample average, the difference from that average, and a seven-sample change when enough history exists.

## Important Learner Lab design decision

This project does **not** create or attach IAM roles or policies. It looks up the existing AWS Academy `LabRole` and assigns that role to Lambda. This avoids the common Learner Lab `iam:CreateRole` denial.

The existing `LabRole` still needs permission to:

- read the created secret,
- query, get, put, and update the DynamoDB table,
- publish to the SNS topic,
- write Lambda logs.

The normal AWS Academy `LabRole` usually supplies broad lab permissions. If your lab has a more restricted role, Terraform cannot solve that without instructor-side IAM changes.

## Project structure

```text
currency-rate-trend-alert/
|-- versions.tf
|-- providers.tf
|-- variables.tf
|-- locals.tf
|-- data.tf
|-- dynamodb.tf
|-- secrets.tf
|-- sns.tf
|-- lambda.tf
|-- eventbridge.tf
|-- cloudwatch.tf
|-- outputs.tf
|-- terraform.tfvars.example
|-- src/
|   `-- lambda_function.py
|-- tests/
|   `-- test_lambda_function.py
|-- events/
|   `-- manual-test.json
`-- build/
    `-- .gitkeep
```

## Prerequisites

1. An active AWS Academy Learner Lab session.
2. AWS CLI configured with the current temporary lab credentials.
3. Terraform 1.5 or later.
4. A free ExchangeRate-API key.
5. Python 3.12 or later only for local tests. Python dependencies are not needed in the Lambda package because the runtime already includes Boto3 and the code uses Python's standard HTTP library.

## 1. Configure AWS Learner Lab credentials

Start the Learner Lab, open **AWS Details**, and copy the current CLI credentials into:

```text
C:\Users\YOUR_USERNAME\.aws\credentials
```

Verify them in PowerShell:

```powershell
aws sts get-caller-identity
```

Both commands must succeed before Terraform is run. Learner Lab credentials expire, so repeat this step after restarting the lab.

## 2. Configure Terraform values

From the project folder:

```powershell
Copy-Item terraform.tfvars.example terraform.tfvars
notepad terraform.tfvars
```

At minimum, decide whether to add your email:

```hcl
alert_email = "your.email@example.com"
```

Keep `aws_region = "us-east-1"` and `lab_role_name = "LabRole"` unless your lab explicitly shows a different role.

## 3. Initialize and deploy

```powershell
terraform init
terraform fmt -recursive
terraform validate
terraform plan -out tfplan
terraform apply tfplan
```

Terraform automatically packages `src/lambda_function.py` into `build/lambda_function.zip` through the Archive provider.

## 4. Add the ExchangeRate-API key securely

The secret resource is created by Terraform, but the key value is deliberately added outside Terraform so it never appears in `terraform.tfstate`.

```powershell
$secretArn = terraform output -raw exchange_rate_secret_arn
aws secretsmanager put-secret-value `
  --secret-id $secretArn `
  --secret-string '{"api_key":"YOUR_REAL_API_KEY"}' `
  --region us-east-1
```

Check only the secret metadata, not the value:

```powershell
aws secretsmanager describe-secret --secret-id $secretArn --region us-east-1
```

## 5. Confirm the SNS email subscription

If `alert_email` was set, open the AWS SNS confirmation email and click **Confirm subscription**. Until that is done, exchange-rate and Lambda-error emails are not delivered.

You can see the subscription state with:

```powershell
$topicArn = terraform output -raw sns_topic_arn
aws sns list-subscriptions-by-topic --topic-arn $topicArn --region us-east-1
```

## 6. Run the first manual Lambda test

```powershell
$functionName = terraform output -raw lambda_function_name
aws lambda invoke `
  --function-name $functionName `
  --cli-binary-format raw-in-base64-out `
  --payload file://events/manual-test.json `
  response.json
Get-Content response.json
```

Expected first-run behavior:

- three currency pairs are stored,
- `daily_change_pct` is empty because there is no earlier record,
- `trend_sample_count` is 1,
- no movement alert is sent,
- the invocation returns status code 200.

## 7. Verify each AWS component

### Lambda logs

```powershell
$logGroup = terraform output -raw cloudwatch_log_group
aws logs tail $logGroup --since 30m --region us-east-1
```

### DynamoDB records

```powershell
$tableName = terraform output -raw dynamodb_table_name
aws dynamodb scan --table-name $tableName --region us-east-1
```

In the AWS Console, go to **DynamoDB > Tables > your table > Explore table items**. You should see one item for each configured pair.

### EventBridge schedule

```powershell
$ruleName = terraform output -raw eventbridge_rule_name
aws events describe-rule --name $ruleName --region us-east-1
aws events list-targets-by-rule --rule $ruleName --region us-east-1
```

The default schedule is `cron(0 7 * * ? *)`, which means every day at 07:00 UTC.

### SNS topic

```powershell
aws sns get-topic-attributes --topic-arn $topicArn --region us-east-1
```

### CloudWatch error alarm

In the console, go to **CloudWatch > Alarms > All alarms** and open the alarm ending in `lambda-errors`.

## 8. Test the alert path without waiting for a real 1% market move

Temporarily lower the threshold in `terraform.tfvars`:

```hcl
alert_threshold_percent = 0.0001
```

A daily percentage change still requires a previous-date item. For an immediate demonstration, add a controlled previous-day record for one pair before invoking Lambda again.

PowerShell example:

```powershell
$tableName = terraform output -raw dynamodb_table_name
$yesterday = (Get-Date).ToUniversalTime().AddDays(-1).ToString("yyyy-MM-dd")
$expires = [int][double]::Parse((Get-Date -UFormat %s)) + (400 * 86400)

aws dynamodb put-item `
  --table-name $tableName `
  --region us-east-1 `
  --item "{\"pair\":{\"S\":\"EUR/INR\"},\"observed_at\":{\"S\":\"$yesterday\"},\"rate\":{\"N\":\"1\"},\"expires_at\":{\"N\":\"$expires\"}}"
```

Then apply the lower threshold and invoke Lambda:

```powershell
terraform apply -auto-approve
aws lambda invoke `
  --function-name $functionName `
  --cli-binary-format raw-in-base64-out `
  --payload file://events/manual-test.json `
  response.json
Get-Content response.json
```

This should create an obvious EUR/INR movement and publish an SNS message. After the screenshot/demo, restore the real threshold:

```hcl
alert_threshold_percent = 1.0
```

Then run `terraform apply -auto-approve` again. Delete the artificial record from DynamoDB if you do not want it in the final dataset.

## 9. Run local unit tests

Create and activate a virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
pytest -q
```

## 10. Useful screenshots for the final submission

Capture these after a successful invocation:

1. Terraform `apply` output and `terraform output`.
2. Lambda function configuration showing Python runtime and `LabRole`.
3. CloudWatch log stream showing all three pairs processed.
4. DynamoDB **Explore table items** showing the stored fields.
5. EventBridge rule and Lambda target.
6. SNS topic plus confirmed subscription.
7. CloudWatch Lambda error alarm.
8. An SNS alert email after the controlled alert test.

Do not include the API key or the secret value in screenshots.

## 11. Update application code

After editing `src/lambda_function.py`, run:

```powershell
terraform fmt -recursive
terraform plan
terraform apply
```

The Archive provider changes the ZIP checksum, so Terraform updates the Lambda code automatically.

## 12. Destroy resources when the capstone is finished

```powershell
terraform destroy
```

Then confirm that the DynamoDB table, Lambda function, EventBridge rule, SNS topic, secret, log group, and alarm are gone. The secret uses a zero-day recovery window so Terraform can remove it immediately in the temporary Learner Lab.

## Troubleshooting

### `NoSuchEntity: Role with name LabRole cannot be found`

1. Confirm that the AWS Academy Learner Lab is started.
2. Refresh the temporary AWS CLI credentials from **AWS Details**.
3. Verify the active credentials:

```powershell
aws sts get-caller-identity

Use the exact existing lab role name in `terraform.tfvars`. Do not add an `aws_iam_role` resource because Learner Lab commonly blocks role creation.

### `ExpiredToken` or `InvalidClientTokenId`

Restart the Learner Lab and replace the local AWS credentials with the new temporary values.

### Lambda reports `AccessDeniedException`

Read the denied action in CloudWatch logs. The required categories are Secrets Manager read, DynamoDB read/write, SNS publish, and CloudWatch Logs. This project intentionally uses the existing `LabRole`; only an instructor or the lab configuration can expand that role if it is restricted.

### Lambda reports `invalid-key`, `inactive-account`, or `quota-reached`

Open the ExchangeRate-API dashboard and verify that the account is confirmed and the key is active. Re-run the `put-secret-value` command after correcting the key.

### No SNS email arrives

Check that the subscription is `Confirmed`, inspect the spam folder, and verify that the threshold was actually crossed. The first real invocation has no previous daily record, so it cannot calculate a daily movement.

### EventBridge does not run at local 07:00

The default cron is 07:00 **UTC**, not German local time. Change `schedule_expression` if your demonstration requires a different UTC time.
