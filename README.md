# News Analytics API 🚀

> **Serverless news article ingestion and analytics platform powered by AWS Lambda**

A production-ready, event-driven system that fetches news articles, deduplicates them using Redis, stores them in S3, and provides SQL-based analytics through Athena. Built with FastAPI, deployed as Lambda containers, managed with Terraform.

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Architecture](#-architecture)
- [Features](#-features)
- [Migration Story](#-migration-story-ecs--lambda)
- [Quick Start](#-quick-start)
- [API Documentation](#-api-documentation)
- [Infrastructure](#-infrastructure)
- [Cost Analysis](#-cost-analysis)
- [Deployment](#-deployment)
- [Development](#-development)
- [Monitoring](#-monitoring)

---

## 🎯 Overview

The News Analytics API is a serverless platform that:

1. **Ingests** news articles from NewsAPI on a schedule (every 6 hours)
2. **Deduplicates** articles using Redis (14-day TTL for hashes)
3. **Normalizes** article data to a canonical schema
4. **Stores** articles in S3 (raw JSON + normalized Parquet)
5. **Analyzes** data using Athena (SQL queries on S3 data lake)

### Why This Project?

- ✅ **Learn serverless architecture** - Lambda, SQS, API Gateway, EventBridge
- ✅ **Practice data engineering** - ETL pipelines, Parquet, partitioning
- ✅ **Master infrastructure as code** - Terraform, AWS best practices
- ✅ **Implement deduplication** - Redis caching, distributed systems
- ✅ **Build analytics** - Athena, SQL, data visualization

---

## 🏗️ Architecture

### Current Architecture (Lambda + SQS + S3 + Athena)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          EVENT-DRIVEN PIPELINE                           │
└─────────────────────────────────────────────────────────────────────────┘

 Client/EventBridge
        │
        ▼
  API Gateway ──────────────┐
        │                   │
        ▼                   ▼
   API Lambda          (HTTP Responses)
        │
        │ Publish
        ▼
    SQS Queue ─────────────┐
        │                  │
        │ Trigger          │ DLQ (after 3 failures)
        ▼                  ▼
  Worker Lambda      Dead Letter Queue
        │                  │
        │                  └──▶ CloudWatch Alarm
        ├─ Fetch NewsAPI
        ├─ Check Redis (dedup) ──▶ Upstash Redis
        ├─ Normalize                (14-day TTL)
        ├─ Store S3 ──────────────▶ S3 Buckets
        └─ Mark Redis               - Raw (7-day lifecycle)
                                    - Normalized (Parquet)
                │
                ▼
            Athena ────────────────▶ Analytics API
            (SQL Queries)            (Trends, Counts, etc.)
```

### Data Flow

```
1. EventBridge (every 6 hours) OR Client (POST /ingest)
   └─▶ Message: {"query": "AI", "limit": 100, "language": "en"}

2. API Lambda validates and publishes to SQS
   └─▶ Returns 202 Accepted immediately

3. SQS triggers Worker Lambda
   ├─▶ Fetch 100 articles from NewsAPI
   ├─▶ Calculate SHA256 hashes for each article
   ├─▶ Batch-check Redis: 35 exist (duplicates), 65 new
   ├─▶ Skip 35 duplicates, process 65 new articles
   ├─▶ Normalize and validate new articles
   ├─▶ Store raw (all 100) + normalized (65) to S3
   └─▶ Mark 65 new hashes in Redis (14-day TTL)

4. Athena queries S3 Parquet files
   └─▶ Partition pruning: Only scan relevant dates/sources
```

---

## ✨ Features

### Core Functionality

- 🔄 **Async Article Ingestion** - SQS-based event-driven processing
- 🎯 **Smart Deduplication** - Redis hash cache with TTL (saves 30-50% storage)
- 📊 **Efficient Storage** - Parquet format (2-3x smaller than JSON)
- 🔍 **SQL Analytics** - Athena queries on partitioned data
- ⏱️ **Scheduled Fetching** - EventBridge triggers every 6 hours
- 🔐 **Security** - IAM roles, encrypted S3, private subnets

### API Endpoints

| Endpoint | Method | Description | Rate Limit |
|----------|--------|-------------|------------|
| `/` | GET | API information and metadata | N/A |
| `/health` | GET | Health check (for ALB/monitoring) | 60/min |
| `/api/v1/ingest` | POST | Submit article fetch request | 10/min |
| `/api/v1/analytics/counts` | GET | Article counts by source/topic/day | 20/min |
| `/api/v1/analytics/trending` | GET | Trending topics by frequency | 20/min |
| `/api/v1/analytics/sources` | GET | Source distribution statistics | 20/min |
| `/docs` | GET | Swagger UI (interactive docs) | N/A |
| `/redoc` | GET | ReDoc (alternative docs) | N/A |

### Data Pipeline

```
NewsAPI Response → Validation → Deduplication → Normalization → Storage → Analytics
     (JSON)          (Pydantic)    (Redis)        (Canonical)     (S3)    (Athena)
```

### Deduplication Logic

```python
# Article hash calculation (consistent across runs)
hash_input = f"{article_url}:{article_title}"
article_hash = sha256(hash_input).hexdigest()[:16]  # 16 chars

# Deduplication flow
hashes = [calculate_hash(a) for a in articles]
exists = await redis.batch_check_exists(hashes)  # Single Redis call

new_articles = [a for a, exists in zip(articles, exists) if not exists]
# Result: 100 fetched → 65 new → 35 duplicates skipped

# Mark processed (14-day TTL)
await redis.batch_mark_processed(new_hashes)
```

---

## 🔄 Migration Story: ECS → Lambda

### Why We Migrated

**Original Architecture: ECS Fargate**
- ✅ Always-on container (fast responses)
- ✅ Simple Docker deployment
- ❌ **$27/month fixed cost** (even with zero traffic)
- ❌ Manual scaling configuration
- ❌ Cold start not an issue (always warm)

**New Architecture: Lambda Containers**
- ✅ **$7-15/month** (45-75% cost reduction)
- ✅ Auto-scales 0-1000+ concurrent (no config)
- ✅ Pay-per-use (no idle costs)
- ✅ Managed infrastructure (no EC2/ECS)
- ❌ Cold starts (~1-2s for first request)
- ⚠️ 15-minute max execution time

### Key Tradeoffs Considered

| Decision | Options | Choice | Rationale |
|----------|---------|--------|-----------|
| **Processing Model** | Sync vs Async | **Async (SQS)** | Better scalability, handles NewsAPI rate limits, decouples API from processing |
| **Redis Provider** | ElastiCache vs Upstash | **Upstash** | No VPC complexity, REST API (simpler), serverless pricing, no cold start penalty |
| **Hot Storage** | Redis data cache vs Dedup only | **Dedup only** | Simpler, sufficient for use case, Athena for analytics instead |
| **Dedup TTL** | 7d vs 14d vs 30d | **14 days** | Balances memory (~8 MB for 500K articles) vs duplicate prevention for news relevance |
| **Ingestion Frequency** | Hourly vs 6-hour vs Daily | **Every 6 hours** | 4 runs/day fits 100 req/day limit, balances freshness vs quota |
| **Error Handling** | Retry vs DLQ | **3 retries → DLQ + alarm** | Resilient to transient errors, alerts on persistent failures |

### Migration Benefits

```
Cost Savings:
  ECS Fargate: $27/month (fixed)
  Lambda:      $7-15/month (usage-based)
  Savings:     $12-20/month (45-75%)
  
Scalability:
  ECS: Manual scaling (1-4 tasks)
  Lambda: Automatic (0-1000+ concurrent)
  
Operational:
  ECS: Manage cluster, tasks, ALB
  Lambda: Fully managed, zero infrastructure
```

### What Changed in Code

1. **Dockerfile**: `python:3.11-slim` → `public.ecr.aws/lambda/python:3.11`
2. **Server**: Removed `uvicorn` → Added `mangum` (FastAPI → Lambda adapter)
3. **Split handlers**: `main.py` → `lambda_api_handler.py` + `lambda_worker_handler.py`
4. **Rate limiting**: `slowapi` → API Gateway native (simpler)
5. **Quota tracking**: In-memory → DynamoDB planned (currently disabled)
6. **Infrastructure**: `ecs.tf` → `lambda.tf` + `sqs.tf` + API Gateway

---

## 🚀 Quick Start

### Prerequisites

```bash
# Required
- AWS Account with CLI configured
- Terraform >= 1.2.0
- Docker Desktop
- Python 3.11+
- NewsAPI Key (free at newsapi.org/register)
- Upstash Redis Account (free at upstash.com)

# Optional
- Make (for convenience commands)
- AWS CDK (alternative to Terraform)
```

### 1. Clone and Setup

```bash
# Clone repository
git clone <your-repo-url>
cd news-analytics-api

# Create environment file
cp .env.example .env

# Edit .env with your credentials
nano .env
```

### 2. Configure Environment

```bash
# .env file
NEWS_API_KEY=your_newsapi_key_here
UPSTASH_REDIS_URL=https://your-db.upstash.io
UPSTASH_REDIS_TOKEN=your_token_here
AWS_REGION_CUSTOM=us-east-1
ENVIRONMENT=dev
LOG_LEVEL=INFO
```

### 3. Deploy Infrastructure

```bash
cd infra

# Initialize Terraform
terraform init

# Review plan
terraform plan \
  -var="news_api_key=YOUR_KEY" \
  -var="upstash_redis_url=YOUR_URL" \
  -var="upstash_redis_token=YOUR_TOKEN"

# Deploy
terraform apply -auto-approve

# Save outputs
terraform output > ../outputs.txt
```

### 4. Build and Push Docker Image

```bash
# Get AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=us-east-1
ECR_REPO=news-analytics-dev

# Authenticate Docker with ECR
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin \
  $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Build Lambda container image
docker build -t $ECR_REPO:latest .

# Tag for ECR
docker tag $ECR_REPO:latest \
  $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:latest

# Push to ECR
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:latest

# Lambda will automatically use new image on next invocation
```

### 5. Test the API

```bash
# Get API Gateway URL from Terraform outputs
API_URL=$(terraform output -raw api_gateway_url)

# Test health endpoint
curl $API_URL/health

# Test ingest endpoint
curl -X POST $API_URL/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "query": "artificial intelligence",
    "limit": 50,
    "language": "en"
  }'

# Check SQS queue (should have 1 message)
aws sqs get-queue-attributes \
  --queue-url $(terraform output -raw sqs_queue_url) \
  --attribute-names ApproximateNumberOfMessages

# Wait 30-60 seconds for processing, then check analytics
curl "$API_URL/api/v1/analytics/counts?group_by=source"
```

---

## 📚 API Documentation

### Ingest Articles

**Endpoint:** `POST /api/v1/ingest`

**Description:** Submit async request to fetch and process articles

**Request Body:**
```json
{
  "query": "climate change OR global warming",
  "limit": 100,
  "language": "en"
}
```

**Response (202 Accepted):**
```json
{
  "status": "accepted",
  "message": "Ingestion request queued for processing",
  "request_id": "abc123-def456-...",
  "query": "climate change OR global warming",
  "estimated_processing_time_seconds": 30
}
```

**Processing Flow:**
1. API validates request
2. Message published to SQS
3. Worker Lambda triggered
4. Fetch from NewsAPI
5. Check Redis for duplicates
6. Normalize new articles
7. Store to S3 (raw + Parquet)
8. Mark hashes in Redis

### Get Article Counts

**Endpoint:** `GET /api/v1/analytics/counts`

**Query Parameters:**
- `group_by`: `source` | `source_name` | `topic` | `day` (default: `source`)
- `start_date`: YYYY-MM-DD (default: 7 days ago)
- `end_date`: YYYY-MM-DD (default: today)
- `days`: Alternative to start_date (e.g., `days=30`)

**Example:**
```bash
# Count by source for last 7 days
curl "$API_URL/api/v1/analytics/counts?group_by=source"

# Daily counts for last 30 days
curl "$API_URL/api/v1/analytics/counts?group_by=day&days=30"

# Topics in February
curl "$API_URL/api/v1/analytics/counts?group_by=topic&start_date=2026-02-01&end_date=2026-02-28"
```

**Response:**
```json
{
  "status": "success",
  "start_date": "2026-02-01",
  "end_date": "2026-02-06",
  "group_by": "source",
  "results": [
    {"source": "newsapi", "count": 1250},
    {"source": "guardian", "count": 85}
  ],
  "total_results": 2,
  "execution_time_ms": 850
}
```

### Get Trending Topics

**Endpoint:** `GET /api/v1/analytics/trending`

**Query Parameters:**
- `days`: 1-90 (default: 7)
- `limit`: 1-100 (default: 20)

**Example:**
```bash
curl "$API_URL/api/v1/analytics/trending?days=3&limit=10"
```

**Response:**
```json
{
  "status": "success",
  "days": 3,
  "results": [
    {"topic": "artificial intelligence", "count": 342, "sources": 12},
    {"topic": "climate change", "count": 187, "sources": 8}
  ],
  "total_results": 10,
  "execution_time_ms": 1200
}
```

---

## 🏗️ Infrastructure

### AWS Resources Created

| Resource | Purpose | Cost Driver |
|----------|---------|-------------|
| **Lambda (API)** | Handle HTTP requests | Invocations + compute time |
| **Lambda (Worker)** | Process article ingestion | Invocations + compute time |
| **API Gateway** | HTTP endpoint | Requests |
| **SQS Queue** | Async message queue | Requests (first 1M free) |
| **S3 (Raw)** | Temporary JSON storage | Storage (7-day lifecycle) |
| **S3 (Normalized)** | Parquet data lake | Storage + transitions |
| **S3 (Athena Results)** | Query results | Storage (30-day lifecycle) |
| **Athena** | SQL queries | Data scanned (per TB) |
| **Glue Catalog** | Table metadata | Free (minimal) |
| **EventBridge** | Scheduled ingestion | Free |
| **CloudWatch** | Logs and alarms | Storage + API calls |
| **ECR** | Container registry | Storage (5 images kept) |

### Terraform Modules

```
infra/
├── main.tf              # Main configuration (backend, providers)
├── variables.tf         # Input variables
├── outputs.tf           # Output values
├── lambda.tf           # Lambda functions, API Gateway, SQS
├── s3.tf               # S3 buckets with lifecycle policies
├── athena.tf           # Glue database, tables, Athena workgroup
├── iam.tf              # IAM roles and policies
├── ecr.tf              # Container registry
└── terraform.tfvars    # Variable values (gitignored)
```

---

## 💰 Cost Analysis

### Monthly Cost Breakdown

**Free Tier (First 12 months):**
| Service | Free Tier | Estimated Usage | Cost |
|---------|-----------|-----------------|------|
| Lambda Requests | 1M requests | ~5K requests | $0.00 |
| Lambda Compute | 400K GB-seconds | ~50K GB-seconds | $0.00 |
| API Gateway | 1M requests | ~5K requests | $0.00 |
| S3 Storage | 5 GB | ~2 GB | $0.05 |
| Athena Scans | None | ~0.5 GB/month | $0.00 |
| Upstash Redis | 10K commands/day | ~800/day | $0.00 |
| **Total** | | | **$0.05-1/month** |

**After Free Tier:**
| Service | Usage | Cost |
|---------|-------|------|
| Lambda API | 5K invocations × 256MB × 1s | $0.50 |
| Lambda Worker | 120 invocations × 1GB × 30s | $3.00 |
| API Gateway | 5K requests | $0.02 |
| S3 Storage | 10 GB (with transitions) | $2.00 |
| Athena | 1 GB scanned | $0.01 |
| Upstash | Pro plan (optional) | $0-5.00 |
| CloudWatch | Logs | $0.50 |
| **Total** | | **$6-11/month** |

**Comparison with ECS Fargate:**
```
ECS Fargate:  $27/month (fixed)
Lambda:       $6-11/month (usage-based)
Savings:      $16-21/month (60-75%)
```

### Cost Optimization Tips

1. **Partition Pruning** - Always filter by year/month/day in Athena queries
2. **Parquet Format** - 2-3x smaller than JSON, faster scans
3. **S3 Lifecycle** - Auto-delete raw after 7 days, transition to IA/Glacier
4. **Query Result Reuse** - Enable 24-hour caching in Athena
5. **Reserved Concurrency** - Set to 5 for worker (prevents runaway costs)
6. **Lambda Layers** - Extract heavy dependencies (pyarrow) to layers

---

## 🚢 Deployment


### CI/CD Pipeline (Manual)

```bash
# 1. Make code changes
git add .
git commit -m "feat: add new feature"
git push

# 2. Build new Docker image
docker build -t news-analytics-api:latest .

# 3. Push to ECR
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
docker tag news-analytics-api:latest \
  $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/news-analytics-dev:latest
docker push $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/news-analytics-dev:latest

# 4. Lambda automatically pulls new image on next invocation
# Or force update:
aws lambda update-function-code \
  --function-name news-analytics-dev-api \
  --image-uri $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/news-analytics-dev:latest
```

### Infrastructure Updates

```bash
cd infra

# Update Terraform code
nano lambda.tf

# Plan changes
terraform plan

# Apply with approval
terraform apply

# Selective apply (single resource)
terraform apply -target=aws_lambda_function.worker
```

---

## 🛠️ Development

### Project Structure

```
news-analytics-api/
├── app/
│   ├── __init__.py
│   ├── main.py                     # Original FastAPI app (deprecated)
│   ├── lambda_api_handler.py       # Lambda API handler (NEW)
│   ├── lambda_worker_handler.py    # Lambda worker handler (NEW)
│   ├── api/
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── health.py           # Health check endpoint
│   │       ├── ingest.py           # Ingest endpoint (deprecated)
│   │       └── analytics.py        # Analytics endpoints (NEW)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py               # Configuration management
│   │   └── logging.py              # Structured logging setup
│   ├── models/
│   │   ├── __init__.py
│   │   └── article.py              # Article Pydantic model
│   └── services/
│       ├── __init__.py
│       ├── news_fetcher.py         # NewsAPI client
│       ├── normalizer.py           # Article normalization
│       ├── redis_client.py         # Redis deduplication (NEW)
│       ├── s3_client.py            # S3 storage (NEW)
│       └── athena.py               # Athena queries (NEW)
├── infra/
│   ├── main.tf                     # Main Terraform config
│   ├── variables.tf                # Input variables
│   ├── outputs.tf                  # Output values
│   ├── lambda.tf                   # Lambda, API Gateway, SQS (NEW)
│   ├── s3.tf                       # S3 buckets (NEW)
│   ├── athena.tf                   # Glue, Athena (NEW)
│   ├── iam.tf                      # IAM roles
│   ├── ecr.tf                      # Container registry
│   ├── ecs.tf                      # ECS resources (DEPRECATED)
│   └── network.tf                  # VPC, subnets (DEPRECATED for Lambda)
├── .env.example                    # Environment template
├── .gitignore
├── Dockerfile                      # Lambda container image (UPDATED)
├── docker-compose.yml              # Local development (optional)
├── requirements.txt                # Python dependencies (UPDATED)
└── README.md                       # This file

Total Files: ~30
Lines of Code: ~5,000
Languages: Python (85%), HCL/Terraform (15%)
```

### Local Testing

#### Test Lambda Handlers Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export NEWS_API_KEY=your_key
export UPSTASH_REDIS_URL=https://your-db.upstash.io
export UPSTASH_REDIS_TOKEN=your_token
export S3_BUCKET_RAW=test-raw
export S3_BUCKET_NORMALIZED=test-normalized

# Test worker handler
python -c "
import asyncio
from app.lambda_worker_handler import process_single_message

message = {
    'query': 'artificial intelligence',
    'limit': 10,
    'language': 'en'
}

result = asyncio.run(process_single_message(message))
print(result)
"
```

#### Test with Docker

```bash
# Build Lambda container
docker build -t news-analytics-api:lambda .

# Run Lambda Runtime Interface Emulator
docker run -p 9000:8080 \
  -e NEWS_API_KEY=your_key \
  -e UPSTASH_REDIS_URL=your_url \
  -e UPSTASH_REDIS_TOKEN=your_token \
  news-analytics-api:lambda

# Invoke with test event
curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -d '{
    "rawPath": "/health",
    "requestContext": {
      "http": {"method": "GET"}
    }
  }'
```

### Code Style

```bash
# Format code
black app/

# Lint
flake8 app/

# Type checking
mypy app/

# Security check
pip-audit
```

---

## 📊 Monitoring

### CloudWatch Dashboards

**Key Metrics to Monitor:**
- Lambda invocations (API + Worker)
- Lambda errors and throttles
- SQS queue depth (messages waiting)
- DLQ message count (failures)
- Athena query execution time
- S3 bucket size and costs
- API Gateway 4xx/5xx errors

### CloudWatch Logs

```bash
# View Lambda logs
aws logs tail /aws/lambda/news-analytics-dev-api --follow

aws logs tail /aws/lambda/news-analytics-dev-worker --follow

# Filter for errors
aws logs filter-pattern /aws/lambda/news-analytics-dev-worker \
  --filter-pattern "ERROR" \
  --start-time "1h ago"

# Query with Logs Insights
aws logs start-query \
  --log-group-name /aws/lambda/news-analytics-dev-worker \
  --start-time $(date -u -d '1 hour ago' +%s) \
  --end-time $(date +%s) \
  --query-string '
    fields @timestamp, query, fetched, duplicates, new_articles, processing_time_ms
    | filter status = "success"
    | sort @timestamp desc
    | limit 20
  '
```

### Alarms

**DLQ Alarm (Critical):**
- Triggers when messages land in DLQ
- Indicates persistent processing failures
- Action: Investigate worker logs, check NewsAPI status

**Lambda Error Rate (Warning):**
- Triggers on >5% error rate
- Action: Check CloudWatch logs for exception traces

**API Gateway 5xx Rate (Warning):**
- Triggers on >1% server errors
- Action: Check Lambda health and timeouts

---

## 🔧 Troubleshooting

### Common Issues

#### 1. Lambda Cold Starts Too Slow

**Problem:** First API request takes 3-5 seconds

**Solutions:**
```bash
# Option A: Provision concurrency (costs extra)
aws lambda put-provisioned-concurrency-config \
  --function-name news-analytics-dev-api \
  --provisioned-concurrent-executions 1

# Option B: Optimize dependencies (reduce imports)
# Option C: Use Lambda SnapStart (when available for Python)
```

#### 2. All Articles Are Duplicates

**Problem:** Worker logs show 100% duplicates

**Cause:** Redis TTL too long or incorrect hash calculation

**Solution:**
```bash
# Check Redis stats
curl -H "Authorization: Bearer $UPSTASH_REDIS_TOKEN" \
  $UPSTASH_REDIS_URL/dbsize

# Clear Redis (caution: resets deduplication)
curl -X POST \
  -H "Authorization: Bearer $UPSTASH_REDIS_TOKEN" \
  $UPSTASH_REDIS_URL/flushdb

# Or adjust TTL in lambda.tf:
# REDIS_TTL_DAYS = "7"  # Shorter window
```

#### 3. Athena Queries Too Slow/Expensive

**Problem:** Query takes 10+ seconds, scans GB of data

**Solution:**
```sql
-- BAD: Full table scan
SELECT * FROM normalized_articles WHERE topic = 'AI';

-- GOOD: Partition pruning
SELECT * FROM normalized_articles
WHERE year = 2026
  AND month = 2
  AND day BETWEEN 1 AND 7
  AND topic = 'AI';

-- Enable partition projection (already configured in athena.tf)
```

#### 4. NewsAPI Rate Limit Exceeded

**Problem:** `newsapi_quota_exceeded` errors

**Solutions:**
```bash
# Check current usage
# (Currently in-memory, lost on restart - use DynamoDB in future)

# Reduce ingestion frequency
# Edit EventBridge rule in lambda.tf:
# schedule_expression = "cron(0 */12 * * ? *)"  # Every 12 hours

# Reduce articles per fetch
# Edit EventBridge input in lambda.tf:
# "limit": 50  # Instead of 100
```

---

## 🚀 Future Enhancements

### Phase 1: Reliability (Next Sprint)

- [ ] DynamoDB quota tracker (replace in-memory)
- [ ] SNS notifications for DLQ alarms
- [ ] CloudWatch dashboard with key metrics
- [ ] Automated testing (pytest + moto for AWS)
- [ ] GitHub Actions CI/CD pipeline

### Phase 2: Features

- [ ] Multiple NewsAPI queries per run (tech, business, sports)
- [ ] Support for additional news sources (Guardian API, NYTimes)
- [ ] Real-time WebSocket for ingestion status
- [ ] Athena query result caching with Redis
- [ ] Data export (CSV, Excel) from analytics API

### Phase 3: Advanced Analytics

- [ ] Sentiment analysis with ML model
- [ ] Named Entity Recognition (extract people, places)
- [ ] Topic clustering (LDA, K-means)
- [ ] Time-series forecasting (trending predictions)
- [ ] Interactive dashboard (React + Chart.js)

### Phase 4: Enterprise

- [ ] Multi-tenancy (separate data per customer)
- [ ] API authentication (JWT, API keys)
- [ ] Usage-based billing integration
- [ ] SLA monitoring and reporting
- [ ] Data retention policies (GDPR compliance)

---

## 📄 License

MIT License - see LICENSE file for details

---

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📧 Contact

**Project Maintainer:** Your Name

- GitHub: [@yourusername](https://github.com/yourusername)
- LinkedIn: [your-profile](https://linkedin.com/in/your-profile)
- Email: your.email@example.com

---

## 🙏 Acknowledgments

- **NewsAPI** - Free news API for development
- **Upstash** - Serverless Redis platform
- **AWS** - Cloud infrastructure
- **FastAPI** - Modern Python web framework
- **Terraform** - Infrastructure as Code
- **Open Source Community** - For amazing tools and libraries

---

## 📚 Additional Resources

### Documentation
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [AWS Lambda Docs](https://docs.aws.amazon.com/lambda/)
- [Athena Docs](https://docs.aws.amazon.com/athena/)
- [Terraform AWS Provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)

### Related Projects
- [Serverless Framework](https://www.serverless.com/)
- [AWS SAM](https://aws.amazon.com/serverless/sam/)
- [Chalice](https://github.com/aws/chalice)

### Articles
- [ECS vs Lambda Cost Comparison](https://example.com)
- [Parquet File Format Guide](https://parquet.apache.org/)
- [Redis Deduplication Patterns](https://example.com)
- [Athena Partition Projection](https://docs.aws.amazon.com/athena/latest/ug/partition-projection.html)

---

**Built with ❤️ for learning serverless architecture and data engineering**
  news-analytics-api:latest

# Check logs
docker logs -f news-api

# Stop container
docker stop news-api && docker rm news-api
```

### Docker Compose

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

---

## 📡 API Endpoints

### Root
```http
GET /
```
Returns API information and available endpoints.

### Health Check
```http
GET /api/v1/health
```
**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-02-02T12:00:00Z",
  "service": "news-analytics-api",
  "newsapi_quota": {
    "remaining": 95,
    "limit": 100,
    "used": 5
  }
}
```

### Ingest Articles
```http
POST /api/v1/ingest
Content-Type: application/json

{
  "query": "artificial intelligence",
  "limit": 10,
  "language": "en"
}
```

**Request Parameters:**
- `query` (string, required): Search term (1-100 characters)
- `limit` (integer, optional): Max articles to fetch (1-100, default: 10)
- `language` (string, optional): ISO 639-1 language code (default: "en")

**Response:**
```json
{
  "status": "success",
  "count": 10,
  "articles_preview": [
    {
      "source": "techcrunch",
      "title": "AI Breakthrough in Natural Language Processing",
      "description": "Researchers announce new model...",
      "url": "https://techcrunch.com/...",
      "published_at": "2026-02-02T10:30:00Z",
      "topic": "artificial intelligence"
    }
  ],
  "message": "Successfully normalized 10 articles"
}
```

**Rate Limits:**
- 10 requests per minute per IP address
- NewsAPI: 100 requests per day (free tier)

**Error Responses:**
- `422 Unprocessable Entity` - Invalid input parameters
- `429 Too Many Requests` - Rate limit exceeded
- `502 Bad Gateway` - External API error
- `500 Internal Server Error` - Server error

---

## 🧪 Testing

### Run Test Suite

```bash
# Basic functionality tests
python api-testing/test_basic.py

# Rate limiting tests (takes ~60 seconds)
python api-testing/test_rate_limit.py

# Comprehensive test suite (takes ~3 minutes)
python api-testing/testing_suite.py
```

### Manual Testing with cURL

```bash
# Health check
curl http://localhost:8000/api/v1/health

# Fetch single article
curl -X POST "http://localhost:8000/api/v1/ingest" \
  -H "Content-Type: application/json" \
  -d '{"query": "technology", "limit": 1}'

# Pretty print with jq
curl -X POST "http://localhost:8000/api/v1/ingest" \
  -H "Content-Type: application/json" \
  -d '{"query": "climate change", "limit": 5}' | jq .
```

---

## 📂 Project Structure

```
news-analytics-api/
├── app/
│   ├── __init__.py
│   ├── main.py                      # FastAPI application
│   ├── api/
│   │   └── v1/
│   │       ├── health.py            # Health check endpoint
│   │       └── ingest.py            # Article ingestion endpoint
│   ├── core/
│   │   ├── config.py                # Configuration management
│   │   └── logging.py               # Logging setup
│   ├── models/
│   │   └── article.py               # Pydantic models
│   ├── services/
│   │   ├── news_fetcher.py          # NewsAPI client
│   │   ├── normalizer.py            # Data normalization
│   │   ├── newsapi_quota_tracker.py # Quota management
│   │   ├── s3_client.py             # S3 storage (planned)
│   │   └── athena.py                # Athena queries (planned)
│   └── utils/
│       └── time.py                  # Date/time utilities
├── api-testing/
│   ├── test_basic.py                # Basic API tests
│   ├── test_rate_limit.py           # Rate limiting tests
│   └── testing_suite.py             # Comprehensive test suite
├── infra/
│   ├── ecs.tf                       # ECS cluster & services
│   ├── iam.tf                       # IAM roles & policies
│   ├── s3.tf                        # S3 buckets
│   └── variables.tf                 # Terraform variables
├── docker/
│   └── (Docker-related files)
├── .env.example                     # Environment template
├── .gitignore
├── Dockerfile                       # Container definition
├── docker-compose.yml               # Local multi-container setup
├── requirements.txt                 # Python dependencies
└── README.md
```

---

## 🔧 Configuration

### Environment Variables

Create a `.env` file based on `.env.example`:

```bash
# NewsAPI Configuration
NEWS_API_KEY=your_newsapi_key_here
NEWS_API_BASE_URL=https://newsapi.org/v2

# Application Settings
LOG_LEVEL=INFO
RATE_LIMIT_PER_MINUTE=10
NEWSAPI_DAILY_QUOTA=100

# AWS Configuration (for deployment)
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=123456789012
S3_BUCKET_NAME=news-analytics-data
```

### Rate Limiting

Configure in `app/api/v1/ingest.py`:

```python
@limiter.limit("10/minute")  # Adjust as needed
```

Options:
- `"10/minute"` - 10 requests per minute
- `"100/hour"` - 100 requests per hour
- `"1000/day"` - 1000 requests per day

---

## 🏗️ Infrastructure Deployment

### Prerequisites

- AWS CLI configured
- Terraform installed
- Docker installed
- AWS account with appropriate permissions

### Deploy to AWS

```bash
# Navigate to infrastructure directory
cd infra/

# Initialize Terraform
terraform init

# Review planned changes
terraform plan

# Apply infrastructure
terraform apply

# Get outputs (API URL, etc.)
terraform output
```

### Infrastructure Components

- **ECR**: Docker image repository
- **VPC**: Network isolation with public/private subnets
- **ALB**: Application Load Balancer with health checks
- **ECS Fargate**: Serverless container orchestration
- **CloudWatch**: Centralized logging and monitoring
- **S3**: Article storage (JSON format)
- **Athena**: SQL-based analytics
- **Secrets Manager**: Secure credential storage
- **IAM**: Least-privilege access roles

---

## 📊 Data Schema

### Article Model

```json
{
  "source": "string",           // Normalized source identifier
  "title": "string",            // Article headline
  "description": "string|null", // Article summary
  "url": "string",              // Article URL
  "published_at": "datetime",   // ISO 8601 timestamp
  "topic": "string|null"        // Search query used
}
```

### S3 Storage Structure (Planned)

```
s3://news-analytics-data/
└── articles/
    └── year=2026/
        └── month=02/
            └── day=02/
                └── topic=artificial_intelligence/
                    └── 2026-02-02T12-00-00_batch.json
```

---

## 🔒 Security

- ✅ API keys stored in environment variables (not in code)
- ✅ Rate limiting to prevent abuse
- ✅ Input validation with Pydantic
- ✅ Non-root Docker user
- 🚧 AWS Secrets Manager for production credentials
- ✅ HTTPS/TLS via Application Load Balancer
- ✅ VPC security groups for network isolation
- ✅ IAM roles with least-privilege access

---

## 📈 Monitoring & Observability

### Structured Logging

All logs are in JSON format for easy parsing:

```json
{
  "event": "ingest_request",
  "query": "climate change",
  "limit": 10,
  "client_ip": "192.168.1.1",
  "timestamp": "2026-02-02T12:00:00Z",
  "level": "info"
}
```

### Health Checks

- Endpoint: `/api/v1/health`
- Includes NewsAPI quota information
- Used by load balancer for instance health

### Metrics (Planned)

- Request count and latency
- Error rates by endpoint
- NewsAPI quota usage
- Article ingestion rate
- S3 storage size

---

## 🛣️ Roadmap

### Phase 1: API ✅ (Complete)
- [x] NewsAPI integration
- [x] Data normalization
- [x] Rate limiting
- [x] Quota tracking
- [x] Health checks
- [x] Test suite

### Phase 2: Infrastructure ✅ (Complete)
- [x] Dockerfile
- [x] Docker Compose
- [x] AWS ECR setup
- [x] Terraform for ECS
- [x] Load balancer configuration
- [x] CloudWatch integration

### Phase 3: Data Pipeline 🚧 (In Progress)
- [ ] S3 storage implementation
- [ ] Athena table creation
- [ ] Partition management
- [ ] Analytics endpoints
- [ ] Query optimization

### Phase 4: Analytics 📋 (Planned)
- [ ] Sentiment analysis integration
- [ ] Trend detection algorithms
- [ ] Visualization dashboards
- [ ] Real-time alerts
- [ ] Historical data analysis

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📝 License

MIT License

Copyright (c) 2026 Kevin Williams

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## 📧 Contact

Email: kevin.williams2218@gmail.com

---

## 🙏 Acknowledgments

- [NewsAPI](https://newsapi.org/) - News article data source
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [AWS](https://aws.amazon.com/) - Cloud infrastructure

---

## 📚 Additional Resources

- [API Documentation](http://localhost:8000/docs) - Interactive Swagger UI
- [NewsAPI Documentation](https://newsapi.org/docs)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Terraform AWS Provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)

---

**Current Version:** v1.0.0 (API Complete)  
**Last Updated:** February 2026
