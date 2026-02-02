# News Analytics Platform

End-to-end news analytics platform that ingests articles from NewsAPI, normalizes data to a canonical schema, stores in S3, and provides SQL-based analytics via AWS Athena. Built with FastAPI, deployed on ECS Fargate with Terraform IaC, featuring rate limiting, quota tracking, and real-time sentiment analysis capabilities.

## 🎯 Project Overview

### Architecture
```
┌──────────┐     ┌─────────────┐     ┌──────────┐     ┌─────────┐
│  Client  │────▶│     ALB     │────▶│   ECS    │────▶│ NewsAPI │
└──────────┘     └─────────────┘     │ (Fargate)│     └─────────┘
                                      └────┬─────┘
                                           │
                                           ▼
                                      ┌─────────┐
                                      │   S3    │
                                      │ (JSON)  │
                                      └────┬────┘
                                           │
                                           ▼
                                      ┌─────────┐
                                      │ Athena  │
                                      │Analytics│
                                      └─────────┘
```

### Features

#### ✅ Completed (API)
- 🔌 **NewsAPI Integration** - Fetch articles from multiple sources with error handling
- 📊 **Data Normalization** - Canonical schema for consistent data structure
- 🚦 **Rate Limiting** - 10 requests/minute per IP address
- 📈 **Quota Tracking** - Monitor NewsAPI usage (100 requests/day free tier)
- 🔍 **Structured Logging** - JSON logs with structlog for observability
- 📚 **Auto Documentation** - Swagger UI at `/docs` and ReDoc at `/redoc`
- ✅ **Input Validation** - Pydantic models for request/response validation
- 🏥 **Health Checks** - Endpoint for load balancer monitoring

#### 🚧 In Progress (Infrastructure)
- 🐳 **Containerization** - Docker image with multi-stage builds
- ☁️ **AWS Deployment** - ECS Fargate with Terraform IaC
- 🔐 **Secrets Management** - AWS Secrets Manager for API keys
- 📊 **CloudWatch Integration** - Centralized logging and monitoring

#### 📋 Planned (Analytics Pipeline)
- 💾 **S3 Storage** - JSON file storage organized by date/topic
- 🔍 **Athena Queries** - SQL-based analytics on stored articles
- 📈 **Sentiment Analysis** - Real-time sentiment scoring
- 📊 **Trend Detection** - Identify emerging topics and patterns
- 📊 **Analytics API** - Query endpoints for insights

---

## 🚀 Quick Start

### Prerequisites

- Python 3.9+
- Docker (optional, for containerization)
- AWS Account (for deployment)
- NewsAPI Key ([Get one free](https://newsapi.org/register))

### Local Development

```bash
# Clone the repository
git clone <your-repo-url>
cd news-analytics-api

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env and add your NEWS_API_KEY

# Run the server
uvicorn app.main:app --reload

# API will be available at:
# - Swagger UI: http://localhost:8000/docs
# - ReDoc: http://localhost:8000/redoc
# - Health: http://localhost:8000/api/v1/health
```

### Docker

```bash
# Build the image
docker build -t news-analytics-api:latest .

# Run the container
docker run -d \
  --name news-api \
  -p 8000:8000 \
  --env-file .env \
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
- 🚧 HTTPS/TLS via Application Load Balancer
- 🚧 VPC security groups for network isolation
- 🚧 IAM roles with least-privilege access

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

### Phase 2: Infrastructure 🚧 (In Progress)
- [ ] Dockerfile
- [ ] Docker Compose
- [ ] AWS ECR setup
- [ ] Terraform for ECS
- [ ] Load balancer configuration
- [ ] CloudWatch integration

### Phase 3: Data Pipeline 📋 (Planned)
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

[Your License Here]

---

## 📧 Contact

[Your Contact Information]

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
