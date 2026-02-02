📰 News Analytics REST API

A cloud-native, analytics-driven RESTful API for ingesting, normalizing, and analyzing news data from multiple sources.
The system is designed as a data ingestion + analytics backend, supporting topic trends, source-level comparisons, and future bias analysis using an S3-based data lake and Athena.

⸻

📌 Project Overview

Modern news analysis requires:
	•	Aggregating data from multiple news providers
	•	Normalizing inconsistent schemas
	•	Storing data in a query-friendly analytics format
	•	Enabling trend, frequency, and source-level insights

This project solves that by acting as the contract layer between:
	•	External news APIs
	•	A cloud-based data lake
	•	Analytics and visualization tools

The API is built with Python + FastAPI, deployed as a stateless, scalable service, and designed to mirror real-world data engineering and backend workflows.

⸻

🏗 Architecture Overview

High-level flow:
	1.	Scheduled or on-demand ingestion requests hit the REST API
	2.	The API fetches data from external news providers
	3.	Raw responses are normalized into a unified schema
	4.	Normalized data is stored in Amazon S3 (data lake)
	5.	Data can be queried using Amazon Athena for analytics
	6.	Aggregates are exposed via analytics endpoints or dashboards

Key design principle:

Treat the API as a production data service, not a script.

⸻

🧰 Tech Stack

Backend
	•	Python 3.11
	•	FastAPI – async REST API framework
	•	Pydantic – schema validation & serialization
	•	Uvicorn – ASGI server

Cloud & Infrastructure
	•	Amazon S3 – raw & processed data lake
	•	Amazon Athena – SQL analytics on S3 data
	•	AWS ECS (Fargate) – containerized deployment
	•	Terraform – infrastructure as code
	•	Docker – containerization

Data & Analytics
	•	JSON (raw ingestion)
	•	Parquet (planned optimization)
	•	Schema normalization for cross-source analysis

⸻

🗂 Repository Structure

news-analytics-api/
├── app/
│   ├── main.py              # FastAPI application entry point
│   ├── api/
│   │   └── v1/
│   │       ├── ingest.py    # ingestion endpoints
│   │       ├── analytics.py # analytics endpoints
│   │       └── health.py    # health checks
│   ├── services/
│   │   ├── news_fetcher.py  # external API clients
│   │   ├── normalizer.py    # schema normalization
│   │   ├── s3_client.py    # S3 interactions
│   │   └── athena.py       # Athena query execution
│   ├── models/
│   │   └── article.py      # unified article schema
│   ├── core/
│   │   ├── config.py       # environment configuration
│   │   └── logging.py      # structured logging
│   └── utils/
│       └── time.py
├── docker/
│   └── Dockerfile
├── terraform/
│   ├── ecs.tf
│   ├── s3.tf
│   ├── iam.tf
│   └── variables.tf
├── requirements.txt
└── README.md

This structure intentionally mirrors real backend and data-platform repos.

⸻

🔄 Data Normalization Strategy

Different news providers return different schemas.
To support analytics, all incoming data is normalized into a single canonical model:

Article(
    source: str,
    title: str,
    description: Optional[str],
    url: str,
    published_at: datetime,
    topic: Optional[str]
)

Why this matters:
	•	Enables cross-source comparisons
	•	Simplifies downstream analytics
	•	Allows future bias & sentiment analysis
	•	Decouples ingestion logic from analytics logic

⸻

📥 API Endpoints

Health Check

GET /health

Used for load balancers and service monitoring.

⸻

Ingest News Data

POST /api/v1/ingest?query=<topic>

What it does:
	•	Fetches articles from external news APIs
	•	Normalizes data into a unified schema
	•	Stores raw normalized data in S3

Response:

{
  "status": "success",
  "count": 42,
  "s3_key": "raw/2026-02-01T21:14:32.json"
}


⸻

Analytics (Planned / Expandable)

GET /api/v1/analytics/topics
GET /api/v1/analytics/sources

Provides:
	•	Topic frequency counts
	•	Source-level distributions
	•	Time-based trends

These endpoints are backed by Athena SQL queries on S3 data.

⸻

☁️ Data Lake Design (S3)

s3://news-datalake/
├── raw/         # raw normalized JSON
├── processed/   # cleaned / enriched data
└── analytics/   # aggregates & query outputs

This layout mirrors industry-standard data lake architectures.

⸻

🚀 Local Development

Install dependencies

pip install -r requirements.txt

Run the API

uvicorn app.main:app --reload

API Docs

FastAPI auto-generates OpenAPI docs:

http://localhost:8000/docs


⸻

🐳 Docker Support

The service is fully containerized for local and cloud deployment.

docker build -t news-analytics-api .
docker run -p 8000:80 news-analytics-api


⸻

🌍 Cloud Deployment (AWS)

The API is designed for:
	•	Stateless execution
	•	Horizontal scaling
	•	Managed infrastructure

Deployment stack:
	•	ECS Fargate for compute
	•	IAM roles for secure S3 & Athena access
	•	Terraform for repeatable provisioning

⸻

📊 Analytics & Use Cases

This platform enables:
	•	Tracking trending topics over time
	•	Comparing coverage across news sources
	•	Measuring publication volume by category
	•	Supporting future bias, sentiment, and framing analysis

Example analytics questions:
	•	Which outlets publish the most political content?
	•	How does topic coverage shift week-to-week?
	•	Are certain topics over-represented by specific sources?

⸻

🔮 Future Enhancements
	•	Parquet conversion via AWS Glue
	•	Sentiment analysis (NLP)
	•	Source bias metrics
	•	Scheduled ingestion via EventBridge
	•	Dashboards via QuickSight or Grafana
	•	Authentication (JWT / IAM)
	•	Rate limiting and caching

⸻

🎯 Why This Project Exists

This project was built to demonstrate:
	•	Real REST API design (not toy endpoints)
	•	Data engineering fundamentals
	•	Cloud-native architecture
	•	Analytics-first thinking
	•	Production-ready structure and tooling

It reflects how modern backend systems support data pipelines, analytics, and decision-making, not just CRUD.

⸻

If you want next, I can:
	•	Rewrite this README shorter for recruiters
	•	Add a system architecture diagram
	•	Generate resume bullets directly from this README
	•	Help you implement bias metrics properly

Just tell me how hard you want to go 🚀