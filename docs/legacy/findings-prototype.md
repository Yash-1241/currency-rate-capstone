\# Architecture Review Findings



1\. \*\*Accept:\*\* The Lambda timeout should be increased because the function depends on an external API and may need more than the default execution time.



2\. \*\*Push back:\*\* The API Gateway endpoint is public by design because Phase 2 requires a public front door; the ExchangeRate-API key remains protected in Secrets Manager.



3\. \*\*Push back:\*\* Amazon RDS is unnecessary because the application stores predictable currency-pair and timestamp records that fit DynamoDB's key-based access pattern.



4\. \*\*Accept:\*\* DynamoDB data retention is currently unlimited; TTL could be added in a later version to remove old records and control storage growth.

