# Development Scripts

Cost-efficient development workflow scripts for the News Analytics API.

## Quick Start

```bash
# Start a development session
./scripts/startup.sh

# Check status and costs
./scripts/status.sh

# End your work day (saves money)
./scripts/shutdown.sh
```

## Scripts Overview

### 🚀 `startup.sh`
**Resume development work**

- Rebuilds Lambda functions, API Gateway, SQS queues
- Preserves existing secrets (no 7-day recovery window issue)
- Rebuilds and pushes Docker image
- Tests deployment with health check
- Creates `dev-env.sh` with environment variables

**Time**: 5-10 minutes  
**Use when**: Starting a new work session

```bash
./scripts/startup.sh
source dev-env.sh  # Load API URLs
```

### 🛑 `shutdown.sh`
**Clean up to minimize costs**

- Destroys Lambda, API Gateway, SQS queues
- Empties S3 buckets (keeps bucket structure)
- Deletes CloudWatch logs
- **Preserves**: Secrets Manager, ECR repository, S3 buckets, Athena tables
- Avoids secret deletion 7-day recovery window

**Cost while shut down**: ~$1.20/month (secrets only)  
**Use when**: Done for the day/week

```bash
./scripts/shutdown.sh
```

### 📊 `status.sh`
**Check deployment status and costs**

Shows:
- Lambda function status
- API Gateway URL
- S3 storage usage
- SQS queue statistics
- Lambda invocations today
- Estimated monthly costs
- EventBridge status

```bash
./scripts/status.sh
```

## Typical Workflow

### Daily Development

```bash
# Morning: Start infrastructure
./scripts/startup.sh

# Load environment variables
source dev-env.sh

# Do your development work
curl $API_HEALTH_CHECK
curl -X POST $API_INGEST -H 'Content-Type: application/json' \
  -d '{"query":"test","limit":2,"language":"en"}'

# Monitor logs
aws logs tail /aws/lambda/news-analytics-dev-worker --follow

# Evening: Shut down
./scripts/shutdown.sh
```

### Weekend/Break

```bash
# Before leaving
./scripts/shutdown.sh

# Cost while paused: ~$1.20/month
# No need to terraform destroy completely
```

### Checking Status

```bash
# Quick status check
./scripts/status.sh

# See what's running and current costs
```

## Cost Comparison

| Scenario | Monthly Cost |
|----------|-------------|
| Fully running (no EventBridge) | ~$2-3 |
| Shut down (preserved secrets) | ~$1.20 |
| Completely destroyed | $0 (but 7-day secret recovery) |
| Running with EventBridge | ~$8-12 |

## What Gets Preserved?

When you run `shutdown.sh`, these resources remain (by design):

- ✅ **Secrets Manager** ($1.20/month) - Avoids 7-day recovery window
- ✅ **ECR Repository** ($0) - Avoids re-pushing Docker images
- ✅ **S3 Buckets** ($0 when empty) - Structure preserved
- ✅ **Athena Database/Tables** ($0) - Metadata only
- ✅ **IAM Roles** ($0) - No cost

## Troubleshooting

### Startup fails with "secret not found"

Secrets were force-deleted. Recreate them:

```bash
cd infra
terraform apply -target=aws_secretsmanager_secret.news_api_key
terraform apply -target=aws_secretsmanager_secret_version.news_api_key
# Repeat for other secrets
```

### Docker image fails to build

Check Docker is running:

```bash
docker info
```

Start Docker Desktop or: `sudo systemctl start docker`

### Lambda still has old code

Force update:

```bash
cd infra
terraform taint null_resource.docker_build_push
terraform apply
```

### Want to completely destroy everything

```bash
cd infra

# Force delete secrets (no recovery)
aws secretsmanager delete-secret --secret-id "news-analytics/dev/news-api-key" --force-delete-without-recovery
aws secretsmanager delete-secret --secret-id "news-analytics/dev/upstash-redis-url" --force-delete-without-recovery
aws secretsmanager delete-secret --secret-id "news-analytics/dev/upstash-redis-token" --force-delete-without-recovery

# Destroy everything
terraform destroy -auto-approve
```

## Environment Variables

After `startup.sh`, source the environment file:

```bash
source dev-env.sh
```

Provides:
- `$API_URL` - Base API Gateway URL
- `$API_HEALTH_CHECK` - Health endpoint
- `$API_INGEST` - Ingestion endpoint
- `$API_ANALYTICS` - Analytics endpoint
- `$SQS_QUEUE_URL` - Main SQS queue
- `$SQS_DLQ_URL` - Dead letter queue
- `$S3_BUCKET_RAW` - Raw articles bucket
- `$S3_BUCKET_NORMALIZED` - Normalized articles bucket
- `$S3_BUCKET_ATHENA` - Athena results bucket

## Manual Operations

If you prefer manual control:

```bash
# Deploy everything
cd infra
terraform apply

# Destroy only expensive resources
terraform destroy \
  -target=aws_lambda_function.api_handler \
  -target=aws_lambda_function.worker \
  -target=aws_apigatewayv2_api.http_api

# Destroy everything
terraform destroy
```

## Best Practices

1. **Always use `shutdown.sh`** when done for the day
2. **Check `status.sh`** before leaving to confirm shutdown
3. **Never enable EventBridge** until production-ready
4. **Test with small limits** (2-5 articles) during development
5. **Monitor NewsAPI quota** at https://newsapi.org/account
6. **Set up billing alerts** for peace of mind

## Questions?

See main README.md or check the scripts source code for details.
