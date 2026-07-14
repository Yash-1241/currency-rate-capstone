\# Currency Exchange Rate Trend Alert Service



\## Architecture



```mermaid
flowchart LR
    A[User or PowerShell] -->|GET rates| B[API Gateway HTTP API]
    B --> C[AWS Lambda]
    C --> D[AWS Secrets Manager]
    D -->|API key| C
    C --> E[ExchangeRate API]
    E -->|EUR exchange rates| C
    C -->|Selected currency rates| F[Amazon DynamoDB]
    C --> G[Amazon CloudWatch Logs]
```



\## Architecture Decisions



\### 1. API Gateway HTTP API over Lambda Function URL



\*\*Chosen:\*\* API Gateway HTTP API.



\*\*Rejected:\*\* Lambda Function URL with AWS IAM authorization.



\*\*Reason:\*\* API Gateway provides a clear HTTP route and is easier to test and demonstrate. An IAM-authorized Function URL would require every request to be SigV4-signed.



\*\*Pillar:\*\* Operational Excellence.



\### 2. DynamoDB over Amazon RDS



\*\*Chosen:\*\* Amazon DynamoDB.



\*\*Rejected:\*\* Amazon RDS.



\*\*Reason:\*\* The application stores simple currency-pair records identified by currency pair and timestamp. RDS would introduce unnecessary database administration and idle cost.



\*\*Pillar:\*\* Cost Optimization.



\### 3. Secrets Manager over hard-coded credentials



\*\*Chosen:\*\* AWS Secrets Manager.



\*\*Rejected:\*\* Storing the ExchangeRate-API key in Python, Terraform or environment-variable literals.



\*\*Reason:\*\* Secrets Manager prevents the API key from appearing in source code, submissions, screenshots and version control.



\*\*Pillar:\*\* Security.

