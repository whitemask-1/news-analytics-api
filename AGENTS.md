# AGENTS.md — AI Assistant Context

> **Purpose:** This file provides LLM context for the `news-analytics-api` repository so AI assistants can help effectively without needing full repo re-explanation each session.

---

## Project Overview

**Name:** News Analytics API  
**Architecture:** Serverless event-driven pipeline on AWS Lambda  
**Primary Language:** Python 3.11  
**Infrastructure:** Terraform (IaC)  
**Status:** Production-deployed, functional API at API Gateway endpoint

**What it does:**  
Fetches news articles from NewsAPI, deduplicates them via Redis (Upstash), normalizes data, stores in S3 (Parquet format), and enables SQL analytics via Athena. Built for low-cost, auto-scaling serverless execution.

**Key transition:** Migrated from ECS Fargate (always-on containers, $27/mo) to Lambda containers ($7-15/mo, 50%+ cost reduction).

---

## Architecture (Data Flow)

```
Client/EventBridge → API Gateway → API Lambda → SQS Queue → Worker Lambda
                                       ↓                            ↓
                                   Returns 202              NewsAPI fetch
                                                                   ↓
                                                            Redis dedup check
                                                                   ↓
                                                            Normalize (Pydantic)
                                                                   ↓
                                                         S3 (raw JSON + Parquet)
                                                                   ↓
                                                            Athena queryable
```

**Key insight:** Async architecture. API responds instantly (202 Accepted) by queuing work in SQS. Worker processes in background. No long-running HTTP requests.

---

## Repository Structure

```
news-analytics-api/
├── app/
│   ├── lambda_api_handler.py        # Entry: API Gateway → FastAPI routes
│   ├── lambda_worker_handler.py     # Entry: SQS → article processing pipeline
│   ├── api/v1/
│   │   ├── health.py                # GET /health
│   │   └── analytics.py             # GET /analytics/* (Athena queries)
│   ├── core/
│   │   ├── config.py                # Pydantic Settings (env var loader)
│   │   └── logging.py               # structlog JSON setup
│   ├── models/
│   │   └── article.py               # Pydantic models (Article, IngestRequest)
│   └── services/
│       ├── news_fetcher.py          # NewsAPI HTTP client
│       ├── normalizer.py            # Raw JSON → Article model + Parquet
│       ├── redis_client.py          # Upstash Redis REST API wrapper
│       ├── s3_client.py             # boto3 S3 uploads (raw/normalized)
│       └── athena.py                # SQL query executor
├── infra/
│   ├── lambda.tf                    # Lambda functions, SQS, API Gateway, IAM
│   ├── s3.tf                        # Buckets + lifecycle policies
│   ├── athena.tf                    # Glue tables, Athena workgroup
│   ├── ecr.tf                       # Container registry
│   ├── variables.tf                 # Input variables
│   └── outputs.tf                   # Terraform outputs (API URL, etc.)
├── Dockerfile                       # Lambda container image (AWS base)
├── requirements.txt                 # Python dependencies
├── .env.example                     # Local dev env template
└── docker-compose.yml               # Local development setup
```

---

## Core Components Explained

### 1. API Lambda (`lambda_api_handler.py`)

**Entry point:** `lambda_handler(event, context)` (line 266)  
**Adapter:** Mangum wraps FastAPI for API Gateway compatibility (line 258)  
**Main route:** `POST /api/v1/ingest` (line 163)

**What it does:**
1. Receives HTTP request via API Gateway
2. Validates request body against `IngestRequest` Pydantic model (auto-validation)
3. Publishes message to SQS queue (`boto3.client("sqs").send_message()`)
4. Returns `202 Accepted` immediately

**Dev mode:** If `ENVIRONMENT=development`, bypasses SQS and calls `process_single_message()` directly for local testing.

**Key pattern:** Singleton SQS client (`_sqs_client`, line 95) — reused across warm Lambda invocations for performance.

### 2. Worker Lambda (`lambda_worker_handler.py`)

**Entry point:** `lambda_handler(event, context)` (line 336)  
**Main function:** `process_single_message(message_body)` (line 67)

**Pipeline steps (all in `process_single_message`):**
1. **Line 146:** Fetch articles from NewsAPI (`await news_fetcher.fetch_articles()`)
2. **Line 178-185:** Calculate SHA256 hashes (title + URL, truncated to 16 chars)
3. **Line 195:** Batch-check Redis for existing hashes (`await redis.batch_check_exists()`)
4. **Line 199-211:** Filter out duplicates using `zip(articles, hashes, exists_list)`
5. **Line 244:** Normalize new articles (`normalizer.normalize_batch()` → Pydantic models)
6. **Line 262:** Store raw JSON to S3 (all fetched, for audit)
7. **Line 276:** Store normalized Parquet to S3 (only new articles, partitioned by date)
8. **Line 292:** Mark new hashes in Redis with 14-day TTL
9. **Line 306:** Return metrics dict

**Error handling:** Line 325 catches exceptions, logs, then re-raises so SQS knows the message failed (triggers retry → DLQ after 3 failures).

**Async bridge:** Line 395 uses `asyncio.run(process_single_message())` because `lambda_handler` is sync but the pipeline is async.

### 3. Services Layer

All services are importable, testable modules with single responsibilities:

- **`news_fetcher.py`**: `async def fetch_articles()` → calls NewsAPI REST endpoint
- **`redis_client.py`**: Upstash REST API wrapper (not traditional Redis connection)
  - `batch_check_exists(hashes)` → returns `[True, False, True, ...]`
  - `batch_mark_processed(hashes)` → sets keys with 14-day TTL
- **`normalizer.py`**: Raw NewsAPI dict → Pydantic `Article` → Parquet bytes
- **`s3_client.py`**: boto3 wrappers for `put_object` with partition paths
- **`athena.py`**: Executes SQL queries on S3 data lake

### 4. Infrastructure (Terraform)

**`lambda.tf`** — The main file, defines:
- SQS queue + DLQ (lines 14-43)
- IAM role with permissions (lines 79-199)
- API Lambda function (lines 211-257)
- Worker Lambda function (lines 274-323)
- Event source mapping (SQS → Worker trigger, lines 335-350)
- API Gateway HTTP API (lines 358-434)
- EventBridge schedule (lines 442-494)

**Key resources to know:**
- `aws_lambda_function.api_handler` — the API Lambda
- `aws_lambda_function.worker` — the Worker Lambda
- `aws_sqs_queue.ingest_queue` — the message queue
- `aws_lambda_event_source_mapping.sqs_trigger` — connects Worker to SQS

**Pattern:** Terraform auto-wires everything. Example:
```hcl
SQS_QUEUE_URL = aws_sqs_queue.ingest_queue.url
```
Terraform creates the queue, AWS generates the URL, Terraform injects it as a Lambda env var. You never hardcode ARNs/URLs.

---

## Code Patterns & Conventions

### Type Hints (Everywhere)

```python
async def process_single_message(message_body: Dict[str, Any]) -> Dict[str, Any]:
    ...
```

- All function parameters are typed
- Return types specified
- Use `from typing import Dict, List, Optional, Any`

### Async/Await Usage

**When to use `async def`:**
- Function makes network I/O calls (NewsAPI, Redis, S3)
- Function calls another `async def` function

**When NOT to use `async def`:**
- Pure CPU work (normalization, hashing, validation)

**Critical:** Always `await` async functions. Forgetting `await` returns a coroutine object, not the result.

```python
# ❌ WRONG — returns coroutine, not data
result = redis.batch_check_exists(hashes)

# ✅ CORRECT
result = await redis.batch_check_exists(hashes)
```

### Pydantic Models

All data structures use Pydantic `BaseModel`:

```python
from pydantic import BaseModel, Field

class IngestRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(default=100, ge=1, le=100)
    language: str = Field(default="en", min_length=2, max_length=2)
```

- FastAPI auto-validates request bodies
- Returns 422 if validation fails (before your code runs)
- Use `.model_dump()` to convert model → dict (for S3/JSON)

### Environment Variables

Never hardcode secrets or config. Always use `os.getenv()`:

```python
queue_url = os.getenv("SQS_QUEUE_URL")
redis_url = os.getenv("UPSTASH_REDIS_URL")
```

**Pattern:** Check if optional services are configured, gracefully degrade if not:

```python
use_redis = os.getenv("UPSTASH_REDIS_URL") and os.getenv("UPSTASH_REDIS_TOKEN")
if use_redis:
    # Use Redis deduplication
else:
    # Skip dedup, process all articles
```

### Logging (structlog + JSON)

```python
logger.info(
    "event_name",
    key1=value1,
    key2=value2
)
```

- All logs are JSON for CloudWatch parsing
- Event names use `snake_case`
- Include context: `query`, `count`, `message_id`, etc.

### Error Handling

**API Lambda:** Catch specific exceptions first, let `HTTPException` propagate

```python
try:
    # code
except HTTPException:
    raise  # Let FastAPI handle it
except Exception as e:
    logger.error("event", error=str(e))
    raise HTTPException(status_code=500, detail=str(e))
```

**Worker Lambda:** Log and re-raise so SQS retries

```python
try:
    # pipeline code
except Exception as e:
    logger.error("ingestion_failed", error=str(e), exc_info=True)
    raise  # SQS will retry, then DLQ after 3 failures
```

---

## Key Variables & Config

### Environment Variables (Lambda)

| Variable | Where Set | Used By |
|----------|-----------|---------|
| `ENVIRONMENT` | Terraform | API (local dev vs prod) |
| `SQS_QUEUE_URL` | Terraform (from queue resource) | API Lambda |
| `S3_BUCKET_RAW` | Terraform | Worker Lambda |
| `S3_BUCKET_NORMALIZED` | Terraform | Worker Lambda |
| `NEWS_API_KEY` | terraform.tfvars | Both Lambdas |
| `UPSTASH_REDIS_URL` | terraform.tfvars | Worker Lambda |
| `UPSTASH_REDIS_TOKEN` | terraform.tfvars | Worker Lambda |
| `REDIS_TTL_DAYS` | Terraform (hardcoded "14") | Worker Lambda |

### Terraform Variables (Key Ones)

Defined in `variables.tf`, values set in `terraform.tfvars`:

- `project_name` (default: "news-analytics") — prefixes all resource names
- `environment` (default: "dev") — dev/staging/prod
- `aws_region` (default: "us-east-1")
- `news_api_key` (sensitive, no default) — **REQUIRED**
- `upstash_redis_url` (sensitive, no default) — **REQUIRED**
- `upstash_redis_token` (sensitive, no default) — **REQUIRED**

**Note:** Old ECS variables (`container_cpu`, `desired_count`, etc.) still exist but aren't used. Safe to ignore.

---

## Common Operations

### Deploy Changes

```bash
cd infra
terraform apply
```

Terraform rebuilds Docker image, pushes to ECR, updates Lambda functions. Takes ~2-3 minutes.

### View Logs

```bash
# API Lambda
aws logs tail /aws/lambda/news-analytics-dev-api --follow

# Worker Lambda
aws logs tail /aws/lambda/news-analytics-dev-worker --follow
```

### Test Ingestion

```bash
curl -X POST https://YOUR-API-URL/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{"query": "AI", "limit": 10}'
```

Should return `202 Accepted` with a `request_id`.

### Check SQS Queue Depth

```bash
aws sqs get-queue-attributes \
  --queue-url $(terraform output -raw sqs_queue_url) \
  --attribute-names ApproximateNumberOfMessages
```

### Query Stored Articles (Athena)

```sql
SELECT source, COUNT(*) as count
FROM normalized_articles
WHERE year = 2026 AND month = 2
GROUP BY source
ORDER BY count DESC
```

---

## Known Issues & Gotchas

### 1. **datetime.now() vs datetime.utcnow() mismatch**
- **Location:** `lambda_worker_handler.py` line 303
- **Issue:** `start_time = datetime.utcnow()` but `end_time = datetime.now()`
- **Impact:** `processing_time_ms` calculation may be off if timezones differ
- **Fix:** Change line 303 to `end_time = datetime.utcnow()`

### 2. **Missing S3_BUCKET_RAW in older Terraform**
- Worker Lambda needs both `S3_BUCKET_RAW` and `S3_BUCKET_NORMALIZED` env vars
- If missing, `use_s3` becomes falsy → storage silently skipped
- Fixed in latest `lambda.tf` but check if deploying from old state

### 3. **Import inside loop**
- **Location:** `lambda_worker_handler.py` line 180
- **Issue:** `import hashlib` inside the for loop
- **Impact:** None (Python caches imports), but bad style
- **Fix:** Move to top of file

### 4. **Duplicate variable declarations**
- `variables.tf` has both `newsapi_key` (line 89, old) and `news_api_key` (line 135, current)
- Code uses `news_api_key` — the old one should be deleted

---

## Testing Approach

### Local Development

1. Set `ENVIRONMENT=development` in `.env`
2. Run `docker-compose up`
3. API processes requests synchronously (no SQS) for fast iteration
4. Redis/S3 optional (gracefully degrades if not configured)

### Manual Testing

```bash
# Health check
curl http://localhost:8000/health

# Ingest (local dev mode processes immediately)
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{"query": "technology", "limit": 5}'
```

### Production Testing

Use actual API Gateway URL from `terraform output api_gateway_url`.

---

## Dependencies

### Python (`requirements.txt`)

Key packages:
- `fastapi` — web framework
- `mangum` — FastAPI → Lambda adapter
- `pydantic` — data validation
- `boto3` — AWS SDK (SQS, S3, Athena)
- `httpx` — async HTTP client (for NewsAPI)
- `pyarrow` — Parquet generation
- `structlog` — structured JSON logging
- `python-dotenv` — local .env loading

### AWS Resources (Created by Terraform)

- Lambda functions (2)
- SQS queue + DLQ
- S3 buckets (3: raw, normalized, athena-results)
- API Gateway HTTP API
- ECR repository
- CloudWatch log groups
- Glue database + table
- IAM roles + policies
- EventBridge rule

---

## Decision Log

### Why Lambda over ECS?
- **Cost:** $7-15/mo vs $27/mo (50% reduction)
- **Scaling:** 0-1000+ auto vs manual config
- **Ops:** Zero infrastructure management

### Why SQS between API and Worker?
- **Decoupling:** API responds fast, worker processes slowly
- **Reliability:** Messages durably stored, retry on failure
- **Backpressure:** Queue absorbs traffic spikes

### Why Upstash Redis (not ElastiCache)?
- **Serverless:** No VPC, no warm connections to maintain
- **Cost:** $0 free tier, usage-based after
- **API:** REST API = simple httpx calls, no connection pooling needed

### Why Parquet format?
- **Size:** 2-3x smaller than JSON
- **Speed:** Athena scans only needed columns (columnar format)
- **Cost:** Less data scanned = lower Athena costs ($5/TB)

### Why 14-day TTL for Redis hashes?
- **Balance:** Long enough to catch duplicates during "news cycle"
- **Memory:** ~8 MB for 500K articles (negligible cost)
- **Expiry:** Automatic cleanup, no manual maintenance

---

## When You Need to Modify

### Adding a new API endpoint

1. Create route function in `app/api/v1/` (or new file)
2. Use `@router.get()` or `@router.post()` decorator
3. Include router in `lambda_api_handler.py` with `app.include_router()`
4. No Terraform changes needed (catch-all `$default` route)

### Adding a new env var

1. Add to `variables.tf` if it's a secret or config input
2. Add to Lambda env block in `lambda.tf` (both API and Worker if needed)
3. Read in Python with `os.getenv("VAR_NAME")`
4. `terraform apply` to update

### Changing memory/timeout

Edit `lambda.tf`:
- `memory_size` (256-10240 MB)
- `timeout` (max 900 seconds for Lambda)
- Costs scale with memory × duration

### Adding a new service

1. Create file in `app/services/`
2. Define class with methods
3. Import in `lambda_worker_handler.py`
4. Call in `process_single_message()` pipeline
5. Add any new boto3 permissions to IAM policy in `lambda.tf`

---

## Useful Snippets

### Adding a new Pydantic validator

```python
from pydantic import validator

class MyModel(BaseModel):
    field: str
    
    @validator("field")
    def validate_field(cls, v):
        if some_condition:
            raise ValueError("Error message")
        return v.strip().lower()  # Transform before storing
```

### Calling S3 with boto3

```python
import boto3

s3 = boto3.client("s3")
s3.put_object(
    Bucket="bucket-name",
    Key="path/to/file.json",
    Body=json.dumps(data),
    ContentType="application/json"
)
```

### Terraform: referencing one resource from another

```hcl
resource "aws_sqs_queue" "my_queue" {
  name = "my-queue"
}

resource "aws_lambda_function" "my_function" {
  environment {
    variables = {
      QUEUE_URL = aws_sqs_queue.my_queue.url  # Auto-populated
    }
  }
}
```

---

## Contact & Resources

- **Repo:** github.com/whitemask-1/news-analytics-api
- **Owner:** Kevin Williams (FSU Statistics major, aspiring cloud/data engineer)
- **Docs:** README.md, DEPLOYMENT.md, PROGRESS.md

**External Docs:**
- [FastAPI](https://fastapi.tiangolo.com/)
- [Pydantic](https://docs.pydantic.dev/)
- [boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html)
- [Terraform AWS Provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
- [AWS Lambda](https://docs.aws.amazon.com/lambda/)
- [Upstash Redis](https://docs.upstash.com/redis)

---

**Last Updated:** 2026-02-11  
**Version:** 2.0 (Lambda migration complete, production-deployed)