# Deployment Checklist

Use this as the exact order of work in AWS Academy Learner Lab.

- [ ] Start Learner Lab and copy fresh AWS CLI credentials.
- [ ] Run `aws sts get-caller-identity`.
- [ ] Copy `terraform.tfvars.example` to `terraform.tfvars`.
- [ ] Optionally add an SNS email address.
- [ ] Run `terraform init`.
- [ ] Run `terraform fmt -recursive`.
- [ ] Run `terraform validate`.
- [ ] Run `terraform plan -out tfplan`.
- [ ] Run `terraform apply tfplan`.
- [ ] Put the ExchangeRate-API key into the created secret using AWS CLI.
- [ ] Confirm the SNS email subscription.
- [ ] Invoke Lambda manually.
- [ ] Check CloudWatch logs.
- [ ] Check DynamoDB items.
- [ ] Check EventBridge rule and target.
- [ ] Check SNS topic/subscription.
- [ ] Check CloudWatch error alarm.
- [ ] Perform the controlled alert test.
- [ ] Restore the threshold to the real value.
- [ ] Capture final screenshots.
- [ ] Commit code to GitHub without `terraform.tfvars`, state files, or API keys.
- [ ] Run `terraform destroy` when the project no longer needs to remain deployed.
