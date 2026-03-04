# News Analytics Platform

A serverless news ingestion and analytics pipeline built on AWS. Processes 100+ articles daily through an event-driven architecture with Redis deduplication, Parquet compression, and Infrastructure as Code via Terraform. Currently inactive.

---

## Architecture

```
NewsAPI
    → EventBridge (scheduled trigger)
        → SQS (message queue)
            → Lambda Worker (normalization + deduplication)
                → Redis (Upstash) — duplicate check via article hash
                → DynamoDB — primary article storage
                → S3 / Parquet — compressed archival storage
                    → Athena — analytical queries over S3
API Gateway → Lambda API — RESTful access to stored articles
```

All infrastructure is defined in Terraform and provisioned to AWS. No persistent compute — the system is entirely event-driven and scales to zero when idle.

---

## Infrastructure

| Service         | Role                                                            |
| --------------- | --------------------------------------------------------------- |
| Lambda          | Article ingestion worker + API handler (two separate functions) |
| API Gateway     | RESTful endpoints for article retrieval and health checks       |
| SQS             | Decouples ingestion trigger from processing worker              |
| EventBridge     | Scheduled cron trigger for automated news collection            |
| DynamoDB        | Primary storage for normalized articles                         |
| S3 + Parquet    | Archival storage with 2-3x compression vs JSON                  |
| Athena          | Serverless SQL queries over S3 Parquet data                     |
| Redis (Upstash) | Deduplication layer via article hash before write               |
| ECR             | Container registry for Lambda Docker images                     |
| Secrets Manager | API keys and environment secrets                                |
| CloudWatch      | Logging and monitoring across all services                      |
| Terraform       | IaC for all AWS resources                                       |

---

## Project Structure

```
├── app/
│   ├── api/v1/             # FastAPI route handlers (health, analytics)
│   ├── core/               # Config and logging
│   ├── models/             # Article schema and hash generation
│   ├── services/           # Business logic — fetcher, normalizer, Redis, S3, Athena, Secrets Manager
│   ├── utils/              # Shared utilities
│   ├── lambda_api_handler.py     # Lambda entrypoint for API Gateway
│   └── lambda_worker_handler.py  # Lambda entrypoint for SQS worker
├── infra/                  # Terraform — all AWS resource definitions
├── docker/                 # Lambda container images
├── scripts/                # startup.sh, shutdown.sh, status.sh
├── api-testing/            # Integration tests against live endpoints
└── Dockerfile / Dockerfile.dev
```

Two Lambda functions share the same codebase but use separate entrypoints — `lambda_api_handler.py` handles synchronous API requests, `lambda_worker_handler.py` handles asynchronous SQS message processing.

---

## Data Flow

**Ingestion**

EventBridge fires on a schedule → pushes a message to SQS → Lambda worker pulls from the queue → calls NewsAPI → normalizes each article into a consistent schema → generates a content hash → checks Redis for duplicates → writes new articles to DynamoDB and S3 as Parquet.

**Retrieval**

API Gateway receives a request → Lambda API handler queries DynamoDB for recent articles or routes analytical queries to Athena over S3.

---

## Key Engineering Decisions

**ECS Fargate → Lambda migration**

The initial architecture ran a containerized FastAPI app on ECS Fargate at a fixed $27/month regardless of traffic. Migrating to Lambda containers dropped costs to $7-15/month on a usage-based model and added auto-scaling from 0 to 1,000+ concurrent requests without any configuration. The tradeoff is cold start latency on infrequent invocations, which is acceptable for a batch ingestion workload.

**SQS decoupling**

EventBridge triggers SQS rather than invoking Lambda directly. This means if the worker fails or is throttled, messages queue rather than drop. It also makes the ingestion trigger and processing logic independently deployable.

**Redis deduplication via content hash**

Each article is hashed on content before any write operation. Redis stores seen hashes with a TTL. This eliminates duplicate articles from NewsAPI (which frequently returns the same articles across paginated requests) before they hit DynamoDB or S3, achieving 30-50% storage reduction.

**Parquet over JSON for archival**

DynamoDB handles recent article lookups. Older articles are archived to S3 as Parquet — a columnar format that compresses 2-3x smaller than JSON and is natively queryable by Athena without any ETL. Analytical queries over historical data run directly against S3.

**Two Lambda entrypoints, one codebase**

Splitting API and worker logic into separate Lambda functions while sharing the underlying services layer means each function has the minimum permissions and memory allocation it needs, without duplicating business logic.

---

## Cost Profile

| Architecture      | Monthly Cost | Model       |
| ----------------- | ------------ | ----------- |
| ECS Fargate       | ~$27         | Fixed       |
| Lambda containers | $7-15        | Usage-based |

70% cost reduction with higher scalability ceiling.

---

## Local Development

```bash
cp .env.example .env        # configure NewsAPI key and AWS credentials
docker-compose up           # run API locally
```

Integration tests against live endpoints are in `api-testing/`.

---

## Tech Stack

- **Runtime**: Python, FastAPI
- **Cloud**: AWS Lambda, API Gateway, SQS, EventBridge, DynamoDB, S3, Athena, ECR, Secrets Manager, CloudWatch
- **IaC**: Terraform
- **Storage**: DynamoDB, S3/Parquet, Redis (Upstash)
- **Data**: NewsAPI
- **Containers**: Docker
