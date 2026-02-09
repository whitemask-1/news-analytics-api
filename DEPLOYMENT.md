# 🚀 AWS Deployment Guide

This guide walks you through deploying the News Analytics API to AWS Lambda.

---

## ✅ What You're Deploying

When you run `terraform apply`, you get:

- **2 Lambda Functions** (API + Worker) with auto-scaling
- **SQS Queue** for async processing
- **2 S3 Buckets** (raw + normalized data)
- **Athena Tables** for SQL analytics
- **ECR Repository** for Docker images
- **EventBridge Schedule** (fetch news every 6 hours)
- **CloudWatch Logs** for monitoring

**Estimated Cost**: $5-10/month (low traffic)

---

## 📋 Prerequisites (One-Time Setup)

### 1. **AWS CLI Configured**
```bash
# Install AWS CLI (if not already)
brew install awscli  # macOS

# Configure with your credentials
aws configure
# Enter: Access Key ID, Secret Access Key, Region (us-east-1), Output format (json)

# Verify
aws sts get-caller-identity
```

### 2. **Upstash Redis Account** (Free Tier)
```bash
# Sign up at https://upstash.com/
# Create a Redis database
# Copy:
#   - REST URL (e.g., https://abc-xyz.upstash.io)
#   - REST Token (starts with Bearer ...)
```

### 3. **NewsAPI Key** (Already have: 85141997387f43c2...)
Already in your `.env` - you'll add this to AWS Secrets Manager.

---

## 🏗️ Deployment Steps

### Step 1: Navigate to Infrastructure Directory
```bash
cd /Users/p/Documents/Code/terraform/news-analytics-api/infra
```

### Step 2: Initialize Terraform
```bash
terraform init
```
Downloads AWS provider (~2-3 minutes first time).

### Step 3: Create AWS Secrets
```bash
# NewsAPI Key
aws secretsmanager create-secret \
  --name news-analytics/dev/news-api-key \
  --secret-string "85141997387f43c2aba8b8f9f26fbefa" \
  --region us-east-1

# Upstash Redis URL (replace with yours)
aws secretsmanager create-secret \
  --name news-analytics/dev/redis-url \
  --secret-string "https://YOUR-REDIS.upstash.io" \
  --region us-east-1

# Upstash Redis Token (replace with yours)
aws secretsmanager create-secret \
  --name news-analytics/dev/redis-token \
  --secret-string "YOUR_REDIS_TOKEN_HERE" \
  --region us-east-1
```

### Step 4: Review Plan
```bash
terraform plan
```
Shows what will be created. Review for any issues.

### Step 5: Deploy! 🚀
```bash
terraform apply
```
Type `yes` when prompted. Takes ~5-10 minutes.

**What happens:**
1. Builds Docker image from main `Dockerfile`
2. Pushes to ECR
3. Creates all AWS resources
4. Deploys Lambda functions
5. Outputs: API Gateway URL, S3 bucket names, etc.

---

## 🧪 Test Deployment

Once deployed, Terraform outputs your API URL:

```bash
# Health check
curl https://YOUR-API-ID.execute-api.us-east-1.amazonaws.com/health

# Should return:
# {"status":"ok","version":"1.0.0","service":"news-analytics-api"}

# Trigger ingestion
curl -X POST https://YOUR-API-ID.execute-api.us-east-1.amazonaws.com/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "query": "artificial intelligence",
    "limit": 20,
    "language": "en"
  }'

# Should return 202 Accepted with message ID
```

### Check Worker Processing

```bash
# View Lambda logs (Worker)
aws logs tail /aws/lambda/news-analytics-dev-worker --follow

# Check S3 for articles
aws s3 ls s3://news-analytics-dev-raw/raw/ --recursive

# Query with Athena (after a few ingestions)
aws athena start-query-execution \
  --query-string "SELECT COUNT(*) FROM normalized_articles" \
  --result-configuration "OutputLocation=s3://YOUR-ATHENA-BUCKET/"
```

---

## 🔧 Environment Variables

Lambda automatically gets these from Terraform:

| Variable | Source | Purpose |
|----------|--------|---------|
| `ENVIRONMENT` | Terraform var | `production` (enables SQS) |
| `NEWS_API_KEY` | Secrets Manager | Fetch articles |
| `UPSTASH_REDIS_URL` | Secrets Manager | Deduplication |
| `UPSTASH_REDIS_TOKEN` | Secrets Manager | Redis auth |
| `S3_BUCKET_RAW` | Terraform output | Store raw JSON |
| `S3_BUCKET_NORMALIZED` | Terraform output | Store Parquet |
| `SQS_QUEUE_URL` | Terraform output | Async processing |
| `AWS_REGION` | Lambda default | us-east-1 |

**No manual configuration needed** - Terraform handles everything!

---

## 📊 Monitoring

### CloudWatch Dashboards
```bash
# View all logs
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/news-analytics

# Stream API Lambda logs
aws logs tail /aws/lambda/news-analytics-dev-api --follow

# Stream Worker Lambda logs
aws logs tail /aws/lambda/news-analytics-dev-worker --follow
```

### Key Metrics to Watch
- **Lambda Errors**: Should be 0
- **SQS DLQ Messages**: Should be 0 (dead letter queue)
- **Deduplication Rate**: ~30-50% after first day
- **Processing Time**: Should be 10-30 seconds per batch

---

## 💰 Cost Estimate

**Free Tier (First 12 months):**
- Lambda: 1M requests + 400K GB-seconds free
- S3: 5GB storage free
- Your usage: ~100K requests/month = **$0**

**After Free Tier:**
- Lambda API: ~$0.20/month (1K requests/day)
- Lambda Worker: ~$2/month (4 runs/day × 30 days)
- S3: ~$1/month (50GB storage)
- Athena: ~$1/month (10 queries)
- **Total: ~$5-10/month**

---

## 🔄 Updating Code

After making changes locally:

```bash
cd infra

# Terraform automatically:
# 1. Rebuilds Docker image
# 2. Pushes to ECR
# 3. Updates Lambda functions
terraform apply
```

Lambda picks up changes in ~30 seconds.

---

## 🧹 Cleanup (Destroy Everything)

To avoid charges:

```bash
cd infra
terraform destroy
```

Type `yes` to confirm. Removes all resources (~5 minutes).

**Note:** S3 buckets with data may need manual deletion:
```bash
aws s3 rm s3://news-analytics-dev-raw --recursive
aws s3 rm s3://news-analytics-dev-normalized --recursive
terraform destroy  # Run again
```

---

## 🐛 Troubleshooting

### Issue: `terraform init` fails
**Solution:** Ensure AWS CLI is configured (`aws configure`)

### Issue: Secret not found error
**Solution:** Create secrets in Step 3 before deploying

### Issue: Lambda timeout
**Solution:** Increase timeout in `infra/lambda.tf` (default: 60s)

### Issue: No articles fetched
**Solution:** Check NewsAPI key and quota (100 requests/day free tier)

### Issue: Redis connection error
**Solution:** Verify Upstash credentials in Secrets Manager

---

## ✅ Success Criteria

You'll know deployment worked when:

1. ✅ `terraform apply` completes without errors
2. ✅ Health endpoint returns 200 OK
3. ✅ POST to `/ingest` returns 202 Accepted
4. ✅ Worker Lambda logs show "ingestion_complete"
5. ✅ S3 buckets contain JSON and Parquet files
6. ✅ Athena can query `normalized_articles` table

---

## 📚 Next Steps

After successful deployment:

1. **Set up monitoring** - CloudWatch alarms for errors
2. **Add API authentication** - API Gateway API keys
3. **Enable CORS** - For frontend access
4. **Add more sources** - Guardian API, etc.
5. **Build dashboards** - Grafana, QuickSight

---

## 🎉 Congratulations!

You've built and deployed a production serverless data pipeline!

- Event-driven architecture ✅
- Auto-scaling to 0 when idle ✅
- Pay only for what you use ✅
- Infrastructure as code ✅
- Production-ready monitoring ✅
